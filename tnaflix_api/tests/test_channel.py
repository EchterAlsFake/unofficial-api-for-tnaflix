from pathlib import Path
import pytest
from tnaflix_api.api import Channel

ROOT_DIR = Path(__file__).resolve().parents[2]
SAMPLE_CHANNEL_PATH = ROOT_DIR / "sample_channel.html"
SAMPLE_CHANNEL_2_PATH = ROOT_DIR / "sample_channel_2.html"


def test_channel_extract_sample_1():
    assert SAMPLE_CHANNEL_PATH.exists()
    html_content = SAMPLE_CHANNEL_PATH.read_text(encoding="utf-8")

    data = Channel._extract_html(html_content, url="https://www.tnaflix.com/channel/team-skeet")
    assert data["name"] == "Team Skeet"
    assert data["rank"] == "#13"
    assert data["total_videos"] == 77
    assert data["total_videos_str"] == "77"
    assert data["subscribers"] == "2K"
    assert data["subscribers_count"] == 2000
    assert data["entity_id"] == "72864"
    assert data["manager_name"] == "teamskeet"
    assert data["manager_url"] == "https://www.tnaflix.com/profile/teamskeet/channels"
    assert data["last_update"] == "1 year ago"
    assert data["description"] == "All Exclusive content network of sites!"
    assert data["external_website"] == "http://www.teamskeet.com/t1/"
    assert len(data["related_channels"]) >= 5
    assert data["related_channels"][0]["name"] == "The Real Workout"
    assert data["related_channels"][0]["rank"] == "#2"


def test_channel_extract_sample_2():
    assert SAMPLE_CHANNEL_2_PATH.exists()
    html_content = SAMPLE_CHANNEL_2_PATH.read_text(encoding="utf-8")

    data = Channel._extract_html(html_content, url="https://www.tnaflix.com/channel/pov-life")
    assert data["name"] == "POV life"
    assert data["rank"] == "#9"
    assert data["total_videos"] == 35
    assert data["total_videos_str"] == "35"
    assert data["subscribers"] == "305"
    assert data["subscribers_count"] == 305
    assert data["entity_id"] == "72856"
    assert data["manager_name"] == "teamskeet"
    assert "girls want cock" in data["description"]
    assert data["external_website"] == "http://povlife.com/"
