# AGENTS.md – Karchiz

> **Objective:** Give AI coding agents (GitHub Copilot / OpenAI Codex / future LLM tooling) the structured context they need to understand, extend, and safely modify this repository.

---

## 1 • What Is **Karchiz**?

`karchiz` is an **asynchronous job‑scraping and analytics stack** written in **Python 3.11+**.  It

* **Scrapes** multiple Persian job‑board APIs on a schedule.
* **Persists** raw JSON in PostgreSQL or local files (Parquet / CSV / JSON).
* **Derives** tidy analytic columns with PL/pgSQL triggers.
* **Surfaces** metrics through Apache Superset and Prometheus.
* **Ships** as reproducible Docker services (scraper, DB, Superset).

Agents should optimise for **data integrity, observability, and low‑latency incremental runs**.

---

## 2 • High‑Level Architecture

```
               ┌──────────────┐      cron/async loop      ┌──────────────┐
               │  scheduler   │ ─────────────────────────►│  scraper.py  │
               └──────────────┘                           └──────┬───────┘
                                                                 │ validated jobs (JSON)
                                                                 ▼
                                                         ┌──────────────┐
                                                         │ db_manager   │  bulk‑upsert / triggers
                                                         └──────────────┘
                                                                 │
                                                                 ▼
   Prometheus ⇐ /metrics   Superset ⇐ SQL                    PostgreSQL 15
```

Data flow of a single run (simplified):

```
JobScraper.run()
   └─ initialize()
        └─ scrape()
             └─ fetch_jobs()  →  process_jobs()  →  _process_jobs()
                                              /                 \
                                     insert_jobs()          save_batch()
                                              \                 /
                                                _save_batch_with_state()
                                                          |
                                               _log_final_statistics()
```

---

## 3 • Repository Map

```
job_scraper/
├── Dockerfile
├── docker-compose.yml
├── main.py
├── src/
│   ├── log_setup.py        # Central logging config (structlog JSON)
│   ├── scraper.py          # JobScraper class (async HTTP)
│   ├── scheduler.py        # Cron loop wrapper
│   ├── db_manager.py       # AsyncPG queries, bulk‑upsert helpers
│   ├── config_manager.py   # YAML/env merge + state persistence
│   └── health.py           # /health & /metrics (Prometheus)
├── tests/
│   ├── test_db_manager.py
│   └── test_scraper.py
├── config/
│   └── api_config.yaml
├── scripts/
│   └── create_superset_connection.py
├── secrets/                # Docker secrets mount point (db_password.txt)
├── init-db/                # SQL schema + triggers
├── Makefile                # build / up / lint / test shortcuts
└── README.md               # human‑friendly getting‑started
```

(Data structure confirmed from GitHub listing) 

---

## 4 • Primary Tasks for Agents

| ID                | Task                                                                                                                         | Success Criteria                                                                       |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `scrape_jobs`     | Implement/extend async REST pagination, back‑off, retry & dedupe logic in `src/scraper.py`.                                  | ≥ 99 % successful page fetches, idempotent inserts, <0.5 s mean per‑page latency.      |
| `transform_store` | Maintain `db_manager.py` + PG triggers so derived columns (`tag_remote`, `category`, …) stay correct on every insert/update. | Zero constraint violations, derived columns match JSON source on >10 k row smoke‑test. |
| `schedule_runs`   | Improve `scheduler.py` cron orchestration & graceful shutdown.                                                               | Jobs fire on time; container exits 0; no orphan asyncio tasks.                         |
| `serve_dash`      | Keep Superset Docker image (`Dockerfile.superset`) up to date and automate dataset + dashboard seeding.                      | `make superset-init` brings up UI with example dashboards in <2 min.                   |
| `healthcheck`     | Harden `src/health.py` (HTTP + Prometheus) so k8s/compose can probe liveness & readiness.                                    | `GET /health/live` and `/health/ready` return 200 in <50 ms under load.                |

Secondary tasks: CI /CD, log enrichment, test coverage, codebase refactors.

---

## 5 • Environment & Tooling

* **Python 3.11**, `asyncio`, `httpx[http2]`, `asyncpg`, `pydantic`, `structlog`, `croniter`, `prometheus_client`.
* **PostgreSQL 15** (official image) – schema + triggers in `init-db/`.
* **Apache Superset 3.x** – exposed on port 8088.
* **pytest / coverage.py** – unit + integration tests.
* **ruff & black** – lint & format.
* **Docker Compose v2** – orchestration.

Agents must *not* introduce frameworks that bloat image size > 500 MB compressed.

---

## 6 • Setup & Installation

### 6.1 Docker Deployment

```bash
make build   # builds scraper & Superset images
make start   # docker compose up -d
```

The scraper container runs automatically on a cron schedule; logs land in `job_data/logs/` (via `log_setup.py`).

### 6.2 Local Development

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py  # one‑off scrape
```

### 6.3 Testing

```bash
pip install -r requirements.txt
pytest --asyncio-mode=auto --cov=src --cov-report=html
```

If the execution environment lacks internet, place the `pip install` line inside `setup.sh` for offline Docker builds.

---

## 7 • Data Visualisation with Superset

Start Superset alongside the stack:

```bash
docker-compose up -d superset
```

`superset-init.sh` upgrades the internal DB, creates an `admin/admin` account, and runs `scripts/create_superset_connection.py`, which reads the DB password from `/run/secrets/db_password`.  To point at another PG instance set `APP_DB_URI`.

Visit [http://localhost:8088](http://localhost:8088), log in, and start building charts — the `jobsdb` connection is pre‑registered.

---

## 8 • Monitoring & Observability

* `health.py` exposes `GET /health` and Prometheus metrics at `/metrics` (port 8080).
* Add a Prometheus scrape job for `http://<scraper-host>:8080/metrics`.
* Grafana dashboards can be imported from `dashboards/` (planned).

---

## 9 • Coding Guidelines

1. **Type‑hint everything**; use `mypy`‑friendly patterns.
2. Write **single‑responsibility functions** ≤ 60 logical lines.
3. Prefer **functional composition** over deep class hierarchies.
4. Log **structured JSON** via `structlog`; never `print`.
5. Use **async context managers** for network & DB resources.
6. Cover new code with **pytest** at ≥ 90 % branch coverage; mock external APIs.
7. Keep **secrets out of VCS** – read from `os.getenv` or Docker secrets.

---

## 10 • Known Pain Points / TODO

* **Network resilience:** occasional 502s from job‑board API → retry jitter (#12).
* **Backfill script:** historical postings currently imported manually.
* **Superset seeding race:** first‑run sometimes fails if DB not ready.
* **CI pipeline:** GitHub Actions skeleton needs coverage artifact upload.
* **Flaky test:** `test_db_manager.py::test_bulk_upsert` on Windows.

Agents should open issues before large refactors.

---

## 11 • Versioning & Releases

Semantic Versioning (MAJOR.MINOR.PATCH) tagged in `main`.  Use `bump2version` via `make release patch|minor|major`.

---

## 12 • Security & Compliance

* Follow **OWASP** top‑10; sanitise user input if/when scraper becomes public API.
* DB creds loaded via **Docker secrets** (`secrets/db_password.txt`).
* Consider AWS Secrets Manager / Vault for prod secret retrieval.
* No PII is scraped; ensure this remains true.

---

## 13 • Contact & Ownership

| Role           | GitHub     | Responsibility                    |
| -------------- | ---------- | --------------------------------- |
| **Maintainer** | @AliAzimiD | Vision, code‑review, merge rights |
| **Ops**        | *vacant*   | CI/CD, container registry         |

---

*Happy scraping.  ☕️*
