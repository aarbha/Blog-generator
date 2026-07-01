from __future__ import annotations

import json

from agents.base import BaseAgent
from agents.context import BlogContext, SectionPlan
from config import settings


class ChapterArchitectAgent(BaseAgent):
    name = "chapter_architect"
    model = "qwen2.5:3b"
    key_name = "WRITER"
    temperature = 0.4
    max_tokens = 2048

    SYSTEM = (
        "You are a chapter architect. Given the overall content analysis and the purpose "
        "of one specific chapter, you create detailed section plans for that chapter.\n\n"
        "Rules:\n"
        "- Each section must have a specific, non-generic title\n"
        "- Mix formats: use tables for comparative data, bullet lists for features/reasons, "
        "numbered lists for steps\n"
        "- Each section must contribute to the chapter's purpose\n"
        "- Sections should flow logically within the chapter\n"
        "Return ONLY a JSON array of section objects."
    )

    def build_prompt(self, ctx: BlogContext, chapter_index: int) -> tuple[str, str]:
        chapter = ctx.chapters[chapter_index]
        analysis_text = json.dumps(ctx.analysis, indent=2)

        chapters_context = ""
        for i, ch in enumerate(ctx.chapters):
            marker = " ← YOU ARE HERE" if i == chapter_index else ""
            chapters_context += f"  {i+1}. \"{ch.title}\" — {ch.purpose}{marker}\n"

        user = (
            f"Overall content analysis:\n{analysis_text}\n\n"
            f"Document structure:\n{chapters_context}\n\n"
            f"NOW PLAN SECTIONS FOR: \"{chapter.title}\"\n"
            f"Chapter purpose: {chapter.purpose}\n"
            f"Target section count: {chapter.section_count}\n\n"
            f"Create section plans as a JSON array. Each element must have:\n"
            '- "title": section title (specific, not generic)\n'
            '- "key_points": array of 2-4 bullet points this section must cover\n'
            '- "format_instructions": string — e.g. "Use a table comparing X and Y", '
            '"Present as 4-6 bullet points", "Write as prose"\n'
            '- "target_word_count": number (300-500)\n'
            '- "source_refs": array of source numbers this section should reference\n\n'
            "Output ONLY the JSON array, nothing else."
        )
        return self.SYSTEM, user

    def parse_output(self, raw: str) -> list:
        cleaned = super().parse_output(raw)
        if isinstance(cleaned, dict):
            cleaned = cleaned.get("sections", [])
        if not isinstance(cleaned, list):
            raise ValueError(f"Expected list, got {type(cleaned).__name__}")
        return cleaned

    def apply_result(self, ctx: BlogContext, parsed: list) -> BlogContext:
        return ctx

    async def run_chapter(self, ctx: BlogContext, chapter_index: int) -> BlogContext:
        import asyncio
        try:
            system, user = self.build_prompt(ctx, chapter_index)
            from agents.base import _call_llm_routed, get_groq_rate_limiter
            use_groq = settings.agent_uses_cloud(self.name)
            if use_groq:
                limiter = get_groq_rate_limiter()
                est = limiter.estimate_tokens(system, user, self.max_tokens)
                await limiter.wait_if_needed(est)
            raw = await asyncio.to_thread(
                _call_llm_routed,
                system, user,
                None, self.key_name,
                None, self.temperature, self.max_tokens,
                use_groq,
            )
            parsed = self.parse_output(raw)
            chapter = ctx.chapters[chapter_index]
            for sec in parsed:
                ctx.outline.append(SectionPlan(
                    title=sec.get("title", "Untitled Section"),
                    key_points=sec.get("key_points", []),
                    format_instructions=sec.get("format_instructions", ""),
                    target_word_count=sec.get("target_word_count", 400),
                    source_refs=sec.get("source_refs", []),
                    chapter_index=chapter_index,
                    chapter_title=chapter.title,
                ))
            return ctx
        except Exception as e:
            from agents.base import AgentError
            raise AgentError(self.name, f"Chapter {chapter_index} failed: {e}", original=e)
