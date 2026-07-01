from __future__ import annotations

import json

from agents.base import BaseAgent
from agents.context import BlogContext, ChapterPlan, _is_chapter_depth
from formatter import _build_source_text, _truncate_sources


class DocumentArchitectAgent(BaseAgent):
    name = "document_architect"
    model = "qwen2.5:3b"
    key_name = "WRITER"
    temperature = 0.4
    max_tokens = 2048

    SYSTEM = (
        "You are a document architect. You plan the high-level structure of long-form content. "
        "Given source materials and a content analysis, you divide the document into chapters — "
        "each with a focused theme, a clear purpose, and a target number of sections.\n\n"
        "Rules:\n"
        "- Plan 3-6 chapters depending on the breadth of the material\n"
        "- Each chapter must have a specific, thematic title\n"
        "- Each chapter must have a distinct purpose that advances the narrative\n"
        "- Assign each chapter a target section count (3-6 sections)\n"
        "- The first chapter should set context; the last should conclude\n"
        "- Chapters should follow a logical progression\n"
        "Return ONLY a JSON array of chapter objects."
    )

    def build_prompt(self, ctx: BlogContext) -> tuple[str, str]:
        analysis_text = json.dumps(ctx.analysis, indent=2)
        sources_text = _truncate_sources(_build_source_text(ctx.articles), max_chars=self._source_limit())

        total_sections = 25 if ctx.depth == "comprehensive" else 16

        user = (
            f"Content analysis:\n{analysis_text}\n\n"
            f"Source materials:\n{sources_text}\n\n"
            f"Create a chapter-level blueprint as a JSON array. "
            f"Target {total_sections} sections total across all chapters. "
            f"Each element must have:\n"
            '- "title": chapter title (thematic, not generic)\n'
            '- "purpose": 1-2 sentences explaining what this chapter achieves\n'
            '- "section_count": number of sections in this chapter (3-6)\n\n'
            "Cover all key themes from the analysis. "
            "Output ONLY the JSON array, nothing else."
        )
        return self.SYSTEM, user

    def parse_output(self, raw: str) -> list:
        cleaned = super().parse_output(raw)
        if isinstance(cleaned, dict):
            cleaned = cleaned.get("chapters", [])
        if not isinstance(cleaned, list):
            raise ValueError(f"Expected list, got {type(cleaned).__name__}")
        return cleaned

    def apply_result(self, ctx: BlogContext, parsed: list) -> BlogContext:
        ctx.chapters = []
        for ch in parsed:
            ctx.chapters.append(ChapterPlan(
                title=ch.get("title", "Untitled Chapter"),
                purpose=ch.get("purpose", ""),
                section_count=ch.get("section_count", 4),
            ))
        return ctx

    async def run(self, ctx: BlogContext) -> BlogContext:
        if not _is_chapter_depth(ctx.depth):
            return ctx
        return await super().run(ctx)
