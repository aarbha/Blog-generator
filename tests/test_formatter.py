import json
from unittest.mock import patch

from formatter import _build_source_text, _extract_json, _truncate_sources, analyze_content, critique_blog, write_blog


def test_build_source_text():
    articles = [
        {"title": "Test", "body": "Content", "url": "https://example.com", "date": "", "author": "", "summary": ""}
    ]
    text = _build_source_text(articles)
    assert "Test" in text
    assert "Content" in text


@patch("formatter._call_llm")
def test_analyze_content(mock_call_llm):
    mock_call_llm.return_value = json.dumps(
        {
            "content_type": "news_analysis",
            "topic": "test topic",
            "key_themes": ["theme1"],
            "table_candidates": [],
            "timeline_events": [],
            "target_audience": "general",
            "recommended_tone": "balanced",
        }
    )
    articles = [{"title": "Test", "body": "Content", "url": "https://example.com"}]
    result = analyze_content(articles)
    assert result["content_type"] == "news_analysis"
    assert result["topic"] == "test topic"


@patch("formatter._call_llm")
def test_analyze_content_fallback(mock_call_llm):
    mock_call_llm.return_value = "not valid json"
    articles = [{"title": "Test", "body": "Content", "url": "https://example.com"}]
    result = analyze_content(articles, topic="fallback")
    assert result["topic"] == "fallback"
    assert result["content_type"] == "news_analysis"


@patch("formatter._call_llm")
def test_write_blog(mock_call_llm):
    mock_call_llm.return_value = "# My Blog Post\n\nContent here."
    articles = [{"title": "Test", "body": "Article content", "url": "https://example.com"}]
    analysis = {"content_type": "news_analysis", "topic": "test", "key_themes": []}
    result = write_blog(articles, analysis)
    assert "# My Blog Post" in result


@patch("formatter._call_llm")
def test_critique_blog(mock_call_llm):
    mock_call_llm.return_value = json.dumps(
        {
            "score": 7,
            "issues": ["Needs better structure"],
            "suggestions": ["Add a comparison table"],
        }
    )
    articles = [{"title": "Test", "body": "Content", "url": "https://example.com"}]
    result = critique_blog("# Draft", articles)
    assert result["score"] == 7
    assert len(result["issues"]) == 1


@patch("formatter._call_llm")
def test_critique_blog_fallback(mock_call_llm):
    mock_call_llm.return_value = "bad response"
    articles = [{"title": "Test", "body": "Content", "url": "https://example.com"}]
    result = critique_blog("# Draft", articles)
    assert result["score"] == 5
    assert "Could not parse critique" in result["issues"]


class TestExtractJson:
    def test_plain_json(self):
        assert _extract_json('{"key": "value"}') == '{"key": "value"}'

    def test_fenced_json(self):
        result = _extract_json('```json\n{"key": "value"}\n```')
        assert result == '{"key": "value"}'

    def test_fenced_no_lang(self):
        result = _extract_json('```\n{"key": "value"}\n```')
        assert result == '{"key": "value"}'

    def test_trailing_text(self):
        result = _extract_json('{"key": "value"}\nsome notes')
        assert result == '{"key": "value"}\nsome notes'


class TestTruncateSources:
    def test_under_limit(self):
        text = "short text"
        assert _truncate_sources(text, max_chars=100) == text

    def test_over_limit(self):
        text = "x" * 200
        result = _truncate_sources(text, max_chars=100)
        assert len(result) < 150
        assert "truncated" in result

    def test_exact_limit(self):
        text = "x" * 50
        assert _truncate_sources(text, max_chars=50) == text


class TestCritiqueScoreParsing:
    @patch("formatter._call_llm")
    def test_float_score(self, mock_call_llm):
        mock_call_llm.return_value = json.dumps({"score": 8.9, "issues": [], "suggestions": []})
        articles = [{"title": "T", "body": "C", "url": "https://x.com"}]
        result = critique_blog("# D", articles)
        assert result["score"] == 9

    @patch("formatter._call_llm")
    def test_string_score(self, mock_call_llm):
        mock_call_llm.return_value = json.dumps({"score": "7", "issues": [], "suggestions": []})
        articles = [{"title": "T", "body": "C", "url": "https://x.com"}]
        result = critique_blog("# D", articles)
        assert result["score"] == 7
