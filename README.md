# Job Scraper

## Overview
A Python 3.11+ asynchronous application that scrapes job postings from remote APIs and stores them in a PostgreSQL database or local files (JSON, CSV, Parquet). Deployable via Docker for robust scheduling (cron-based) and containerized observability.

## Directory Structure

```
job_scraper/
├── Dockerfile
├── docker-compose.yml
├── main.py
├── src/
│   ├── log_setup.py        # Central logging config
│   ├── scraper.py
│   ├── scheduler.py
│   ├── db_manager.py
│   ├── config_manager.py
│   └── health.py
├── tests/
│   ├── test_db_manager.py
│   └── test_scraper.py
└── ...
```

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

## Scraper Data Flow

The following diagram outlines how a single run of the scraper processes data:

```
JobScraper.run()
    |
    v
  initialize()
    |
    v
  scrape()
    |
    v
  fetch_jobs()  ->  process_jobs()  ->  _process_jobs()
                                    /                \
                           insert_jobs()          save_batch()
                                    \                /
                                    _save_batch_with_state()
                                              |
                                              v
                                 _log_final_statistics()
```

`fetch_jobs()` retrieves raw pages from the API. `process_jobs()` validates and
filters records. `_process_jobs()` writes the cleaned jobs to the database via
`insert_jobs()` (or `save_batch()` when storing locally). After each batch,
`_save_batch_with_state()` persists progress and finally
`_log_final_statistics()` records summary metrics.

## Setup & Installation

### Docker Deployment
1. `make build`  
2. `make start`

The scraper container runs automatically, uses a cron job to schedule repeated scraping, and logs to `job_data/logs/`.
An additional `nginx` service proxies HTTP traffic from a configurable port
(default `80`) to Superset (port specified by `SUPERSET_PORT`, default
`8088`) and exposes the scraper's `/metrics` and `/health` endpoints from the
port defined by `SCRAPER_PORT` (default `8080`). Set the `SERVER_NAME`
environment variable and optionally override these port variables when running
`docker-compose`, e.g.:

```bash
SERVER_NAME=karchiz.upgrade4u.space SUPERSET_PORT=8088 SCRAPER_PORT=8080 \
NGINX_PORT=80 make start
```

Once started, visit `http://<SERVER_NAME>` for the Superset UI and
`/metrics` or `/health` for monitoring endpoints.

### Local Development
1. `python -m venv venv && source venv/bin/activate`
2. `pip install -r requirements.txt`
3. `python main.py`

## Testing
The project uses `pytest` with the `pytest-asyncio` plugin. Both packages are
included in `requirements.txt`.

Before running the tests make sure all dependencies are installed:

```bash
pip install -r requirements.txt
```

If Codex doesn't have internet access you can prepare a `setup.sh` script to
install the packages during container startup.

Run tests from the repository root with:

```bash
pytest --asyncio-mode=auto --cov=src --cov-report=html
```

Before running the tests, make sure the Python dependencies are installed:

```bash
pip install -r requirements.txt
```

If Codex does not have internet access when your environment is created,
consider placing the install command in a `setup.sh` script so the required
packages can be preinstalled during container setup.

### Configuration
The main settings live in `config/api_config.yaml`. Database credentials are
loaded from `POSTGRES_*` variables or Docker secrets so no passwords live in the
repository. You can override the API endpoint by setting the environment
variable `API_BASE_URL`.

CI/CD
Minimal example in `.github/workflows/ci.yml` sets up mypy checks, lint,
bandit, tests and code coverage.

## Data Visualization with Superset
This project integrates [Apache Superset](https://superset.apache.org/) for exploring the scraped
PostgreSQL data. Start the service with:

```bash
docker-compose up -d superset
```

The `superset` service executes `superset-init.sh` which upgrades the Superset
database, creates the default `admin` account and runs the helper script
`scripts/create_superset_connection.py` to automatically register the
`jobsdb` database connection. The script reads the database password from the
file specified by `APP_DB_PASSWORD_FILE` (set in `docker-compose.yml` to
`/run/secrets/db_password` which maps to `secrets/db_password.txt`) and exports
it as `APP_DB_PASSWORD` for Superset.

If you need to connect Superset to a different PostgreSQL instance, set the
`APP_DB_URI` environment variable for the `superset` service. When provided, this
full SQLAlchemy URI overrides the individual host and credential variables. The
helper script now verifies the connection before registering it with Superset and
logs any connection errors for easier debugging.

Once running, visit `http://localhost:${SUPERSET_PORT}` (default
`http://localhost:8088`) and log in
using the default credentials `admin`/`admin`. Superset is pre-configured to
connect to the `jobsdb` database so you can start building charts immediately.
The container installs the PostgreSQL driver at startup using
`PIP_ADDITIONAL_REQUIREMENTS=psycopg2-binary`.


## Monitoring
`health.py` exposes `/health` and `/metrics`. The `/metrics` endpoint now serves Prometheus-formatted metrics using `prometheus_client`.

When running with the provided Docker Compose file, the metrics are exposed on
`SCRAPER_PORT` (default `8080`), so a Prometheus server can scrape metrics from
`http://localhost:${SCRAPER_PORT}/metrics`.

Integration with Prometheus or other monitoring solutions is straightforward—just add a scrape job pointing at the above URL.

## Security & Secrets
Uses Docker secrets for the database password. For advanced production, adopt
AWS Secrets Manager, Vault, or another secure secret source.

## License
[Specify your license here, e.g. MIT]

