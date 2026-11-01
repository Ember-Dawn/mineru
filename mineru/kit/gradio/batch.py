"""In-process Gradio batch history and serial export coordination.

The registry intentionally does not survive a WebUI restart. Source files and
artifacts remain in their existing per-conversion output directories.
"""
from __future__ import annotations

import threading
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from .artifacts import RunArtifacts

ItemStatus = Literal["pending", "running", "completed", "failed"]


@dataclass
class BatchItem:
    source: str
    status: ItemStatus = "pending"
    artifacts: dict[str, Any] | None = None
    error: str = ""


@dataclass
class BatchJob:
    job_id: str
    files: list[BatchItem]
    tier_position: int | float
    force_ocr: bool
    page_range: str
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))
    running: bool = True
    receipt_outputs: list[Any] | None = None
    current_artifacts: dict[str, Any] | None = None
    hosted_path: str = ""
    hosted_errors: list[str] = field(default_factory=list)
    failed_count: int = 0
    in_history: bool = True

    @property
    def successful(self) -> list[RunArtifacts]:
        return [RunArtifacts.from_state(item.artifacts) for item in self.files if item.artifacts is not None]

    @property
    def label(self) -> str:
        filename = Path(self.files[0].source).name if len(self.files) == 1 else f"{len(self.files)} 个 PDF · 批量任务"
        return f"{self.created_at} · {filename} · {sum(bool(item.artifacts) for item in self.files)}/{len(self.files)}"


class BatchRegistry:
    """Small locked index shared by WebUI sessions; no persistent database."""

    def __init__(self) -> None:
        self.jobs: dict[str, BatchJob] = {}
        self.active: dict[str, str] = {}
        self.lock = threading.RLock()

    def start(self, session: str, files: list[str], tier: int | float, force_ocr: bool, page_range: str) -> BatchJob:
        with self.lock:
            if session in self.active:
                raise ValueError("Another conversion or image-host operation is running")
            job = BatchJob(uuid.uuid4().hex, [BatchItem(source=file) for file in files], tier, force_ocr, page_range)
            self.jobs[job.job_id] = job
            self.active[session] = job.job_id
            return job

    def busy(self, session: str) -> bool:
        with self.lock:
            return session in self.active

    def end(self, session: str, job_id: str) -> None:
        with self.lock:
            if self.active.get(session) == job_id:
                self.active.pop(session, None)
            job = self.jobs.get(job_id)
            if job is not None:
                job.running = False

    def acquire(self, session: str, job_id: str) -> None:
        with self.lock:
            if session in self.active:
                raise ValueError("Another operation is running")
            if job_id not in self.jobs or self.jobs[job_id].running:
                raise ValueError("History item is not ready")
            self.active[session] = job_id
            self.jobs[job_id].running = True

    def choices(self) -> list[tuple[str, str]]:
        with self.lock:
            return [
                (job.label, job_id)
                for job_id, job in reversed(list(self.jobs.items()))
                if job.in_history and not job.running and job.receipt_outputs is not None
            ]

    def clear_history(self, preserve_ids: set[str] | None = None) -> None:
        """Drop history while retaining jobs currently displayed by a session."""
        with self.lock:
            if self.active:
                raise ValueError("Cannot clear history while processing")
            keep = preserve_ids or set()
            self.jobs = {key: job for key, job in self.jobs.items() if key in keep}
            for job in self.jobs.values():
                job.in_history = False


def _unique_folder(stem: str, occupied: set[str]) -> str:
    folder = stem or "document"
    name = folder
    index = 2
    while name.casefold() in occupied:
        name = f"{folder} ({index})"
        index += 1
    occupied.add(name.casefold())
    return name


def archive_job(job: BatchJob, *, output_root: Path, hosted: bool) -> Path:
    """Produce one ZIP using verified artifact directories, never user paths."""
    artifacts = job.successful
    if not artifacts:
        raise ValueError("No successful document to download")
    destination = output_root / "gradio" / "batch-downloads" / job.job_id
    destination.mkdir(parents=True, exist_ok=True)
    destination = destination.resolve()
    if not destination.is_relative_to(output_root.resolve()):
        raise ValueError("Invalid output directory")
    target = destination / ("图床版MD.zip" if hosted else "批量结果.zip")
    used: set[str] = set()
    report = []
    with zipfile.ZipFile(target.with_suffix(".tmp"), "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in job.files:
            if item.artifacts is None:
                report.append(f"{Path(item.source).name}: 解析失败 - {item.error}")
                continue
            result = RunArtifacts.from_state(item.artifacts)
            if not result.root.resolve().is_relative_to(output_root.resolve()):
                raise ValueError("Invalid artifact directory")
            folder = _unique_folder(result.stem, used)
            if hosted:
                md = result.downloads_dir / f"{result.stem}.md"
                if not md.is_file():
                    report.append(f"{Path(item.source).name}: 图床版 MD 未完成")
                    continue
                archive.write(md, f"{folder}.md")
            else:
                archive.write(result.markdown_path, f"{folder}/{result.stem}.md")
                images = result.root / "images"
                if images.is_dir():
                    for image in sorted(images.rglob("*")):
                        if image.is_symlink():
                            raise ValueError("Image asset symlink is forbidden")
                        if image.is_file():
                            archive.write(image, f"{folder}/{image.relative_to(result.root).as_posix()}")
        if report:
            archive.writestr("处理报告.txt", "\n".join(report) + "\n")
    target.with_suffix(".tmp").replace(target)
    return target


__all__ = ["BatchItem", "BatchJob", "BatchRegistry", "archive_job"]
