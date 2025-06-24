from pathlib import Path

from src.scraper import JobScraper


def test_create_payload(monkeypatch, tmp_path):
    cfg_path = Path(__file__).resolve().parents[1] / "config" / "api_config.yaml"
    monkeypatch.chdir(tmp_path)
    scraper = JobScraper(config_path=str(cfg_path))
    payload = scraper.create_payload(page=2)
    assert payload["page"] == 2
    assert payload["pageSize"] == scraper.scraper_config.get("batch_size", 100)
