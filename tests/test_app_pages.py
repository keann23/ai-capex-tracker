"""Smoke test: every page renders without an exception (default company)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app"
PAGES = [APP / "Home.py", *sorted((APP / "pages").glob("*.py"))]


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_page_renders(page):
    at = AppTest.from_file(str(page), default_timeout=300).run()
    assert not at.exception, [e.message for e in at.exception]
    assert any("Estimates, not reported figures" in c.value for c in at.caption)
