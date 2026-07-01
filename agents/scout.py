from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from agents.base import AgentError, BaseAgent
from agents.context import BlogContext
from config import settings
from formatter import _build_source_text
from researcher import discover_sources


def _detect_file_or_text(input_data: str) -> tuple[str, str]:
    stripped = input_data.strip()
    if input_data.startswith("file:"):
        path = input_data[5:].strip()
        return "file", path
    if stripped.startswith(("http://", "https://", "www.")):
        return "auto", input_data
    if len(stripped) > 100 and not stripped.startswith("feeds"):
        return "text", stripped
    return "auto", input_data


def _read_file(path_str: str) -> str:
    p = Path(path_str)
    if not p.exists():
        raise AgentError("scout", f"File not found: {path_str}")
    if p.suffix.lower() == ".pdf":
        return _read_pdf(p)
    return p.read_text(encoding="utf-8")


def _read_pdf(path: Path) -> str:
    try:
        import fitz
    except ImportError:
        raise AgentError("scout",
            "PDF support requires PyMuPDF. Install it: pip install PyMuPDF")
    text_parts = []
    doc = fitz.open(str(path))
    for page in doc:
        text_parts.append(page.get_text())
    doc.close()
    return "\n\n".join(text_parts)


def _make_article_from_text(text: str, source: str = "paste") -> dict:
    lines = text.split("\n")
    title_line = ""
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) > 10:
            title_line = stripped[:80]
            break
    return {
        "title": title_line or "User-provided content",
        "date": datetime.now().isoformat(),
        "author": "",
        "body": text,
        "summary": text[:200],
        "images": [],
        "url": "",
    }


class ScoutAgent(BaseAgent):
    name = "scout"
    model = settings.cheap_model
    key_name = "CHEAP"

    def build_prompt(self, ctx: BlogContext) -> tuple[str, str]:
        return "", ""

    def apply_result(self, ctx: BlogContext, parsed: dict | list) -> BlogContext:
        return ctx

    async def run(self, ctx: BlogContext) -> BlogContext:
        try:
            verbose = ctx.verbose
            input_type = ctx.input_type
            if input_type == "auto":
                input_type, resolved_data = _detect_file_or_text(ctx.input_data)
                ctx.input_type = input_type

            if input_type == "file":
                text = _read_file(ctx.input_data[5:].strip())
                ctx.articles = [_make_article_from_text(text, source="file")]
                ctx.input_type = "text"
            elif input_type == "text":
                ctx.articles = [_make_article_from_text(ctx.input_data, source="paste")]
            else:
                if verbose:
                    print("  Searching web for sources...")
                try:
                    articles = await asyncio.wait_for(
                        discover_sources(
                            ctx.input_data,
                            input_type,
                            max_sources=3,
                            verbose=verbose,
                        ),
                        timeout=60,
                    )
                    ctx.articles = articles
                except asyncio.TimeoutError:
                    if verbose:
                        print("  [TIMEOUT] Web search took >60s — falling back to query as article")
                    ctx.articles = [_make_article_from_text(ctx.input_data, source="fallback")]
                    ctx.input_type = "text"

            if not ctx.articles:
                if verbose:
                    print("  [FALLBACK] No web sources found — using query as article")
                ctx.articles = [_make_article_from_text(ctx.input_data, source="fallback")]
                ctx.input_type = "text"

            ctx.sources_text = _build_source_text(ctx.articles)

            return ctx
        except AgentError:
            raise
        except Exception as e:
            raise AgentError(self.name, f"Scout failed: {e}", original=e)
