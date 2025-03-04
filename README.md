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
Tests are in `tests/`; run with:
```bash
pytest --asyncio-mode=auto --cov=src --cov-report=html
Configuration
config/api_config.yaml: Main scraping + DB parameters
Environment variables override YAML settings:
SCRAPER_ENV, POSTGRES_HOST, LOG_LEVEL, etc.
CI/CD
Minimal example in .github/workflows/ci.yml sets up mypy checks, lint, bandit, tests, code coverage.
Monitoring
health.py listens on /health and /metrics.
Integration with Prometheus or other monitoring solutions is possible by adding Prometheus exporters.
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
-------------------------------------------------------------

In PostgreSQL, you have essentially two main ways to ensure that these derived columns are always populated for new or updated rows:

1. **Use a Trigger** (most common approach)
2. Use a **Generated Column** (with limitations, especially when referencing JSON data).

Below is the recommended approach using a **trigger**. The high-level idea is:

- Create the columns (if they do not exist).
- Write a PL/pgSQL function that calculates/populates those columns from the JSON fields.
- Attach that function to the table via a `BEFORE INSERT OR UPDATE` trigger so that every new or updated row automatically gets these fields populated.

---

## 1) Create the columns (if they do not already exist)

```sql
ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS tag_no_experience INT DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tag_remote INT DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tag_part_time INT DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tag_internship INT DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tag_military_exemption INT DEFAULT 0,
  ADD COLUMN IF NOT EXISTS jobBoard_titleEn TEXT,
  ADD COLUMN IF NOT EXISTS jobBoard_titleFa TEXT,
  ADD COLUMN IF NOT EXISTS primary_city TEXT,
  ADD COLUMN IF NOT EXISTS work_type TEXT,
  ADD COLUMN IF NOT EXISTS category TEXT,
  ADD COLUMN IF NOT EXISTS parent_cat TEXT,
  ADD COLUMN IF NOT EXISTS sub_cat TEXT;
```

> **Note**: If some of these columns already exist or you already added them, you can skip the columns already in place.

---

## 2) Create a PL/pgSQL Function to Populate the Columns

This function will apply the same logic that you were using in your manual `UPDATE` statements but will do so whenever a row is inserted or updated.

```sql
CREATE OR REPLACE FUNCTION fn_update_derived_columns()
RETURNS TRIGGER AS
$$
BEGIN
    -------------------------------------------------------------------
    -- Tags logic
    -------------------------------------------------------------------
    IF NEW.tags IS NOT NULL THEN

        -- tag_no_experience
        NEW.tag_no_experience := CASE 
            WHEN EXISTS (SELECT 1 
                         FROM jsonb_array_elements_text(NEW.tags) AS t
                         WHERE t = 'بدون نیاز به سابقه')
            THEN 1
            ELSE 0
        END;
        
        -- tag_remote
        NEW.tag_remote := CASE 
            WHEN EXISTS (SELECT 1 
                         FROM jsonb_array_elements_text(NEW.tags) AS t
                         WHERE t = 'دورکاری')
            THEN 1
            ELSE 0
        END;

        -- tag_part_time
        NEW.tag_part_time := CASE 
            WHEN EXISTS (SELECT 1 
                         FROM jsonb_array_elements_text(NEW.tags) AS t
                         WHERE t = 'پاره وقت')
            THEN 1
            ELSE 0
        END;

        -- tag_internship
        NEW.tag_internship := CASE 
            WHEN EXISTS (SELECT 1 
                         FROM jsonb_array_elements_text(NEW.tags) AS t
                         WHERE t = 'کارآموزی')
            THEN 1
            ELSE 0
        END;

        -- tag_military_exemption
        NEW.tag_military_exemption := CASE 
            WHEN EXISTS (SELECT 1 
                         FROM jsonb_array_elements_text(NEW.tags) AS t
                         WHERE t = 'امریه سربازی')
            THEN 1
            ELSE 0
        END;

    END IF;

    -------------------------------------------------------------------
    -- jobBoard_titleEn & jobBoard_titleFa logic
    -------------------------------------------------------------------
    IF NEW.raw_data ? 'jobBoard' THEN
        NEW.jobBoard_titleEn := NEW.raw_data->'jobBoard'->>'titleEn';
        NEW.jobBoard_titleFa := NEW.raw_data->'jobBoard'->>'titleFa';
    END IF;

    -------------------------------------------------------------------
    -- primary_city (from locations)
    -------------------------------------------------------------------
    IF NEW.locations IS NOT NULL
       AND jsonb_typeof(NEW.locations) = 'array' THEN
        NEW.primary_city := (
            SELECT elem->'city'->>'titleEn'
            FROM jsonb_array_elements(NEW.locations) AS elem
            LIMIT 1
        );
    END IF;

    -------------------------------------------------------------------
    -- work_type (from work_types)
    -------------------------------------------------------------------
    IF NEW.work_types IS NOT NULL
       AND jsonb_typeof(NEW.work_types) = 'array' THEN
        NEW.work_type := (
            SELECT elem->>'titleEn'
            FROM jsonb_array_elements(NEW.work_types) AS elem
            LIMIT 1
        );
    END IF;

    -------------------------------------------------------------------
    -- category, parent_cat, sub_cat (from job_post_categories)
    -------------------------------------------------------------------
    IF NEW.job_post_categories IS NOT NULL
       AND jsonb_typeof(NEW.job_post_categories) = 'array'
       AND jsonb_array_length(NEW.job_post_categories) > 0 THEN

        -- If there's only one element in the array, that becomes "category"
        -- If there are at least two, the first is "parent_cat" and the second is "sub_cat" (and also "category").
        IF jsonb_array_length(NEW.job_post_categories) = 1 THEN
            NEW.category := NEW.job_post_categories->0->>'titleEn';
            NEW.parent_cat := NULL; -- or same as category if you prefer
            NEW.sub_cat := NULL;
        ELSIF jsonb_array_length(NEW.job_post_categories) >= 2 THEN
            NEW.category := NEW.job_post_categories->1->>'titleEn';
            NEW.parent_cat := NEW.job_post_categories->0->>'titleEn';
            NEW.sub_cat := NEW.job_post_categories->1->>'titleEn';
        END IF;
    END IF;

    RETURN NEW;
