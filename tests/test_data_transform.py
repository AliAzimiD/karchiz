import pandas as pd
from src import data_transform


def test_extract_tables(tmp_path):
    csv_content = """created_at,id,raw_data,COUNT(*)
2025-06-05,1,"{""id"": 1, ""title"": ""Test"", ""companyDetailsSummary"": {""id"": 10, ""name"": {""titleFa"": ""Co""}}, ""locations"": []}",1
"""
    path = tmp_path / "jobs.csv"
    path.write_text(csv_content)

    df = data_transform.load_raw_csv(path)
    jobs, companies, locations = data_transform.extract_tables(df)

    assert len(jobs) == 1
    assert jobs.loc[0, "job_id"] == 1
    assert len(companies) == 1
    assert companies.loc[0, "company_id"] == 10
    assert locations.empty
