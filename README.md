# Job Scraper

## Overview
A Python 3.11+ asynchronous application that scrapes job postings from remote APIs and stores them in a PostgreSQL database or local files (JSON, CSV, Parquet). Deployable via Docker for robust scheduling (cron-based) and containerized observability.

## Directory Structure

job_scraper/ ├── Dockerfile ├── docker-compose.yml ├── main.py ├── src/ │ ├── log_setup.py <-- Central logging config │ ├── scraper.py │ ├── scheduler.py │ ├── db_manager.py │ ├── config_manager.py │ ├── health.py ├── tests/ │ ├── test_db_manager.py │ └── test_scraper.py └── ...

perl
Copy
Edit

## Major Components
1. **`main.py`**  
   - Sets up resources, runs the scraper, logs results, triggers graceful shutdown.
2. **`scraper.py`**: `JobScraper`  
   - Fetches paginated data from configured API, handles retries, saves results.
3. **`db_manager.py`**: `DatabaseManager`  
   - Manages async DB access (bulk upsert with temp tables), plus stats & batch tracking.
4. **`config_manager.py`**: `ConfigManager`  
   - Loads YAML config, merges environment overrides, saves “scraper_state.json”.
5. **`health.py`**: `HealthCheck`  
   - Exposes `aiohttp`-based endpoints for health and metrics checks.
6. **`log_setup.py`** (newly added)  
   - Centralized logging logic to be imported by other modules.
7. **`scheduler.py`**: `JobScraperScheduler`  
   - Repeated scheduled runs of the scraper in a loop.

## Setup & Installation

### Docker Deployment
1. `make build`  
2. `make start`  

The scraper container runs automatically, uses a cron job to schedule repeated scraping, and logs to `job_data/logs/`.

### Local Development
1. `python -m venv venv && source venv/bin/activate`
2. `pip install -r requirements.txt`
3. `python main.py`

## Testing
The project uses `pytest` with the `pytest-asyncio` plugin. Both packages are
included in `requirements.txt`.

Run tests from the repository root with:

```bash
pytest --asyncio-mode=auto --cov=src --cov-report=html
```

Configuration
config/api_config.yaml: Main scraping + DB parameters
Environment variables override YAML settings. Database credentials are pulled
from `POSTGRES_*` variables or files so no passwords live in the repo.
CI/CD
Minimal example in .github/workflows/ci.yml sets up mypy checks, lint, bandit, tests, code coverage.

## Data Visualization with Superset
This project integrates [Apache Superset](https://superset.apache.org/) for exploring the scraped
PostgreSQL data. Start the service with:

```bash
docker-compose up -d superset
```

-- Step 8: Update category, parent_cat, and sub_cat from job_post_categories JSON array.
UPDATE jobs
SET 
  category = CASE 
    WHEN jsonb_array_length(job_post_categories::jsonb) >= 2 
      THEN job_post_categories::jsonb -> 1 ->> 'titleEn'
    WHEN jsonb_array_length(job_post_categories::jsonb) = 1 
      THEN job_post_categories::jsonb -> 0 ->> 'titleEn'
    ELSE NULL
  END,
  parent_cat = CASE 
    WHEN jsonb_array_length(job_post_categories::jsonb) >= 2 
      THEN job_post_categories::jsonb -> 0 ->> 'titleEn'
    ELSE NULL
  END,
  sub_cat = CASE 
    WHEN jsonb_array_length(job_post_categories::jsonb) >= 2 
      THEN job_post_categories::jsonb -> 1 ->> 'titleEn'
    ELSE NULL
  END
WHERE job_post_categories IS NOT NULL
  AND jsonb_typeof(job_post_categories::jsonb) = 'array';
