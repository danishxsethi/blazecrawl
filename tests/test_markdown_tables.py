"""HTML table fixtures must retain their rows and columns in Markdown."""

import pytest

from blazecrawl_core.engine.markdown_converter import MarkdownConverter


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        pytest.param(
            "<table><tr><th>Name</th><th>Count</th></tr>"
            "<tr><td>Alpha</td><td>1</td></tr><tr><td>Beta</td><td>2</td></tr></table>",
            "| Name | Count |\n| --- | --- |\n| Alpha | 1 |\n| Beta | 2 |",
            id="two-rows-two-columns",
        ),
        pytest.param(
            "<table><thead><tr><th>A</th><th>B</th><th>C</th></tr></thead>"
            "<tbody><tr><td>left</td><td></td><td>right</td></tr>"
            "<tr><td></td><td>middle</td><td></td></tr></tbody></table>",
            "| A | B | C |\n| --- | --- | --- |\n| left | | right |\n| | middle | |",
            id="sections-and-empty-cells",
        ),
        pytest.param(
            "<table><tr><th>City</th><th>Label</th></tr>"
            "<tr><td>İstanbul</td><td>Café &amp; tea</td></tr>"
            "<tr><td>東京</td><td>&lt;3</td></tr></table>",
            "| City | Label |\n| --- | --- |\n| İstanbul | Café & tea |\n| 東京 | <3 |",
            id="unicode-and-entities",
        ),
        pytest.param(
            "<table><tr><th>Item</th><th>Details</th></tr>"
            '<tr><td><strong>bold</strong></td><td><a href="https://example.com/">link</a>'
            " and <em>emphasis</em></td></tr></table>",
            "| Item | Details |\n| --- | --- |\n"
            "| **bold** | [link](https://example.com/) and *emphasis* |",
            id="inline-formatting",
        ),
    ],
)
def test_table_conversion_preserves_structure(html, expected):
    assert MarkdownConverter().convert(html) == expected


def test_adjacent_tables_remain_separate():
    table = "<table><tr><th>Header</th></tr><tr><td>{}</td></tr></table>"
    html = table.format("first") + "<p>Between tables</p>" + table.format("second")
    markdown = MarkdownConverter().convert(html)
    assert markdown == (
        "| Header |\n| --- |\n| first |\n\nBetween tables\n\n| Header |\n| --- |\n| second |"
    )
