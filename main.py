import asyncio
import logging
import os
import signal
import sys
import time
import yaml
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from src.scraper import JobScraper
from src.health import HealthCheck
from src.db_manager import DatabaseManager
from src.log_setup import get_logger  # <-- Our new centralized logger

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class GracefulExit:
    """
    Handles graceful shutdown for the application by capturing
    SIGINT and SIGTERM signals and triggering registered async tasks.
    """
    def __init__(self) -> None:
        self.shutdown: bool = False
        self.shutdown_tasks: list[Any] = []
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def register_shutdown_task(self, task: Any) -> None:
        """
        Register a coroutine to be executed during shutdown.

        Args:
            task: Any async function or coroutine to be run at shutdown.
        """
        self.shutdown_tasks.append(task)

    async def execute_shutdown(self) -> None:
        """
        Execute all registered shutdown tasks in sequence.
        """
        if self.shutdown_tasks:
            logging.info(f"Executing {len(self.shutdown_tasks)} shutdown tasks...")
            for task in self.shutdown_tasks:
                try:
                    await task()
                except Exception as e:
                    logging.error(f"Error during shutdown task: {str(e)}")

    def _signal_handler(self, signum, frame) -> None:
        """
        Internal signal handler that sets the shutdown flag.
        """
        print("\nShutdown signal received. Cleaning up...")
        self.shutdown = True

@asynccontextmanager
async def lifespan():
    """
    Context manager for application lifespan management.
    Sets up shared resources (DB, health server) and ensures
    a graceful teardown when finished or if a shutdown signal is received.

    Yields:
        dict: Contains references to the graceful_exit object, logger, db_manager, and config.
    """
    # Setup logging (centralized)
    logger = get_logger(name="main")

    # Setup resources
    graceful_exit = GracefulExit()
    config = load_config()
    db_manager: DatabaseManager = None  # type: ignore
    health_runner = None
    health_site = None

    try:
        # Initialize database connection
        connection_str = config["database"]["connection_string"]
        db_manager = DatabaseManager(connection_string=connection_str)
        db_success = await db_manager.initialize()

        if not db_success:
            logger.error("Failed to initialize database connection")
            raise RuntimeError("Database initialization failed")

        # Start health check server if enabled
        if config["app"].get("enable_health_check", True):
            health_check = HealthCheck(db_manager)
            host = config["app"].get("health_host", "0.0.0.0")
            port = config["app"].get("health_port", 8082)
            health_runner, health_site = await health_check.start(host=host, port=port)
            logger.info(f"Health check server started on port {port}")

        # Register shutdown tasks
        if db_manager:
            graceful_exit.register_shutdown_task(lambda: db_manager.close())
        if health_runner:
            graceful_exit.register_shutdown_task(lambda: health_runner.cleanup())

        yield {
            "graceful_exit": graceful_exit,
            "logger": logger,
            "db_manager": db_manager,
            "config": config
        }

    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")
        if db_manager:
            await db_manager.close()
        if health_runner:
            await health_runner.cleanup()
        raise
    finally:
        if graceful_exit.shutdown:
            await graceful_exit.execute_shutdown()
            logger.info("Graceful shutdown completed")

def load_config() -> Dict[str, Any]:
    """
    Load application configuration from files and environment variables.

    Returns:
        Dict[str, Any]: Consolidated config from file plus environment overrides.
    """
    config: Dict[str, Any] = {
        "app": {
            "environment": "development",
            "enable_health_check": True,
            "health_port": 8080,
            "log_level": "INFO",
        },
        "database": {
            "connection_string": "postgresql://postgres:postgres@localhost:5432/jobsdb",
            "schema": "public",
            "pool_size": 10,
        },
        "scraper": {
            "config_path": "config/api_config.yaml",
            "save_dir": "job_data",
            "batch_size": 100,
            "max_retries": 3,
            "retry_delay": 5,
        },
    }

    config_path = os.getenv("CONFIG_PATH", "config/app_config.yaml")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                file_config = yaml.safe_load(f)
                for section in config:
                    if section in file_config:
                        config[section].update(file_config[section])
        except Exception as e:
            logging.warning(f"Error loading config file: {str(e)}")

    # Environment overrides
    # Database
    if os.getenv("POSTGRES_HOST"):
        db_user = os.getenv("POSTGRES_USER", "postgres")
        db_password = os.getenv("POSTGRES_PASSWORD", "")
        db_host = os.getenv("POSTGRES_HOST", "localhost")
        db_port = os.getenv("POSTGRES_PORT", "5432")
        db_name = os.getenv("POSTGRES_DB", "jobsdb")

        # If password file is present
        pw_file = os.getenv("POSTGRES_PASSWORD_FILE")
        if pw_file and os.path.exists(pw_file):
            with open(pw_file, "r", encoding="utf-8") as pf:
                db_password = pf.read().strip()

        config["database"]["connection_string"] = (
            f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        )

    # App
    if os.getenv("SCRAPER_ENV"):
        config["app"]["environment"] = os.getenv("SCRAPER_ENV")

    if os.getenv("LOG_LEVEL"):
        config["app"]["log_level"] = os.getenv("LOG_LEVEL")

    if os.getenv("ENABLE_HEALTH_CHECK"):
        config["app"]["enable_health_check"] = os.getenv("ENABLE_HEALTH_CHECK").lower() == "true"

    if os.getenv("HEALTH_PORT"):
        config["app"]["health_port"] = int(os.getenv("HEALTH_PORT"))

    # Scraper
    if os.getenv("SCRAPER_CONFIG_PATH"):
        config["scraper"]["config_path"] = os.getenv("SCRAPER_CONFIG_PATH")

    if os.getenv("SAVE_DIR"):
        config["scraper"]["save_dir"] = os.getenv("SAVE_DIR")

    return config

