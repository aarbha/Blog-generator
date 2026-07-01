from __future__ import annotations

from agents.base import BaseAgent
from agents.context import BlogContext
from formatter import _build_source_text, _truncate_sources


class EditorAgent(BaseAgent):
    name = "editor"
    model = "qwen2.5:3b"
    key_name = "ANALYZER"
    temperature = 0.3
    max_tokens = 4096

    EDITOR_SYSTEM = (
        "You are a rigorous blog post editor. Review the draft against the original sources.\n\n"
        "Score DOWN for:\n"
        "- Vague claims without specific names, figures, or dates\n"
        "- Hallucinations or facts not present in the source materials\n"
        "- Missing source attribution for key claims\n"
        "- Poor structure — format doesn't match content type\n"
        "- Missing tables where comparative/structured data exists in sources\n"
        "- Walls of text that should be broken into bullet lists\n"
        "- Generic or boring section headers\n"
        "- Factual inaccuracies\n"
        "- Sections that don't flow well from one to the next\n\n"
        "Return ONLY a JSON object with:\n"
        '- "score": 1-10\n'
        '- "issues": array of specific issues found\n'
        '- "suggestions": array of specific fixes\n'
        '- "section_fixes": object mapping section title to per-section fix instructions'
    )

    def build_prompt(self, ctx: BlogContext) -> tuple[str, str]:
        draft = ctx.assembled_draft
        sources_text = _truncate_sources(_build_source_text(ctx.articles))

        outline_text = ""
        for i, sec in enumerate(ctx.outline):
            outline_text += f"{i+1}. {sec.title} (format: {sec.format_instructions})\n"

        user = (
            f"BLOG STRUCTURE:\n{outline_text}\n\n"
            f"BLOG POST DRAFT:\n\n{draft}\n\n"
            f"SOURCE MATERIALS:\n\n{sources_text}\n\n"
            "Review the draft against the sources and the planned structure. "
            "Be strict about vagueness, accuracy, and formatting compliance. "
            "For each issue, identify which section it belongs to."
        )
        return self.EDITOR_SYSTEM, user

    def parse_output(self, raw: str) -> dict:
        cleaned = super().parse_output(raw)
        if not isinstance(cleaned, dict):
            raise ValueError(f"Expected dict, got {type(cleaned).__name__}")
        if not isinstance(cleaned.get("issues"), list):
            cleaned["issues"] = []
        if not isinstance(cleaned.get("suggestions"), list):
            cleaned["suggestions"] = []
        if not isinstance(cleaned.get("section_fixes"), dict):
            cleaned["section_fixes"] = {}
        try:
            score_val = float(cleaned.get("score", 5))
        except (TypeError, ValueError):
            score_val = 5.0
        cleaned["score"] = max(1, min(10, int(round(score_val))))
        return cleaned

    def apply_result(self, ctx: BlogContext, parsed: dict) -> BlogContext:
        ctx.critique = parsed
        return ctx
