"""Idle VLM unload tests: no real model, GPU or network is required."""

import asyncio
import threading
import time

import pytest

from mineru.kit.router.workers import ManagedLocalWorker, RouterSettings
from mineru.model.vlm import runtime as vlm_runtime
from mineru.parser.api_server import JobStore, _JobRecord


def test_idle_minutes_is_validated_and_passed_to_local_worker() -> None:
    with pytest.raises(ValueError, match="model_idle_minutes"):
        JobStore(model_idle_minutes=-1)
    with pytest.raises(ValueError, match="model_idle_minutes"):
        RouterSettings(model_idle_minutes=-1)
    settings = RouterSettings(model_idle_minutes=30, local_gpus="none")
    command = ManagedLocalWorker("test", "127.0.0.1", None, settings).command(
        8000, __import__("pathlib").Path("/tmp/uploads")
    )
    assert command[command.index("--model-idle-minutes") + 1] == "30"
    assert "--model-idle-minutes" not in ManagedLocalWorker(
        "test", "127.0.0.1", None, RouterSettings()
    ).command(8000, __import__("pathlib").Path("/tmp/uploads"))


def test_idle_unloads_once_and_new_job_rearms(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        vlm_runtime, "shutdown_cached_models", lambda: calls.append("unload")
    )

    async def check() -> None:
        store = JobStore(model_idle_minutes=1)
        assert not await store.unload_idle_models_once()  # Never used.
        store._model_last_activity = time.monotonic() - 61
        assert await store.unload_idle_models_once()
        assert not await store.unload_idle_models_once()
        assert calls == ["unload"]

        rec = _JobRecord("job-next")
        store._jobs[rec.id] = rec
        done = asyncio.Event()

        async def work() -> None:
            done.set()

        store.start_task(rec, work)
        assert not await store.unload_idle_models_once()  # Queued/running.
        await done.wait()
        await asyncio.sleep(0)  # JobStore completion callback.
        await asyncio.sleep(0)
        assert not store._tasks
        assert not await store.unload_idle_models_once()  # Recently used.
        store._model_last_activity = time.monotonic() - 61
        assert await store.unload_idle_models_once()
        assert calls == ["unload", "unload"]
        await store.shutdown()

    asyncio.run(check())


def test_idle_gate_blocks_admission_until_unload_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release = threading.Event(), threading.Event()

    def shutdown() -> None:
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(vlm_runtime, "shutdown_cached_models", shutdown)

    async def check() -> None:
        store = JobStore(model_idle_minutes=1)
        store._model_last_activity = time.monotonic() - 61
        unload = asyncio.create_task(store.unload_idle_models_once())
        assert await asyncio.to_thread(entered.wait, 5)
        admission = asyncio.create_task(store.wait_for_model_unload())
        await asyncio.sleep(0)
        assert not admission.done()
        release.set()
        assert await unload
        await admission
        await store.shutdown()

    try:
        asyncio.run(check())
    finally:
        release.set()


def test_active_job_and_failure_protection(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def failure() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("simulated failed close")

    monkeypatch.setattr(vlm_runtime, "shutdown_cached_models", failure)

    async def check() -> None:
        store = JobStore(model_idle_minutes=1)
        store._model_last_activity = time.monotonic() - 61
        active = asyncio.create_task(asyncio.sleep(10))
        store._tasks["active"] = active
        assert not await store.unload_idle_models_once()
        assert calls == 0
        active.cancel()
        await asyncio.gather(active, return_exceptions=True)
        store._tasks.clear()
        assert not await store.unload_idle_models_once()
        assert store._model_idle_disabled
        assert not await store.unload_idle_models_once()
        assert calls == 1
        store._jobs.clear()
        await store.shutdown()

    asyncio.run(check())
