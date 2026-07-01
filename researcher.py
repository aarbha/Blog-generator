import asyncio
import hashlib
import json
import re
import time
import warnings
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import feedparser
import httpx
warnings.filterwarnings("ignore", message="This package.*renamed to ddgs")
from duckduckgo_search import DDGS

from config import settings
from scraper import fetch_article

CACHE_DIR = settings.cache_dir_path
SEARCH_CACHE_TTL = settings.search_cache_ttl
FEEDS_CONFIG_PATH = settings.feeds_config_path_obj
FEEDS_STATE_PATH = settings.feeds_state_path_obj

_fetch_semaphore = asyncio.Semaphore(5)
_CURRENT_YEAR = 2026
DOMAIN_REP_PATH = settings.cache_dir_path / ".domain_reputation.json"


async def _search_google_news(query: str, max_results: int = 5) -> list[dict]:
    try:
        url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        entries = []
        for entry in feed.entries[:max_results]:
            entries.append({
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "snippet": entry.get("description", "")[:300],
            })
        return entries
    except Exception:
        return []


async def _search_hacker_news(query: str, max_results: int = 5) -> list[dict]:
    try:
        url = f"https://hn.algolia.com/api/v1/search?query={quote_plus(query)}&hitsPerPage={max_results}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        entries = []
        for hit in data.get("hits", []):
            entries.append({
                "title": hit.get("title", ""),
                "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
                "snippet": hit.get("story_text", "")[:300] if hit.get("story_text") else "",
            })
        return entries
    except Exception:
        return []


async def _search_reddit(query: str, max_results: int = 5) -> list[dict]:
    try:
        url = f"https://www.reddit.com/search.json?q={quote_plus(query)}&limit={max_results}&sort=relevance"
        headers = {"User-Agent": "BlogWriter/1.0"}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        entries = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            entries.append({
                "title": d.get("title", ""),
                "url": d.get("url", ""),
                "snippet": (d.get("selftext", "") or d.get("url", ""))[:300],
            })
        return entries
    except Exception:
        return []


async def _search_devto(query: str, max_results: int = 5) -> list[dict]:
    try:
        url = f"https://dev.to/api/articles?per_page={max_results}&search={quote_plus(query)}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            articles = resp.json()
        entries = []
        for art in articles:
            entries.append({
                "title": art.get("title", ""),
                "url": art.get("url", ""),
                "snippet": (art.get("description", "") or "")[:300],
            })
        return entries
    except Exception:
        return []


async def _search_alt_sources(query: str, max_results: int = 5) -> list[dict]:
    sources = [
        _search_google_news(query, max_results),
        _search_hacker_news(query, max_results),
        _search_reddit(query, max_results),
        _search_devto(query, max_results),
    ]
    all_results = []
    seen_urls = set()
    for coro in asyncio.as_completed(sources):
        results = await coro
        for r in results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)
    return all_results[:max_results]


