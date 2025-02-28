import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
import logging
from datetime import datetime
import json

class ConfigManager:
    def __init__(self, config_path: str = "config/api_config.yaml"):
        """Initialize ConfigManager with path to config file"""
        self.env = os.getenv('SCRAPER_ENV', 'development')
        self.config_path = Path(config_path)
        self.logger = self._setup_logging()
        self.config = self._load_config()
        self.state_file = Path("job_data/state/scraper_state.json")
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    def _setup_logging(self) -> logging.Logger:
        """Setup logging for config manager"""
        logger = logging.getLogger('ConfigManager')
        logger.propagate = False
        
        if not logger.handlers:
            logger.setLevel(logging.INFO)
            
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)
            ch.setFormatter(formatter)
            logger.addHandler(ch)
        
        return logger

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        try:
            if not self.config_path.exists():
                raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
                
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                
            self._validate_config(config)
            return config
            
        except Exception as e:
            self.logger.error(f"Error loading configuration: {str(e)}")
            raise

    def load_state(self) -> Dict[str, Any]:
        """Public method to load state - this is what the scraper will call"""
        return self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """Internal method to load scraper state from JSON file"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                self.logger.info(f"Loaded state: last page {state.get('last_page_scraped', 0)}, "
                               f"total jobs {state.get('total_jobs_scraped', 0)}")
                return state
            except Exception as e:
                self.logger.error(f"Error loading state: {str(e)}")
                return self._create_default_state()
        return self._create_default_state()

    def _create_default_state(self) -> Dict[str, Any]:
        """Create default state structure"""
        default_state = {
            'last_run': None,
            'total_jobs_scraped': 0,
            'last_page_scraped': 1,
            'last_job_id': None,
            'errors': [],
            'stats': {
                'success_count': 0,
                'error_count': 0,
                'retry_count': 0
            }
        }
        self.logger.info("Created default state")
        return default_state

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """Validate configuration structure"""
        required_sections = ['api', 'request', 'scraper']
        required_api_fields = ['base_url', 'headers']
        required_scraper_fields = [
            'jobs_per_batch', 'sleep_time', 'max_retries',
            'timeout', 'batch_size', 'max_concurrent_requests'
        ]

        for section in required_sections:
            if section not in config:
                raise ValueError(f"Missing required section: {section}")

        for field in required_api_fields:
            if field not in config['api']:
                raise ValueError(f"Missing required API field: {field}")

        for field in required_scraper_fields:
            if field not in config['scraper']:
                raise ValueError(f"Missing required scraper field: {field}")

    def save_state(self, state_update: Dict[str, Any]) -> None:
        """Update and save scraper state"""
        try:
            self.state.update(state_update)
            self.state['last_updated'] = datetime.now().isoformat()
            
            # Create parent directories if they don't exist
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
                
            self.logger.info(f"Saved state: page {self.state.get('last_page_scraped')}, "
                           f"total jobs {self.state.get('total_jobs_scraped')}")
                
        except Exception as e:
            self.logger.error(f"Error saving state: {str(e)}")

    @property
    def api_config(self) -> Dict[str, Any]:
        """Get API configuration"""
        return self.config.get('api', {})

    @property
    def request_config(self) -> Dict[str, Any]:
        """Get request configuration"""
        return self.config.get('request', {})

    @property
    def scraper_config(self) -> Dict[str, Any]:
        """Get scraper configuration"""
        return self.config.get('scraper', {})

    def update_config(self, new_config: Dict[str, Any]) -> None:
        """Update configuration and save to file"""
        try:
            merged_config = self.config.copy()
            merged_config.update(new_config)
            self._validate_config(merged_config)
            
            self.config = merged_config
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, allow_unicode=True)
                
            self.logger.info("Configuration updated successfully")
            
        except Exception as e:
            self.logger.error(f"Error updating configuration: {str(e)}")
            raise

    def get_state(self) -> Dict[str, Any]:
        """Get current scraper state"""
        return self.state.copy()

    def reset_state(self) -> None:
        """Reset scraper state to default values"""
        self.state = self._create_default_state()
        self.save_state({})
        self.logger.info("State reset to default values")
