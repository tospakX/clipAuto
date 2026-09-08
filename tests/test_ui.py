from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from clipauto.api import create_app
from clipauto.config import Settings
from clipauto.store import JobStore


class NoopQueue:
    async def start(self, resume=True):
        pass

    async def stop(self):
        pass


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def test_root_delivers_accessible_batch_workspace(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings, store=JobStore(settings.database_path), queue=NoopQueue())

    with TestClient(app) as client:
        response = client.get("/")

    parser = Elements()
    parser.feed(response.text)
    elements = parser.elements
    assert response.status_code == 200
    assert any(tag == "textarea" and attrs.get("id") == "urls" for tag, attrs in elements)
    assert any(tag == "button" and attrs.get("id") == "create-batch" for tag, attrs in elements)
    assert any(
        attrs.get("id") == "queue" and attrs.get("aria-live") == "polite" for _, attrs in elements
    )
    assert any(tag == "template" and attrs.get("id") == "job-template" for tag, attrs in elements)
    assert any(tag == "button" and attrs.get("id") == "clear-history" for tag, attrs in elements)
    assert any(tag == "button" and attrs.get("id") == "export-all" for tag, attrs in elements)
    assert any(tag == "button" and attrs.get("class") == "remove-button" for tag, attrs in elements)
    assert any(tag == "button" and attrs.get("class") == "retry-button" for tag, attrs in elements)
    assert any(tag == "button" and attrs.get("class") == "copy-button" for tag, attrs in elements)
    assert any(tag == "button" and attrs.get("class") == "clips-toggle" for tag, attrs in elements)
    assert any(
        tag == "button"
        and "filter-button" in attrs.get("class", "")
        and attrs.get("data-filter") == "active"
        for tag, attrs in elements
    )
    assert any(tag == "input" and attrs.get("id") == "queue-search" for tag, attrs in elements)
    assert any(
        attrs.get("id") == "connection-status" and attrs.get("role") == "status"
        for _, attrs in elements
    )
    assert any(tag == "button" and attrs.get("id") == "load-more" for tag, attrs in elements)
    assert any(
        tag == "details" and attrs.get("class") == "error-details"
        for tag, attrs in elements
    )


def test_static_assets_are_served_with_expected_types(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings, store=JobStore(settings.database_path), queue=NoopQueue())

    with TestClient(app) as client:
        css = client.get("/static/app.css")
        js = client.get("/static/app.js")

    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
