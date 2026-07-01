from __future__ import annotations

from agents.base import BaseAgent
from agents.context import BlogContext


class PolisherAgent(BaseAgent):
    name = "polisher"
    model = "qwen2.5:1.5b"
    key_name = "CHEAP"
    temperature = 0.3
    max_tokens = 2048

    POLISHER_SYSTEM = (
        "You are a blog post polisher. Given a complete draft, you generate:\n"
        "1. A compelling, SEO-friendly title (not clickbait, but specific and engaging)\n"
        "2. A search engine description (1-2 sentences)\n"
        "3. 3-6 relevant tags\n\n"
        "Return ONLY a JSON object with: title, seo_description, tags (array of strings)."
    )

    def build_prompt(self, ctx: BlogContext) -> tuple[str, str]:
        draft = ctx.assembled_draft

        critique_text = ""
        if ctx.critique:
            issues = ctx.critique.get("issues", [])[:3]
            if issues:
                critique_text = "\nTop issues to address in the revision:\n" + "\n".join(f"- {i}" for i in issues)

        user = (
            f"Blog draft:\n\n{draft}\n\n"
            f"{critique_text}"
            f"\n\nAnalyze this draft and return the JSON as specified. "
            f"Title should be specific and compelling (not generic). "
            f"Tags should include the main topics, content type, and target audience keywords."
        )
        return self.POLISHER_SYSTEM, user

    def apply_result(self, ctx: BlogContext, parsed: dict) -> BlogContext:
        ctx.title = parsed.get("title", _extract_first_h1(ctx.assembled_draft))
        ctx.seo_description = parsed.get("seo_description", "")
        ctx.tags = parsed.get("tags", [])[:6]

        draft = ctx.assembled_draft
        if ctx.title and not draft.startswith("# "):
            ctx.polished_markdown = f"# {ctx.title}\n\n{draft}"
        else:
            ctx.polished_markdown = draft

        return ctx


def _extract_first_h1(md: str) -> str:
    for line in md.split("\n"):
        line = line.strip()
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip()
    return "Blog Post"
