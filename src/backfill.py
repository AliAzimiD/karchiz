import aiohttp
from datetime import datetime
from .scraper import JobScraper
from .db_manager import DatabaseManager
from .log_setup import get_logger

logger = get_logger("backfill")


async def run_backfill(start_page: int, end_page: int, db: DatabaseManager) -> None:
    scraper = JobScraper(db_manager=db)
    await scraper.initialize()
    page = start_page
    async with aiohttp.ClientSession() as session:
        while page <= end_page:
            payload = scraper.create_payload(page=page)
            data = await scraper.fetch_jobs(session, payload, page)
            if not data:
                break
            jobs = await scraper.process_jobs(data["data"]["jobPosts"])
            await scraper._process_jobs(jobs)
            page += 1
    logger.info(f"Backfill {start_page}-{end_page} completed at {datetime.utcnow()}")
