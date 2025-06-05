import os
from pathlib import Path

import pytest

from src.config_manager import ConfigManager


def test_load_config_base_url(monkeypatch, tmp_path):
    cfg_path = Path(__file__).resolve().parents[1] / "config" / "api_config.yaml"
    # run inside temporary directory to avoid creating files in repo
    monkeypatch.chdir(tmp_path)
    cm = ConfigManager(config_path=str(cfg_path))
    assert cm.api_config["base_url"] == "https://api.karbord.io/api/v1/Candidate/JobPost/GetList"


def test_default_max_concurrent_requests(monkeypatch, tmp_path):
    config_file = tmp_path / "conf.yaml"
    config_file.write_text(
        "api: {}\nrequest: {}\nscraper: {}\n"
    )
    monkeypatch.chdir(tmp_path)
    cm = ConfigManager(config_path=str(config_file))
    assert cm.get_max_concurrent_requests() == 3

