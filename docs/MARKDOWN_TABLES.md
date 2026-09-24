# HTML tables in Markdown output

The Markdown converter preserves simple rectangular HTML tables as pipe tables,
including header cells, multiple rows, empty cells, Unicode text and inline
formatting. Regression fixtures are in `tests/test_markdown_tables.py`:

```bash
pytest tests/test_markdown_tables.py -q
```

Complex or deeply nested tables are not guaranteed to preserve their layout.
In particular, do not rely on pipe-table output to retain nested tables or
`rowspan`/`colspan` relationships. Request the `html` format alongside `markdown`
when the original table structure is important, and inspect the HTML before
using the converted cells as structured data.

These tests exercise conversion of supplied HTML. They do not establish that
main-content extraction retains every table from every page.
