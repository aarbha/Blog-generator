from __future__ import annotations

from agents.base import BaseAgent
from agents.context import BlogContext
from formatter import _build_source_text, _truncate_sources


class AnalystAgent(BaseAgent):
    name = "analyst"
    model = "llama3.2:3b"
    key_name = "ANALYZER"
    temperature = 0.3
    max_tokens = 2048

    ANALYST_SYSTEM = (
        "You are a content analyst. You identify structural patterns in source materials "
        "and flag data that belongs in tables or lists."
    )

    def build_prompt(self, ctx: BlogContext) -> tuple[str, str]:
        topic = ctx.input_data if ctx.input_type in ("topic", "idea") else (
            ctx.articles[0].get("title", "") if ctx.articles else ""
        )
        topic_line = f"\nTopic: {topic}" if topic else ""
        sources_text = _truncate_sources(_build_source_text(ctx.articles), max_chars=self._source_limit())

        user = (
            f"Analyze these source materials for writing a blog post.{topic_line}\n\n"
            f"{sources_text}\n\n"
            "Return ONLY a JSON object with these fields:\n"
            "- content_type: comparison, news_analysis, tutorial, opinion, digest, listicle, trend_analysis\n"
            "- topic: the main topic in 5-10 words\n"
            "- key_themes: list of 2-4 key themes\n"
            "- table_candidates: list of objects with {title, columns: [col1, col2, ...]}. "
            "If ANY source contains comparative data (pricing, specs, features, side-by-side), "
            "statistical data, or structured information \u2014 flag it here. "
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
        return self.ANALYST_SYSTEM, user

    def apply_result(self, ctx: BlogContext, parsed: dict | list) -> BlogContext:
        if not isinstance(parsed, dict):
            parsed = {}
        ctx.analysis = {
            "content_type": parsed.get("content_type", "news_analysis"),
            "topic": parsed.get("topic", ctx.input_data or ctx.articles[0].get("title", "") if ctx.articles else ""),
            "key_themes": parsed.get("key_themes", []),
            "table_candidates": parsed.get("table_candidates", []),
            "list_candidates": parsed.get("list_candidates", []),
            "timeline_events": parsed.get("timeline_events", []),
            "target_audience": parsed.get("target_audience", "general readers"),
            "recommended_tone": parsed.get("recommended_tone", "balanced"),
        }
        return ctx
