import json
import time
from pathlib import Path

from scraper import _cache_key, _load_cache, _save_cache


def test_cache_key_consistency():
    url = "https://example.com/article"
    assert _cache_key(url) == _cache_key(url)
    assert isinstance(_cache_key(url), str)
    assert len(_cache_key(url)) > 0
    assert "example_com" in _cache_key(url)


def test_cache_key_readable():
    key = _cache_key("https://example.com/article/hello-world")
    assert "example_com" in key
    assert "article" in key or "hello" in key


def test_save_and_load_cache(tmp_path):
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    key = "test_key_article"
    article = {"title": "Test", "body": "Content"}
    _save_cache(key, article)
    loaded = _load_cache(key)
    assert loaded == article


def test_cache_expiry(tmp_path):
    key = "expired_key"
    cache_dir = Path(__file__).parent.parent / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{key}.json"
    path.write_text(
        json.dumps({"_cached_at": time.time() - 99999, "article": {"title": "Old"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    result = _load_cache(key)
    assert result is None
