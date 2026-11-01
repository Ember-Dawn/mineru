"""Lightweight image-host post-processing tests (no network or GPU)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mineru.kit.gradio import image_host


def test_endpoint_accepts_site_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASYIMAGES_API_URL", "https://easyimages.example.org/")
    assert image_host._endpoint() == "https://easyimages.example.org/api/index.php"
    monkeypatch.setenv("EASYIMAGES_API_URL", "http://example.org")
    with pytest.raises(ValueError):
        image_host._endpoint()


def test_references_ignore_code_and_remote(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    (images / "a.png").write_bytes(b"png")
    md = "![one](images/a.png)\n![remote](https://example.com/other.png)\n```md\n![code](images/a.png)\n```\n<img src=\"images/a.png\">"
    spans, paths = image_host._references(md, tmp_path)
    assert len(paths) == 1
    assert len(spans) == 2


def test_generate_caches_successes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "images").mkdir()
    (tmp_path / "downloads").mkdir()
    (tmp_path / "images" / "a.png").write_bytes(b"abc")
    (tmp_path / "markdown.md").write_text("![a](images/a.png) and ![again](images/a.png)", encoding="utf-8")
    artifacts = SimpleNamespace(root=tmp_path, markdown_path=tmp_path / "markdown.md", downloads_dir=tmp_path / "downloads", stem="book")
    monkeypatch.setenv("EASYIMAGES_API_URL", "https://example.com")
    monkeypatch.setenv("EASYIMAGES_TOKEN", "test")
    calls: list[str] = []
    def upload(path: Path) -> str:
        calls.append(path.name)
        return "https://example.com/image.png"
    monkeypatch.setattr(image_host, "_upload", upload)
    output = image_host.generate(artifacts, allowed_root=tmp_path)
    assert output.read_text().count("https://example.com/image.png") == 2
    image_host.generate(artifacts, allowed_root=tmp_path)
    assert calls == ["a.png"]
    assert "images/a.png" in artifacts.markdown_path.read_text()


def test_rejects_parent_escape(tmp_path: Path) -> None:
    (tmp_path / "images").mkdir()
    with pytest.raises(ValueError):
        image_host._safe_local_path(tmp_path, "images/../../secret.png")
