import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import ValidationError

from .config_models import (
    APIConfig,
    AppConfig,
    DatabaseConfig,
    RequestConfig,
    ScraperConfig,
)
from .log_setup import get_logger

# Central logger for ConfigManager
logger = get_logger("ConfigManager")


class ConfigManager:
    """
    Manages configuration and state for the job scraper.
    Loads from a YAML file and optionally merges environment variables.
    Also handles saving 'state' to allow resuming or tracking scraping progress.
    """

    def __init__(self, config_path: str = "config/api_config.yaml") -> None:
        """
        Initialize the config manager and load the YAML configuration.

        Args:
            config_path (str): Path to the YAML config file.
        """
        self.config_path: str = config_path
        # Immediately load and validate configuration
        self._load_config()

        # Setup the directory for storing persistent 'state' JSON
        self.state_dir = Path("job_data/state")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / "scraper_state.json"

    def _load_config(self) -> None:
        """
        Load configuration from the specified YAML file
        and parse it into class attributes (api_config, request_config, scraper_config, etc.).
        """
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw_config = yaml.safe_load(f) or {}

            env_base_url = os.getenv("API_BASE_URL")
            if env_base_url:
                raw_config.setdefault("api", {})
                raw_config["api"]["base_url"] = env_base_url

            try:
                parsed = AppConfig.model_validate(raw_config)
            except ValidationError as e:
                logger.error("Configuration validation failed")
                logger.error(str(e))
                raise

            # Store parsed sections
            self.config: AppConfig = parsed
            self.api_config: APIConfig = parsed.api
            self.request_config: RequestConfig = parsed.request
            self.scraper_config: ScraperConfig = parsed.scraper
            self.database_config: DatabaseConfig = parsed.scraper.database

            logger.info("Configuration loaded and validated successfully")
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {self.config_path}")
            raise
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error loading configuration: {str(e)}")
            raise

    def load_state(self) -> Dict[str, Any]:
        """
        Load the latest scraper state from a JSON file, or return an empty dict if none exists.

        Returns:
            Dict[str, Any]: The loaded state dictionary.
        """
        if not self.state_file.exists():
            logger.info("No state file found. Starting fresh.")
            return {}
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            logger.info(f"Loaded state from {self.state_file}")
            return state
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing state file: {str(e)}")
            return {}
        except Exception as e:
            logger.error(f"Error loading state: {str(e)}")
            return {}

    def save_state(self, state_update: Dict[str, Any]) -> None:
        """
        Update and persist the scraper state with new values in JSON form.

        Args:
            state_update (Dict[str, Any]): Key-value pairs to update in the stored state.
        """
        try:
            current_state = self.load_state()
            current_state.update(state_update)

            # Always store a timestamp of the last update if not included
            if "last_updated" not in state_update:
                current_state["last_updated"] = datetime.now().isoformat()

            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(current_state, f, indent=2, ensure_ascii=False)

            # Optionally create a backup if configured in 'state_tracking'
            backup_count = self.scraper_config.state_tracking.backup_count
            if backup_count > 0:
                self._create_state_backup(backup_count)

            logger.debug("State updated successfully")
        except Exception as e:
            logger.error(f"Error saving state: {str(e)}")

    def _create_state_backup(self, backup_count: int) -> None:
        """
        Create a timestamped backup of the current state file, then remove older backups.

        Args:
            backup_count (int): Number of backups to keep.
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = self.state_dir / f"scraper_state_{timestamp}.json"

            if self.state_file.exists():
                with open(self.state_file, "r", encoding="utf-8") as src:
                    with open(backup_file, "w", encoding="utf-8") as dst:
                        dst.write(src.read())

            # Remove oldest backups if exceeding backup_count
            backups = sorted(self.state_dir.glob("scraper_state_*.json"))
            if len(backups) > backup_count:
                for old_backup in backups[:-backup_count]:
                    old_backup.unlink()
        except Exception as e:
            logger.error(f"Error creating state backup: {str(e)}")

    def should_save_files_with_db(self) -> bool:
        """
        Check if we should still save raw JSON/CSV/Parquet locally
        even when the database is enabled.

        Returns:
            bool: True if local file saving is desired alongside DB usage.
        """
        return self.database_config.save_raw_data

    def get_db_connection_string(self) -> Optional[str]:
        """
        Return the database connection string if 'enabled' is True in the config.

        Returns:
            Optional[str]: Connection URI or None if the database is not enabled.
        """
        if self.database_config.enabled:
            return self.database_config.connection_string
        return None

    def get_max_concurrent_requests(self) -> int:
        """
        Get the maximum number of concurrent HTTP requests allowed by the scraper.

        Returns:
            int: The concurrency limit (default 3 if missing).
        """
        return self.scraper_config.max_concurrent_requests

    def get_rate_limits(self) -> Dict[str, int]:
        """
        Get rate-limiting parameters from the config (requests_per_minute, burst).

        Returns:
            dict: Rate limit parameters.
        """
        rl = self.scraper_config.rate_limit
        return {
            "requests_per_minute": rl.requests_per_minute,
            "burst": rl.burst,
        }

    def get_retry_config(self) -> Dict[str, Any]:
        """
        Get retry-related parameters for controlling backoff logic.

        Returns:
            dict: Contains max_retries, min_delay, max_delay used for tenacity or similar.
        """
        rd = self.scraper_config.retry_delay
        return {
            "max_retries": self.scraper_config.max_retries,
            "min_delay": rd.min,
            "max_delay": rd.max,
        }

    def get_monitoring_config(self) -> Dict[str, Any]:
        """
        Retrieve monitoring-related configuration if present.

        Returns:
            dict: A dictionary of monitoring settings (metrics, thresholds, etc.).
        """
        return self.scraper_config.monitoring.model_dump()

    def update_config(self, section: str, key: str, value: Any) -> None:
        """
        Update a specific configuration value in the YAML file, then reload.

        Args:
            section (str): Name of the top-level config section (e.g. 'scraper', 'database').
            key (str): Key within that section.
            value (Any): New value to store.
        """
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            if section not in config:
                config[section] = {}
            config[section][key] = value

            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, default_flow_style=False)

            # Reload the config into memory
            self._load_config()
            logger.info(f"Updated config: {section}.{key} = {value}")

        except Exception as e:
            logger.error(f"Error updating config: {str(e)}")