def _load_domain_reputation() -> dict[str, dict]:
    if DOMAIN_REP_PATH.exists():
        try:
            return json.loads(DOMAIN_REP_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            pass
    return {}


def _save_domain_reputation(rep: dict[str, dict]):
    DOMAIN_REP_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOMAIN_REP_PATH.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_domain_reputation(articles: list[dict]):
    rep = _load_domain_reputation()
    for a in articles:
        url = a.get("url", "")
        score = a.get("_relevance_score", 0)
        if not url or score <= 0:
            continue

        domain = urlparse(url).netloc
        if not domain:
            continue
        domain = domain.removeprefix("www.")
        entry = rep.get(domain, {"score": 0, "count": 0})
        entry["score"] = ((entry["score"] * entry["count"]) + score) / (entry["count"] + 1)
        entry["count"] += 1
        rep[domain] = entry
    _save_domain_reputation(rep)


def _extract_year(text: str) -> int | None:
    matches = re.findall(r"\b(20[2-9]\d)\b", text)
    if matches:
        return max(int(y) for y in matches)
    return None


def _filter_by_year(articles: list[dict], year: int) -> list[dict]:
    filtered = []
    for a in articles:
        date_str = a.get("date", "") or ""
        if date_str and len(date_str) >= 4:
            try:
                article_year = int(date_str[:4])
                if article_year != year:
                    continue
            except ValueError:
                pass
        filtered.append(a)
    return filtered


def _pointer_key(prefix: str, value: str) -> str:
    safe = re.sub(r"[^\w\s-]", "_", value.lower())
    safe = re.sub(r"[_\s]+", "_", safe).strip("_")
    max_len = 100
    if len(safe) > max_len:
        suffix = hashlib.sha256(value.encode()).hexdigest()[:8]
        safe = safe[:max_len] + "_" + suffix
    return f"{prefix}_{safe}"


def _load_cache(key: str):
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - data["_cached_at"] < SEARCH_CACHE_TTL:
            return data["result"]
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def _save_cache(key: str, result: any):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    data = {"_cached_at": time.time(), "result": result}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _select_timeout(key_name: str) -> float:
    return {
        "WRITER": settings.writer_timeout,
        "ANALYZER": settings.analyzer_timeout,
        "CHEAP": settings.cheap_timeout,
    }.get(key_name, settings.cheap_timeout)


def _call_llm(system_prompt: str, user_prompt: str, key_name: str = "CHEAP", temperature: float = 0.3) -> str:
    from openai import OpenAI

    model = settings.cheap_model
    timeout = _select_timeout(key_name)

    client = OpenAI(
        base_url=settings.ollama_base_url,
        api_key="ollama",
        timeout=timeout,
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=8192,
        extra_body={"keep_alive": "0s"},
    )

    content = response.choices[0].message.content
    if content is None:
        raise ValueError("LLM returned None content")
    return content.strip()


def search_web(query: str, max_results: int = 10, timelimit: str | None = None) -> list[dict]:
    if not query or not query.strip():
        return []

    key = _pointer_key("search", query)
    cached = _load_cache(key)
    if cached:
        return cached

    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results, timelimit=timelimit):
                results.append(
                    {
                        "title": r.get("title", ""),
                        "snippet": r.get("body", ""),
                        "url": r.get("href", ""),
                    }
                )
    except Exception:
        results = []

    _save_cache(key, results)
    return results


def fetch_rss(feed_url: str, max_articles: int = 10) -> list[dict]:
    key = _pointer_key("rss", feed_url)
    cached = _load_cache(key)
    if cached:
        return cached[:max_articles]

    entries = []
    try:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:max_articles]:
            entries.append(
                {
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "summary": entry.get("summary", "") or entry.get("description", ""),
                    "published": entry.get("published", "") or entry.get("updated", ""),
                }
            )
    except Exception:
        entries = []

    _save_cache(key, entries)
    return entries


def load_feed_subscriptions(config_path: str | None = None) -> list[str]:
    path = Path(config_path) if config_path else FEEDS_CONFIG_PATH
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("feeds", [])
    except (json.JSONDecodeError, KeyError):
        return []


def load_feeds_state(path: str | None = None) -> dict:
    state_path = Path(path) if path else FEEDS_STATE_PATH
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_feeds_state(state: dict, path: str | None = None):
    state_path = Path(path) if path else FEEDS_STATE_PATH
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


async def discover_from_feeds(config_path: str | None = None, track_seen: bool = True) -> list[dict]:
    feed_urls = load_feed_subscriptions(config_path)
    if not feed_urls:
        return []

    state = load_feeds_state() if track_seen else {}
    all_articles = []

    for feed_url in feed_urls:
        try:
            entries = fetch_rss(feed_url, max_articles=15)
        except Exception:
            continue
        feed_state = state.get(feed_url, {"seen": []})
        seen = set(feed_state.get("seen", []))

        for entry in entries:
            if track_seen and entry["url"] in seen:
                continue
            try:
                article = await fetch_article(entry["url"])
                article["_feed_source"] = feed_url
                all_articles.append(article)
            except Exception:
                pass
            if track_seen:
                seen.add(entry["url"])

        if track_seen:
            state[feed_url] = {"seen": list(seen)}

    if track_seen:
        save_feeds_state(state)
    return all_articles


