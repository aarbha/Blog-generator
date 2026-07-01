from pathlib import Path

from agents import BlogContext, Orchestrator


async def generate_blog(
    input_data: str,
    input_type: str = "auto",
    depth: str = "auto",
    max_sources: int = 3,
    max_refine_iterations: int = 1,
    output_path: str | None = None,
    verbose: bool = True,
) -> str:
    ctx = BlogContext(
        input_data=input_data,
        input_type=input_type,
        depth=depth,
    )

    import time as _time
    _t_start = _time.time()

    orchestrator = Orchestrator()
    orchestrator._verbose = verbose

    ctx = await orchestrator.run(ctx)

    draft = ctx.best_draft
    if not draft:
        return "No content was generated."

    if verbose:
        total = _time.time() - _t_start
        print(f"  Total generation time: {total:.0f}s")

    from formatter import _extract_lessons_from_critique
    if ctx.critique:
        _extract_lessons_from_critique(ctx.critique)
    from researcher import _update_domain_reputation
    _update_domain_reputation(ctx.articles)

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(draft, encoding="utf-8")
        if verbose:
            print(f"  [SAVED] {out.resolve()}")

    return draft
