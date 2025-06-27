import aiohttp
import asyncio

import pytest

from src.backfill import run_backfill
from src.db_manager import DatabaseManager


class DummyScraper:
    def __init__(self, db_manager=None):
        self.session = aiohttp.ClientSession()
        self.base_url = "http://example.com"
        self.headers = {}
        self.db_manager = db_manager
        self.semaphore = asyncio.Semaphore(1)

    async def initialize(self):
        return True

    def create_payload(self, page: int = 1):
        return {}

    async def fetch_jobs(self, session, payload, page):
        if page > 1:
            return None
        return {"data": {"jobPosts": [{"id": "1"}]}}

    async def process_jobs(self, jobs):
        return jobs

    async def _process_jobs(self, jobs):
        await self.db_manager.insert_jobs(jobs, "b1")
        self.last_jobs = jobs


class DummyDB(DatabaseManager):
    async def initialize(self):
        return True

    async def insert_jobs(self, jobs, batch_id):
        self.inserted = len(jobs)
        return self.inserted


@pytest.mark.asyncio
async def test_run_backfill(monkeypatch):
    db = DummyDB("postgresql://u:p@localhost/db")
    monkeypatch.setattr("src.backfill.JobScraper", DummyScraper)
    await run_backfill(1, 1, db)
    assert db.inserted == 1
