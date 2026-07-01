import json
from pathlib import Path

from openai import OpenAI

from config import settings

MAX_SOURCE_CHARS = settings.max_source_chars
LESSONS_PATH = Path(settings.cache_dir) / ".learned_lessons.json"
MAX_LESSONS = 10


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        cleaned = []
        for line in lines:
            if line.strip().startswith("```"):
                continue
            cleaned.append(line)
        return "\n".join(cleaned).strip()
    return text


def _truncate_sources(sources_text: str, max_chars: int = MAX_SOURCE_CHARS) -> str:
    if len(sources_text) <= max_chars:
        return sources_text
    return sources_text[:max_chars] + "\n\n[Source text truncated due to length...]"


def _select_timeout(key_name: str) -> float:
    return {
        "WRITER": settings.writer_timeout,
        "ANALYZER": settings.analyzer_timeout,
        "CHEAP": settings.cheap_timeout,
    }.get(key_name, settings.writer_timeout)


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    key_name: str = "WRITER",
    temperature: float = 0.7,
    max_tokens: int = 8192,
) -> str:
    model = settings.writer_model if key_name == "WRITER" else settings.analyzer_model
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
        max_tokens=max_tokens,
        extra_body={"keep_alive": "0s"},
    )

    content = response.choices[0].message.content
    if content is None:
        raise ValueError("LLM returned None content")
    return content


def _load_lessons() -> list[str]:
    if LESSONS_PATH.exists():
        try:
            data = json.loads(LESSONS_PATH.read_text(encoding="utf-8"))
            return data.get("lessons", [])
        except (json.JSONDecodeError, KeyError):
            pass
    return []


def _save_lessons(lessons: list[str]):
    LESSONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {"lessons": lessons[-MAX_LESSONS:]}
    LESSONS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_lessons_from_critique(critique: dict) -> list[str]:
    new_lessons = []
    for issue in critique.get("issues", [])[:2]:
        issue_lower = issue.lower()
        if any(kw in issue_lower for kw in ["vague", "specific", "example", "data", "detail", "source", "citation"]):
            new_lessons.append(f"AVOID: {issue.strip().rstrip('.')}")
    combined = _load_lessons() + new_lessons
    seen = set()
    deduped = []
    for lesson in combined:
        key = lesson.lower()[:80]
        if key not in seen:
            seen.add(key)
            deduped.append(lesson)
    _save_lessons(deduped)
    return new_lessons


def _build_source_text(articles: list[dict]) -> str:
    parts = []
    for i, article in enumerate(articles, 1):
        images_text = ""
        if article.get("images"):
            images_text = "\n\nImages:\n" + "\n".join(
                f"- {img['alt'] or '(no alt)'}: {img['url']}" for img in article["images"]
            )
        parts.append(
            f"--- Source {i} ---\n"
            f"TITLE: {article.get('title', '')}\n"
            f"DATE: {article.get('date', '')}\n"
            f"AUTHOR: {article.get('author', '')}\n"
            f"URL: {article.get('url', '')}\n"
            f"SUMMARY: {article.get('summary', '')}\n"
            f"BODY:\n{article.get('body', '')}"
            f"{images_text}"
        )
    return "\n\n".join(parts)


