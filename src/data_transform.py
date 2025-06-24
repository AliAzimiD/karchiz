"""Utilities for transforming raw job data into structured tables."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple

import pandas as pd


def load_raw_csv(path: str | Path) -> pd.DataFrame:
    """Load the CSV file with a ``raw_data`` column containing JSON strings."""

    df = pd.read_csv(path)
    df["raw_json"] = df["raw_data"].apply(json.loads)
    return df


def extract_tables(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Convert the raw JSON column into normalized job, company and location tables."""

    job_records = []
    company_records = []
    location_records = []

    for row in df["raw_json"]:
        job_id = row.get("id")
        company = row.get("companyDetailsSummary") or {}
        company_id = company.get("id")

        job_records.append(
            {
                "job_id": job_id,
                "title": row.get("title"),
                "salary": row.get("salary"),
                "company_id": company_id,
                "gender": row.get("gender"),
                "payment_method": row.get("paymentMethod"),
                "activation_time": (row.get("activationTime") or {}).get("date"),
            }
        )

        if company:
            company_records.append(
                {
                    "company_id": company_id,
                    "name_fa": (company.get("name") or {}).get("titleFa"),
                    "name_en": (company.get("name") or {}).get("titleEn"),
                    "about": (company.get("about") or {}).get("titleFa"),
                    "url": company.get("url"),
                }
            )

        for loc in row.get("locations", []):
            location_records.append(
                {
                    "job_id": job_id,
                    "province_id": (loc.get("province") or {}).get("id"),
                    "province_title": (loc.get("province") or {}).get("titleFa"),
                    "city_id": (loc.get("city") or {}).get("id"),
                    "city_title": (loc.get("city") or {}).get("titleFa"),
                }
            )

    jobs_df = pd.DataFrame(job_records)
    companies_df = pd.DataFrame(company_records).drop_duplicates("company_id")
    locations_df = pd.DataFrame(location_records)

    return jobs_df, companies_df, locations_df


__all__ = ["load_raw_csv", "extract_tables"]
