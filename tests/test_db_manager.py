from typing import Any

import pytest

from src.db_manager import DatabaseManager


def test_parse_connection_string():
    mgr = DatabaseManager("postgresql://user:pass@localhost:5432/dbname")
    params = mgr._parse_connection_string(
        "postgresql://user:pass@localhost:5432/dbname"
    )
    assert params == {
        "user": "user",
        "password": "pass",
        "host": "localhost",
        "port": 5432,
        "database": "dbname",
    }


def test_deduplicate_jobs():
    mgr = DatabaseManager("postgresql://u:p@localhost/db")
    jobs = [
        {"id": 1, "title": "a"},
        {"id": 1, "title": "b"},
        {"id": 2, "title": "c"},
        {"id": None, "title": "d"},
    ]
    unique = mgr._deduplicate_jobs(jobs)
    assert len(unique) == 2
    assert any(j["title"] == "b" for j in unique)


def test_extract_metadata():
    mgr = DatabaseManager("postgresql://u:p@localhost/db")
    chunk = [
        {
            "jobBoard": {
                "id": 1,
                "titleEn": "EN",
                "titleFa": "FA",
                "organizationColor": "C",
            }
        },
        {
            "companyDetailsSummary": {
                "id": 5,
                "name": {"titleEn": "CE", "titleFa": "CF"},
                "about": {"titleFa": "A"},
                "logo": "L",
            }
        },
    ]
    boards, companies = mgr._extract_metadata(chunk)
    assert boards[1]["title_en"] == "EN"
    assert companies[5]["title_fa"] == "CF"


@pytest.mark.asyncio
async def test_stage_and_perform_upsert():
    mgr = DatabaseManager("postgresql://u:p@localhost/db")

    class DummyConn:
        def __init__(self) -> None:
            self.commands = []

        async def execute(self, query: str, *args: Any) -> str:  # type: ignore[override]
            self.commands.append(query)
            return "INSERT 0 1"

        async def copy_records_to_table(self, *, table_name, records, columns, schema_name):  # type: ignore[override]
            self.commands.append(f"copy {table_name} {len(records)}")
            self.last_copy = {
                "table_name": table_name,
                "records": records,
                "columns": columns,
                "schema_name": schema_name,
            }

    values = [
        {
            "id": "1",
            "title": "t",
            "url": "u",
            "gender": None,
            "salary": "",
            "company_id": None,
            "job_board_id": 1,
            "raw_data": "{}",
            "job_board_title_en": "board",
            "job_board_title_fa": "fa",
            "primary_city": None,
            "work_type": None,
            "category": None,
            "parent_cat": None,
            "sub_cat": None,
            "tag_no_experience": 0,
            "tag_remote": 0,
            "tag_part_time": 0,
            "tag_internship": 0,
            "tag_military_exemption": 0,
        }
    ]

    conn = DummyConn()
    columns = await mgr._stage_jobs(conn, values)
    assert columns[0] == "id"
    assert conn.last_copy["table_name"] == "jobs_temp"
    affected = await mgr._perform_upsert(conn, columns)
    assert affected == 1
    assert any("INSERT INTO" in c for c in conn.commands)
