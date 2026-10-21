"""
The UI must not depend on any runtime CDN: Tailwind is pre-built into
css/app.min.css and lucide/chart.js/three/d3 are vendored under js/vendor/.
These tests guard that (and the strict CSP that relies on it).
"""

import re

import pytest
from httpx import AsyncClient, ASGITransport

_ASSETS = [
    "/css/app.min.css",
    "/css/fonts/inter-latin-400-normal.woff2",
    "/js/vendor/lucide.min.js",
    "/js/vendor/chart.umd.js",
    "/js/vendor/three.min.js",
    "/js/vendor/d3.min.js",
]


@pytest.fixture(scope="module")
def app():
    from app import app as _app
    return _app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_index_loads_no_cdn_scripts_or_styles(client):
    html = (await client.get("/")).text
    tags = re.findall(r'<(?:script|link)[^>]+(?:src|href)="(https?://[^"]+)"', html)
    assert tags == [], f"index.html still loads external assets: {tags}"
    assert "cdn.tailwindcss.com" not in html
    assert "fonts.googleapis.com" not in html


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _ASSETS)
async def test_vendored_assets_are_served(client, path):
    res = await client.get(path)
    assert res.status_code == 200, path
    assert len(res.content) > 1000, path


@pytest.mark.asyncio
async def test_csp_is_strict(client):
    csp = (await client.get("/")).headers["content-security-policy"]
    assert "unsafe-eval" not in csp
    for origin in ("cdn.tailwindcss.com", "unpkg.com", "cdn.jsdelivr.net",
                   "cdnjs.cloudflare.com", "d3js.org", "fonts.googleapis.com"):
        assert origin not in csp, origin
