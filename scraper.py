import asyncio
import json
import random
import time
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup

from config import settings

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

CACHE_DIR = settings.cache_dir_path
CACHE_TTL = settings.cache_ttl
RETRY_ATTEMPTS = settings.retry_attempts
RETRY_DELAY = settings.retry_delay


def _pointer_key(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "").replace(".", "_")
    path = parsed.path.strip("/").replace("/", "_") if parsed.path else "index"
    if not path:
        path = "index"
    safe = f"{domain}_{path}"[:120]
    return safe


def _cache_key(url: str) -> str:
    return _pointer_key(url)


def _load_cache(key: str) -> dict | None:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - data["_cached_at"] < CACHE_TTL:
            return data["article"]
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def _save_cache(key: str, article: dict):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    data = {"_cached_at": time.time(), "article": article}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def fetch_page(url: str) -> str:
    key = _cache_key(url)
    cached = _load_cache(key)
    if cached:
        return cached.get("_raw_html", "")

    last_exc = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": USER_AGENT},
                    follow_redirects=True,
                )
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                retry_after = int(e.response.headers.get("Retry-After", str(RETRY_DELAY * attempt)))
                await asyncio.sleep(min(retry_after, 30))
            elif attempt < RETRY_ATTEMPTS:
                wait = RETRY_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 1)
                await asyncio.sleep(min(wait, 30))
            last_exc = e
        except httpx.RequestError as e:
            if attempt < RETRY_ATTEMPTS:
                wait = RETRY_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 1)
                await asyncio.sleep(min(wait, 30))
            last_exc = e
    raise RuntimeError(f"Failed to fetch {url} after {RETRY_ATTEMPTS} attempts: {last_exc}")


async def fetch_article(url: str) -> dict:
    key = _cache_key(url)
    cached = _load_cache(key)
    if cached:
        return cached

    html = await fetch_page(url)
    article = _extract_with_trafilatura(html, url)

    if not article.get("body") or len(article["body"]) < 50:
        article = _extract_with_beautifulsoup(html, url)

    _save_cache(key, article)
    return article


def _extract_with_trafilatura(html: str, url: str) -> dict:
    result = trafilatura.extract(
        html,
        url=url,
        output_format="txt",
        include_links=True,
        include_images=False,
        include_tables=False,
        favor_precision=True,
    )

    body = result.strip() if result else ""

    soup = BeautifulSoup(html, "lxml")
    tables_md = _extract_tables(soup)
    if tables_md:
        if body:
            body += "\n\n" + tables_md
        else:
            body = tables_md

    metadata = trafilatura.extract(
        html,
        url=url,
        output_format="json",
        include_links=False,
        include_images=False,
        favor_precision=True,
    )

    title = ""
    date = ""
    author = ""
    summary = ""
    if metadata:
        try:
            meta = json.loads(metadata)
            if isinstance(meta, dict):
                title = meta.get("title", "")
                date = meta.get("date", "")
                author = meta.get("author", "")
            elif isinstance(meta, list) and len(meta) > 0:
                title = meta[0].get("title", "")
                date = meta[0].get("date", "")
                author = meta[0].get("author", "")
        except (json.JSONDecodeError, KeyError, IndexError):
            pass

    images = _extract_images(soup, url)

    if not summary:
        summary = _extract_summary(soup)

    if not title:
        title = _extract_title(soup)

    return {
        "title": title,
        "date": date,
        "author": author,
        "body": body,
        "summary": summary,
        "images": images,
        "url": url,
    }


