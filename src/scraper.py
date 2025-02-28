import aiohttp
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union, Set
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential, RetryError
import traceback
from .config_manager import ConfigManager

class JobScraper:
    def __init__(self, 
                 config_path: str = "config/api_config.yaml",
                 save_dir: str = "job_data"):
        """Initialize JobScraper with configuration"""
        # Load configuration
        self.config_manager = ConfigManager(config_path)
        self.api_config = self.config_manager.api_config
        self.request_config = self.config_manager.request_config
        self.scraper_config = self.config_manager.scraper_config
        
        # Initialize attributes
        self.base_url = self.api_config['base_url']
        self.headers = self.api_config['headers']
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup directories
        self.raw_dir = self.save_dir / "raw_data"
        self.processed_dir = self.save_dir / "processed_data"
        self.log_dir = self.save_dir / "logs"
        
        for dir_path in [self.raw_dir, self.processed_dir, self.log_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        # Setup logging
        self.logger = self._setup_logging()
        
        # Initialize state
        self.processed_job_ids: Set[str] = set()
        self.last_item_index = 0
        self.earliest_date: Optional[datetime] = None
        self.latest_date: Optional[datetime] = None
        self.current_batch = 0
        self.total_jobs_scraped = 0
        self.failed_requests: List[int] = []
        self.semaphore = asyncio.Semaphore(
            self.scraper_config.get('max_concurrent_requests', 3)
        )
        
        # Load existing state
        self._load_existing_state()
        
    async def _handle_error(self, page: int, error: Exception) -> None:
        """Handle scraping errors with logging and tracking"""
        error_msg = str(error)
        self.logger.error(f"Error on page {page}: {error_msg}")
        self.logger.error(traceback.format_exc())
        
        self.failed_requests.append(page)
        
        # Update state with error information
        error_state = {
            'last_error': {
                'page': page,
                'error': error_msg,
                'timestamp': datetime.now().isoformat()
            },
            'failed_requests': self.failed_requests
        }
        
        try:
            self.config_manager.save_state(error_state)
        except Exception as e:
            self.logger.error(f"Failed to save error state: {str(e)}")
        
        # Check if we should retry based on error type
        if isinstance(error, (aiohttp.ClientError, asyncio.TimeoutError)):
            retry_delay = self.scraper_config.get('error_sleep_time', 2)
            self.logger.info(f"Will retry page {page} after {retry_delay} seconds")
            await asyncio.sleep(retry_delay)
        else:
            self.logger.error(f"Unrecoverable error on page {page}")
            raise
    async def _log_final_statistics(self, pages_processed: int) -> None:
        """Log final scraping statistics"""
        stats = {
            'total_jobs_scraped': self.total_jobs_scraped,
            'pages_processed': pages_processed,
            'failed_requests': len(self.failed_requests),
            'unique_jobs': len(self.processed_job_ids),
            'end_time': datetime.now().isoformat()
        }
        
        self.logger.info("Scraping completed. Final statistics:")
        for key, value in stats.items():
            self.logger.info(f"{key}: {value}")
        
        try:
            self.config_manager.save_state({
                'last_run_stats': stats,
                'scraping_complete': True
            })
        except Exception as e:
            self.logger.error(f"Failed to save final statistics: {str(e)}")

    def _setup_logging(self) -> logging.Logger:
        """Configure logging with both file and console handlers"""
        logger = logging.getLogger('JobScraper')
        logger.propagate = False  # Add this line
        
        if not logger.handlers:
            logger.setLevel(logging.INFO)
            
            # Create formatters and handlers
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            
            # File handler
            log_file = self.log_dir / f"scraper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            fh = logging.FileHandler(log_file)
            fh.setLevel(logging.INFO)
            fh.setFormatter(formatter)
            
            # Console handler
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)
            ch.setFormatter(formatter)
            
            logger.addHandler(fh)
            logger.addHandler(ch)
    
        return logger

    def _load_existing_state(self) -> None:
        """Load existing state from saved files"""
        try:
            json_files = sorted(self.raw_dir.glob("batch_*.json"))
            
            if not json_files:
                self.logger.info("No existing files found. Starting fresh.")
                return
            
            for json_file in json_files:
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        jobs = json.load(f)
                        
                    for job in jobs:
                        self.processed_job_ids.add(job['id'])
                        
                        if job.get('itemIndex', 0) > self.last_item_index:
                            self.last_item_index = job['itemIndex']
                        
                        # Handle different date formats
                        date_str = job['activationTime']['date']
                        try:
                            # Try the format with microseconds
                            job_date = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f")
                        except ValueError:
                            try:
                                # Try the format without microseconds
                                job_date = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
                            except ValueError:
                                # Try just the date and time
                                job_date = datetime.strptime(date_str, "%Y-%m-%dT%H:%M")
                        
                        if not self.earliest_date or job_date < self.earliest_date:
                            self.earliest_date = job_date
                        if not self.latest_date or job_date > self.latest_date:
                            self.latest_date = job_date
                                
                except Exception as e:
                    self.logger.error(f"Error loading file {json_file}: {str(e)}")
                    continue
                        
            self.logger.info(f"Loaded {len(self.processed_job_ids)} existing job IDs")
            if self.earliest_date and self.latest_date:
                self.logger.info(f"Date range: {self.earliest_date} to {self.latest_date}")
            self.logger.info(f"Last item index: {self.last_item_index}")
                
        except Exception as e:
            self.logger.error(f"Error loading existing state: {str(e)}")
            raise

    def create_payload(self, page: int = 1) -> Dict:
        """Create API request payload"""
        payload = self.request_config['default_payload'].copy()
        payload.update({
            'page': page,
            'pageSize': self.scraper_config.get('batch_size', 100),
            'nextPageToken': None
            # Removed 'last_index' to avoid limiting results
        })
        return payload

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    async def fetch_jobs(
        self,
        session: aiohttp.ClientSession,
        params: dict,
        page: int
    ) -> Optional[Dict]:
        """Fetch jobs with retry logic"""
        async with self.semaphore:
            try:
                async with session.post(
                    self.base_url,
                    headers=self.headers,
                    json=params,
                    timeout=self.scraper_config.get('timeout', 60)
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    self.logger.info(f"Successfully fetched page {page}")
                    self.logger.debug(f"Retrieved {len(data.get('data', {}).get('jobPosts', []))} jobs from page {page}")
                    return data
            except aiohttp.ClientError as e:
                self.logger.error(f"Network error fetching page {page}: {str(e)}")
                raise
            except json.JSONDecodeError as e:
                self.logger.error(f"JSON decode error on page {page}: {str(e)}")
                raise
            except Exception as e:
                self.logger.error(f"Unexpected error fetching page {page}: {str(e)}")
                raise

    async def process_jobs(self, jobs: List[dict]) -> List[dict]:
        """Process and validate job data"""
        processed = []
        
        for job in jobs:
            try:
                # Skip if we've seen this job before
                if job['id'] in self.processed_job_ids:
                    continue
                    
                # Basic validation
                required_fields = ['id', 'title', 'activationTime']
                if not all(field in job for field in required_fields):
                    self.logger.warning(
                        f"Skipping invalid job: {job.get('id', 'unknown')} - "
                        f"Missing required fields"
                    )
                    continue
                    
                # Add to processed set and list
                self.processed_job_ids.add(job['id'])
                processed.append(job)
                
            except Exception as e:
                self.logger.error(f"Error processing job: {str(e)}")
                continue
        
        return processed

    def save_batch(self, jobs: List[Dict], batch_number: int) -> None:
        """Save a batch of jobs to file"""
        if not jobs:
            return
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_name = f"batch_{batch_number:04d}_{timestamp}"
        
        try:
            # Save raw JSON
            json_path = self.raw_dir / f"{batch_name}.json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(jobs, f, ensure_ascii=False, indent=2)
            
            # Convert to DataFrame and save processed data
            df = pd.json_normalize(jobs)
            
            # Save as Parquet
            parquet_path = self.processed_dir / f"{batch_name}.parquet"
            df.to_parquet(parquet_path, index=False)
            
            # Save as CSV
            csv_path = self.processed_dir / f"{batch_name}.csv"
            df.to_csv(csv_path, index=False, encoding='utf-8')
            
            self.logger.info(
                f"Saved batch {batch_number} with {len(jobs)} jobs - "
                f"Total jobs: {self.total_jobs_scraped}"
            )
            
        except Exception as e:
            self.logger.error(f"Error saving batch {batch_number}: {str(e)}")
            self.logger.error(traceback.format_exc())

    async def scrape(self) -> None:
        """Main scraping method that handles both resume functionality and new job detection"""
        async with aiohttp.ClientSession() as session:
            # Load previous state and job tracking info
            last_state = self.config_manager.load_state()
            start_page = last_state.get('last_page_scraped', 1)
            last_run_timestamp = None
            
            if last_state.get('last_run'):
                try:
                    last_run_timestamp = datetime.fromisoformat(last_state['last_run'])
                    time_difference = datetime.now() - last_run_timestamp
                    
                    # If it's been more than configured hours, start fresh
                    if time_difference.total_seconds() > self.scraper_config.get('max_resume_age', 86400):
                        self.logger.info(f"Last run was {time_difference.total_seconds()/3600:.2f} hours ago. Starting fresh scan")
                        start_page = 1
                    else:
                        # Start a few pages back to catch new insertions
                        lookback_pages = self.scraper_config.get('lookback_pages', 5)
                        start_page = max(1, start_page - lookback_pages)
                        self.logger.info(f"Resuming from page {start_page} (with {lookback_pages} pages lookback)")
                except ValueError:
                    self.logger.warning("Invalid last run timestamp. Starting fresh scan")
                    start_page = 1
                    
            page = start_page
            batch_num = len(list(self.raw_dir.glob("batch_*.json"))) + 1
            current_batch_jobs = []
            max_pages = self.scraper_config.get('max_pages', 1000)
            consecutive_empty_pages = 0
            max_empty_pages = self.scraper_config.get('max_empty_pages', 3)
            new_jobs_found = False
            
            # Track the most recent job timestamp we've seen
            most_recent_timestamp = last_run_timestamp
            
            while page <= max_pages:
                try:
                    params = self.create_payload(page=page)
                    
                    result = await self.fetch_jobs(session, params, page)
                    
                    if not result or not result.get('data', {}).get('jobPosts'):
                        self.logger.info("No more jobs found in API response")
                        break
                    
                    jobs = result['data']['jobPosts']
                    self.logger.info(f"Retrieved {len(jobs)} jobs from page {page}")
                    
                    if not jobs:
                        consecutive_empty_pages += 1
                        self.logger.info(f"Empty page {page} (empty count: {consecutive_empty_pages})")
                        if consecutive_empty_pages >= max_empty_pages and page > start_page:
                            self.logger.info(f"Received {max_empty_pages} consecutive empty pages. Stopping.")
                            break
                        page += 1
                        continue
                    
                    # Process jobs and track timestamps
                    processed_jobs = await self.process_jobs(jobs)
                    
                    # Update most recent timestamp
                    for job in jobs:
                        job_timestamp = await self._parse_job_timestamp(job)  # Added await here
                        if job_timestamp and (not most_recent_timestamp or job_timestamp > most_recent_timestamp):
                            most_recent_timestamp = job_timestamp
                    
                    if processed_jobs:
                        new_jobs_found = True
                        consecutive_empty_pages = 0
                        current_batch_jobs.extend(processed_jobs)
                        
                        # Save batch if threshold reached
                        if len(current_batch_jobs) >= self.scraper_config.get('jobs_per_batch', 500):
                            await self._save_batch_with_state(
                                current_batch_jobs, 
                                batch_num,
                                page,
                                most_recent_timestamp
                            )
                            batch_num += 1
                            current_batch_jobs = []
                    else:
                        consecutive_empty_pages += 1
                        self.logger.info(f"No new jobs on page {page} (empty count: {consecutive_empty_pages})")
                        
                        # Check if we should continue based on job timestamps
                        oldest_job_timestamp = await self._get_oldest_job_timestamp(jobs)  # Added await here
                        if oldest_job_timestamp and last_run_timestamp:
                            if oldest_job_timestamp < last_run_timestamp and consecutive_empty_pages >= max_empty_pages:
                                self.logger.info("Reached older jobs with no new content. Stopping.")
                                break
                    
                    # Continue if we're finding new jobs or still in initial pages
                    if new_jobs_found or page - start_page < self.scraper_config.get('minimum_pages', 10):
                        page += 1
                        await asyncio.sleep(self.scraper_config.get('sleep_time', 1))
                    else:
                        if consecutive_empty_pages >= max_empty_pages:
                            self.logger.info("No new jobs found in recent pages. Stopping.")
                            break
                        page += 1
                    
                except Exception as e:
                    await self._handle_error(page, e)
                    
                    if len(self.failed_requests) >= self.scraper_config.get('max_retries', 5):
                        self.logger.error(f"Too many failed requests ({len(self.failed_requests)}). Stopping.")
                        break
                    
                    await asyncio.sleep(self.scraper_config.get('error_sleep_time', 2))
            
            # Save any remaining jobs in the final batch
            if current_batch_jobs:
                await self._save_batch_with_state(
                    current_batch_jobs, 
                    batch_num, 
                    page,
                    most_recent_timestamp
                )
            
            await self._log_final_statistics(page - start_page)

    async def _parse_job_timestamp(self, job: Dict) -> Optional[datetime]:
        """Extract and parse job timestamp"""
        try:
            # Handle the specific structure of your job timestamps
            if 'activationTime' in job and 'date' in job['activationTime']:
                timestamp_str = job['activationTime']['date']
                # Try different timestamp formats
                for fmt in [
                    "%Y-%m-%dT%H:%M:%S.%f",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%dT%H:%M"
                ]:
                    try:
                        return datetime.strptime(timestamp_str, fmt)
                    except ValueError:
                        continue
                
                self.logger.warning(f"Could not parse timestamp {timestamp_str} for job {job.get('id')}")
                return None
            else:
                self.logger.warning(f"No timestamp found for job {job.get('id')}")
                return None
                
        except Exception as e:
            self.logger.warning(f"Error parsing timestamp for job {job.get('id')}: {str(e)}")
            return None

    async def _get_oldest_job_timestamp(self, jobs: List[Dict]) -> Optional[datetime]:
        """Get the oldest timestamp from a list of jobs"""
        timestamps = []
        for job in jobs:
            timestamp = await self._parse_job_timestamp(job)  # Ensure we await the timestamp parsing
            if timestamp:
                timestamps.append(timestamp)
        return min(timestamps) if timestamps else None


    async def _save_batch_with_state(
        self, 
        jobs: List[Dict], 
        batch_num: int, 
        current_page: int, 
        most_recent_timestamp: Optional[datetime]
    ) -> None:
        """Save batch and update state atomically"""
        self.save_batch(jobs, batch_num)
        self.total_jobs_scraped += len(jobs)
        self.logger.info(
            f"Saved batch {batch_num} with {len(jobs)} jobs - "
            f"Total jobs: {self.total_jobs_scraped}"
        )
        
        # Update state with batch and timestamp information
        current_state = {
            'last_page_scraped': current_page,
            'total_jobs_scraped': self.total_jobs_scraped,
            'last_batch_num': batch_num,
            'last_run': datetime.now().isoformat(),
            'most_recent_job_timestamp': (
                most_recent_timestamp.isoformat() 
                if most_recent_timestamp else None
            )
        }
        self.config_manager.save_state(current_state)
        self.logger.debug(f"Updated state after batch save: {current_state}")

    async def _log_final_statistics(self, pages_processed: int) -> None:
        """Log final scraping statistics"""
        stats = {
            'total_jobs_scraped': self.total_jobs_scraped,
            'pages_processed': pages_processed,
            'failed_requests': len(self.failed_requests),
            'unique_jobs': len(self.processed_job_ids),
            'end_time': datetime.now().isoformat()
        }
        
        self.logger.info("Scraping completed. Final statistics:")
        for key, value in stats.items():
            self.logger.info(f"{key}: {value}")
        
        try:
            self.config_manager.save_state({
                'last_run_stats': stats,
                'scraping_complete': True
            })
        except Exception as e:
            self.logger.error(f"Failed to save final statistics: {str(e)}")

    async def _handle_error(self, page: int, error: Exception) -> None:
        """Handle scraping errors with logging and tracking"""
        error_msg = str(error)
        self.logger.error(f"Error on page {page}: {error_msg}")
        self.logger.error(traceback.format_exc())
        
        self.failed_requests.append(page)
        
        # Update state with error information
        error_state = {
            'last_error': {
                'page': page,
                'error': error_msg,
                'timestamp': datetime.now().isoformat()
            },
            'failed_requests': self.failed_requests
        }
        
        try:
            self.config_manager.save_state(error_state)
        except Exception as e:
            self.logger.error(f"Failed to save error state: {str(e)}")
        
        # Check if we should retry based on error type
        if isinstance(error, (aiohttp.ClientError, asyncio.TimeoutError)):
            retry_delay = self.scraper_config.get('error_sleep_time', 2)
            self.logger.info(f"Will retry page {page} after {retry_delay} seconds")
            await asyncio.sleep(retry_delay)
        else:
            self.logger.error(f"Unrecoverable error on page {page}")
            raise