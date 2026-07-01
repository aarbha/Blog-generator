from __future__ import annotations

import json

from agents.base import BaseAgent
from agents.context import BlogContext
from config import settings


class ChapterEditorAgent(BaseAgent):
    name = "chapter_editor"
    model = "qwen2.5:1.5b"
    key_name = "ANALYZER"
    temperature = 0.3
    max_tokens = 2048

    SYSTEM = (
        "You review one chapter of a blog post. Check:\n"
        "- Does the chapter fulfill its stated purpose?\n"
        "- Do the sections flow logically into each other?\n"
        "- Is there a smooth transition from the previous chapter?\n"
        "- Are any key points from the sources missing?\n"
        "- Is the writing specific and fact-dense?\n\n"
        "Return ONLY a JSON object with:\n"
        '- "score": 1-10\n'
        '- "issues": array of specific issues\n'
        '- "suggestions": array of specific fixes\n'
        '- "transition_note": a sentence bridging to the next chapter'
    )

    def build_prompt(self, ctx: BlogContext, chapter_index: int) -> tuple[str, str]:
        chapter = ctx.chapters[chapter_index]
        chapter_sections = ctx.sections_for_chapter(chapter_index)
        chapter_drafts = ctx.drafts_for_chapter(chapter_index)

        sections_text = ""
        for i, sec in enumerate(chapter_sections):
            draft = chapter_drafts[i] if i < len(chapter_drafts) else "(not yet written)"
            sections_text += f"## {sec.title}\n\n{draft}\n\n"

        previous_chapter_text = ""
        if chapter_index > 0:
            prev = ctx.chapters[chapter_index - 1]
            prev_drafts = ctx.drafts_for_chapter(chapter_index - 1)
            if prev_drafts:
                last_200 = prev_drafts[-1][-500:] if prev_drafts[-1] else ""
                previous_chapter_text = f"Previous chapter: \"{prev.title}\"\nEnd of previous chapter:\n{last_200}\n\n"

        next_chapter_text = ""
        if chapter_index < len(ctx.chapters) - 1:
            next_ch = ctx.chapters[chapter_index + 1]
            next_chapter_text = f"Next chapter: \"{next_ch.title}\" — {next_ch.purpose}"

        analysis_text = json.dumps(ctx.analysis, indent=2) if ctx.analysis else ""

        user = (
            f"Chapter: \"{chapter.title}\"\n"
            f"Purpose: {chapter.purpose}\n\n"
            f"{previous_chapter_text}"
            f"Chapter content:\n\n{sections_text}\n\n"
            f"{next_chapter_text}\n\n"
            f"Content analysis:\n{analysis_text}\n"
            "Review this chapter. Score it, list issues, and provide a transition note."
        )
        return self.SYSTEM, user

    def parse_output(self, raw: str) -> dict:
        cleaned = super().parse_output(raw)
        if not isinstance(cleaned, dict):
            return {"score": 5, "issues": [], "suggestions": [], "transition_note": ""}
        if not isinstance(cleaned.get("issues"), list):
            cleaned["issues"] = []
        if not isinstance(cleaned.get("suggestions"), list):
            cleaned["suggestions"] = []
        try:
            score_val = float(cleaned.get("score", 5))
        except (TypeError, ValueError):
            score_val = 5.0
        cleaned["score"] = max(1, min(10, int(round(score_val))))
        return cleaned

    def apply_result(self, ctx: BlogContext, parsed: dict) -> BlogContext:
        if not hasattr(ctx, "_chapter_critiques"):
            ctx._chapter_critiques = []
        ctx._chapter_critiques.append(parsed)
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
            return self.apply_result(ctx, parsed)
        except Exception as e:
            from agents.base import AgentError
            raise AgentError(self.name, f"Chapter {chapter_index} failed: {e}", original=e)