def _deduplicate_articles(articles: list[dict]) -> list[dict]:
    seen_urls = set()
    deduped = []
    for a in articles:
        url = a.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduped.append(a)
    return deduped


def _extract_key_terms(query: str) -> list[str]:
    stop_words = {
        "the",
        "a",
        "an",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "by",
        "with",
        "from",
        "as",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "latest",
        "new",
        "recent",
        "about",
        "what",
        "how",
        "why",
        "when",
        "where",
        "who",
        "all",
        "any",
        "create",
        "make",
        "get",
        "find",
        "show",
        "tell",
        "give",
        "uploaded",
        "whatever",
        "them",
        "they",
        "their",
        "last",
        "week",
        "weeks",
        "day",
        "days",
        "month",
        "ago",
        "now",
        "then",
        "some",
        "things",
        "thing",
        "just",
        "like",
        "really",
        "very",
        "much",
        "many",
        "more",
        "also",
        "blog",
        "post",
        "write",
        "need",
        "want",
        "know",
        "think",
        "look",
        "first",
        "second",
        "next",
        "previous",
        "other",
        "another",
        "still",
        "well",
        "back",
        "going",
        "said",
        "says",
        "way",
        "even",
        "every",
    }
    words = re.findall(r"\b[a-zA-Z]{3,}\b", query.lower())
    return [w for w in words if w not in stop_words]


async def create_research_plan(query: str) -> dict:
    system_prompt = (
        "You are a research strategist. Convert the following user request "
        "into a precise, actionable research plan.\n\n"
        "Rules:\n"
        "- Extract specific entity names (companies, people, products, "
        "technologies) and use their exact names in queries\n"
        "- If the request mentions a timeframe, include time qualifiers in queries (e.g., '2026', 'past two weeks')\n"
        "- Prioritize primary sources: official announcements, press releases, earnings reports, company blogs\n"
        "- Generate 4-6 search queries that each target a different angle or sub-topic\n"
        "- Each query should be specific enough to find relevant content but broad enough to return results\n\n"
        "Return ONLY a JSON object with this exact structure:\n"
        "{\n"
        '  "topic": "concise topic in 8-12 words",\n'
        '  "entities": ["list of specific companies, people, or products mentioned"],\n'
        '  "sub_topics": ["angle 1", "angle 2", "angle 3"],\n'
        '  "search_queries": [\n'
        '    "specific search query 1",\n'
        '    "specific search query 2",\n'
        '    "specific search query 3",\n'
        '    "specific search query 4"'
        "  ],\n"
        '  "target_sources": ["press releases", "news analysis", "company blogs"],\n'
        '  "relevance_terms": ["keyword1", "keyword2", "keyword3"]\n'
        "}"
    )

    from agents.base import _call_llm_routed, get_groq_rate_limiter
    use_groq = settings.agent_uses_cloud("scout")
    if use_groq:
        limiter = get_groq_rate_limiter()
        est = limiter.estimate_tokens(system_prompt, query, 2048)
        await limiter.wait_if_needed(est)
    result = _call_llm_routed(system_prompt, query, key_name="CHEAP", use_groq=use_groq, max_tokens=2048)
    try:
        plan = json.loads(result)
        if not isinstance(plan.get("search_queries"), list):
            plan["search_queries"] = [query]
        if not isinstance(plan.get("relevance_terms"), list):
            plan["relevance_terms"] = _extract_key_terms(query)
        if not isinstance(plan.get("entities"), list):
            plan["entities"] = []
        return plan
    except (json.JSONDecodeError, TypeError):
        return {
            "topic": query[:80],
            "entities": [],
            "sub_topics": [],
            "search_queries": [query],
            "target_sources": ["news"],
            "relevance_terms": _extract_key_terms(query),
        }


