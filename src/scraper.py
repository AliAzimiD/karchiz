import aiohttp
import asyncio
import json
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd
from tenacity import AsyncRetrying, RetryCallState, stop_after_attempt, wait_exponential
import time

from .config_manager import ConfigManager
from .config_models import APIConfig, RequestConfig, ScraperConfig, DatabaseConfig
from .db_manager import DatabaseManager
from .log_setup import get_logger


class JobScraper:
    """
    Asynchronous job scraper that fetches job listings from a specified API,
    processes them, and optionally stores them in a database or local disk.
    """

    def __init__(
        self,
        config_path: str = "config/api_config.yaml",
        save_dir: str = "job_data",
        db_manager: Optional[DatabaseManager] = None,
    ) -> None:
        """
        Initialize the JobScraper with configuration, logging, and optional DB.

        Args:
            config_path (str): Path to the YAML config file.
            save_dir (str): Directory to store data and logs (only used if saving locally).
            db_manager (Optional[DatabaseManager]): If provided, use this manager for DB operations.
        """
        self.logger = get_logger("JobScraper")

        # Load configuration (YAML + environment overrides)
        self.config_manager = ConfigManager(config_path)
        self.api_config: APIConfig = self.config_manager.api_config
        self.request_config: RequestConfig = self.config_manager.request_config
        self.scraper_config: ScraperConfig = self.config_manager.scraper_config

        # Setup directories (if local saving is needed)
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.save_dir / "raw_data"
        self.processed_dir = self.save_dir / "processed_data"
        self.log_dir = self.save_dir / "logs"
        for d in [self.raw_dir, self.processed_dir, self.log_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Database usage config
        database_cfg: DatabaseConfig = self.scraper_config.database
        self.db_enabled = database_cfg.enabled
        self.db_manager = db_manager
        if self.db_enabled and not self.db_manager:
            # If the database is enabled but no db_manager was passed, create one
            self.logger.info(
                "Database integration enabled but no manager provided; creating one."
            )
            db_config = self.config_manager.database_config
            self.db_manager = DatabaseManager(
                connection_string=db_config.connection_string,
                schema=db_config.schema,
                batch_size=db_config.batch_size,
            )

        # API base URL + request headers
        self.base_url = self.api_config.base_url
        self.headers = self.api_config.headers

        # Tracking counters
        self.current_batch: int = 0
        self.total_jobs_scraped: int = 0
        self.failed_requests: List[int] = []
        self.pages_processed: int = 0

        # Concurrency limit for HTTP requests
        max_concurrent = self.scraper_config.max_concurrent_requests
        self.semaphore = asyncio.Semaphore(max_concurrent)

        self.logger.info(
            "JobScraper initialized successfully. Database Enabled? "
            f"{self.db_enabled}"
        )

    async def initialize(self) -> bool:
        """
        Initialize the scraper, including DB connections if enabled.

        Returns:
            bool: True if initialization was successful, False otherwise.
        """
        try:
            if self.db_enabled and self.db_manager:
                self.logger.info("Initializing database connection (JobScraper)...")
                success = await self.db_manager.initialize()
                if not success:
                    # If DB fails, we fallback to local file saving
                    self.logger.warning(
                        "DB initialization failed, falling back to file storage."
                    )
                    self.db_enabled = False
            return True
        except Exception as e:
            self.logger.error(f"Error during scraper initialization: {str(e)}")
            return False

    def create_payload(self, page: int = 1) -> Dict[str, Any]:
        """
        Create the request payload for a given page using the default request config.

        Args:
            page (int): Page number to fetch.

        Returns:
            Dict[str, Any]: JSON body for the POST request.
        """
        payload = dict(self.request_config.default_payload)
        payload.update(
            {
                "page": page,
                "pageSize": self.scraper_config.batch_size,
                "nextPageToken": None,
            }
        )
        return payload

    async def fetch_jobs(
        self,
        session: aiohttp.ClientSession,
        json_body: Dict[str, Any],
        page: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch jobs from the API with retry logic using tenacity. Each retry
        attempt and the total duration are logged for visibility.

        Args:
            session (aiohttp.ClientSession): Shared session for HTTP requests.
            json_body (Dict[str, Any]): POST body JSON for the request.
            page (int): The page number being fetched.

        Returns:
            Optional[Dict[str, Any]]: Parsed JSON data if successful, else None.
        """

        start_time = time.monotonic()
        attempt_no = 0

        def _log_before_sleep(retry_state: "RetryCallState") -> None:  # type: ignore
            self.logger.warning(
                "Request for page %s failed on attempt %s. Retrying in %.2f s",
                page,
                retry_state.attempt_number,
                retry_state.next_action.sleep,
            )

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=4, max=10),
            reraise=True,
            before_sleep=_log_before_sleep,
        ):
            with attempt:
                attempt_no = attempt.retry_state.attempt_number
                self.logger.debug("Fetching page %s (attempt %s)", page, attempt_no)
                async with self.semaphore:
                    async with session.post(
                        self.base_url,
                        headers=self.headers,
                        json=json_body,
                        timeout=self.scraper_config.get("timeout", 60),
                    ) as response:
                        response.raise_for_status()
                        data = await response.json()
                        self.logger.info(
                            "Successfully fetched page %s on attempt %s in %.2f s",
                            page,
                            attempt_no,
                            time.monotonic() - start_time,
                        )
                        self.logger.debug(
                            "Retrieved %s jobs from page %s",
                            len(data.get("data", {}).get("jobPosts", [])),
                            page,
                        )
                        return data

        # If all retries fail, return None
        self.logger.error(
            "Failed to fetch page %s after %s attempts (%.2f s)",
            page,
            attempt_no,
            time.monotonic() - start_time,
        )
        return None

    async def process_jobs(self, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Validate each job before insertion. Rely on DB upsert for deduplication.

        Args:
            jobs (List[Dict[str, Any]]): Raw job data from the API.

        Returns:
            List[Dict[str, Any]]: Filtered/validated job objects.
        """
        processed = []
        for job in jobs:
            try:
                # Basic required fields check
                if not all(k in job for k in ("id", "title", "activationTime")):
                    self.logger.warning(
                        f"Skipping invalid job: {job.get('id', 'unknown')} - missing required fields"
                    )
                    continue
                processed.append(job)
            except Exception as e:
                self.logger.error(f"Error processing job: {str(e)}")
                continue
        return processed

    async def _process_jobs(self, jobs: List[Dict[str, Any]]) -> int:
        """
        Insert or upsert job data into the DB if enabled, otherwise save them to file if configured.

        Args:
            jobs (List[Dict[str, Any]]): Valid job dictionaries to store.

        Returns:
            int: Number of jobs successfully processed (upserted or saved).
        """
        if not jobs:
            return 0

        try:
            batch_id = str(uuid.uuid4())

            # If DB enabled, attempt saving to DB
            if self.db_enabled and self.db_manager:
                self.logger.info(
                    f"Saving {len(jobs)} jobs to DB in batch_id={batch_id}"
                )
                inserted_count = await self.db_manager.insert_jobs(jobs, batch_id)
                self.logger.info(
                    f"DB upsert complete: {inserted_count} jobs inserted/updated for batch {batch_id}"
                )

                # If database saving was successful, skip file saving if config demands
                if (
                    inserted_count > 0
                    and not self.config_manager.should_save_files_with_db()
                ):
                    self.logger.info(
                        "All jobs saved to DB; skipping file-based storage."
                    )
                    return inserted_count

            # If DB is not enabled OR we want to keep local backups, save to file
            self.save_batch(jobs, self.current_batch)
            self.current_batch += 1
            return len(jobs)
        except Exception as e:
            self.logger.error(f"Error in _process_jobs: {str(e)}")
            return 0

    def save_batch(self, jobs: List[Dict[str, Any]], batch_number: int) -> None:
        """
        Optionally save a batch of jobs to JSON, Parquet, and CSV files.
        Only used if config_manager.should_save_files_with_db() is True or DB is disabled.

        Args:
            jobs (List[Dict[str, Any]]): List of job items to save.
            batch_number (int): Index of the current batch.
        """
        if not jobs:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_name = f"batch_{batch_number:04d}_{timestamp}"

        try:
            json_path = self.raw_dir / f"{batch_name}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(jobs, f, ensure_ascii=False, indent=2)

            df = pd.json_normalize(jobs)
            parquet_path = self.processed_dir / f"{batch_name}.parquet"
            df.to_parquet(parquet_path, index=False)

            csv_path = self.processed_dir / f"{batch_name}.csv"
            df.to_csv(csv_path, index=False, encoding="utf-8")

            self.logger.info(
                f"Saved batch {batch_number} with {len(jobs)} jobs locally. "
                f"Total jobs scraped so far: {self.total_jobs_scraped}"
            )
        except Exception as e:
            self.logger.error(f"Error saving batch {batch_number}: {str(e)}")
            self.logger.error(traceback.format_exc())

    async def scrape(self) -> None:
        """
        Main scraping loop. Fetch pages until no more data or hitting max_pages / empty pages.
        """
        async with aiohttp.ClientSession() as session:
            page = 1
            batch_num = 1
            current_batch_jobs: List[Dict[str, Any]] = []
            max_pages = self.scraper_config.max_pages

            consecutive_empty_pages = 0
            max_empty_pages = self.scraper_config.max_empty_pages

            while page <= max_pages:
                try:
                    payload = self.create_payload(page=page)
                    result = await self.fetch_jobs(session, payload, page)

                    if not result or not result.get("data", {}).get("jobPosts"):
                        self.logger.info(
                            f"No more jobs found on page {page}, stopping."
                        )
                        break

                    jobs = result["data"]["jobPosts"]
                    self.logger.info(f"Retrieved {len(jobs)} jobs from page {page}")

                    if not jobs:
                        consecutive_empty_pages += 1
                        self.logger.info(
                            f"Empty page {page}, consecutive empties: {consecutive_empty_pages}"
                        )
                        if consecutive_empty_pages >= max_empty_pages:
                            self.logger.info(
                                f"Reached {max_empty_pages} consecutive empty pages; stopping scrape."
                            )
                            break
                        page += 1
                        continue

                    processed_jobs = await self.process_jobs(jobs)
                    if processed_jobs:
                        consecutive_empty_pages = 0
                        current_batch_jobs.extend(processed_jobs)

                        job_batch_size = self.scraper_config.jobs_per_batch
                        # Once we have enough jobs to form a full batch, insert them
                        if len(current_batch_jobs) >= job_batch_size:
                            processed_count = await self._process_jobs(
                                current_batch_jobs
                            )
                            self.total_jobs_scraped += processed_count

                            # Save state
                            await self._save_batch_with_state(
                                current_batch_jobs, batch_num, page
                            )
                            batch_num += 1
                            current_batch_jobs = []
                    else:
                        consecutive_empty_pages += 1
                        self.logger.info(
                            f"No valid new jobs, consecutive empties: {consecutive_empty_pages}"
                        )
                        if consecutive_empty_pages >= max_empty_pages:
                            break

                    page += 1
                    await asyncio.sleep(self.scraper_config.sleep_time)

                except Exception as e:
                    await self._handle_error(page, e)

                    if len(self.failed_requests) >= self.scraper_config.get(
                        "max_retries", 5
                    ):

                        self.logger.error(f"Too many failed requests, stopping.")
                        break
                    await asyncio.sleep(self.scraper_config.error_sleep_time)

            # Handle any leftover jobs in final batch
            if current_batch_jobs:
                processed_count = await self._process_jobs(current_batch_jobs)
                self.total_jobs_scraped += processed_count
                # Use the last successfully processed page for state tracking
                await self._save_batch_with_state(
                    current_batch_jobs, batch_num, page - 1
                )
            self.pages_processed = page - 1
            await self._log_final_statistics(pages_processed=self.pages_processed)

    async def _save_batch_with_state(
        self, jobs: List[Dict[str, Any]], batch_num: int, current_page: int
    ) -> None:
        """
        Save the current state to config_manager after processing a batch of jobs.

        Args:
            jobs (List[Dict[str, Any]]): The list of processed jobs in the batch.
            batch_num (int): The batch number index.
            current_page (int): The last page processed for this batch.
        """
        current_state = {
            "last_page_scraped": current_page,
            "total_jobs_scraped": self.total_jobs_scraped,
            "last_batch_num": batch_num,
            "last_run": datetime.now().isoformat(),
        }
        self.config_manager.save_state(current_state)
        self.logger.debug(
            f"Updated state after batch {batch_num} on page {current_page}"
        )

    async def _log_final_statistics(self, pages_processed: int) -> None:
        """
        Output final scraping statistics to logs and update config_manager.

        Args:
            pages_processed (int): Number of pages processed in this run.
        """
        stats = {
            "total_jobs_scraped": self.total_jobs_scraped,
            "pages_processed": pages_processed,
            "failed_requests": len(self.failed_requests),
            "end_time": datetime.now().isoformat(),
        }
        self.logger.info("Scraping completed. Final statistics:")
        for k, v in stats.items():
            self.logger.info(f"{k}: {v}")

        try:
            self.config_manager.save_state(
                {"last_run_stats": stats, "scraping_complete": True}
            )
        except Exception as e:
            self.logger.error(f"Failed to save final statistics: {str(e)}")

    async def _handle_error(self, page: int, error: Exception) -> None:
        """
        Handle scraping errors by logging, tracking state, and scheduling a retry if needed.

        Args:
            page (int): The page number where the error occurred.
            error (Exception): The exception thrown.
        """
        self.logger.error(f"Error on page {page}: {str(error)}")
        self.logger.error(traceback.format_exc())
        self.failed_requests.append(page)

        error_state = {
            "last_error": {
                "page": page,
                "error": str(error),
                "timestamp": datetime.now().isoformat(),
            },
            "failed_requests": self.failed_requests,
        }
        try:
            self.config_manager.save_state(error_state)
        except Exception as ex:
            self.logger.error(f"Failed to save error state: {str(ex)}")

        # If it's likely a network or timeout error, we can retry
        if isinstance(error, (aiohttp.ClientError, asyncio.TimeoutError)):
            retry_delay = self.scraper_config.error_sleep_time
            self.logger.info(f"Will retry page {page} after {retry_delay} seconds.")
            await asyncio.sleep(retry_delay)
        else:
            self.logger.error("Unrecoverable error encountered. Stopping.")
            raise

    async def run(self) -> Dict[str, Union[int, str]]:
        """
        A convenience method to initialize, start scraping, and handle cleanup.

        Returns:
            Dict[str, Union[int, str]]: Final scraping statistics.
        """
        try:
            self.logger.info("Starting job scraper run().")
            await self.initialize()
            await self.scrape()
            self.logger.info("Job scraper completed successfully.")
            return {
                "total_jobs": self.total_jobs_scraped,
                "pages_processed": self.pages_processed,
                "status": "completed",
            }
        except Exception as e:
            self.logger.error(f"Error during scraper execution: {str(e)}")
            self.logger.error(traceback.format_exc())
            return {
                "total_jobs": 0,
                "pages_processed": 0,
                "status": "failed",
                "error": str(e),
            }
        finally:
            # Close DB connections if used
            if self.db_enabled and self.db_manager:
                await self.db_manager.close()
