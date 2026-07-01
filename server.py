import asyncio
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from blogger import generate_blog
from config import settings
from log import get_logger

logger = get_logger("server")

app = Server("news-to-blog")


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="generate_blog",
            description=(
                "Autonomous blog post generator. Accepts a topic, URL, RSS feed URL, "
                "or raw idea. Automatically researches sources, analyzes content, "
                "writes a blog post with dynamic structure (tables, timelines, etc.), "
                "self-critiques, and refines until high quality. "
                "Optionally sends the result as a draft to Medium."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": (
                            "The input: a topic to research, a URL to rewrite, "
                            "an RSS feed URL for a digest, or a raw idea to expand"
                        ),
                    },
                    "input_type": {
                        "type": "string",
                        "enum": ["auto", "topic", "url", "rss", "idea", "feeds"],
                        "description": (
                            "Input type. 'auto' detects automatically: URLs, "
                            "RSS feeds, 'feeds' for subscriptions, "
                            "short text as topic, long text as idea"
                        ),
                        "default": "auto",
                    },
                    "max_sources": {
                        "type": "integer",
                        "description": "Maximum number of source articles to fetch",
                        "default": 5,
                    },
                    "max_refine_iterations": {
                        "type": "integer",
                        "description": "Maximum self-critique refinement passes",
                        "default": 3,
                    },
                },
                "required": ["input"],
            },
        ),
        Tool(
            name="list_subscribed_feeds",
            description="List all RSS feeds configured in feeds.json for subscription checking",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "list_subscribed_feeds":
        from researcher import load_feed_subscriptions

        feeds = load_feed_subscriptions()
        if not feeds:
            return [TextContent(type="text", text="No feeds configured in feeds.json.")]
        text = "Subscribed feeds:\n" + "\n".join(f"- {f}" for f in feeds)
        return [TextContent(type="text", text=text)]

    if name == "generate_blog":
        input_data = arguments["input"]
        input_type = arguments.get("input_type", "auto")
        max_sources = arguments.get("max_sources", 5)
        max_refine = arguments.get("max_refine_iterations", 3)

        logger.info(f"Generating blog: type={input_type}, sources={max_sources}")

        try:
            result = await generate_blog(
                input_data=input_data,
                input_type=input_type,
                max_sources=max_sources,
                max_refine_iterations=max_refine,
                verbose=False,
            )
            logger.info("Blog post generated successfully")
            return [TextContent(type="text", text=result)]
        except Exception as e:
            logger.error(f"Failed to generate blog: {e}")
            return [TextContent(type="text", text=f"Error: {e}")]

    raise ValueError(f"Unknown tool: {name}")


async def main():
    try:
        settings.validate()
    except ValueError as e:
        logger.error(e)
        sys.exit(1)

    logger.info("Starting Autonomous Blog Writer MCP server...")
    async with stdio_server() as (read, write):
        await app.run(
            read,
            write,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
