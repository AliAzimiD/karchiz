import asyncio
import logging
from pathlib import Path
from datetime import datetime
import signal
import sys
from src.scraper import JobScraper

class GracefulExit:
    def __init__(self):
        self.shutdown = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        print("\nShutdown signal received. Cleaning up...")
        self.shutdown = True

async def setup_logging():
    log_dir = Path("job_data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / f"scraper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.getLogger().handlers = []  # Add this line here
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger(__name__)

async def main():
    # Initialize graceful exit handler
    graceful_exit = GracefulExit()
    
    # Setup logging
    logger = await setup_logging()
    logger.info("Starting job scraper...")

    try:
        # Initialize scraper
        scraper = JobScraper(
            config_path="config/api_config.yaml",
            save_dir="job_data"
        )
        
        # Run scraper until completion or interruption
        while not graceful_exit.shutdown:
            try:
                await scraper.scrape()
                logger.info("Scraping completed successfully")
                break
            except Exception as e:
                logger.error(f"Error during scraping: {str(e)}")
                if not graceful_exit.shutdown:
                    logger.info("Retrying in 60 seconds...")
                    await asyncio.sleep(60)
                else:
                    break
        
    except Exception as e:
        logger.error(f"Critical error: {str(e)}")
        sys.exit(1)
    finally:
        if graceful_exit.shutdown:
            logger.info("Graceful shutdown completed")
        
        # Cleanup code here if needed
        await asyncio.sleep(1)  # Allow final logs to be written

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScript terminated by user")
    except Exception as e:
        print(f"Fatal error: {str(e)}")
        sys.exit(1)
