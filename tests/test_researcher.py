from pathlib import Path

from researcher import (
    _deduplicate_articles,
    _detect_input_type,
    _extract_key_terms,
    _pointer_key,
    load_feed_subscriptions,
    load_feeds_state,
    save_feeds_state,
    search_web,
)


class TestPointerKey:
    def test_readable(self):
        key = _pointer_key("search", "fortune 200 companies news")
        assert key == "search_fortune_200_companies_news"

    def test_different_prefixes(self):
        assert _pointer_key("search", "test") != _pointer_key("rss", "test")

    def test_consistent(self):
        assert _pointer_key("search", "hello world") == _pointer_key("search", "hello world")

    def test_special_chars(self):
        key = _pointer_key("search", "what's new in AI?")
        assert "_" in key


class TestDetectInputType:
    def test_url(self):
        assert _detect_input_type("https://example.com/article") == "url"
        assert _detect_input_type("http://blog.com/post") == "url"

    def test_rss_url(self):
        assert _detect_input_type("https://example.com/rss") == "rss"
        assert _detect_input_type("https://example.com/feed.xml") == "rss"
        assert _detect_input_type("https://feeds.feedburner.com/example") == "rss"

    def test_feeds_keyword(self):
        assert _detect_input_type("feeds") == "feeds"
        assert _detect_input_type("subscriptions") == "feeds"

    def test_topic(self):
        assert _detect_input_type("AI news") == "topic"
        assert _detect_input_type("Python programming tips 2026") == "topic"

    def test_idea(self):
        idea = (
            "I think serverless computing is overhyped for early stage "
            "startups because of cold starts and vendor lock-in risks"
        )
        assert _detect_input_type(idea) == "idea"


class TestFeedSubscriptions:
    def test_load_empty_config(self, tmp_path):
        path = tmp_path / "feeds.json"
        path.write_text('{"feeds": []}', encoding="utf-8")
        feeds = load_feed_subscriptions(str(path))
        assert feeds == []

    def test_load_with_feeds(self, tmp_path):
        path = tmp_path / "feeds.json"
        path.write_text('{"feeds": ["https://example.com/rss"]}', encoding="utf-8")
        feeds = load_feed_subscriptions(str(path))
        assert feeds == ["https://example.com/rss"]

    def test_load_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        feeds = load_feed_subscriptions(str(path))
        assert feeds == []


class TestFeedsState:
    def test_save_and_load(self, tmp_path):
        state_path = str(tmp_path / ".feeds_state.json")
        state = {"https://example.com/rss": {"seen": ["url1", "url2"]}}
        save_feeds_state(state, path=state_path)
        assert Path(state_path).exists()
        loaded = load_feeds_state(path=state_path)
        assert loaded == state


class TestKeyTerms:
    def test_extract_key_terms(self):
        query = "latest fortune 200 companies announcements in the last two weeks"
        terms = _extract_key_terms(query)
        assert "fortune" in terms
        assert "companies" in terms
        assert "announcements" in terms
        assert "latest" not in terms
        assert "the" not in terms
        assert "last" not in terms

    def test_no_short_words(self):
        terms = _extract_key_terms("AI in 2026")
        assert "AI" not in terms

    def test_empty_query(self):
        terms = _extract_key_terms("")
        assert terms == []


class TestDeduplicate:
    def test_deduplicate_articles(self):
        articles = [
            {"url": "https://example.com/a", "title": "A"},
            {"url": "https://example.com/b", "title": "B"},
            {"url": "https://example.com/a", "title": "A dup"},
        ]
        result = _deduplicate_articles(articles)
        assert len(result) == 2

    def test_deduplicate_empty(self):
        assert _deduplicate_articles([]) == []


class TestSearchWeb:
    def test_empty_query_returns_empty(self):
        assert search_web("") == []
        assert search_web("   ") == []



