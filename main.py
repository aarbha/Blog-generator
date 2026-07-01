import asyncio
import io
import os
import re
import sys
import tempfile
import webbrowser
from datetime import datetime
from html import escape
from http.server import HTTPServer, SimpleHTTPRequestHandler

if getattr(sys.stdout, "encoding", "").lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import click

from blogger import generate_blog
from config import settings


def headings_to_bullets(text: str) -> str:
    return re.sub(r"^#{1,6}\s+", "• ", text, flags=re.MULTILINE)


HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
  body {{ max-width: 720px; margin: 2em auto; padding: 0 1em; line-height: 1.7; color: #222; }}
  h1,h2,h3,h4,h5,h6 {{ margin-top: 1.5em; margin-bottom: 0.5em; }}
  code {{ background: #f4f4f4; padding: 0.15em 0.4em; border-radius: 3px; font-size: 0.9em; }}
  pre {{ background: #f4f4f4; padding: 1em; border-radius: 5px; overflow-x: auto; }}
  pre code {{ background: none; padding: 0; }}
  blockquote {{ border-left: 3px solid #ccc; margin-left: 0; padding-left: 1em; color: #555; }}
  img {{ max-width: 100%; height: auto; }}
  a {{ color: #0366d6; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #ccc; padding: 0.5em; text-align: left; }}
  th {{ background: #f0f0f0; font-weight: 600; }}
  tr:nth-child(even) td {{ background: #fafafa; }}
  #copy-btn {{ position: fixed; top: 16px; right: 16px; z-index: 999; padding: 10px 20px; font-size: 14px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a8917; color: #fff; border: none; border-radius: 6px; cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,0.15); transition: background 0.2s; }}
  #copy-btn:hover {{ background: #157a15; }}
  #copy-btn:active {{ transform: scale(0.97); }}
  #toast {{ position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); z-index: 999; padding: 10px 24px; font-size: 14px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #323232; color: #fff; border-radius: 6px; opacity: 0; transition: opacity 0.3s; pointer-events: none; }}
  #toast.show {{ opacity: 1; }}
  .copy-check {{ margin-right: 6px; }}
</style>
</head>
<body>
<button id="copy-btn" onclick="copyToMedium()">📋 Copy to Medium</button>
<div id="toast">Copied! Paste into Medium (Ctrl+V)</div>
{body}
<script>
function copyToMedium() {{
  var content = document.body.cloneNode(true);
  var btn = content.querySelector('#copy-btn');
  if (btn) btn.remove();
  var toast = content.querySelector('#toast');
  if (toast) toast.remove();
  var script = content.querySelector('script');
  if (script) script.remove();
  var html = '<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><style>' +
    'body{{font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",Roboto,sans-serif;max-width:720px;margin:2em auto;padding:0 1em;line-height:1.7;color:#222;}}' +
    'h1,h2,h3,h4,h5,h6{{margin-top:1.5em;margin-bottom:0.5em;}}' +
    'code{{background:#f4f4f4;padding:0.15em 0.4em;border-radius:3px;font-size:0.9em;}}' +
    'pre{{background:#f4f4f4;padding:1em;border-radius:5px;overflow-x:auto;}}' +
    'pre code{{background:none;padding:0;}}' +
    'blockquote{{border-left:3px solid #ccc;margin-left:0;padding-left:1em;color:#555;}}' +
    'img{{max-width:100%;height:auto;}}' +
    'a{{color:#0366d6;}}' +
    'table{{border-collapse:collapse;width:100%;margin:1em 0;}}' +
    'th,td{{border:1px solid #ccc;padding:0.5em;text-align:left;}}' +
    'th{{background:#f0f0f0;font-weight:600;}}' +
    'tr:nth-child(even) td{{background:#fafafa;}}' +
    '</style></head><body>' + content.innerHTML + '</body></html>';
  var blob = new Blob([html], {{ type: 'text/html' }});
  var textBlob = new Blob([content.textContent], {{ type: 'text/plain' }});
  navigator.clipboard.write([
    new ClipboardItem({{
      'text/html': blob,
      'text/plain': textBlob
    }})
  ]).then(function() {{
    var t = document.getElementById('toast');
    t.classList.add('show');
    setTimeout(function() {{ t.classList.remove('show'); }}, 2500);
  }}, function() {{
    fallbackCopy(content);
  }});
}}
function fallbackCopy(content) {{
  var range = document.createRange();
  range.selectNodeContents(content);
  var sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  var ok = false;
  try {{
    ok = document.execCommand('copy');
  }} catch(e) {{}}
  sel.removeAllRanges();
  var t = document.getElementById('toast');
  if (ok) {{
    t.textContent = 'Copied! Paste into Medium (Ctrl+V)';
    t.classList.add('show');
    setTimeout(function() {{ t.classList.remove('show'); t.textContent = 'Copied! Paste into Medium (Ctrl+V)'; }}, 2500);
  }} else {{
    alert('Press Ctrl+A to select all, then Ctrl+C to copy.');
  }}
}}
</script>
</body>
</html>"""


def md_to_html(md: str) -> str:
    lines = md.split("\n")
    html_parts: list[str] = []
    in_code = False
    code_lang = ""
    code_lines: list[str] = []
    in_list = False
    list_type = ""
    in_table = False
    table_rows: list[list[str]] = []
    table_align: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()

        if stripped.startswith("```"):
            if in_code:
                lang_attr = f' class="language-{code_lang}"' if code_lang else ""
                code = escape("\n".join(code_lines))
                html_parts.append(f"<pre><code{lang_attr}>{code}\n</code></pre>\n")
                code_lines = []
                in_code = False
                code_lang = ""
            else:
                in_code = True
                code_lang = stripped[3:].strip()
            i += 1
            continue

        if in_code:
            code_lines.append(stripped)
            i += 1
            continue

        if stripped == "":
            if in_table:
                html_parts.append(_build_table(table_rows, table_align))
                table_rows = []
                table_align = []
                in_table = False
            if in_list:
                html_parts.append(f"</{list_type}>\n")
                in_list = False
            i += 1
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            cells = _parse_table_row(stripped)
            if not in_table:
                in_table = True
                table_rows = []
                table_align = []
                table_rows.append(cells)
            else:
                sep = re.match(r"^[\s:|:-]+$", stripped)
                is_sep = (
                    sep
                    and all(
                        c.strip().replace(":", "").strip() == "" or re.match(r"^:?-+:?$", c.strip())
                        for c in cells
                    )
                )
                if is_sep:
                    table_align = [_table_align_class(c) for c in cells]
                else:
                    table_rows.append(cells)
            i += 1
            continue

        if stripped.startswith("> "):
            if in_table:
                html_parts.append(_build_table(table_rows, table_align))
                table_rows = []
                table_align = []
                in_table = False
            if in_list:
                html_parts.append(f"</{list_type}>\n")
                in_list = False
            content = escape(stripped[2:])
            html_parts.append(f"<blockquote><p>{inline_md_to_html(content)}</p></blockquote>\n")
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m:
            if in_table:
                html_parts.append(_build_table(table_rows, table_align))
                table_rows = []
                table_align = []
                in_table = False
            if in_list:
                html_parts.append(f"</{list_type}>\n")
                in_list = False
            level = len(m.group(1))
            content = inline_md_to_html(escape(m.group(2)))
            html_parts.append(f"<h{level}>{content}</h{level}>\n")
            i += 1
            continue

        if stripped.startswith("- ") or stripped.startswith("* "):
            if in_table:
                html_parts.append(_build_table(table_rows, table_align))
                table_rows = []
                table_align = []
                in_table = False
            if not in_list:
                in_list = True
                list_type = "ul"
                html_parts.append("<ul>\n")
            content = inline_md_to_html(escape(stripped[2:]))
            html_parts.append(f"<li>{content}</li>\n")
            i += 1
            continue

        if re.match(r"^\d+\.\s+", stripped):
            if in_table:
                html_parts.append(_build_table(table_rows, table_align))
                table_rows = []
                table_align = []
                in_table = False
            if not in_list:
                in_list = True
                list_type = "ol"
                html_parts.append("<ol>\n")
            content = inline_md_to_html(escape(re.sub(r"^\d+\.\s+", "", stripped)))
            html_parts.append(f"<li>{content}</li>\n")
            i += 1
            continue

        if in_table:
            html_parts.append(_build_table(table_rows, table_align))
            table_rows = []
            table_align = []
            in_table = False
        if in_list:
            html_parts.append(f"</{list_type}>\n")
            in_list = False

        content = inline_md_to_html(escape(stripped))
        html_parts.append(f"<p>{content}</p>\n")
        i += 1

    if in_table:
        html_parts.append(_build_table(table_rows, table_align))
    if in_list:
        html_parts.append(f"</{list_type}>\n")
    if in_code:
        lang_attr = f' class="language-{code_lang}"' if code_lang else ""
        code = escape("\n".join(code_lines))
        html_parts.append(f"<pre><code{lang_attr}>{code}\n</code></pre>\n")

    body = "".join(html_parts).strip()
    title_match = re.search(r"<h1[^>]*>(.+?)</h1>", body)
    title = re.sub(r"<[^>]+>", "", title_match.group(1)) if title_match else "Blog Post"
    return HTML_TEMPLATE.format(title=title, body=body)


def _parse_table_row(line: str) -> list[str]:
    parts = line.split("|")
    parts = parts[1:-1] if len(parts) > 2 else parts
    return [p.strip() for p in parts]


def _table_align_class(cell: str) -> str:
    c = cell.strip()
    if c.startswith(":") and c.endswith(":"):
        return "center"
    if c.endswith(":"):
        return "right"
    return "left"


def _build_table(rows: list[list[str]], align: list[str]) -> str:
    if not rows:
        return ""
    thead = ""
    tbody = ""
    max_cols = max(len(r) for r in rows) if rows else 0
    if not align or len(align) < max_cols:
        align = ["left"] * max_cols
    if len(rows) >= 1:
        header_cells = ""
        for j, cell in enumerate(rows[0]):
            al = align[j] if j < len(align) else "left"
            header_cells += f"<th style=\"text-align:{al}\">{inline_md_to_html(escape(cell))}</th>"
        thead = f"<thead><tr>{header_cells}</tr></thead>"
    if len(rows) >= 2:
        body_rows = ""
        for row in rows[1:]:
            cells = ""
            for j, cell in enumerate(row):
                al = align[j] if j < len(align) else "left"
                cells += f"<td style=\"text-align:{al}\">{inline_md_to_html(escape(cell))}</td>"
            body_rows += f"<tr>{cells}</tr>"
        if body_rows:
            tbody = f"<tbody>{body_rows}</tbody>"
    return f"<table>{thead}{tbody}</table>\n"


def inline_md_to_html(text: str) -> str:
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)
    return text


async def process_input(
    input_data: str,
    input_type: str = "auto",
    depth: str = "auto",
    max_sources: int = 5,
    output_dir: str | None = None,
    local_only: bool = False,
):
    settings.agent_force_local = local_only
    print(f"\n{'=' * 70}")
    print("  Autonomous Blog Writer")
    print(f"{'=' * 70}")

    output_path = None
    if output_dir:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in input_data[:50])
        output_path = f"{output_dir}/{timestamp}_{safe_name}.md"

    try:
        result = await generate_blog(
            input_data=input_data,
            input_type=input_type,
            depth=depth,
            max_sources=max_sources,
            output_path=output_path,
            verbose=True,
        )
    except Exception as e:
        print(f"\n  [ERROR] Blog generation failed: {e}")
        print(f"{'=' * 70}\n")
        return

    print(f"\n{'=' * 70}")
    print("  BLOG POST")
    print(f"{'=' * 70}\n")
    display = headings_to_bullets(result)
    print(display)
    print(f"\n{'=' * 70}")
    print("  Starting preview server...")
    preview_dir = tempfile.mkdtemp(prefix="blog_preview_")
    html_path = os.path.join(preview_dir, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(md_to_html(result))

    _orig_cwd = os.getcwd()
    os.chdir(preview_dir)
    try:
        server = HTTPServer(("127.0.0.1", 8765), SimpleHTTPRequestHandler)
        print("  >>> PREVIEW: http://127.0.0.1:8765")
        print("  >>> Click 'Copy to Medium' button, then paste (Ctrl+V) into Medium")
        print("  >>> Press Enter in this terminal to close the preview")
        webbrowser.open("http://127.0.0.1:8765")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        server.shutdown()
    finally:
        os.chdir(_orig_cwd)
    print()
    print("  DONE")
    print(f"{'=' * 70}\n")


async def interactive_loop():
    print()
    print("   ==============================================")
    print("      Autonomous Blog Writer v2")
    print("      AI-powered research + dynamic blogging")
    print("   ==============================================")
    print()
    print("   Input modes (auto-detected):")
    print("     URL     → Fetch and rewrite a single article")
    print("     Topic   → Search the web and write about a subject")
    print("     Idea    → Expand a raw idea into a researched post")
    print("     RSS URL → Parse a feed and write a digest")
    print("     'feeds' → Check subscribed feeds for new articles")
    print()
    print()

    max_sources = 5
    output_dir = None
    depth = "auto"
    local_only = False

    while True:
        cloud_status = "LOCAL ONLY" if local_only else "HYBRID (Groq+local)"
        print("Enter a topic, URL, RSS feed, idea, or 'q' to quit:")
        print(f"  [{cloud_status}] [Depth: {depth}]  Commands: 'local-only', 'hybrid', 'depth:...', 'sources:N', 'dir:PATH', 'help'")
        try:
            cmd = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nGoodbye!\n")
            break

        if cmd.lower() in ("q", "quit", "exit"):
            print("\nGoodbye!\n")
            break

        if cmd.lower() == "help":
            print("  Examples:")
            print('    "AI chip trends 2026"    → web search + blog')
            print("    https://example.com      → fetch and rewrite")
            print("    https://example.com/rss   → RSS feed digest")
            print('    "serverless vs containers for startups"  → idea → research → blog')
            print("    feeds                   → check subscribed RSS feeds")
            print("    depth:comprehensive      → long 16-25 section report")
            print("    depth:short              → quick 3-4 section post")
            print("    sources:10              → use up to 10 sources")
            print("    dir:./output            → save blog posts to ./output")
            continue

        if cmd.lower() == "local-only":
            local_only = True
            settings.agent_force_local = True
            print("  [OK] Local-only mode — all agents using Ollama")
            continue

        if cmd.lower() == "hybrid":
            local_only = False
            settings.agent_force_local = False
            print("  [OK] Hybrid mode — Groq + local models")
            continue

        if cmd.lower().startswith("depth:"):
            val = cmd.split(":", 1)[1].strip().lower()
            if val in ("auto", "short", "medium", "long", "comprehensive"):
                depth = val
                print(f"  [OK] Depth set to '{depth}'")
            else:
                print("  [WARN] Depth must be: auto, short, medium, long, or comprehensive")
            continue

        if cmd.lower().startswith("sources:"):
            try:
                max_sources = int(cmd.split(":", 1)[1])
                print(f"  [OK] Max sources set to {max_sources}")
            except ValueError:
                print("  [WARN] Invalid number")
            continue

        if cmd.lower().startswith("dir:"):
            output_dir = cmd.split(":", 1)[1].strip()
            print(f"  [OK] Output directory set to '{output_dir}'")
            continue

        if not cmd:
            continue

        try:
            await process_input(cmd, "auto", depth, max_sources, output_dir, local_only)
        except Exception as e:
            print(f"\n  [ERROR] Unexpected error: {e}")
            print("  The interactive session continues. Please try again.\n")


SUBCOMMANDS = frozenset({"generate", "serve", "feeds", "interactive", "--help", "-h"})


def main():
    if len(sys.argv) > 1 and sys.argv[1] in SUBCOMMANDS:
        cli()
    elif len(sys.argv) > 1:
        input_data = " ".join(sys.argv[1:])
        asyncio.run(process_input(input_data))
    else:
        asyncio.run(interactive_loop())


@click.group()
def cli():
    pass


@cli.command()
@click.argument("input_data")
@click.option(
    "--mode", default="auto", type=click.Choice(["auto", "topic", "url", "rss", "idea", "feeds"]), help="Input type"
)
@click.option(
    "--depth", default="auto", type=click.Choice(["auto", "short", "medium", "long", "comprehensive"]),
    help="Document depth / length"
)
@click.option("--sources", default=5, help="Maximum source articles")
@click.option("--dir", "output_dir", default=None, help="Output directory for markdown file")
@click.option("--local-only", is_flag=True, default=False, help="Use local models only (no Groq)")
def generate(input_data, mode, depth, sources, output_dir, local_only):
    """Generate a blog post from a topic, URL, RSS feed, or idea."""
    asyncio.run(process_input(input_data, mode, depth, sources, output_dir, local_only))


@cli.command()
def serve():
    """Run the MCP server for AI client integration."""
    from server import main as server_main

    asyncio.run(server_main())


@cli.command()
def feeds():
    """List subscribed RSS feeds."""
    from researcher import load_feed_subscriptions

    feeds = load_feed_subscriptions()
    if not feeds:
        click.echo("No feeds configured in feeds.json.")
        return
    click.echo("Subscribed feeds:")
    for f in feeds:
        click.echo(f"  - {f}")


@cli.command()
def interactive():
    """Start the interactive prompt loop."""
    asyncio.run(interactive_loop())


if __name__ == "__main__":
    main()
