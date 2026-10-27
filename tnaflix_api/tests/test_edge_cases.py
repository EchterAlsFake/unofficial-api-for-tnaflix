import os
import tempfile
import pytest
from tnaflix_api import Client, Video, Profile, Pornstar, Channel, Sort, SortDate, DownloadConfigRAW
from base_api.modules.errors import MediaLoadError, NotFound, DownloadFailed


def test_url_normalizations():
    # Video
    assert Client._normalize_video_url("11751954") == "https://www.tnaflix.com/video/11751954"
    assert Client._normalize_video_url("video11751954") == "https://www.tnaflix.com/video/11751954"
    assert Client._normalize_video_url("video/11751954") == "https://www.tnaflix.com/video/11751954"
    assert Client._normalize_video_url("videos/11751954") == "https://www.tnaflix.com/video/11751954"
    assert Client._normalize_video_url("https://player.tnaflix.com/video/11751954") == "https://www.tnaflix.com/video/11751954"
    assert Client._normalize_video_url("https://www.tnaflix.com/amateur-porn/foo/video11751954") == "https://www.tnaflix.com/amateur-porn/foo/video11751954"
    assert Client._normalize_video_url("amateur-porn/foo/video11751954") == "https://www.tnaflix.com/amateur-porn/foo/video11751954"

    # Profile
    assert Client._normalize_profile_url("lisa-ann") == "https://www.tnaflix.com/profile/lisa-ann"
    assert Client._normalize_profile_url("profile/lisa-ann") == "https://www.tnaflix.com/profile/lisa-ann"
    assert Client._normalize_profile_url("profiles/lisa-ann") == "https://www.tnaflix.com/profile/lisa-ann"
    assert Client._normalize_profile_url("pornstar/lisa-ann") == "https://www.tnaflix.com/profile/lisa-ann"
    assert Client._normalize_profile_url("pornstars/lisa-ann") == "https://www.tnaflix.com/profile/lisa-ann"
    assert Client._normalize_profile_url("https://www.tnaflix.com/pornstar/lisa-ann") == "https://www.tnaflix.com/profile/lisa-ann"
    assert Client._normalize_profile_url("https://www.tnaflix.com/profiles/lisa-ann") == "https://www.tnaflix.com/profile/lisa-ann"

    # Channel
    assert Client._normalize_channel_url("team-skeet") == "https://www.tnaflix.com/channel/team-skeet"
    assert Client._normalize_channel_url("channel/team-skeet") == "https://www.tnaflix.com/channel/team-skeet"
    assert Client._normalize_channel_url("channels/team-skeet") == "https://www.tnaflix.com/channel/team-skeet"
    assert Client._normalize_channel_url("https://www.tnaflix.com/channels/team-skeet") == "https://www.tnaflix.com/channel/team-skeet"


@pytest.mark.asyncio
async def test_canonical_resolution_and_metadata():
    client = Client()
    # Loading via bare ID should auto-resolve canonical full URL and populate all metadata
    video = await client.get_video("11751954")
    assert video.title is not None
    assert "You're The Boss" in video.title
    assert video.author_name == "nolan_cecile"
    assert video.author_link == "https://www.tnaflix.com/profile/nolan_cecile"
    assert video.views is not None
    assert video.tags is not None and len(video.tags) > 0
    assert video.video_qualities is not None and len(video.video_qualities) > 0

    # Related videos should work when loaded via short ID
    related = await video.get_related_videos()
    assert isinstance(related, list)
    assert len(related) > 0
    assert "video_id" in related[0]
    assert "url" in related[0]


@pytest.mark.asyncio
async def test_channel_uploader_and_get_author():
    client = Client()
    # Video uploaded by a Channel (Team Skeet)
    video = await client.get_video("https://www.tnaflix.com/cum-videos/TEAM-SKEET-Sexy-Mocha-Teen-Sucks-And-Fucks-a-BWC/video3764646")
    assert video.author_name == "Team Skeet"
    assert video.author_link == "https://www.tnaflix.com/channel/team-skeet"
    assert video.author_verified is True

    # "Team Skeet" should NOT be classified as category
    cat_names = [c["name"] for c in (video.categories or [])]
    assert "Team Skeet" not in cat_names

    # get_author() is an async method (not a property!) and returns a Channel
    author = await video.get_author(load_html=True)
    assert isinstance(author, Channel)
    assert author.name == "Team Skeet"
    assert author.rank == "#13"
    assert author.total_videos is not None and author.total_videos > 0


