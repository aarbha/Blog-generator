from pathlib import Path

from agents import BlogContext, Orchestrator


def _extract_title_from_markdown(md: str) -> str:
    for line in md.split("\n"):
        line = line.strip()
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip()
    return "Blog Post"


def _extract_tags(articles: list[dict]) -> list[str]:
    tags = set()
    for article in articles:
        title = article.get("title", "")
        body = article.get("body", "")[:500]
        text = (title + " " + body).lower()
        for kw in [
            "ai",
            "machine learning",
            "startup",
            "technology",
            "software",
            "cloud",
            "security",
            "data",
            "mobile",
            "web",
            "saas",
            "enterprise",
            "open source",
            "python",
            "javascript",
            "api",
            "blockchain",
            "crypto",
            "finance",
            "health",
            "education",
            "design",
            "product",
        ]:
            if kw in text:
                tags.add(kw)
    return list(tags)[:5]


async def generate_blog(
    input_data: str,
    input_type: str = "auto",
    depth: str = "auto",
    max_sources: int = 3,
    max_refine_iterations: int = 1,
    output_path: str | None = None,
    publish_to_medium: bool = False,
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

    if publish_to_medium:
        from medium import publish_blog

        if verbose:
            print("  Publishing draft to Medium...")

        title = ctx.title or _extract_title_from_markdown(draft)
        tags = ctx.tags or _extract_tags(ctx.articles)
        all_images = []
        for a in ctx.articles:
            for img in a.get("images", []):
                if img.get("url"):
                    all_images.append(img["url"])

        try:
            result = await publish_blog(
                title=title,
                content=draft,
                tags=tags,
                image_urls=all_images if all_images else None,
                verbose=verbose,
            )
            if verbose:
                print(f"  [OK] Medium draft: {result.get('url', '(saved)')}")
        except Exception as e:
            print(f"  [WARN] Medium publish failed: {e}")

    return draft
