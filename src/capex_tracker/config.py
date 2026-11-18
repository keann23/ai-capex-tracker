"""Load the YAML config files in config/."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
# Saved SEC data the app and tests read; refreshed by scripts/fetch_*.py, committed.
SNAPSHOT_DIR = REPO_ROOT / "snapshots"

MONTHS = {
    m: i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"],
        start=1,
    )
}


def load_yaml(name: str, config_dir: Path = CONFIG_DIR) -> dict:
    return yaml.safe_load((config_dir / name).read_text())


def load_companies(config_dir: Path = CONFIG_DIR) -> dict:
    """Full companies.yaml: {'companies': {...}, 'baseline': {...}, 'defaults': {...}}."""
    return load_yaml("companies.yaml", config_dir)


def load_tag_map(config_dir: Path = CONFIG_DIR) -> dict:
    """tag_map.yaml 'items' section: {item: {type, tags, derive?}}."""
    return load_yaml("tag_map.yaml", config_dir)["items"]


def fiscal_year_end_month(company: dict) -> int:
    """Month number (1-12) of a company's fiscal year end, from companies.yaml."""
    return MONTHS[company["fiscal_year_end"]]
