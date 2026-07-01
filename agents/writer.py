from __future__ import annotations

from agents.base import (
    BaseAgent,
    _call_llm_routed,
    _select_timeout,
    get_groq_rate_limiter,
)
from agents.context import BlogContext
from config import settings
from formatter import _load_lessons


class WriterAgent(BaseAgent):
    name = "writer"
    model = "gemma2:2b"
    key_name = "WRITER"
    temperature = 0.7
    max_tokens = 2048

    SECTION_SYSTEM = (
        "You are an expert blog section writer. You write one section of a blog post at a time. "
        "The section must be self-contained but flow from what came before.\n\n"
        "CRITICAL RULES:\n"
        "- Every claim must be backed by specific information from the source articles. "
        "Name specific companies, people, products, and exact figures.\n"
        "- NEVER use vague language like 'some companies', 'several reports', 'many experts'. "
        "Instead say exactly which companies, which reports, which experts.\n"
        "- If sources contain prices, percentages, dates, or statistics — include them precisely.\n"
        "- Follow the format instructions for this section exactly.\n"
        "- Use markdown bullet points (- item) for lists.\n"
        "- Use markdown tables for comparative data.\n"
        "- Use blockquotes for direct quotes.\n"
        "- Output ONLY the section content in markdown. No headings like 'Section 2:' — just the content.\n"
        "- Start with an H2 heading (##) for the section title.\n"
        "- Do not repeat the blog title or write an introduction — just write the assigned section."
    )

    def build_prompt(self, ctx: BlogContext, section_index: int) -> tuple[str, str]:
        section = ctx.outline[section_index]
        previous = ctx.assembled_draft

        source_block = section.source_snippets or ctx.sources_text or "No direct source material available."
        if len(source_block) > 3000:
            source_block = source_block[:3000] + "\n\n[Source snippet truncated...]"

        lessons = _load_lessons()
        lessons_block = ""
        if lessons:
            lessons_block = "\n".join(f"- {lesson}" for lesson in lessons)
            lessons_block = f"\nCOMMON ISSUES TO AVOID (from past critiques):\n{lessons_block}\n"

        user = (
            f"BLOG SECTION: {section.title}\n\n"
            f"KEY POINTS TO COVER:\n" + "\n".join(f"- {p}" for p in section.key_points) +
            f"\n\nFORMAT INSTRUCTIONS: {section.format_instructions}\n"
            f"TARGET WORD COUNT: {section.target_word_count} words\n"
            f"{lessons_block}\n"
            f"RELEVANT SOURCE EXCERPTS:\n{source_block}\n\n"
        )

        if previous:
            previous_trimmed = previous[-3000:] if len(previous) > 3000 else previous
            user += (
                f"PREVIOUS SECTIONS (for continuity — end of last section):\n"
                f"{previous_trimmed}\n\n"
            )

        user += (
            f"Write section \"{section.title}\" now. Follow the format instructions. "
            f"Be specific — name names, cite exact figures. "
            f"Output ONLY the section content starting with ## {section.title}"
        )

        return self.SECTION_SYSTEM, user

    def parse_output(self, raw: str) -> str:
        return raw.strip()

    def apply_result(self, ctx: BlogContext, parsed: str) -> BlogContext:
        ctx.add_section(parsed)
        return ctx

    async def run_section(self, ctx: BlogContext, section_index: int) -> BlogContext:
        import asyncio
        try:
            system, user = self.build_prompt(ctx, section_index)
            use_groq = settings.agent_uses_cloud(self.name)
            if use_groq:
                limiter = get_groq_rate_limiter()
                estimated = limiter.estimate_tokens(system, user, self.max_tokens)
                await limiter.wait_if_needed(estimated)
            raw = await asyncio.to_thread(
                _call_llm_routed,
                system, user,
                None, self.key_name,
                None, self.temperature, self.max_tokens,
                use_groq,
            )
            parsed = self.parse_output(raw)
            return self.apply_result(ctx, parsed)
        except Exception as e:
            from agents.base import AgentError
            raise AgentError(self.name, f"Section {section_index} failed: {e}", original=e)
