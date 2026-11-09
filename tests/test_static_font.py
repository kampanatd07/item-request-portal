"""STORY-018: the self-hosted Thai font is served without login, and /static
serves only what is in app/static."""

from fastapi.testclient import TestClient


def test_font_is_served_without_login(anon_client: TestClient) -> None:
    r = anon_client.get("/static/fonts/noto-sans-thai-thai-wght-normal.woff2")
    assert r.status_code == 200
    assert r.content[:4] == b"wOF2"


def test_login_page_points_at_the_served_font(anon_client: TestClient) -> None:
    page = anon_client.get("/login").text
    assert "/static/fonts/noto-sans-thai-thai-wght-normal.woff2" in page
    assert "/static/fonts/noto-sans-thai-latin-wght-normal.woff2" in page
    for url in ("/static/fonts/noto-sans-thai-thai-wght-normal.woff2",
                "/static/fonts/noto-sans-thai-latin-wght-normal.woff2"):
        assert anon_client.get(url).status_code == 200


def test_static_does_not_reach_outside_its_folder(anon_client: TestClient) -> None:
    for path in ("/static/../config.py", "/static/%2e%2e/config.py",
                 "/static/fonts/missing.woff2", "/static/templates/base.html"):
        r = anon_client.get(path)
        assert r.status_code == 404, path
        assert "SECRET_KEY" not in r.text