async def run_scraper(resources: Dict[str, Any]) -> bool:
    """
    Run the job scraper with proper error handling and metrics collection.

    Args:
        resources (Dict[str, Any]): Contains references to the logger, db_manager, config, etc.

    Returns:
        bool: True if the scraping completed successfully, False otherwise.
    """
    logger: logging.Logger = resources["logger"]
    db_manager: DatabaseManager = resources["db_manager"]
    config: Dict[str, Any] = resources["config"]
    graceful_exit: GracefulExit = resources["graceful_exit"]

    start_time = time.time()
    stats = {
        "total_jobs_scraped": 0,
        "new_jobs_found": 0,
        "pages_processed": 0,
        "errors": 0,
        "status": "running",
        "metadata": {},
    }

    try:
        # Initialize scraper
        scraper = JobScraper(
            config_path=config["scraper"]["config_path"],
            save_dir=config["scraper"]["save_dir"],
            db_manager=db_manager,
        )
        init_success = await scraper.initialize()
        if not init_success:
            logger.error("Failed to initialize scraper. Exiting.")
            stats["status"] = "failed"
            stats["metadata"]["failure_reason"] = "initialization_failed"
            await db_manager.record_scraper_stats(stats)
            return False

        # Run the scraping
        try:
            scraper_results = await scraper.run()
            stats.update(
                {
                    "total_jobs_scraped": scraper_results.get("total_jobs", 0),
                    "new_jobs_found": scraper_results.get("new_jobs", 0),
                    "pages_processed": scraper_results.get("pages_processed", 0),
                    "status": "completed",
                }
            )
            logger.info(
                f"Scraper run completed. Processed {stats['pages_processed']} pages, "
                f"found {stats['new_jobs_found']} new jobs, total {stats['total_jobs_scraped']}."
            )

        except Exception as e:
            if graceful_exit.shutdown:
                logger.info("Scraper stopped due to shutdown signal")
                stats["status"] = "interrupted"
            else:
                logger.error(f"Error during scraping: {str(e)}")
                stats["status"] = "failed"
                stats["errors"] += 1
                stats["metadata"]["error"] = str(e)

    except Exception as e:
        logger.error(f"Critical error: {str(e)}")
        stats["status"] = "failed"
        stats["errors"] += 1
        stats["metadata"]["critical_error"] = str(e)
        return False
    finally:
        stats["processing_time"] = time.time() - start_time
        try:
            await db_manager.record_scraper_stats(stats)
        except Exception as e:
            logger.error(f"Failed to record scraper stats: {str(e)}")

        logger.info(
            f"Scraper run {stats['status']} in {stats['processing_time']:.2f} seconds"
        )

    return stats["status"] == "completed"

async def main() -> int:
    """
    Main application entry point with proper resource management.

    Returns:
        int: 0 if the scraper completes successfully, 1 otherwise.
    """
    try:
        async with lifespan() as resources:
            success = await run_scraper(resources)
            return 0 if success else 1
    except Exception as e:
        print(f"Fatal error in main(): {str(e)}")
        return 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nScript terminated by user")
        sys.exit(130)
    except Exception as e:
        print(f"Fatal error: {str(e)}")
        sys.exit(1)
