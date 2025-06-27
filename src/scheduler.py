import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .log_setup import get_logger
from .scraper import JobScraper
from .election import LeaderElection


class JobScraperScheduler:
    """
    A simple scheduler that runs the JobScraper at a regular interval.
    Useful for time-based scraping (e.g., every 30 minutes).
    """

    def __init__(
        self,
        config_path: str = "config/api_config.yaml",
        base_dir: str = "job_data",
        interval_minutes: int = 30,
        use_leader_election: bool = False,
    ) -> None:
        """
        Initialize the scheduler with the desired interval and config paths.

        Args:
            config_path (str): Path to the config file for the JobScraper.
            base_dir (str): Base directory for data.
            interval_minutes (int): Interval in minutes between each run.
        """
        self.config_path = config_path
        self.base_dir = Path(base_dir)
        self.interval_minutes = interval_minutes
        self.logger = get_logger("JobScraperScheduler")
        self.use_leader_election = use_leader_election
        self.leader: Optional[LeaderElection] = None

    async def run(self) -> None:
        """Run the scraper in a loop with optional leader election."""
        if self.use_leader_election:
            self.leader = LeaderElection()
            acquired = await self.leader.acquire()
            if not acquired:
                self.logger.info("Leader not acquired; watching for changes")
                await self.leader.watch()
            else:
                self.logger.info("Leader acquired")
                asyncio.create_task(self.leader.hold())
        while True:
            try:
                self.logger.info("Starting scraping run in scheduler.")
                start_time = datetime.now()

                scraper = JobScraper(
                    config_path=self.config_path,
                    save_dir=str(self.base_dir),
                )
                await scraper.scrape()

                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                self.logger.info(
                    f"Completed scraping run. Duration: {duration:.2f} seconds. "
                    f"Jobs collected so far: {scraper.total_jobs_scraped}"
                )

                self.logger.info(
                    f"Waiting {self.interval_minutes} minutes until next run."
                )
                await asyncio.sleep(self.interval_minutes * 60)
            except Exception as e:
                self.logger.error(f"Error in JobScraperScheduler: {str(e)}")
                await asyncio.sleep(60)