@pytest.mark.asyncio
async def test_profile_uploader_and_pornstars():
    client = Client()
    video = None
    async for r in client.search("lisa ann", pages=1):
        if r.item:
            v = r.item
            await v.load_sources("html")
            if v.pornstars and len(v.pornstars) > 0 and v.author_name:
                video = v
                break

    assert video is not None
    author = await video.get_author(load_html=True)
    assert isinstance(author, Profile)
    assert author.name == video.author_name

    # get_pornstars() is an async generator method (not a property!) yielding Pornstar
    stars = []
    async for star in video.get_pornstars(load_html=True):
        assert isinstance(star, Pornstar)
        assert isinstance(star, Profile)
        stars.append(star.name)
    assert "Lisa Ann" in stars


@pytest.mark.asyncio
async def test_get_pornstar_client_method():
    client = Client()
    # Calling get_pornstar with a slug should return a Pornstar instance
    star = await client.get_pornstar("lisa-ann", load_html=True)
    assert isinstance(star, Pornstar)
    assert star.name == "Lisa Ann"
    assert star.total_videos is not None and star.total_videos > 1000
    assert star.entity_id == "3205198"

    # Calling with /pornstar/ URL should normalize and work
    star2 = await client.get_pornstar("https://www.tnaflix.com/pornstar/lisa-ann", load_html=False)
    assert isinstance(star2, Pornstar)
    assert star2.url == "https://www.tnaflix.com/profile/lisa-ann"


@pytest.mark.asyncio
async def test_channel_streaming_videos():
    client = Client()
    channel = await client.get_channel("team-skeet", load_html=False)
    vids = []
    async for r in channel.videos(pages=1):
        if r.item:
            vids.append(r.item)
            assert r.item.author_name == "Team Skeet"
            assert r.item.author_link == "https://www.tnaflix.com/channel/team-skeet"
    assert len(vids) > 0


@pytest.mark.asyncio
async def test_search_and_filters():
    client = Client()
    # Search with date and sort filters
    results = []
    async for r in client.search("blonde", sorting_sort=Sort.Sort_most_viewed, sorting_date=SortDate.Sort_month, pages=1):
        if r.item:
            results.append(r.item)
    assert len(results) > 0

    # Search with zero results should return cleanly without error
    empty_results = []
    async for r in client.search("98765432109876543210zyxwvutsrqponmlkjihgfedcba", pages=1):
        if r.item:
            empty_results.append(r.item)
    assert len(empty_results) == 0


@pytest.mark.asyncio
async def test_404_error_handling():
    client = Client()
    with pytest.raises(MediaLoadError):
        await client.get_video("99999999999999")

    with pytest.raises(MediaLoadError):
        await client.get_profile("non_existent_user_9999999999")

    with pytest.raises(MediaLoadError):
        await client.get_channel("non_existent_channel_9999999999")


@pytest.mark.asyncio
async def test_download_short_video_and_cli():
    client = Client()
    # Use 41-second short video
    video = await client.get_video("https://www.tnaflix.com/video/4804605")
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "edge_test.mp4")
        cfg = DownloadConfigRAW(quality="worst", path=out_path, no_title=True)
        res = await video.download(cfg)
        assert res is True
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 100_000

    # Test CLI invocation
    from tnaflix_api.api import run_main
    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = os.path.join(tmpdir, "cli_test.mp4")
        await run_main(["--download", "https://www.tnaflix.com/video/4804605", "--quality", "worst", "--output", out_file, "--no-title"])
        assert os.path.exists(out_file)
        assert os.path.getsize(out_file) > 100_000
