"""STORY-018: a suggested search name is data, never code. It sits in a
data- attribute and the onclick handler is fixed text, so a quote in the
name cannot end the JavaScript string."""

from app.templating import templates

HOSTILE = "X');alert(1);('"


def _render(**ctx: object) -> str:
    return templates.get_template("partials/searchname_suggest.html").render(**ctx)


def test_a_quote_in_a_candidate_stays_inside_the_data_attribute() -> None:
    html = _render(source="llm", candidates=[HOSTILE, "BEARING"], suggestion="")
    handler = "document.getElementById('search_name').value = this.dataset.searchName"
    assert html.count(f'onclick="{handler}"') == 2
    assert "alert(1)" not in html.split('onclick="', 1)[1].split('"', 1)[0]
    assert 'data-search-name="X&#39;);alert(1);(&#39;"' in html
    assert 'data-search-name="BEARING"' in html


def test_the_single_suggestion_is_escaped_the_same_way() -> None:
    html = _render(source="guess", candidates=[], suggestion='A"<b>')
    assert 'data-search-name="A&#34;&lt;b&gt;"' in html
    assert "<b>" not in html
