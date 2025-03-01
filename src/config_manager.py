import json
import logging
import os
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from .log_setup import get_logger

logger = get_logger("ConfigManager")

class ConfigManager:
    """
    Manages configuration and state for the job scraper. Loads from a YAML file
    and optionally merges environment variables. Also handles saving 'state'.
    """

    def __init__(self, config_path: str = "config/api_config.yaml") -> None:
        """
        Initialize the config manager and load the YAML configuration.

        Args:
            config_path (str): Path to the YAML config file.
        """
        self.config_path: str = config_path
        self._load_config()

        self.state_dir = Path("job_data/state")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / "scraper_state.json"

    def _load_config(self) -> None:
        """
        Load configuration from the specified YAML file
        and parse it into class attributes.
        """
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            self.api_config: Dict[str, Any] = config.get("api", {})
            self.request_config: Dict[str, Any] = config.get("request", {})
            self.scraper_config: Dict[str, Any] = config.get("scraper", {})
            self.database_config: Dict[str, Any] = config.get("database", {})

            if not self.api_config:
                logger.warning("API configuration section is missing or empty")
            if not self.request_config:
                logger.warning("Request configuration is missing or empty")
            if not self.scraper_config:
                logger.warning("Scraper configuration is missing or empty")

            logger.info("Configuration loaded successfully from YAML")
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
        Load the latest scraper state from a JSON file.
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
        Update and persist the scraper state with new values.

        Args:
            state_update (Dict[str, Any]): Key-value pairs to update in the state.
        """
        try:
            current_state = self.load_state()
            current_state.update(state_update)

            if "last_updated" not in state_update:
                current_state["last_updated"] = datetime.now().isoformat()

            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(current_state, f, indent=2, ensure_ascii=False)

            backup_count = self.scraper_config.get("state_tracking", {}).get("backup_count", 3)
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

            backups = sorted(self.state_dir.glob("scraper_state_*.json"))
            if len(backups) > backup_count:
                for old_backup in backups[:-backup_count]:
                    old_backup.unlink()
        except Exception as e:
            logger.error(f"Error creating state backup: {str(e)}")

    def should_save_files_with_db(self) -> bool:
        """
        Check if we should save files locally even when the database is enabled.
        """
        return self.database_config.get("save_raw_data", True)

    def get_db_connection_string(self) -> Optional[str]:
        """
        Get the DB connection string if the database is enabled.
        """
        if self.database_config.get("enabled", False):
            return self.database_config.get("connection_string")
        return None


    def get_max_concurrent_requests(self) -> int:
        """
        Get the max number of concurrent requests allowed by the scraper.

        Returns:
            int: The concurrency limit.
        """
        return self.scraper_config.get('max_concurrent_requests', 3)

    def get_rate_limits(self) -> Dict[str, int]:
        """
        Get rate-limiting parameters from the config.

        Returns:
            dict: Contains requests_per_minute and burst sizes.
        """
        rate_limit = self.scraper_config.get('rate_limit', {})
        return {
            'requests_per_minute': rate_limit.get('requests_per_minute', 60),
            'burst': rate_limit.get('burst', 5)
        }

    def get_retry_config(self) -> Dict[str, Any]:
        """
        Get retry configuration from the config.

        Returns:
            dict: Contains max_retries and min/max delays.
        """
        return {
            'max_retries': self.scraper_config.get('max_retries', 5),
            'min_delay': self.scraper_config.get('retry_delay', {}).get('min', 2),
            'max_delay': self.scraper_config.get('retry_delay', {}).get('max', 10)
        }

    def get_monitoring_config(self) -> Dict[str, Any]:
        """
        Get monitoring-related config if specified.

        Returns:
            dict: Monitoring config dictionary.
        """
        return self.scraper_config.get('monitoring', {})

    def update_config(self, section: str, key: str, value: Any) -> None:
        """
        Update a specific configuration value and reload the YAML file.

        Args:
            section (str): Top-level config section (e.g. 'scraper', 'database').
            key (str): The config key to update.
            value (Any): The new value to store.
        """
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            if section not in config:
                config[section] = {}
            config[section][key] = value

            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False)

            self._load_config()
            logger.info(f"Updated config: {section}.{key} = {value}")

        except Exception as e:
            logger.error(f"Error updating config: {str(e)}")
