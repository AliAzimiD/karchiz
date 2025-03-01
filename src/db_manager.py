import asyncio
import logging
import json
import time
import traceback
from datetime import datetime
from typing import Dict, List, Any, Optional, Union

import asyncpg
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base

from .log_setup import get_logger

Base = declarative_base()
logger = get_logger("DatabaseManager")

class DatabaseManager:
    """
    Manages database operations for the job scraper, including initializing
    connections, creating tables, and upserting job data in bulk.
    """

    def __init__(
        self,
        connection_string: str,
        schema: str = "public",
        batch_size: int = 1000
    ) -> None:
        """
        Initialize the database manager with connection details.

        Args:
            connection_string (str): PostgreSQL connection URI.
            schema (str): DB schema. Defaults to "public".
            batch_size (int): Max chunk size for inserts. Defaults to 1000.
        """
        self.connection_string: str = connection_string
        self.schema: str = schema
        self.batch_size: int = batch_size
        self.engine = None
        self.pool: Optional[asyncpg.pool.Pool] = None
        self.is_connected: bool = False
        self.metrics: Dict[str, Union[int, float]] = {
            "total_jobs_inserted": 0,
            "total_jobs_updated": 0,
            "total_batches": 0,
            "failed_operations": 0,
            "avg_insertion_time": 0.0,
        }

    async def initialize(self) -> bool:
        """
        Initialize database connections and create required tables.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            self.engine = create_engine(self.connection_string)
            conn_params = self._parse_connection_string(self.connection_string)
            self.pool = await asyncpg.create_pool(**conn_params)

            async with self.pool.acquire() as conn:
                version = await conn.fetchval("SELECT version()")
                logger.info(f"Connected to database: {version}")

            await self._create_tables()
            self.is_connected = True
            logger.info("Database connection established and tables verified")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize database: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def _parse_connection_string(self, conn_string: str) -> Dict[str, Union[str, int]]:
        """
        Parse a standard PostgreSQL connection string into dict parameters for asyncpg.

        Args:
            conn_string (str): Postgres connection string.

        Returns:
            Dict[str, Union[str,int]]: Connection parameters for asyncpg.
        """
        temp = conn_string
        if temp.startswith("postgresql://"):
            temp = temp.replace("postgresql://", "")
        elif temp.startswith("postgresql+psycopg2://"):
            temp = temp.replace("postgresql+psycopg2://", "")

        auth, rest = temp.split("@", 1)
        host_port, database = rest.split("/", 1)

        if ":" in auth:
            user, password = auth.split(":", 1)
        else:
            user, password = auth, ""

        if ":" in host_port:
            host, port_str = host_port.split(":", 1)
            port = int(port_str)
        else:
            host, port = host_port, 5432

        if "?" in database:
            database = database.split("?", 1)[0]

        return {
            "user": user,
            "password": password,
            "host": host,
            "port": port,
            "database": database,
        }

    async def _create_tables(self) -> None:
        """
        Create necessary schema and tables if they do not exist.
        """
        async with self.pool.acquire() as conn:
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")

            # Main jobs table
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.jobs (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    url TEXT,
                    locations JSONB,
                    work_types JSONB,
                    salary JSONB,
                    gender TEXT,
                    tags JSONB,
                    item_index INTEGER,
                    job_post_categories JSONB,
                    company_fa_name TEXT,
                    province_match_city TEXT,
                    normalize_salary_min FLOAT,
                    normalize_salary_max FLOAT,
                    payment_method TEXT,
                    district TEXT,
                    company_title_fa TEXT,
                    job_board_id TEXT,
                    job_board_title_en TEXT,
                    activation_time TIMESTAMP,
                    company_id TEXT,
                    company_name_fa TEXT,
                    company_name_en TEXT,
                    company_about TEXT,
                    company_url TEXT,
                    location_ids TEXT,
                    tag_number TEXT,
                    raw_data JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    batch_id TEXT,
                    batch_date TIMESTAMP
                )
            """)

            # Temporary table for bulk upserts
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.jobs_temp (
                    LIKE {self.schema}.jobs INCLUDING ALL
                )
            """)

            # job_batches table
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.job_batches (
                    batch_id TEXT PRIMARY KEY,
                    batch_date TIMESTAMP,
                    job_count INTEGER,
                    source TEXT,
                    processing_time FLOAT,
                    status TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                )
            """)

            # Stats table for overall scraper runs
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.scraper_stats (
                    id SERIAL PRIMARY KEY,
                    run_date TIMESTAMP,
                    total_jobs_scraped INTEGER,
                    new_jobs_found INTEGER,
                    pages_processed INTEGER,
                    processing_time FLOAT,
                    errors INTEGER,
                    status TEXT,
                    metadata JSONB
                )
            """)

            # Indices
            await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_jobs_activation_time ON {self.schema}.jobs (activation_time)")
            await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_jobs_batch_id ON {self.schema}.jobs (batch_id)")
            await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_jobs_company_id ON {self.schema}.jobs (company_id) WHERE company_id IS NOT NULL")

            # Trigger to update updated_at
            await conn.execute(f"""
                CREATE OR REPLACE FUNCTION {self.schema}.update_updated_at_column()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = NOW();
                    RETURN NEW;
                END;
                $$ LANGUAGE 'plpgsql';
            """)
            await conn.execute(f"""
                DROP TRIGGER IF EXISTS update_jobs_updated_at ON {self.schema}.jobs;
                CREATE TRIGGER update_jobs_updated_at
                BEFORE UPDATE ON {self.schema}.jobs
                FOR EACH ROW
                EXECUTE FUNCTION {self.schema}.update_updated_at_column();
            """)

    async def insert_jobs(self, jobs: List[Dict[str, Any]], batch_id: str) -> int:
        """
        Insert or upsert a list of jobs. Uses a temporary table (jobs_temp)
        then merges into the main jobs table with a single conflict resolution.

        Args:
            jobs (List[Dict[str, Any]]): The list of job data to upsert.
            batch_id (str): Unique identifier for this batch.

        Returns:
            int: The total number of rows inserted/updated.
        """
        if not jobs:
            return 0

        batch_date = datetime.now()
        inserted_count = 0
        start_time = time.time()

        try:
            await self._start_batch(batch_id, batch_date, len(jobs))

            for i in range(0, len(jobs), self.batch_size):
                chunk = jobs[i : i + self.batch_size]
                values = [self._transform_job_for_db(j, batch_id, batch_date) for j in chunk]

                async with self.pool.acquire() as conn:
                    columns = list(values[0].keys())
                    async with conn.transaction():
                        # Empty temp table
                        await conn.execute(f"TRUNCATE TABLE {self.schema}.jobs_temp")

                        # Copy chunk
                        records = [[row[col] for col in columns] for row in values]
                        await conn.copy_records_to_table(
                            "jobs_temp", records=records, columns=columns, schema_name=self.schema
                        )

                        # Perform upsert
                        col_updates = ", ".join([f"{col} = EXCLUDED.{col}" for col in columns if col != "id"])
                        query = f"""
                            INSERT INTO {self.schema}.jobs ({', '.join(columns)})
                            SELECT {', '.join(columns)} FROM {self.schema}.jobs_temp
                            ON CONFLICT (id)
                            DO UPDATE SET {col_updates}, updated_at = CURRENT_TIMESTAMP
                        """
                        result = await conn.execute(query)
                        logger.info(f"Upsert result for chunk: {result}")
                        affected = int(result.split(" ")[-1])
                        inserted_count += affected

            processing_time = time.time() - start_time
            await self._complete_batch(batch_id, batch_date, len(jobs), processing_time)
            logger.info(f"Upsert completed for batch {batch_id} - total rows: {inserted_count}")
            return inserted_count
        except Exception as e:
            logger.error(f"Error inserting jobs into database: {str(e)}")
            logger.error(traceback.format_exc())
            await self._fail_batch(batch_id, batch_date, str(e))
            return 0

    def _transform_job_for_db(self, job: Dict[str, Any], batch_id: str, batch_date: datetime) -> Dict[str, Any]:
        """
        Transform a raw job dictionary into a format suitable for DB insertion,
        handling activation_time parsing, location IDs, etc.

        Args:
            job (Dict[str, Any]): The raw job data from the API.
            batch_id (str): Unique ID for the batch.
            batch_date (datetime): Timestamp marking the batch processing.

        Returns:
            Dict[str, Any]: Column -> value
        """
        activation_time = None
        if "activationTime" in job and "date" in job["activationTime"]:
            date_str = job["activationTime"]["date"]
            for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"]:
                try:
                    activation_time = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue

        location_ids = []
        if "locations" in job and isinstance(job["locations"], list):
            for loc in job["locations"]:
                if isinstance(loc, dict):
                    prov = loc.get("province", {})
                    cty = loc.get("city", {})
                    if "id" in prov:
                        location_ids.append(prov["id"])
                    if "id" in cty:
                        location_ids.append(cty["id"])
        location_ids_string = ",".join(f"{lid_:03d}" for lid_ in location_ids) if location_ids else ""

        # Example logic for tag mapping
        tag_map = {
            "پاره وقت": 1,
            "بدون نیاز به سابقه": 2,
            "پروژه ای": 3,
            "کارآموزی": 4,
        }

        tag_number = "0"
        if "tags" in job and isinstance(job["tags"], list):
            numeric_tags = [tag_map.get(t, 0) for t in job["tags"]]
            unique_sorted_codes = sorted(set(numeric_tags))
            if unique_sorted_codes:
                tag_number = ",".join(str(x) for x in unique_sorted_codes)

        company_info = job.get("companyDetailsSummary", {})
        company_id = company_info.get("id")
        company_name_fa = None
        company_name_en = None
        company_about = None
        company_url = None
        if "name" in company_info:
            company_name_fa = company_info["name"].get("titleFa")
            company_name_en = company_info["name"].get("titleEn")
        if "about" in company_info:
            company_about = company_info["about"].get("titleFa")
        company_url = company_info.get("url")

        return {
            "id": job.get("id"),
            "title": job.get("title"),
            "url": job.get("url"),
            "locations": self._safe_json_dumps(job.get("locations", [])),
            "work_types": self._safe_json_dumps(job.get("workTypes", [])),
            "salary": self._safe_json_dumps(job.get("salary", {})),
            "gender": job.get("gender"),
            "tags": self._safe_json_dumps(job.get("tags", [])),
            "item_index": job.get("itemIndex"),
            "job_post_categories": self._safe_json_dumps(job.get("jobPostCategories", [])),
            "company_fa_name": job.get("companyFaName"),
            "province_match_city": job.get("provinceMatchCity"),
            "normalize_salary_min": job.get("normalizeSalaryMin"),
            "normalize_salary_max": job.get("normalizeSalaryMax"),
            "payment_method": job.get("paymentMethod"),
            "district": job.get("district"),
            "company_title_fa": job.get("companyTitleFa"),
            "job_board_id": job.get("jobBoardId"),
            "job_board_title_en": job.get("jobBoardTitleEn"),
            "activation_time": activation_time,
            "company_id": company_id,
            "company_name_fa": company_name_fa,
            "company_name_en": company_name_en,
            "company_about": company_about,
            "company_url": company_url,
            "location_ids": location_ids_string,
            "tag_number": tag_number,
            "raw_data": self._safe_json_dumps(job),
            "batch_id": batch_id,
            "batch_date": batch_date,
        }

    def _safe_json_dumps(self, obj: Any) -> str:
        """
        Safely convert an object to JSON string. If serialization fails, return a fallback.
        """
        try:
            return json.dumps(obj, ensure_ascii=False)
        except (TypeError, ValueError, OverflowError) as e:
            logger.warning(f"Error serializing to JSON: {str(e)}")
            if isinstance(obj, dict):
                return "{}"
            elif isinstance(obj, list):
                return "[]"
            else:
                return '""'

    async def _start_batch(self, batch_id: str, batch_date: datetime, job_count: int) -> None:
        """
        Record the start of a batch in job_batches.
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    f"""
                    INSERT INTO {self.schema}.job_batches
                    (batch_id, batch_date, job_count, source, processing_time, status, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (batch_id) DO UPDATE SET
                    job_count = $3,
                    status = $6,
                    created_at = $7
                    """,
                    batch_id,
                    batch_date,
                    job_count,
                    "api_scraper",
                    0.0,
                    "processing",
                    datetime.now(),
                )
        except Exception as e:
            logger.error(f"Failed to record batch start for {batch_id}: {str(e)}")

    async def _complete_batch(
        self, batch_id: str, batch_date: datetime, job_count: int, processing_time: float
    ) -> None:
        """
        Mark a batch as completed in job_batches with final stats.
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    f"""
                    INSERT INTO {self.schema}.job_batches
                    (batch_id, batch_date, job_count, source, processing_time, status, completed_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (batch_id) DO UPDATE SET
                    job_count = $3,
                    processing_time = $5,
                    status = $6,
                    completed_at = $7
                    """,
                    batch_id,
                    batch_date,
                    job_count,
                    "api_scraper",
                    processing_time,
                    "completed",
                    datetime.now(),
                )
        except Exception as e:
            logger.error(f"Failed to record batch completion for {batch_id}: {str(e)}")

    async def _fail_batch(self, batch_id: str, batch_date: datetime, error_message: str) -> None:
        """
        Mark a batch as failed in job_batches.
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    f"""
                    INSERT INTO {self.schema}.job_batches
                    (batch_id, batch_date, source, status, error_message, completed_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (batch_id) DO UPDATE SET
                    status = $4,
                    error_message = $5,
                    completed_at = $6
                    """,
                    batch_id,
                    batch_date,
                    "api_scraper",
                    "failed",
                    error_message,
                    datetime.now(),
                )
        except Exception as e:
            logger.error(f"Failed to record batch failure for {batch_id}: {str(e)}")

    async def get_job_count(self) -> int:
        """
        Returns the total row count in the jobs table.
        """
        if not self.pool:
            return 0
        try:
            async with self.pool.acquire() as conn:
                return await conn.fetchval(f"SELECT COUNT(*) FROM {self.schema}.jobs")
        except Exception as e:
            logger.error(f"Error getting job count: {str(e)}")
            return 0

    async def get_jobs_by_date_range(
        self, start_date: datetime, end_date: datetime, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Return job entries within a specified date range, up to a limit.
        """
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT id, title, url, activation_time, company_name_fa,
                           normalize_salary_min, normalize_salary_max
                    FROM {self.schema}.jobs
                    WHERE activation_time BETWEEN $1 AND $2
                    ORDER BY activation_time DESC
                    LIMIT $3
                    """,
                    start_date,
                    end_date,
                    limit,
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error getting jobs by date range: {str(e)}")
            return []

    async def get_latest_jobs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Return the most recently activated jobs, up to 'limit'.
        """
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT id, title, url, activation_time, company_name_fa,
                           normalize_salary_min, normalize_salary_max
                    FROM {self.schema}.jobs
                    ORDER BY activation_time DESC
                    LIMIT $1
                    """,
                    limit,
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error getting latest jobs: {str(e)}")
            return []

    async def get_job_details(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the full details for a single job by ID.
        """
        if not self.pool:
            return None
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT * FROM {self.schema}.jobs WHERE id = $1", job_id
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting job details: {str(e)}")
            return None

    async def get_batch_status(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve the status record for a particular batch_id from job_batches.
        """
        if not self.pool:
            return None
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT * FROM {self.schema}.job_batches WHERE batch_id = $1", batch_id
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting batch status: {str(e)}")
            return None

    async def get_job_counts_by_company(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Return top N companies by job count.
        """
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT company_id, company_name_fa, COUNT(*) AS job_count
                    FROM {self.schema}.jobs
                    WHERE company_id IS NOT NULL
                    GROUP BY company_id, company_name_fa
                    ORDER BY job_count DESC
                    LIMIT $1
                    """,
                    limit,
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error getting job counts by company: {str(e)}")
            return []

    async def get_job_stats(self) -> Dict[str, Any]:
        """
        Generate some stats about what is in the jobs table.
        """
        if not self.pool:
            return {"error": "No DB pool"}
        try:
            async with self.pool.acquire() as conn:
                total_jobs = await conn.fetchval(f"SELECT COUNT(*) FROM {self.schema}.jobs")

                date_counts = await conn.fetch(
                    f"""
                    SELECT DATE(activation_time) AS date, COUNT(*) AS count
                    FROM {self.schema}.jobs
                    WHERE activation_time > NOW() - INTERVAL '7 days'
                    GROUP BY DATE(activation_time)
                    ORDER BY date
                    """
                )
                salary_stats = await conn.fetchrow(
                    f"""
                    SELECT
                        AVG(normalize_salary_min) as avg_min_salary,
                        AVG(normalize_salary_max) as avg_max_salary,
                        MIN(normalize_salary_min) as min_salary,
                        MAX(normalize_salary_max) as max_salary
                    FROM {self.schema}.jobs
                    WHERE normalize_salary_min IS NOT NULL
                      AND normalize_salary_max IS NOT NULL
                    """
                )
                top_companies = await conn.fetch(
                    f"""
                    SELECT company_name_fa, COUNT(*) AS job_count
                    FROM {self.schema}.jobs
                    WHERE company_name_fa IS NOT NULL
                    GROUP BY company_name_fa
                    ORDER BY job_count DESC
                    LIMIT 10
                    """
                )

                return {
                    "total_jobs": total_jobs,
                    "jobs_by_date": [dict(r) for r in date_counts],
                    "salary_stats": dict(salary_stats) if salary_stats else {},
                    "top_companies": [dict(r) for r in top_companies],
                }
        except Exception as e:
            logger.error(f"Error getting job statistics: {str(e)}")
            return {"error": str(e)}

    async def record_scraper_stats(self, stats: Dict[str, Any]) -> bool:
        """
        Insert a row into scraper_stats logging a run's summary.
        """
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    f"""
                    INSERT INTO {self.schema}.scraper_stats
                    (run_date, total_jobs_scraped, new_jobs_found, pages_processed,
                     processing_time, errors, status, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    datetime.now(),
                    stats.get("total_jobs_scraped", 0),
                    stats.get("new_jobs_found", 0),
                    stats.get("pages_processed", 0),
                    stats.get("processing_time", 0.0),
                    stats.get("errors", 0),
                    stats.get("status", "completed"),
                    json.dumps(stats.get("metadata", {})),
                )
                return True
        except Exception as e:
            logger.error(f"Error recording scraper stats: {str(e)}")
            return False

    async def get_database_size(self) -> Dict[str, Any]:
        """
        Return the total DB size plus per-table size in a structured format.
        """
        if not self.pool:
            return {"error": "No DB pool"}
        try:
            async with self.pool.acquire() as conn:
                db_name = await conn.fetchval("SELECT current_database()")
                rows = await conn.fetch(
                    f"""
                    SELECT
                        table_name,
                        pg_size_pretty(pg_total_relation_size(quote_ident(table_name))) AS total_size,
                        pg_total_relation_size(quote_ident(table_name)) AS size_bytes
                    FROM information_schema.tables
                    WHERE table_schema = $1
                    ORDER BY size_bytes DESC
                    """,
                    self.schema,
                )
                total_size = await conn.fetchval(
                    f"SELECT pg_size_pretty(pg_database_size($1))", db_name
                )
                return {
                    "database_name": db_name,
                    "total_size": total_size,
                    "tables": [dict(r) for r in rows],
                }
        except Exception as e:
            logger.error(f"Error getting database size: {str(e)}")
            return {"error": str(e)}

    async def vacuum_analyze(self) -> bool:
        """
        Run VACUUM ANALYZE on the jobs table to help with performance.
        """
        try:
            conn_params = self._parse_connection_string(self.connection_string)
            conn = await asyncpg.connect(**conn_params)
            try:
                logger.info(f"Running VACUUM ANALYZE on {self.schema}.jobs")
                await conn.execute(f"VACUUM ANALYZE {self.schema}.jobs")
                logger.info("VACUUM ANALYZE completed successfully")
                return True
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"Error during VACUUM ANALYZE: {str(e)}")
            return False

    async def close(self) -> None:
        """
        Close all DB connections cleanly.
        """
        if self.pool:
            await self.pool.close()
        if self.engine:
            self.engine.dispose()
        logger.info("Database connections closed")