async def deep_research(
    query: str,
    max_sources: int = 8,
    verbose: bool = False,
    plan: dict | None = None,
    year: int | None = None,
    relevance_terms: list[str] | None = None,
    entities: list[str] | None = None,
) -> list[dict]:
    if plan is None:
        if verbose:
            print("  Creating research plan...")
        plan = await create_research_plan(query)

    if relevance_terms is None:
        relevance_terms = plan.get("relevance_terms", _extract_key_terms(query))
    if entities is None:
        entities = plan.get("entities", [])

    timelimit = "y" if year and year >= _CURRENT_YEAR - 1 else None

    if verbose:
        print(f"  Topic: {plan.get('topic', query[:60])}")
        if entities:
            print(f"  Entities: {', '.join(entities[:5])}")
        print(f"  Queries: {len(plan.get('search_queries', []))}")

    all_search_results = []
    seen_urls = set()
    rep = _load_domain_reputation()

    queries = plan.get("search_queries", [query])
    num_queries = min(len(queries), max(3, max_sources))

    for i in range(0, num_queries, 2):
        batch = queries[i : i + 2]
        batch_results = []
        for q in batch:
            results = search_web(q, max_results=8, timelimit=timelimit)
            batch_results.extend(results)

        scored = []
        for r in batch_results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                text = (r.get("title", "") + " " + r.get("snippet", "")).lower()
                score = sum(1 for t in relevance_terms if t.lower() in text)
                if entities:
                    score += sum(2 for e in entities if e.lower() in text)
                score += _domain_boost(url, rep)
                scored.append((score, r))
                seen_urls.add(url)

        scored.sort(key=lambda x: -x[0])
        all_search_results.extend([r for _, r in scored[:4]])

    if verbose:
        print(f"  Unique results: {len(all_search_results)}")

    async def _sem_fetch(url: str) -> dict | Exception:
        async with _fetch_semaphore:
            return await fetch_article(url)

    tasks = []
    for r in all_search_results[: max_sources + 3]:
        url = r.get("url", "")
        if url:
            tasks.append(_sem_fetch(url))

    if verbose:
        print(f"  Fetching {len(tasks)} articles...")

    fetched = await asyncio.gather(*tasks, return_exceptions=True)
    articles = []
    for a in fetched:
        if isinstance(a, dict) and a.get("body"):
            text = (a.get("title", "") + " " + a.get("body", "") + " " + a.get("summary", "")).lower()
            score = sum(1 for t in relevance_terms if t.lower() in text)
            if entities:
                score += sum(2 for e in entities if e.lower() in text)
            score += _domain_boost(a.get("url", ""), rep)
            a["_relevance_score"] = score
            articles.append(a)

    articles.sort(key=lambda a: -a.get("_relevance_score", 0))
    seen = set()
    deduped = []
    for a in articles:
        url = a.get("url", "")
        if url not in seen:
            seen.add(url)
            deduped.append(a)
    articles = deduped

    if verbose:
        print(f"  [OK] {len(articles)} articles after scoring + dedup")
        for a in articles[:3]:
            title = a.get("title", "Untitled")[:65]
            score = a.get("_relevance_score", 0)
            print(f"    [{score}] {title}")
        if len(articles) > 3:
            print(f"    ... and {len(articles) - 3} more")

    if len(articles) < max_sources and verbose:
        print(f"  Follow-up search ({len(articles)}/{max_sources})...")
        follow_up = relevance_terms[:3]
        if entities:
            follow_up = entities[:3] + follow_up
        more_query = " ".join(follow_up).strip()
        if not more_query:
            more_query = query
        more_results = search_web(more_query, max_results=10, timelimit=timelimit)
        more_tasks = []
        for r in more_results:
            url = r.get("url", "")
            if url and url not in seen:
                seen.add(url)
                more_tasks.append(_sem_fetch(url))
        if more_tasks:
            more_fetched = await asyncio.gather(*more_tasks, return_exceptions=True)
            for a in more_fetched:
                if isinstance(a, dict) and a.get("body"):
                    a["_relevance_score"] = 0
                    articles.append(a)
            articles.sort(key=lambda x: -x.get("_relevance_score", 0))

    alt_needed = max_sources - len(articles)
    if alt_needed > 0:
        if verbose:
            print(f"  Alternative sources ({alt_needed} more needed)...")
        alt_results = await _search_alt_sources(query, alt_needed + 2)
        alt_tasks = []
        for r in alt_results:
            url = r.get("url", "")
            if url and url not in seen:
                seen.add(url)
                alt_tasks.append(_sem_fetch(url))
        if alt_tasks:
            alt_fetched = await asyncio.gather(*alt_tasks, return_exceptions=True)
            alt_articles = []
            for a in alt_fetched:
                if isinstance(a, dict) and a.get("body"):
                    alt_articles.append(a)
            if alt_articles:
                _score_articles(alt_articles, relevance_terms, entities)
                alt_articles = [a for a in alt_articles if a.get("_relevance_score", 0) >= 1]
                articles.extend(alt_articles)
            articles.sort(key=lambda x: -x.get("_relevance_score", 0))

    if year:
        articles = _filter_by_year(articles, year)

    return articles[:max_sources]


