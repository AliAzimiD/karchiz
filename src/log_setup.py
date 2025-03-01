"""
log_setup.py
Centralized logging configuration to be used by all modules in the Job Scraper project.
"""
import logging
import sys
from pathlib import Path
from datetime import datetime
import os


def get_logger(
    name: str = "job_scraper",
    log_dir: str = "job_data/logs",
    log_level_env_var: str = "LOG_LEVEL"
) -> logging.Logger:
    """
    Return a configured logger instance that writes to both console and a rolling file.

    Args:
        name (str): Name for the logger.
        log_dir (str): Directory path for log files.
        log_level_env_var (str): Environment variable to override logging level.

    Returns:
        logging.Logger: Configured logger.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        # Already configured
        return logger

    # Determine log level
    log_level_str = os.getenv(log_level_env_var, "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    # Ensure directory
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_path = Path(log_dir) / f"{name}_{timestamp}.log"

    # Configure logger
    logger.setLevel(log_level)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")

    # File handler
    fh = logging.FileHandler(log_file_path, encoding="utf-8")
    fh.setLevel(log_level)
    fh.setFormatter(formatter)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(log_level)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)
    logger.propagate = False

    logger.info(f"Logger {name} initialized at level {log_level_str}. Log file: {log_file_path}")
    return logger