END;
$$
LANGUAGE plpgsql;
```

A few notes on the function:

- We used `NEW` rather than the table name since this is a **trigger function**. `NEW` represents the row being inserted or updated.
- We check for `NULL` or array conditions to avoid errors when those JSON fields don’t exist or are invalid.

---

## 3) Create a Trigger that Calls This Function

We want this to happen **before** each row is actually inserted or updated, so the final row inserted/updated has the correct derived columns.

```sql
DROP TRIGGER IF EXISTS trg_update_derived_columns ON jobs;

CREATE TRIGGER trg_update_derived_columns
BEFORE INSERT OR UPDATE
ON jobs
FOR EACH ROW
EXECUTE PROCEDURE fn_update_derived_columns();
```

Now, anytime you do an `INSERT` or `UPDATE` on `jobs`, PostgreSQL will call `fn_update_derived_columns()` before completing the write, and your derived columns will be set automatically.

---

## 4) (Optional) Run a One-Time UPDATE for Existing Rows

If you already have rows in the table and want to backfill these columns based on existing JSON, run:

```sql
UPDATE jobs
SET
    -- Force the columns to recalculate:
    -- We just set them to their own values to trigger BEFORE UPDATE
    tags = tags
;
```

Because of the `BEFORE UPDATE` trigger, doing something like `SET tags = tags` will cause Postgres to run the trigger logic on every row, thereby updating your derived columns. (We basically “touch” the row so the trigger fires.)

If you have a very large table, you may want to break that update into chunks or do it in a maintenance window, as it will re-process every row.

---

## Summary

1. **Add the columns** if they don’t exist.
2. **Create a trigger function** (`fn_update_derived_columns`) which calculates and sets those columns from your JSON data.
3. **Attach that function** to the table with a `BEFORE INSERT OR UPDATE` trigger.
4. **Optionally** do a one-time backfill for existing data.

From then on, **whenever you insert or update a row**, the derived columns will be automatically populated. This is the most common approach in PostgreSQL to keep JSON-derived or computed columns in sync with source fields.


----------------------------------------------------
postgresql+psycopg2://jobuser:your_secure_db_password@db:5432/jobsdb