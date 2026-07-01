from __future__ import annotations

import json

from agents.base import BaseAgent
from agents.context import BlogContext, SectionPlan
from formatter import _build_source_text, _truncate_sources


class ArchitectAgent(BaseAgent):
    name = "architect"
    model = "qwen2.5:3b"
    key_name = "WRITER"
    temperature = 0.4
    max_tokens = 2048

    DEPTH_CONFIG = {
        "short":      {"section_range": (3, 4),   "word_range": (200, 400), "total_words": (800, 1200)},
        "auto":       {"section_range": (4, 8),   "word_range": (300, 600), "total_words": (1500, 3000)},
        "medium":     {"section_range": (6, 10),  "word_range": (300, 500), "total_words": (2500, 4000)},
        "long":       {"section_range": (10, 16), "word_range": (300, 500), "total_words": (5000, 8000)},
        "comprehensive": {"section_range": (16, 25), "word_range": (300, 500), "total_words": (8000, 15000)},
    }

    ARCHITECT_SYSTEM = (
        "You are a blog architect. You create detailed blueprints for blog posts. "
        "Given source materials and a content analysis, you plan every section of the blog — "
        "its title, key points, formatting requirements, and which sources to reference.\n\n"
        "Rules:\n"
        "- Each section must have a specific, non-generic title\n"
        "- Mix formats: use tables for comparative data, bullet lists for features/reasons, "
        "numbered lists for steps\n"
        "- Reference specific source numbers for each section\n"
        "- The introduction should hook readers; the conclusion should summarize takeaways\n"
        "- Do NOT include a 'Key Takeaways' section — that belongs in the conclusion\n"
        "Return ONLY a JSON array of section objects."
    )

    def build_prompt(self, ctx: BlogContext) -> tuple[str, str]:
        depth = ctx.depth if ctx.depth in self.DEPTH_CONFIG else "auto"
        cfg = self.DEPTH_CONFIG[depth]
        sec_min, sec_max = cfg["section_range"]
        wc_min, wc_max = cfg["word_range"]
        tot_min, tot_max = cfg["total_words"]

        analysis_text = json.dumps(ctx.analysis, indent=2)
        sources_text = _truncate_sources(_build_source_text(ctx.articles), max_chars=self._source_limit())

        user = (
            f"Content analysis:\n{analysis_text}\n\n"
            f"Source materials:\n{sources_text}\n\n"
            f"Create a detailed blog blueprint as a JSON array. "
            f"Plan {sec_min}-{sec_max} sections (target {sec_max-1} sections). "
            f"Each section should be {wc_min}-{wc_max} words. "
            f"Total blog word count: {tot_min}-{tot_max} words.\n\n"
            f"Each element must have:\n"
            '- "title": section title (specific, not generic)\n'
            '- "key_points": array of 2-4 bullet points this section must cover\n'
            '- "format_instructions": string specifying format — e.g. "Use a table comparing X and Y", '
            '"Present as 4-6 bullet points", "Write as prose with a blockquote"\n'
            '- "target_word_count": number\n'
            '- "source_refs": array of source numbers this section should reference\n\n'
            "Include an introductory section (hook, context, thesis) and a conclusion.\n"
            "If the analysis mentions table_candidates or list_candidates, create dedicated sections for them.\n"
            "Output ONLY the JSON array, nothing else."
        )
        return self.ARCHITECT_SYSTEM, user

    def parse_output(self, raw: str) -> list:
        cleaned = super().parse_output(raw)
        if isinstance(cleaned, dict):
            cleaned = cleaned.get("sections", [])
        if not isinstance(cleaned, list):
            raise ValueError(f"Expected list, got {type(cleaned).__name__}")
        return cleaned

    def apply_result(self, ctx: BlogContext, parsed: list) -> BlogContext:
        ctx.outline = []
        for sec in parsed:
            ctx.outline.append(SectionPlan(
                title=sec.get("title", "Untitled Section"),
                key_points=sec.get("key_points", []),
                format_instructions=sec.get("format_instructions", ""),
                target_word_count=sec.get("target_word_count", 500),
                source_refs=sec.get("source_refs", []),
            ))
        return ctx