def _detect_input_type(input_data: str) -> str:
    input_data = input_data.strip()
    if input_data.startswith(("http://", "https://")):
        feed_indicators = ["feed", "rss", "atom", ".xml", ".rss", ".atom"]
        if any(ind in input_data.lower() for ind in feed_indicators):
            return "rss"
        return "url"
    if input_data.lower() in ("feeds", "subscriptions", "subscribed"):
        return "feeds"
    word_count = len(input_data.split())
    if word_count < 10:
        return "topic"
    return "idea"


def _domain_boost(url: str, rep: dict[str, dict]) -> float:
    if not url:
        return 0
    domain = urlparse(url).netloc.removeprefix("www.")
    entry = rep.get(domain)
    if entry and entry.get("count", 0) > 0:
        return min(entry["score"] / 20.0, 5.0)
    return 0


def _score_articles(
    articles: list[dict],
    relevance_terms: list[str],
    entities: list[str] | None = None,
) -> None:
    rep = _load_domain_reputation()
    for a in articles:
        text = (a.get("title", "") + " " + a.get("body", "") + " " + a.get("summary", "")).lower()
        score = sum(1 for t in relevance_terms if t.lower() in text)
        if entities:
            score += sum(2 for e in entities if e.lower() in text)
        score += _domain_boost(a.get("url", ""), rep)
        a["_relevance_score"] = score


async def discover_sources(
    input_data: str,
    input_type: str = "auto",
    max_sources: int = 5,
    verbose: bool = False,
) -> list[dict]:
    if input_type == "auto":
        input_type = _detect_input_type(input_data)

    articles = []

    if input_type == "url":
        try:
            article = await fetch_article(input_data)
            if article:
                articles.append(article)
        except Exception:
            pass
        return articles

    if input_type == "rss":
        entries = fetch_rss(input_data, max_articles=max_sources)
        for entry in entries:
            try:
                article = await fetch_article(entry["url"])
                if article:
                    articles.append(article)
            except Exception:
                pass
        return articles[:max_sources]

    if input_type == "feeds":
        articles = await discover_from_feeds()
        return articles[:max_sources]

    if input_type in ("topic", "idea"):
        year = _extract_year(input_data)
        plan = await create_research_plan(input_data)
        relevance_terms = plan.get("relevance_terms", _extract_key_terms(input_data))
        entities = plan.get("entities", [])

        rss_target = max(1, int(max_sources * 0.6 + 0.5))
        ddgs_target = max_sources - rss_target

        if verbose:
            print(f"  RSS target: {rss_target}, DDGS target: {ddgs_target}")

        rss_articles = await discover_from_feeds(track_seen=False)
        if rss_articles:
            _score_articles(rss_articles, relevance_terms, entities)
            rss_articles.sort(key=lambda a: -a.get("_relevance_score", 0))
            if verbose and rss_articles:
                print(f"  RSS: {len(rss_articles)} articles, top score {rss_articles[0].get('_relevance_score', 0)}")
        else:
            if verbose:
                print("  RSS: no articles found")

        ddgs_articles = await deep_research(
            input_data,
            max_sources=ddgs_target + 2,
            verbose=verbose,
            plan=plan,
            year=year,
            relevance_terms=relevance_terms,
            entities=entities,
        )

        all_articles = _deduplicate_articles(rss_articles + ddgs_articles)
        all_articles.sort(key=lambda a: -a.get("_relevance_score", 0))

        if year:
            all_articles = _filter_by_year(all_articles, year)

        return all_articles[:max_sources]

    return articles
