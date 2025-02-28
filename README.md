# Job Scraper

A robust, containerized job scraper application that collects job listings from APIs and stores them for analysis.

## Features

- Asynchronous scraping with robust error handling and retry logic
- Configurable scraping parameters
- Data storage in multiple formats (JSON, CSV, Parquet)
- Docker containerization for easy deployment
- State management for resuming interrupted scraping
- Detailed logging

## Setup

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development)

### Configuration

Edit the `config/api_config.yaml` file to configure:
- API endpoints and headers
- Request payload structure
- Scraper behavior (batch sizes, timeouts, etc.)

### Running with Docker


# Build the container
make build

# Start the scraper
make start

# View logs
make logs

# Stop the scraper
make stop

# Development Mode
make dev

# Project Structure
src/: Core scraper code
scraper.py: Main scraper implementation
config_manager.py: Configuration management
config/: Configuration files
main.py: Application entry point
Dockerfile & docker-compose.yml: Container configuration
Makefile & docker_manage.sh: Utility scripts

# Data Output
Scraped data is saved to:

job_data/raw_data/: Raw JSON files
job_data/processed_data/: Processed CSV and Parquet files
job_data/logs/: Log files EOF