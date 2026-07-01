import asyncio
import os

import httpx

from config import settings

MEDIUM_API_BASE = "https://api.medium.com/v1"


def _get_token() -> str:
    token = settings.medium_token
    if not token:
        raise ValueError("MEDIUM_TOKEN not set in .env. Get it from: Medium → Settings → Security → Integration tokens")
    return token


async def get_user_id(token: str) -> str:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{MEDIUM_API_BASE}/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["data"]["id"]


async def upload_image(token: str, image_url: str, timeout: int = 30) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            img_resp = await client.get(image_url)
            img_resp.raise_for_status()

        content_type = img_resp.headers.get("content-type", "image/jpeg")
        image_data = img_resp.content
        file_name = image_url.rsplit("/", 1)[-1].split("?")[0] or "image.jpg"

        boundary = os.urandom(16).hex()
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="image"; filename="{file_name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
            + image_data
            + f"\r\n--{boundary}--\r\n".encode()
        )

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{MEDIUM_API_BASE}/images",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
                content=body,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["data"]["url"]

    except Exception as e:
        print(f"  [WARN] Failed to upload image {image_url[:60]}: {e}")
        return None


async def create_draft_post(
    token: str,
    user_id: str,
    title: str,
    content: str,
    tags: list[str] | None = None,
) -> dict:
    payload = {
        "title": title,
        "contentFormat": "markdown",
        "content": content,
        "publishStatus": "draft",
    }
    if tags:
        payload["tags"] = tags[:5]

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{MEDIUM_API_BASE}/users/{user_id}/posts",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["data"]


async def publish_blog(
    title: str,
    content: str,
    tags: list[str] | None = None,
    image_urls: list[str] | None = None,
    verbose: bool = True,
) -> dict:
    token = _get_token()

    if verbose:
        print("  Authenticating with Medium...")

    user_id = await get_user_id(token)

    uploaded_image_urls = []
    if image_urls:
        if verbose:
            print(f"  Uploading {len(image_urls)} images to Medium...")
        tasks = [upload_image(token, url) for url in image_urls]
        results = await asyncio.gather(*tasks)
        uploaded_image_urls = [r for r in results if r]
        if verbose and uploaded_image_urls:
            print(f"  [OK] {len(uploaded_image_urls)} images uploaded")

    final_content = content
    if uploaded_image_urls:
        for original, uploaded in zip(image_urls, uploaded_image_urls):
            if uploaded:
                final_content = final_content.replace(original, uploaded)

    if verbose:
        print("  Creating draft on Medium...")

    post_data = await create_draft_post(token, user_id, title, final_content, tags)

    if verbose:
        print("  [OK] Draft saved to Medium")
        print(f"  URL: {post_data.get('url', '(check Medium drafts)')}")

    return {
        "url": post_data.get("url", ""),
        "id": post_data.get("id", ""),
        "title": post_data.get("title", title),
    }
