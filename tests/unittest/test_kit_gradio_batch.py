"""Lightweight batch state and export tests; no API server or GPU required."""

from pathlib import Path
import zipfile

import pytest

from mineru.kit.gradio.artifacts import RunArtifacts
from mineru.kit.gradio.batch import BatchItem, BatchJob, BatchRegistry, archive_job


def _artifacts(root: Path, stem: str) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    (root / "downloads").mkdir()
    (root / "images").mkdir()
    (root / "images" / "photo.png").write_bytes(b"PNG")
    (root / "markdown.md").write_text("![image](images/photo.png)")
    for name in ("middle_json.json", "structured_content.json"):
        (root / name).write_text("{}")
    (root / "source.pdf").write_bytes(b"PDF")
    return RunArtifacts(
        root=root, stem=stem, source_path=root / "source.pdf", middle_json_path=root / "middle_json.json",
        markdown_path=root / "markdown.md", structured_content_path=root / "structured_content.json",
        downloads_dir=root / "downloads", file_suffix="pdf",
    ).as_state()


def test_busy_lock_and_ephemeral_history() -> None:
    registry = BatchRegistry()
    job = registry.start("session", ["a.pdf", "b.pdf"], 0, False, "")
    assert registry.busy("session")
    with pytest.raises(ValueError, match="Another"):
        registry.start("session", ["x.pdf"], 0, False, "")
    with pytest.raises(ValueError, match="Cannot clear"):
        registry.clear_history()
    registry.end("session", job.job_id)
    assert not registry.choices()  # Unfinished or aborted tasks are not restorable.
    job.receipt_outputs = [{}]
    assert registry.choices()[0][1] == job.job_id
    registry.acquire("session", job.job_id)
    with pytest.raises(ValueError, match="Another"):
        registry.acquire("session", job.job_id)
    registry.end("session", job.job_id)
    registry.clear_history()
    assert registry.choices() == []


def test_zip_keeps_partial_results_and_handles_same_name(tmp_path: Path) -> None:
    first = _artifacts(tmp_path / "gradio" / "one", "paper")
    second = _artifacts(tmp_path / "gradio" / "two", "paper")
    job = BatchJob("batch-1", [
        BatchItem("a.pdf", "completed", first),
        BatchItem("b.pdf", "completed", second),
        BatchItem("c.pdf", "failed", None, "broken PDF"),
    ], 0, False, "", running=False)
    target = archive_job(job, output_root=tmp_path, hosted=False)
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        assert "paper/paper.md" in names
        assert "paper (2)/paper.md" in names
        assert "paper/images/photo.png" in names
        assert "paper (2)/images/photo.png" in names
        assert "c.pdf: 解析失败" in archive.read("处理报告.txt").decode()


def test_hosted_zip_only_includes_completed_md(tmp_path: Path) -> None:
    first = _artifacts(tmp_path / "gradio" / "one", "a")
    second = _artifacts(tmp_path / "gradio" / "two", "b")
    (Path(first["downloads_dir"]) / "a.md").write_text("https://example.com/a.png")
    job = BatchJob("batch-2", [BatchItem("a.pdf", "completed", first), BatchItem("b.pdf", "completed", second)],
                   0, False, "", running=False)
    with zipfile.ZipFile(archive_job(job, output_root=tmp_path, hosted=True)) as archive:
        assert "a.md" in archive.namelist()
        assert "b.md" not in archive.namelist()
        assert "b.pdf: 图床版 MD 未完成" in archive.read("处理报告.txt").decode()


def test_history_clear_does_not_break_current_download() -> None:
    registry = BatchRegistry()
    job = registry.start("session", ["example.pdf"], 0, False, "")
    job.receipt_outputs = [{}]
    registry.end("session", job.job_id)
    registry.clear_history({job.job_id})
    assert registry.choices() == []
    assert registry.jobs[job.job_id] is job
    assert not job.in_history
