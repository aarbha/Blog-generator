from __future__ import annotations

import asyncio
import time

from agents.analyst import AnalystAgent
from agents.architect import ArchitectAgent
from agents.base import AgentError
from agents.chapter_architect import ChapterArchitectAgent
from agents.chapter_editor import ChapterEditorAgent
from agents.condenser import CondenserAgent
from agents.context import BlogContext, _is_chapter_depth
from agents.document_architect import DocumentArchitectAgent
from agents.editor import EditorAgent
from agents.polisher import PolisherAgent
from agents.scout import ScoutAgent
from agents.writer import WriterAgent
from config import settings


class Orchestrator:
    def __init__(self):
        self.scout = ScoutAgent()
        self.analyst = AnalystAgent()
        self.architect = ArchitectAgent()
        self.document_architect = DocumentArchitectAgent()
        self.chapter_architect = ChapterArchitectAgent()
        self.condenser = CondenserAgent()
        self.writer = WriterAgent()
        self.chapter_editor = ChapterEditorAgent()
        self.editor = EditorAgent()
        self.polisher = PolisherAgent()
        self._verbose = True

    async def run(self, ctx: BlogContext) -> BlogContext:
        try:
            self._start_time = time.time()
            ctx = await self._phase_research(ctx)
            ctx = await self._phase_analyze(ctx)

            if _is_chapter_depth(ctx.depth):
                ctx = await self._phase_document_architect(ctx)
                ctx = await self._phase_chapter_outlines(ctx)
            else:
                ctx = await self._phase_outline(ctx)

            ctx = await self._phase_condense(ctx)
            ctx = await self._phase_write(ctx)

            if _is_chapter_depth(ctx.depth):
                ctx = await self._phase_chapter_edits(ctx)

            ctx = await self._phase_edit(ctx)
            ctx = await self._phase_polish(ctx)
            if self._verbose:
                print(f"  Final score: {ctx.critique.get('score', '?')}/10")
                print(f"  Title: {ctx.title}")
                total = time.time() - self._start_time
                print(f"  Total generation time: {total:.0f}s")
            return ctx
        except AgentError as e:
            print(f"\n  [ERROR] Pipeline failed at {e.agent_name}: {e.reason}")
            raise

    async def _phase_research(self, ctx: BlogContext) -> BlogContext:
        if self._verbose:
            from agents.scout import _detect_file_or_text
            input_type = ctx.input_type
            if input_type == "auto":
                input_type, _ = _detect_file_or_text(ctx.input_data)
            print(f"\n  Input type: {input_type}")
            print("  Research phase...")

        ctx.verbose = self._verbose

        t0 = time.time()
        try:
            ctx = await asyncio.wait_for(self.scout.run(ctx), timeout=90)
        except asyncio.TimeoutError:
            if self._verbose:
                print(f"  [TIMEOUT] Research took >90s, forcing fallback...")
            raise AgentError(
                "scout",
                "Research phase timed out after 90s (DuckDuckGo may be unreachable on this network)"
            )

        if self._verbose:
            source_type = "text" if ctx.input_type == "text" else f"{len(ctx.articles)} articles"
            print(f"  [OK] Loaded {source_type} in {time.time()-t0:.0f}s")
        return ctx

    async def _phase_analyze(self, ctx: BlogContext) -> BlogContext:
        if self._verbose:
            print("  Analyzing content...")

        t0 = time.time()
        ctx = await self.analyst.run(ctx)

        if self._verbose:
            ct = ctx.analysis.get("content_type", "unknown") if ctx.analysis else "unknown"
            tone = ctx.analysis.get("recommended_tone", "balanced") if ctx.analysis else "balanced"
            print(f"  Type: {ct}  |  Tone: {tone}  ({time.time()-t0:.0f}s)")
            if ctx.analysis and ctx.analysis.get("table_candidates"):
                print(f"  Tables to generate: {len(ctx.analysis['table_candidates'])}")
        return ctx

    async def _phase_outline(self, ctx: BlogContext) -> BlogContext:
        if self._verbose:
            print(f"  Architecting blog outline (depth: {ctx.depth})...")

        t0 = time.time()
        ctx = await self.architect.run(ctx)

        if self._verbose:
            print(f"  [OK] {len(ctx.outline)} sections planned in {time.time()-t0:.0f}s")
            for i, sec in enumerate(ctx.outline):
                print(f"    {i+1}. {sec.title} ({sec.target_word_count}w)")
        return ctx

    async def _phase_document_architect(self, ctx: BlogContext) -> BlogContext:
        if self._verbose:
            print(f"  Planning document chapters (depth: {ctx.depth})...")

        t0 = time.time()
        ctx = await self.document_architect.run(ctx)

        if self._verbose:
            total_sections = sum(ch.section_count for ch in ctx.chapters)
            print(f"  [OK] {len(ctx.chapters)} chapters ({total_sections} sections) in {time.time()-t0:.0f}s")
            for i, ch in enumerate(ctx.chapters):
                print(f"    {i+1}. {ch.title} — {ch.section_count} sections")
        return ctx

    async def _phase_chapter_outlines(self, ctx: BlogContext) -> BlogContext:
        if self._verbose:
            print(f"  Planning sections for {len(ctx.chapters)} chapters...")
            _t0 = time.time()

        for ch_idx in range(len(ctx.chapters)):
            t0 = time.time()
            ctx = await self.chapter_architect.run_chapter(ctx, ch_idx)
            if self._verbose:
                ch = ctx.chapters[ch_idx]
                count = len(ctx.sections_for_chapter(ch_idx))
                print(f"    [{ch_idx+1}/{len(ctx.chapters)}] \"{ch.title}\" — {count} sections ({time.time()-t0:.0f}s)")

        if self._verbose:
            print(f"  [OK] {len(ctx.outline)} total sections in {time.time()-_t0:.0f}s")
        return ctx

    async def _phase_chapter_edits(self, ctx: BlogContext) -> BlogContext:
        if self._verbose:
            print(f"  Reviewing {len(ctx.chapters)} chapters...")
            _t0 = time.time()
            ctx._chapter_critiques = []

        for ch_idx in range(len(ctx.chapters)):
            t0 = time.time()
            ctx = await self.chapter_editor.run_chapter(ctx, ch_idx)
            if self._verbose:
                ch = ctx.chapters[ch_idx]
                critiques = getattr(ctx, "_chapter_critiques", [])
                score = critiques[-1].get("score", "?") if critiques else "?"
                print(f"    [{ch_idx+1}/{len(ctx.chapters)}] \"{ch.title}\" — score {score}/10 ({time.time()-t0:.0f}s)")

        if self._verbose:
            print(f"  [OK] Chapter reviews done in {time.time()-_t0:.0f}s")
        return ctx

    async def _phase_condense(self, ctx: BlogContext) -> BlogContext:
        if settings.agent_uses_cloud("writer"):
            if self._verbose:
                print("  [SKIP] Source condensation skipped — Groq's 128K context handles full sources")
            return ctx
        if self._verbose:
            print("  Extracting source snippets for each section...")

        t0 = time.time()
        ctx = await self.condenser.run(ctx)

        if self._verbose:
            with_snippets = sum(1 for s in ctx.outline if s.source_snippets)
            print(f"  [OK] Snippets for {with_snippets}/{len(ctx.outline)} sections ({time.time()-t0:.0f}s)")
        return ctx

    async def _phase_write(self, ctx: BlogContext) -> BlogContext:
        if self._verbose:
            print(f"  Writing {len(ctx.outline)} sections...")
            import time as _time
            _t0 = _time.time()
            _current_chapter = -1

        for i in range(len(ctx.outline)):
            sec = ctx.outline[i]
            if _is_chapter_depth(ctx.depth) and sec.chapter_index != _current_chapter:
                _current_chapter = sec.chapter_index
                ch = ctx.chapters[_current_chapter] if _current_chapter < len(ctx.chapters) else None
                ch_title = sec.chapter_title or (ch.title if ch else "")
                if self._verbose:
                    print(f"    --- Chapter: {ch_title} ---")

            t0 = time.time()
            ctx = await self.writer.run_section(ctx, i)
            if self._verbose:
                wc = len(ctx.section_drafts[i].split())
                label = f"[{i+1}/{len(ctx.outline)}]"
                if _is_chapter_depth(ctx.depth):
                    ch_idx = sec.chapter_index
                    ch_sections = ctx.sections_for_chapter(ch_idx)
                    sec_in_ch = sum(1 for s in ctx.outline[:i] if s.chapter_index == ch_idx) + 1
                    label = f"  [{sec_in_ch}/{len(ch_sections)}]"
                print(f"    {label} \"{sec.title}\" — {wc}w ({time.time()-t0:.0f}s)")

        if self._verbose:
            print(f"  [OK] All sections done in {time.time()-_t0:.0f}s")
        return ctx

    async def _phase_edit(self, ctx: BlogContext) -> BlogContext:
        if self._verbose:
            chaps = getattr(ctx, "_chapter_critiques", [])
            if chaps:
                avg_score = sum(c.get("score", 5) for c in chaps) / len(chaps)
                print(f"  Document critique (chapter avg: {avg_score:.1f}/10)...")
            else:
                print("  Self-critique...")

        t0 = time.time()
        ctx = await self.editor.run(ctx)

        if self._verbose:
            score = ctx.critique.get("score", "?") if ctx.critique else "?"
            print(f"  [OK] Score: {score}/10 ({time.time()-t0:.0f}s)")
            if ctx.critique and ctx.critique.get("issues"):
                for iss in ctx.critique["issues"][:3]:
                    print(f"    - {iss[:80]}")
        return ctx

    async def _phase_polish(self, ctx: BlogContext) -> BlogContext:
        if self._verbose:
            print("  Polishing final output...")

        t0 = time.time()
        ctx = await self.polisher.run(ctx)

        if self._verbose:
            print(f"  [OK] Polished in {time.time()-t0:.0f}s")
        return ctx

