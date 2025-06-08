from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConfigBase(BaseModel):
    """Base model that supports dict-style access."""

    def __getitem__(self, item: str):
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)


class APIConfig(ConfigBase):
    """Configuration options for the API section."""

    base_url: str = Field("", description="Base URL for the API endpoint")
    headers: Dict[str, str] = Field(default_factory=dict, description="HTTP headers to include")


class RequestConfig(ConfigBase):
    """Default request payload settings."""

    default_payload: Dict[str, Any] = Field(default_factory=dict)


class DatabaseConfig(ConfigBase):
    """Database related configuration."""

    enabled: bool = False
    connection_string: Optional[str] = None
    db_schema: str = Field("public", alias="schema")
    batch_size: int = 1000
    save_raw_data: bool = True
    max_connections: int = 10
    retry_attempts: int = 3
    retry_delay: int = 5


class RateLimitConfig(ConfigBase):
    requests_per_minute: int = 60
    burst: int = 5


class RetryDelayConfig(ConfigBase):
    min: int = 2
    max: int = 10


class StateTrackingConfig(ConfigBase):
    enabled: bool = True
    save_interval: int = 300
    backup_count: int = 3


class TimestampSettings(ConfigBase):
    format: str = "%Y-%m-%dT%H:%M:%S.%fZ"
    timezone: str = "UTC"


class DeduplicationConfig(ConfigBase):
    enabled: bool = True
    method: str = "id_based"
    cache_size: int = 10000


class MonitoringConfig(ConfigBase):
    enabled: bool = False
    metrics: List[str] = Field(default_factory=list)
    alert_thresholds: Dict[str, int] = Field(default_factory=dict)


class ValidationConfig(ConfigBase):
    enabled: bool = False
    required_fields: List[str] = Field(default_factory=list)


class OutputConfig(ConfigBase):
    format: str = "json"
    compression: bool = True
    batch_prefix: str = "batch_"
    timestamp_format: str = "%Y%m%d_%H%M%S"


class CleanupConfig(ConfigBase):
    enabled: bool = True
    max_age_days: int = 7
    keep_last_n_batches: int = 50


class DebugConfig(ConfigBase):
    enabled: bool = False
    verbose_logging: bool = False
    save_raw_responses: bool = False


class ScraperConfig(ConfigBase):
    """Main scraper configuration options."""

    database: DatabaseConfig = DatabaseConfig()
    batch_size: int = 100
    jobs_per_batch: int = 1000
    max_pages: int = 1000
    chunk_size: int = 1000
    memory_limit: int = 1024
    max_concurrent_requests: int = 3
    timeout: int = 60
    sleep_time: float = 0.5
    rate_limit: RateLimitConfig = RateLimitConfig()
    max_retries: int = 5
    retry_delay: RetryDelayConfig = RetryDelayConfig()
    lookback_pages: int = 5
    minimum_pages: int = 10
    max_empty_pages: int = 3
    max_resume_age: int = 86400
    state_tracking: StateTrackingConfig = StateTrackingConfig()
    timestamp_settings: TimestampSettings = TimestampSettings()
    deduplication: DeduplicationConfig = DeduplicationConfig()
    monitoring: MonitoringConfig = MonitoringConfig()
    validation: ValidationConfig = ValidationConfig()
    output: OutputConfig = OutputConfig()
    cleanup: CleanupConfig = CleanupConfig()
    debug: DebugConfig = DebugConfig()
    error_sleep_time: int = 2


class AppConfig(ConfigBase):
    api: APIConfig = APIConfig()
    request: RequestConfig = RequestConfig()
    scraper: ScraperConfig = ScraperConfig()
