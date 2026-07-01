from bs4 import BeautifulSoup

from scraper import (
    _extract_author,
    _extract_body,
    _extract_date,
    _extract_images,
    _extract_summary,
    _extract_tables,
    _extract_title,
)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


class TestExtractTables:
    def test_simple_table(self):
        html = """
        <table>
            <tr><th>Product</th><th>Price</th><th>Rating</th></tr>
            <tr><td>Alpha</td><td>$10</td><td>4.5</td></tr>
            <tr><td>Beta</td><td>$15</td><td>4.2</td></tr>
        </table>
        """
        result = _extract_tables(_soup(html))
        assert "Product" in result
        assert "Price" in result
        assert "Alpha" in result
        assert "Beta" in result
        assert "---" in result

    def test_table_without_th(self):
        html = """
        <table>
            <tr><td>Item</td><td>Value</td></tr>
            <tr><td>A</td><td>100</td></tr>
        </table>
        """
        result = _extract_tables(_soup(html))
        assert "Item" in result
        assert "Value" in result

    def test_no_tables(self):
        assert _extract_tables(_soup("<div><p>No table here</p></div>")) == ""

    def test_table_in_body(self):
        html = """
        <article>
            <p>Some text before the table that is long enough to be useful.</p>
            <table>
                <tr><th>Name</th><th>Score</th></tr>
                <tr><td>Alice</td><td>95</td></tr>
            </table>
            <p>Some text after the table that should also be extracted.</p>
        </article>
        """
        result = _extract_body(_soup(html))
        assert "Some text before the table" in result
        assert "Some text after the table" in result
        assert "Alice" in result
        assert "Score" in result
        assert "---" in result

    def test_empty_cells(self):
        html = """
        <table>
            <tr><th>A</th><th>B</th><th>C</th></tr>
            <tr><td>X</td><td></td><td>Z</td></tr>
        </table>
        """
        result = _extract_tables(_soup(html))
        assert "X" in result
        assert "Z" in result
        assert "\u2014" in result or "—" in result or "---" in result


class TestExtractTitle:
    def test_og_title(self):
        html = '<meta property="og:title" content="Test Article" /><h1>Ignore</h1>'
        assert _extract_title(_soup(html)) == "Test Article"

    def test_h1_fallback(self):
        html = "<h1>Article Title</h1>"
        assert _extract_title(_soup(html)) == "Article Title"

    def test_no_title(self):
        assert _extract_title(_soup("<div></div>")) == ""


class TestExtractDate:
    def test_meta_date(self):
        html = '<meta property="article:published_time" content="2025-01-15T10:00:00Z" />'
        assert _extract_date(_soup(html)) == "2025-01-15"

    def test_time_tag(self):
        html = '<time datetime="2025-03-20">March 20, 2025</time>'
        assert _extract_date(_soup(html)) == "2025-03-20"

    def test_no_date(self):
        assert _extract_date(_soup("<div></div>")) == ""


class TestExtractAuthor:
    def test_meta_author(self):
        html = '<meta name="author" content="John Doe" />'
        assert _extract_author(_soup(html)) == "John Doe"

    def test_byline_class(self):
        html = '<div class="byline">Jane Smith</div>'
        assert _extract_author(_soup(html)) == "Jane Smith"

    def test_no_author(self):
        assert _extract_author(_soup("<div></div>")) == ""


class TestExtractBody:
    def test_paragraphs(self):
        html = "<article><p>Short</p><p>This is a long enough paragraph to be extracted.</p></article>"
        result = _extract_body(_soup(html))
        assert "long enough paragraph" in result
        assert "Short" not in result

    def test_list_extraction(self):
        html = "<article><ul><li>Item one</li><li>Item two</li></ul></article>"
        result = _extract_body(_soup(html))
        assert "- Item one" in result
        assert "- Item two" in result

    def test_blockquote(self):
        html = "<article><blockquote>A meaningful quote that is long enough to matter.</blockquote></article>"
        result = _extract_body(_soup(html))
        assert "> A meaningful quote" in result

    def test_empty_body(self):
        assert _extract_body(_soup("<div></div>")) == ""


class TestExtractSummary:
    def test_og_description(self):
        html = '<meta property="og:description" content="A great article summary" />'
        assert _extract_summary(_soup(html)) == "A great article summary"

    def test_meta_description(self):
        html = '<meta name="description" content="SEO summary here" />'
        assert _extract_summary(_soup(html)) == "SEO summary here"

    def test_no_summary(self):
        assert _extract_summary(_soup("<div></div>")) == ""


class TestExtractImages:
    def test_og_image(self):
        html = '<meta property="og:image" content="https://example.com/hero.jpg" />'
        result = _extract_images(_soup(html), "https://example.com/page")
        assert any(i["url"] == "https://example.com/hero.jpg" for i in result)

    def test_img_tags(self):
        html = '<img src="https://example.com/photo.jpg" alt="A photo" />'
        result = _extract_images(_soup(html), "https://example.com/page")
        assert any(i["url"] == "https://example.com/photo.jpg" for i in result)
        assert any(i["alt"] == "A photo" for i in result)

    def test_relative_url_resolution(self):
        html = '<img src="/images/pic.jpg" alt="pic" />'
        result = _extract_images(_soup(html), "https://example.com/page")
        assert any("example.com/images/pic.jpg" in i["url"] for i in result)

    def test_max_five_images(self):
        imgs = "".join(f'<img src="https://example.com/img{i}.jpg" />' for i in range(10))
        result = _extract_images(_soup(imgs), "https://example.com/page")
        assert len(result) <= 5

    def test_no_images(self):
        assert _extract_images(_soup("<div></div>"), "https://example.com") == []
