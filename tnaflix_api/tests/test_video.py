from pathlib import Path
import pytest
from tnaflix_api.api import Video
from tnaflix_api.modules.consts import extractor_video_list

SAMPLE_HTML_PATH = Path(__file__).resolve().parents[2] / "video_sample.html"


def test_video_extract_html():
    assert SAMPLE_HTML_PATH.exists(), f"Sample HTML not found at {SAMPLE_HTML_PATH}"
    html_content = SAMPLE_HTML_PATH.read_text(encoding="utf-8")

    data = Video._extract_html(html_content, url="https://www.tnaflix.com/amateur-porn/You%27re-The-Boss-%28full-movie%29/video11751954")

    assert data["video_id"] == "11751954"
    assert data["title"] == "You're The Boss (full movie) (Jessica Wylde, Nicole West)"
    assert "Full vintage movie starring Nichole West" in data["description"]
    assert data["duration"] == 5058
    assert data["length"] == "01:24:18"
    assert data["thumbnail_url"].startswith("https://img.tnaflix.com/")
    assert data["mosaic_url_template"].startswith("https://sl187.tnaflix.com/")
    assert data["publish_date"] == "2024-10-29T10:49:39+00:00"
    assert data["publish_date_relative"] == "1 year ago"
    assert data["embed_url"] == "https://player.tnaflix.com/video/11751954"
    assert data["author_name"] == "nolan_cecile"
    assert data["author_link"] == "https://www.tnaflix.com/profile/nolan_cecile"
    assert data["author_verified"] is False
    assert len(data["pornstars"]) == 2
    assert data["pornstars"][0]["name"] == "Jessica Wylde"
    assert data["pornstars"][1]["name"] == "Nicole West"
    assert "Amateur Porn" in data["tags"]
    assert data["likes"] == "4"
    assert data["dislikes"] == "1"
    assert data["rating_percent"] == "80%"
    assert data["rating_votes"] == "5"
    assert data["views"] == "1.1K"

    # Stream sources & qualities
    assert isinstance(data["direct_download_urls"], dict)
    assert 360 in data["direct_download_urls"]
    assert 240 in data["direct_download_urls"]
    assert 144 in data["direct_download_urls"]
    assert data["video_qualities"] == [144, 240, 360]


def test_extractor_video_list():
    html_content = SAMPLE_HTML_PATH.read_text(encoding="utf-8")
    videos = extractor_video_list(html_content, base_url="https://www.tnaflix.com")
    assert len(videos) > 0

    first = videos[0]
    assert first["video_id"] == "8615071"
    assert "You're The Boss" in first["title"]
    assert first["url"] == "https://www.tnaflix.com/babe-videos/You%27re-The-Boss-%28movie%29/video8615071"
    assert first["length"] == "01:24:18"
    assert first["author_name"] == "felipe_murray"
    assert first["views"] == "1.6K"
    assert first["rating"] == "43%"


@pytest.mark.asyncio
async def test_live_video():
    import os
    import tempfile
    from tnaflix_api import Client, DownloadConfigRAW

    client = Client()
    video = None
    try:
        async for res in client.search("blonde", pages=1):
            if res.item:
                if not video:
                    video = res.item
                parts = (res.item.length or "").split(":")
                if len(parts) == 2 and int(parts[0]) <= 2:
                    video = res.item
                    break
    except Exception as e:
        pytest.skip(f"Live network unavailable or connection reset by peer: {e}")

    if video is None:
        pytest.skip("No video returned from search (live site may be blocked or unavailable)")
    await video.load_sources("html")
    assert isinstance(video.title, str) and len(video.title) > 0
    assert video.video_qualities is not None and len(video.video_qualities) > 0
    assert video.direct_download_urls is not None and len(video.direct_download_urls) > 0

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "test.mp4")
        config = DownloadConfigRAW(quality="worst", path=out_path, no_title=True)
        res = await video.download(config)
        assert res is True
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 1000