def analyze_content(articles: list[dict], topic: str = "") -> dict:
    sources_text = _truncate_sources(_build_source_text(articles))
    topic_line = f"\nTopic: {topic}" if topic else ""

    prompt = (
        f"Analyze these source materials for writing a blog post.{topic_line}\n\n"
        f"{sources_text}\n\n"
        "Return ONLY a JSON object with these fields:\n"
        "- content_type: comparison, news_analysis, tutorial, opinion, digest, listicle, trend_analysis\n"
        "- topic: the main topic in 5-10 words\n"
        "- key_themes: list of 2-4 key themes\n"
        "- table_candidates: list of objects with {title, columns: [col1, col2, ...]}. "
        "If ANY source contains comparative data (pricing, specs, features, side-by-side), "
        "statistical data, or structured information — flag it here. "
        "Look for: product comparisons, feature matrices, pricing tiers, "
        "timelines with dates and events, statistics, survey results, "
        "specifications, or any data that would be clearer in a table. "
        "Return empty list if none.\n"
        "- list_candidates: list of objects with {title, items: [item1, item2, ...]}. "
        "Identify any data better presented as bullet lists: key takeaways, feature lists, "
        "pros/cons, action items, steps, or collections of related facts. "
        "Return empty list if none.\n"
        "- timeline_events: list of {date, event} for chronological information, or empty list\n"
        "- target_audience: string describing who this is for\n"
        "- recommended_tone: analytical, conversational, authoritative, enthusiastic, balanced\n"
        "Do not include any text outside the JSON."
    )

    result = _call_llm(
        "You are a content analyst. You identify structural patterns in source materials "
        "and flag data that belongs in tables.",
        prompt,
        key_name="ANALYZER",
        temperature=0.3,
    )

    result = _extract_json(result)
    try:
        return json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return {
            "content_type": "news_analysis",
            "topic": topic or "untitled",
            "key_themes": [],
            "table_candidates": [],
            "list_candidates": [],
            "timeline_events": [],
            "target_audience": "general readers",
            "recommended_tone": "balanced",
        }


def write_blog(articles: list[dict], analysis: dict) -> str:
    sources_text = _truncate_sources(_build_source_text(articles))
    analysis_text = json.dumps(analysis, indent=2)

    lessons = _load_lessons()
    lessons_block = ""
    if lessons:
        lessons_block = "\n".join(f"- {lesson}" for lesson in lessons)
        lessons_block = f"\nCOMMON ISSUES TO AVOID (from past critiques):\n{lessons_block}\n"

    list_analysis = ""
    if analysis.get("list_candidates"):
        list_analysis = "\n\nDATA FOR BULLET LISTS:\n" + "\n".join(
            f"- {lc['title']}: " + "; ".join(lc.get("items", []))
            for lc in analysis["list_candidates"]
        )

    system_prompt = (
        "You are an expert blog writer. You write compelling, fact-dense blog posts "
        "that adapt their format to the content.\n\n"
        "CRITICAL RULES:\n"
        "- Every claim must be backed by specific information from the source articles. "
        "Name specific companies, people, products, and exact figures.\n"
        "- NEVER use vague language like 'some companies', 'several reports', 'many experts'. "
        "Instead say exactly which companies, which reports, which experts.\n"
        "- If sources contain prices, percentages, dates, or statistics — include them precisely.\n"
        "- Use markdown bullet points (- item) to list key points, features, benefits, "
        "reasons, takeaways, or any collection of related items. Each bullet should be "
        "a complete sentence. Aim for 3-6 items per list.\n"
        "- Use numbered lists (1. item) for sequential steps, rankings, or ordered processes.\n"
        "- NEVER present a list of items as a dense paragraph — always break them into "
        "bulleted or numbered lists for readability.\n"
        "- Use markdown tables when presenting comparisons, features, pricing, "
        "or any structured data. Tables should have clear headers and aligned columns.\n"
        "- Use blockquotes for direct quotes from source articles.\n"
        "- Use italics (wrapped in *single asterisks*) for emphasis on key terms, "
        "phrases, or to highlight contrasting points.\n"
        "- For chronological information, present as a timeline or date-anchored table.\n"
        "- Choose section headers that make sense for THIS content — do not use generic headers.\n"
        "- Match the tone to the content type: analytical for deep dives, "
        "conversational for trends, authoritative for analysis.\n"
        "- For multi-source articles, synthesize across sources — do not summarize each source in sequence.\n"
        "- Output ONLY the complete blog post in markdown. No explanations, no notes.\n"
        "- The title must be specific and compelling."
        f"{lessons_block}"
    )

    user_prompt = (
        f"Write a blog post based on the following source materials and content analysis.\n\n"
        f"CONTENT ANALYSIS:\n{analysis_text}{list_analysis}\n\n"
        f"SOURCE MATERIALS:\n{sources_text}\n\n"
        f"Write the blog post now. Use the content analysis as a guide. "
        f"Be specific — name names, cite exact figures, use tables where it adds clarity."
        f"\n\nUse bullet lists (- item) for key points, numbered lists (1. item) for steps, "
        f"and tables for comparisons. Break up dense information into readable lists."
    )

    return _call_llm(system_prompt, user_prompt, key_name="WRITER")


