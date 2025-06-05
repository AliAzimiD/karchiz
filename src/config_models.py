from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class APIConfig(BaseModel):
    """Configuration options for the API section."""

    base_url: str = Field(..., description="Base URL for the API endpoint")
    headers: Dict[str, str] = Field(..., description="HTTP headers to include")


class RequestConfig(BaseModel):
    """Default request payload settings."""

    default_payload: Dict[str, Any] = Field(default_factory=dict)


class DatabaseConfig(BaseModel):
    """Database related configuration."""

    enabled: bool = False
    connection_string: Optional[str] = None
    schema: str = "public"
    batch_size: int = 1000
    save_raw_data: bool = True
    max_connections: int = 10
    retry_attempts: int = 3
    retry_delay: int = 5


class RateLimitConfig(BaseModel):
    requests_per_minute: int = 60
    burst: int = 5


class RetryDelayConfig(BaseModel):
    min: int = 2
    max: int = 10


class StateTrackingConfig(BaseModel):
    enabled: bool = True
    save_interval: int = 300
    backup_count: int = 3


class TimestampSettings(BaseModel):
    format: str = "%Y-%m-%dT%H:%M:%S.%fZ"
    timezone: str = "UTC"


class DeduplicationConfig(BaseModel):
    enabled: bool = True
    method: str = "id_based"
    cache_size: int = 10000


class MonitoringConfig(BaseModel):
    enabled: bool = False
    metrics: List[str] = Field(default_factory=list)
    alert_thresholds: Dict[str, int] = Field(default_factory=dict)


class ValidationConfig(BaseModel):
    enabled: bool = False
    required_fields: List[str] = Field(default_factory=list)


class OutputConfig(BaseModel):
    format: str = "json"
    compression: bool = True
    batch_prefix: str = "batch_"
    timestamp_format: str = "%Y%m%d_%H%M%S"


class CleanupConfig(BaseModel):
    enabled: bool = True
    max_age_days: int = 7
    keep_last_n_batches: int = 50


class DebugConfig(BaseModel):
    enabled: bool = False
    verbose_logging: bool = False
    save_raw_responses: bool = False


class ScraperConfig(BaseModel):
    """Main scraper configuration options."""

    database: DatabaseConfig
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


class AppConfig(BaseModel):
    api: APIConfig
    request: RequestConfig
    scraper: ScraperConfig
