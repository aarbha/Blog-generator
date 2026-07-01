from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChapterPlan:
    title: str
    purpose: str = ""
    section_count: int = 4
    intro: str = ""


@dataclass
class SectionPlan:
    title: str
    key_points: list[str] = field(default_factory=list)
    format_instructions: str = ""
    target_word_count: int = 500
    source_refs: list[str] = field(default_factory=list)
    source_snippets: str = ""
    chapter_index: int = 0
    chapter_title: str = ""


def _is_chapter_depth(depth: str) -> bool:
    return depth in ("long", "comprehensive")


@dataclass
class BlogContext:
    input_data: str = ""
    input_type: str = "auto"
    depth: str = "auto"
    articles: list[dict] = field(default_factory=list)
    sources_text: str = ""

    verbose: bool = False

    research_plan: dict | None = None
    analysis: dict | None = None
    chapters: list[ChapterPlan] = field(default_factory=list)
    outline: list[SectionPlan] = field(default_factory=list)
    section_drafts: list[str] = field(default_factory=list)
    critique: dict | None = None

    title: str = ""
    tags: list[str] = field(default_factory=list)
    seo_description: str = ""
    polished_markdown: str = ""

    @property
    def assembled_draft(self) -> str:
        return "\n\n".join(self.section_drafts)

    @property
    def best_draft(self) -> str:
        return self.polished_markdown or self.assembled_draft

    def add_section(self, md: str):
        self.section_drafts.append(md)

    def sections_for_chapter(self, chapter_index: int) -> list[SectionPlan]:
        return [s for s in self.outline if s.chapter_index == chapter_index]

    def drafts_for_chapter(self, chapter_index: int) -> list[str]:
        result = []
        for i, sec in enumerate(self.outline):
            if sec.chapter_index == chapter_index and i < len(self.section_drafts):
                result.append(self.section_drafts[i])
        return result

    @property
    def chapter_count(self) -> int:
        return len(self.chapters)