def critique_blog(draft: str, articles: list[dict]) -> dict:
    sources_text = _truncate_sources(_build_source_text(articles))

    system_prompt = (
        "You are a rigorous blog post editor. Review the draft against the original sources.\n\n"
        "Score DOWN for:\n"
        "- Vague claims without specific names, figures, or dates (e.g. 'some companies' instead of naming them)\n"
        "- Hallucinations or facts not present in the source materials\n"
        "- Missing source attribution for key claims\n"
        "- Poor structure — format doesn't match content type\n"
        "- Missing tables where comparative/structured data exists in sources\n"
        "- Walls of text that should be broken into bullet lists (key points, features, "
        "reasons presented as dense paragraphs instead of lists)\n"
        "- Generic or boring section headers\n"
        "- Factual inaccuracies\n\n"
        "Return ONLY a JSON object:\n"
        "{\n"
        '  "score": <1-10>,\n'
        '  "issues": ["specific issue 1", "specific issue 2", ...],\n'
        '  "suggestions": ["specific fix 1", "specific fix 2", ...]\n'
        "}"
    )

    user_prompt = (
        f"BLOG POST DRAFT:\n\n{draft}\n\n"
        f"SOURCE MATERIALS:\n\n{sources_text}\n\n"
        "Review the draft against the sources. Be strict about vagueness and accuracy."
    )

    result = _call_llm(system_prompt, user_prompt, key_name="ANALYZER", temperature=0.3)

    result = _extract_json(result)
    try:
        critique = json.loads(result)
        if not isinstance(critique.get("issues"), list):
            critique["issues"] = []
        if not isinstance(critique.get("suggestions"), list):
            critique["suggestions"] = []
        raw_score = critique.get("score", 5)
        try:
            score_val = float(raw_score)
        except (TypeError, ValueError):
            score_val = 5.0
        critique["score"] = max(1, min(10, int(round(score_val))))
        return critique
    except (json.JSONDecodeError, TypeError, ValueError):
        return {
            "score": 5,
            "issues": ["Could not parse critique"],
            "suggestions": ["Review and revise manually"],
        }


def refine_blog(draft: str, critique: dict, articles: list[dict]) -> str:
    sources_text = _truncate_sources(_build_source_text(articles))
    critique_text = json.dumps(critique, indent=2)

    system_prompt = (
        "You are a blog post editor. Revise the draft based on the critique provided.\n\n"
        "Fix every issue mentioned. Address every suggestion.\n"
        "Make the revision more specific — add names, figures, dates where missing.\n"
        "Add tables where the critique suggests them.\n"
        "Convert dense paragraphs listing multiple items into bullet points (- item format).\n"
        "Output the complete revised blog post in markdown. No explanations."
    )

    user_prompt = (
        f"ORIGINAL DRAFT:\n\n{draft}\n\n"
        f"CRITIQUE:\n\n{critique_text}\n\n"
        f"SOURCE MATERIALS:\n\n{sources_text}\n\n"
        "Revise the draft based on the critique. Output ONLY the revised blog post."
    )

    return _call_llm(system_prompt, user_prompt, key_name="WRITER")


def format_article(article: dict, template_name: str = "default", output_path: str | None = None) -> str:
    result = write_blog([article], analyze_content([article]))
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result, encoding="utf-8")
    return result


def format_articles(articles: list[dict], template_name: str = "default", output_path: str | None = None) -> str:
    result = write_blog(articles, analyze_content(articles))
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result, encoding="utf-8")
    return result