def _extract_with_beautifulsoup(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    tables_md = _extract_tables(soup)

    article = {
        "title": _extract_title(soup),
        "date": _extract_date(soup),
        "author": _extract_author(soup),
        "body": _extract_body(soup, tables_md),
        "summary": _extract_summary(soup),
        "images": _extract_images(soup, url),
        "url": url,
    }

    return article


def _extract_tables(soup: BeautifulSoup) -> str:
    tables = soup.find_all("table")
    if not tables:
        return ""

    markdown_tables = []
    for table in tables:
        rows = table.find_all("tr")
        if not rows:
            continue

        headers = []
        header_row = rows[0]
        th_cells = header_row.find_all("th")
        if th_cells:
            headers = [cell.get_text(strip=True) for cell in th_cells]
            data_rows = rows[1:]
        else:
            td_cells = header_row.find_all("td")
            if td_cells:
                headers = [f"Column {i + 1}" for i in range(len(td_cells))]
                data_rows = rows
            else:
                continue

        if len(headers) < 2:
            continue

        table_lines = []
        table_lines.append("| " + " | ".join(headers) + " |")
        table_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        for row in data_rows:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            cell_texts = []
            for i, cell in enumerate(cells):
                text = cell.get_text(strip=True)
                cell_texts.append(text if text else "—")
            while len(cell_texts) < len(headers):
                cell_texts.append("—")
            table_lines.append("| " + " | ".join(cell_texts[: len(headers)]) + " |")

        markdown_tables.append("\n".join(table_lines))

    return "\n\n".join(markdown_tables)


def _extract_title(soup: BeautifulSoup) -> str:
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return ""


def _extract_date(soup: BeautifulSoup) -> str:
    for meta in soup.find_all("meta"):
        prop = (meta.get("property", "") or meta.get("name", "")).lower()
        if any(k in prop for k in ["date", "published_time", "article:published_time"]):
            content = meta.get("content", "")
            if content:
                return content.split("T")[0] if "T" in content else content
    for time_tag in soup.find_all("time"):
        dt = time_tag.get("datetime") or time_tag.get_text(strip=True)
        if dt:
            return dt
    return ""


def _extract_author(soup: BeautifulSoup) -> str:
    for meta in [
        soup.find("meta", property="article:author"),
        soup.find("meta", attrs={"name": "author"}),
    ]:
        if meta and meta.get("content"):
            return meta["content"].strip()
    for cls in ["author", "byline", "writer"]:
        el = soup.find(class_=lambda c: c and cls in c.lower() if c else False)
        if el:
            return el.get_text(strip=True)
    return ""


def _extract_body(soup: BeautifulSoup, tables_md: str | None = None) -> str:
    if tables_md is None:
        tables_md = _extract_tables(soup)
    article = (
        soup.find("article")
        or soup.find("main")
        or soup.find("div", attrs={"role": "main"})
        or soup.find("section", attrs={"role": "main"})
    )
    if not article:
        for cls in ["post-content", "article-content", "entry-content", "story-body", "content"]:
            article = soup.find(class_=lambda c: c and cls in c.lower() if c else False)
            if article:
                break
    if not article:
        article = soup.body
    if not article:
        return tables_md if tables_md else ""

    parts = []
    for el in article.find_all(["p", "ul", "ol", "blockquote", "h2", "h3"], recursive=True):
        tag = el.name
        text = el.get_text(strip=True)

        if tag == "p" and len(text) > 20:
            parts.append(text)
        elif tag in ("ul", "ol"):
            items = []
            for li in el.find_all("li", recursive=False):
                li_text = li.get_text(strip=True)
                if li_text:
                    items.append(f"- {li_text}")
            if items:
                parts.append("\n".join(items))
        elif tag == "blockquote":
            q = el.get_text(strip=True)
            if len(q) > 20:
                parts.append(f"> {q}")
        elif tag in ("h2", "h3") and len(text) > 5:
            parts.append(f"## {text}")

    body = "\n\n".join(parts) if parts else ""

    if tables_md:
        if body:
            body += "\n\n" + tables_md
        else:
            body = tables_md

    return body


def _extract_summary(soup: BeautifulSoup) -> str:
    for meta in [
        soup.find("meta", property="og:description"),
        soup.find("meta", attrs={"name": "description"}),
    ]:
        if meta and meta.get("content"):
            return meta["content"].strip()
    return ""


def _extract_images(soup: BeautifulSoup, page_url: str) -> list:
    images = []
    seen = set()

    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        url = og_image["content"].strip()
        if url not in seen:
            images.append({"url": url, "alt": ""})
            seen.add(url)

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src or src.startswith("data:"):
            continue
        if len(seen) >= 5:
            break
        full_url = src if src.startswith("http") else urljoin(page_url, src)
        if full_url not in seen:
            images.append({"url": full_url, "alt": img.get("alt", "") or ""})
            seen.add(full_url)

    return images
