from __future__ import annotations

from agents.base import BaseAgent
from agents.context import BlogContext
from formatter import _build_source_text, _truncate_sources


class CondenserAgent(BaseAgent):
    name = "condenser"
    model = "llama3.2:3b"
    key_name = "ANALYZER"
    temperature = 0.3
    max_tokens = 4096

    CONDENSER_SYSTEM = (
        "You extract concise, fact-dense source snippets for each section of a blog outline. "
        "Your goal: give the section writer exactly the evidence they need — no more, no less.\n\n"
        "Rules:\n"
        "- For each section, extract 2-4 of the most relevant paragraphs from the provided sources\n"
        "- Preserve specific names, figures, dates, quotes, and statistics\n"
        "- Omit filler text, introductions, and meta-commentary\n"
        "- If a section has no direct source support, write 'No direct source material'\n"
        "- Keep each snippet under 800 characters\n"
        "- Return ONLY a JSON object where keys are section numbers (1, 2, 3...) and values are the excerpt text"
    )

    def build_prompt(self, ctx: BlogContext) -> tuple[str, str]:
        sections_text = ""
        for i, sec in enumerate(ctx.outline):
            points = "; ".join(sec.key_points) if sec.key_points else "(no key points)"
            sections_text += (
                f"Section {i+1}: {sec.title}\n"
                f"  Key points: {points}\n"
                f"  Format: {sec.format_instructions}\n\n"
            )

        sources_text = _truncate_sources(_build_source_text(ctx.articles))

        user = (
            f"Blog outline:\n\n{sections_text}\n\n"
            f"Source materials:\n\n{sources_text}\n\n"
            f"For each section number (1 through {len(ctx.outline)}), extract the most relevant "
            f"source excerpts. Return as JSON: {{\"1\": \"excerpt...\", \"2\": \"excerpt...\", ...}}"
        )
        return self.CONDENSER_SYSTEM, user

    def parse_output(self, raw: str) -> dict:
        parsed = super().parse_output(raw)
        if not isinstance(parsed, dict):
            return {}
        return parsed

    def apply_result(self, ctx: BlogContext, parsed: dict) -> BlogContext:
        for i, sec in enumerate(ctx.outline):
            snippet = parsed.get(str(i + 1), parsed.get(str(i), ""))
            if snippet:
                sec.source_snippets = snippet.strip()
        return ctx
