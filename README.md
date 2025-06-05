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

Then visit [http://localhost:8088](http://localhost:8088) and log in using the default credentials
`admin` / `admin`. Configure a new Postgres database connection pointing to the `db` service to
build charts and dashboards.
Monitoring
health.py listens on /health and /metrics.
Integration with Prometheus or other monitoring solutions is possible by adding Prometheus exporters.
=======
## Monitoring
`health.py` exposes `/health` and `/metrics`. The `/metrics` endpoint now serves Prometheus-formatted metrics using `prometheus_client`.

When running with the provided Docker Compose file, port `8080` is mapped, so a Prometheus server can scrape metrics from `http://localhost:8080/metrics`.

Integration with Prometheus or other monitoring solutions is straightforward—just add a scrape job pointing at the above URL.

Security & Secrets
Uses Docker secrets (db_password_file) for DB.
For advanced production, adopt AWS Secrets Manager, Vault, or other secure secret retrieval.
License
[Specify your license here, e.g. MIT]

importatnt queries:
Add New Columns for Tags (One-Hot Encoding)
sql
Copy
-- Step 1: Add new columns to store binary values
ALTER TABLE jobs_table 
ADD COLUMN tag_no_experience INT DEFAULT 0,
ADD COLUMN tag_remote INT DEFAULT 0,
ADD COLUMN tag_part_time INT DEFAULT 0,
ADD COLUMN tag_internship INT DEFAULT 0,
ADD COLUMN tag_military_exemption INT DEFAULT 0;

-- Step 2: Update the new columns based on JSONB tags array
UPDATE jobs_table
SET 
    tag_no_experience = CASE WHEN EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(tags) AS tag WHERE tag = 'بدون نیاز به سابقه'
    ) THEN 1 ELSE 0 END,

    tag_remote = CASE WHEN EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(tags) AS tag WHERE tag = 'دورکاری'
    ) THEN 1 ELSE 0 END,

    tag_part_time = CASE WHEN EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(tags) AS tag WHERE tag = 'پاره وقت'
    ) THEN 1 ELSE 0 END,

    tag_internship = CASE WHEN EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(tags) AS tag WHERE tag = 'کارآموزی'
    ) THEN 1 ELSE 0 END,

    tag_military_exemption = CASE WHEN EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(tags) AS tag WHERE tag = 'امریه سربازی'
    ) THEN 1 ELSE 0 END;
2️⃣ Add & Populate "jobBoard titleEn" and "jobBoard titleFa"
sql
Copy
-- Step 1: Add new columns
ALTER TABLE jobs_table 
ADD COLUMN jobBoard_titleEn TEXT,
ADD COLUMN jobBoard_titleFa TEXT;

-- Step 2: Update the new columns by extracting values from the "raw_data" JSONB column
UPDATE jobs_table
SET 
    jobBoard_titleEn = raw_data->'jobBoard'->>'titleEn',
    jobBoard_titleFa = raw_data->'jobBoard'->>'titleFa'
WHERE raw_data ? 'jobBoard';


-- Alter the table to add new columns
ALTER TABLE jobs
ADD COLUMN primary_city text,
ADD COLUMN work_type text,
ADD COLUMN category text,
ADD COLUMN sub_cat text,
ADD COLUMN parent_cat text;

-- Update primary_city by extracting the first element's "city"->"titleEn" from locations JSON array
UPDATE jobs
SET primary_city = (
    SELECT elem->'city'->>'titleEn'
    FROM jsonb_array_elements(locations::jsonb) AS elem
    LIMIT 1
)
WHERE locations IS NOT NULL
  AND jsonb_typeof(locations::jsonb) = 'array';

-- Update work_type by extracting the first element's "titleEn" from work_types JSON array
UPDATE jobs
SET work_type = (
    SELECT elem->>'titleEn'
    FROM jsonb_array_elements(work_types::jsonb) AS elem
    LIMIT 1
)
WHERE work_types IS NOT NULL
  AND jsonb_typeof(work_types::jsonb) = 'array';

-- Update category, parent_cat, and sub_cat from job_post_categories JSON array.
-- Only update rows where job_post_categories is a valid JSON array.
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



-------------------------------------
-- Step 1: Add new columns to store binary values (avoid error if they exist)
ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS tag_no_experience INT DEFAULT 0,
ADD COLUMN IF NOT EXISTS tag_remote INT DEFAULT 0,
ADD COLUMN IF NOT EXISTS tag_part_time INT DEFAULT 0,
ADD COLUMN IF NOT EXISTS tag_internship INT DEFAULT 0,
ADD COLUMN IF NOT EXISTS tag_military_exemption INT DEFAULT 0;

-- Step 2: Update the new columns based on JSONB tags array
UPDATE jobs
SET 
    tag_no_experience = CASE WHEN EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(tags) AS tag WHERE tag = 'بدون نیاز به سابقه'
    ) THEN 1 ELSE 0 END,

    tag_remote = CASE WHEN EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(tags) AS tag WHERE tag = 'دورکاری'
    ) THEN 1 ELSE 0 END,

    tag_part_time = CASE WHEN EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(tags) AS tag WHERE tag = 'پاره وقت'
    ) THEN 1 ELSE 0 END,

    tag_internship = CASE WHEN EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(tags) AS tag WHERE tag = 'کارآموزی'
    ) THEN 1 ELSE 0 END,

    tag_military_exemption = CASE WHEN EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(tags) AS tag WHERE tag = 'امریه سربازی'
    ) THEN 1 ELSE 0 END;

-- Step 3: Add columns for job board title (avoid error if they exist)
ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS jobBoard_titleEn TEXT,
ADD COLUMN IF NOT EXISTS jobBoard_titleFa TEXT;

-- Step 4: Update job board title columns based on JSONB data
UPDATE jobs
SET 
    jobBoard_titleEn = raw_data->'jobBoard'->>'titleEn',
    jobBoard_titleFa = raw_data->'jobBoard'->>'titleFa'
WHERE raw_data ? 'jobBoard';

-- Step 5: Add columns for location, work type, and categories (avoid error if they exist)
ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS primary_city TEXT,
ADD COLUMN IF NOT EXISTS work_type TEXT,
ADD COLUMN IF NOT EXISTS category TEXT,
ADD COLUMN IF NOT EXISTS sub_cat TEXT,
ADD COLUMN IF NOT EXISTS parent_cat TEXT;

-- Step 6: Update primary_city by extracting "city"->"titleEn" from locations JSON array
UPDATE jobs
SET primary_city = (
    SELECT elem->'city'->>'titleEn'
    FROM jsonb_array_elements(locations::jsonb) AS elem
    LIMIT 1
)
WHERE locations IS NOT NULL
  AND jsonb_typeof(locations::jsonb) = 'array';

-- Step 7: Update work_type by extracting "titleEn" from work_types JSON array
UPDATE jobs
SET work_type = (
    SELECT elem->>'titleEn'
    FROM jsonb_array_elements(work_types::jsonb) AS elem
    LIMIT 1
)
WHERE work_types IS NOT NULL
  AND jsonb_typeof(work_types::jsonb) = 'array';

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
