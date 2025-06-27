import asyncio

import pytest

from src.election import LeaderElection


class DummyAPI:
    def __init__(self) -> None:
        self.created = False
        self.patched = False

    class DummyExc(Exception):
        def __init__(self):
            self.status = 409

    async def create_namespaced_lease(self, ns, body):
        self.created = True
        raise self.DummyExc()

    async def patch_namespaced_lease(self, name, ns, body):
        self.patched = True
        return body


@pytest.mark.asyncio
async def test_acquire_with_existing(monkeypatch):
    le = LeaderElection()
    api = DummyAPI()

    async def _noop():
        return None

    monkeypatch.setattr("src.election.config.load_incluster_config", _noop)
    monkeypatch.setattr("src.election.client.CoordinationV1Api", lambda: api)
    monkeypatch.setattr("src.election.client.ApiException", DummyAPI.DummyExc)
    acquired = await le.acquire()
    assert acquired
    assert api.patched


@pytest.mark.asyncio
async def test_hold_calls_renew(monkeypatch):
    le = LeaderElection()
    calls = 0

    async def _renew(api):
        nonlocal calls
        calls += 1
        return True

    monkeypatch.setattr("src.election.config.load_incluster_config", lambda: None)
    monkeypatch.setattr("src.election.client.CoordinationV1Api", lambda: None)
    monkeypatch.setattr(le, "_renew", _renew)
    monkeypatch.setattr("src.election.RENEW_SECONDS", 1)
    task = asyncio.create_task(le.hold())
    await asyncio.sleep(0.6)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls > 0


@pytest.mark.asyncio
async def test_watch_stream(monkeypatch):
    le = LeaderElection()

    class DummyWatch:
        def __init__(self):
            self.streamed = False

        async def stream(self, func, ns, timeout_seconds=0):
            self.streamed = True
            yield {}

    class DummyApi:
        async def list_namespaced_lease(self, ns):
            return []

    monkeypatch.setattr("src.election.config.load_incluster_config", lambda: None)
    monkeypatch.setattr("src.election.client.CoordinationV1Api", lambda: DummyApi())
    monkeypatch.setattr("src.election.watch.Watch", DummyWatch)
    await le.watch()
