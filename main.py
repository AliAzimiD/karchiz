import asyncio
import logging
import os
import signal
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
import uuid
from pathlib import Path
from typing import Any, Dict

import yaml

from src.db_manager import DatabaseManager
from src.health import HealthCheck
from src.log_setup import get_logger  # Centralized logger
from src.scraper import JobScraper

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)  # For imports


class GracefulExit:
    """
    Handles graceful shutdown for the application by capturing
    SIGINT and SIGTERM signals, then running registered async tasks.
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
            task (Any): An async function or coroutine to run on exit.
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
        Internal handler that sets shutdown flag on SIGINT or SIGTERM.
        """
        print("\nShutdown signal received. Cleaning up...")
        self.shutdown = True


@asynccontextmanager
async def lifespan():
    """
    Context manager for the app's lifespan. Sets up the DB, health server,
    and ensures graceful teardown if a shutdown signal is received.

    Yields:
        dict: Contains references to graceful_exit, logger, db_manager, config
    """
    logger = get_logger(name="main")
    graceful_exit = GracefulExit()
    config = load_config()

    db_manager: DatabaseManager = None  # type: ignore
    health_runner = None
    health_site = None

    try:
        # Initialize DB connection from config
        connection_str = config["database"]["connection_string"]
        db_manager = DatabaseManager(connection_string=connection_str)
        db_success = await db_manager.initialize()
        if not db_success:
            logger.error("Failed to initialize database connection")
            raise RuntimeError("Database initialization failed")

        # Optionally start health server if config says so
        if config["app"].get("enable_health_check", True):
            health_check = HealthCheck(db_manager)
            host = config["app"].get("health_host", "0.0.0.0")
            port = config["app"].get("health_port", 8082)
            health_runner, health_site = await health_check.start(host=host, port=port)
            logger.info(f"Health check server started on port {port}")

        # On shutdown, close DB + health server
        if db_manager:
            graceful_exit.register_shutdown_task(lambda: db_manager.close())
        if health_runner:
            graceful_exit.register_shutdown_task(lambda: health_runner.cleanup())

        # Provide resources to the caller (e.g. run_scraper)
        yield {
            "graceful_exit": graceful_exit,
            "logger": logger,
            "db_manager": db_manager,
            "config": config,
        }

    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")
        # Cleanup if partial setup occurred
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
    Load config from a YAML file plus environment overrides,
    merging them into a final dictionary.

    Returns:
        dict: Final config with 'app', 'database', 'scraper' keys
    """
    config: Dict[str, Any] = {
        "app": {
            "environment": "development",
            "enable_health_check": True,
            "health_port": 8080,
            "log_level": "INFO",
        },
        "database": {
            "connection_string": "",
            "db_schema": "public",
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

    # Attempt to load from a local config file if it exists
    config_path = os.getenv("CONFIG_PATH", "config/app_config.yaml")
    if os.path.exists(config_path):
        try:
            import yaml

            with open(config_path, "r", encoding="utf-8") as f:
                file_config = yaml.safe_load(f)
                for section in config:
                    if section in file_config:
                        config[section].update(file_config[section])
        except Exception as e:
            logging.warning(f"Error loading config file: {str(e)}")

    # Merge environment variables for DB / app / scraper
    db_user = os.getenv("POSTGRES_USER", "postgres")
    db_password = os.getenv("POSTGRES_PASSWORD", "")
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")
    db_name = os.getenv("POSTGRES_DB", "jobsdb")
    db_schema_env = os.getenv("POSTGRES_SCHEMA")

    # If password is provided via file, prefer that
    pw_file = os.getenv("POSTGRES_PASSWORD_FILE")
    if not db_password and pw_file and os.path.exists(pw_file):
        with open(pw_file, "r", encoding="utf-8") as pf:
            db_password = pf.read().strip()

    config["database"][
        "connection_string"
    ] = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    if db_schema_env:
        config["database"]["db_schema"] = db_schema_env

    # Overwrite app config if present
    if os.getenv("SCRAPER_ENV"):
        config["app"]["environment"] = os.getenv("SCRAPER_ENV")

    if os.getenv("LOG_LEVEL"):
        config["app"]["log_level"] = os.getenv("LOG_LEVEL")

    if os.getenv("ENABLE_HEALTH_CHECK"):
        config["app"]["enable_health_check"] = (
            os.getenv("ENABLE_HEALTH_CHECK").lower() == "true"
        )

    if os.getenv("HEALTH_PORT"):
        config["app"]["health_port"] = int(os.getenv("HEALTH_PORT"))

    # Overwrite scraper config if present
    if os.getenv("SCRAPER_CONFIG_PATH"):
        config["scraper"]["config_path"] = os.getenv("SCRAPER_CONFIG_PATH")

    if os.getenv("SAVE_DIR"):
        config["scraper"]["save_dir"] = os.getenv("SAVE_DIR")

    return config


async def run_scraper(resources: Dict[str, Any]) -> bool:
    """
    Run the job scraper with error handling, DB stats collection, and final logging.

    Args:
        resources (dict): Contains logger, db_manager, config, graceful_exit

    Returns:
        bool: True if successful, False otherwise
    """
    logger: logging.Logger = resources["logger"]
    db_manager: DatabaseManager = resources["db_manager"]
    config: Dict[str, Any] = resources["config"]
    graceful_exit: GracefulExit = resources["graceful_exit"]
    run_id = str(uuid.uuid4())

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
        # Create the scraper with the DB manager
        from src.scraper import JobScraper

        scraper = JobScraper(
            config_path=config["scraper"]["config_path"],
            save_dir=config["scraper"]["save_dir"],
            db_manager=db_manager,
        )

        await db_manager.start_scrape(run_id)

        init_success = await scraper.initialize()
        if not init_success:
            logger.error("Failed to initialize scraper. Exiting.")
            stats["status"] = "failed"
            stats["metadata"]["failure_reason"] = "initialization_failed"
            await db_manager.record_scraper_stats(stats)
            return False

        try:
            # Actually scrape
            result = await scraper.run()
            stats.update(
                {
                    "total_jobs_scraped": result.get("total_jobs", 0),
                    "pages_processed": result.get("pages_processed", 0),
                    # If you track new_jobs separately, include here
                    "status": "completed",
                }
            )
            logger.info(
                f"Scraper run completed. Processed {stats['pages_processed']} pages, "
                f"total {stats['total_jobs_scraped']} jobs."
            )

        except Exception as e:
            # If a fatal error occurs mid-scrape
            if graceful_exit.shutdown:
                logger.info("Scraper interrupted by shutdown signal.")
                stats["status"] = "interrupted"
            else:
                logger.error(f"Error during scraping: {str(e)}")
                stats["status"] = "failed"
                stats["errors"] += 1
                stats["metadata"]["error"] = str(e)
                await db_manager.fail_scrape(run_id, str(e))
        else:
            await db_manager.complete_scrape(run_id, result.get("pages_processed", 0))

    except Exception as e:
        logger.error(f"Critical error in run_scraper: {str(e)}")
        stats["status"] = "failed"
        stats["errors"] += 1
        stats["metadata"]["critical_error"] = str(e)
        await db_manager.fail_scrape(run_id, str(e))
        return False
    finally:
        # Record total run time and store in DB
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
    Main async entry point. Uses lifespan context manager to handle resources.
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
