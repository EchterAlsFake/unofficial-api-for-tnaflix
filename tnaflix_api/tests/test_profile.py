from pathlib import Path
import pytest
from tnaflix_api.api import Profile, Pornstar

ROOT_DIR = Path(__file__).resolve().parents[2]
SAMPLE_PORNSTAR_PATH = ROOT_DIR / "sample_profile_from_pornstar.html"


def test_profile_extract_pornstar():
    assert SAMPLE_PORNSTAR_PATH.exists()
    html_content = SAMPLE_PORNSTAR_PATH.read_text(encoding="utf-8")

    data = Profile._extract_html(html_content, url="https://www.tnaflix.com/profile/lisa-ann")
    assert data["name"] == "Lisa Ann"
    assert data["thumbnail_url"].startswith("https://img.tnaflix.com/")
    assert data["total_videos"] == 4900
    assert data["total_videos_str"] == "4.9K"
    assert data["subscribers"] == "2.7K"
    assert data["subscribers_count"] == 2700
    assert data["entity_id"] == "3205198"

    # Pornstar shares same extraction logic
    p_data = Pornstar._extract_html(html_content, url="https://www.tnaflix.com/profile/lisa-ann")
    assert p_data == data
