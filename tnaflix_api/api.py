from __future__ import annotations

import argparse
import asyncio
import html
import json
import logging
import re
from dataclasses import dataclass
from typing import AsyncGenerator, ClassVar
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from base_api import (
    BaseCore,
    BaseMedia,
    DownloadConfigRAW,
    ErrorAction,
    ErrorMode,
    Helper,
    MediaLoadError,
    MediaLoadErrors,
    RetryPolicy,
    ScrapeErrorContext,
    ScrapeResult,
    default_on_error,
    is_resource_gone,
    make_iterator_config,
    media_field,
    scrape_stream,
)
from base_api.modules.config import IteratorConfig
from base_api.modules.logger import configure_app_logging, get_logger
from base_api.modules.provider import download_errors, fetch_content, prepare_download_config
from base_api.modules.static_functions import choose_quality_from_list, normalize_quality_value, str_to_bool
from selectolax.lexbor import LexborHTMLParser

from tnaflix_api.modules import consts
from tnaflix_api.modules import errors as provider_errors
from tnaflix_api.modules.consts import extractor_video_list, headers
from tnaflix_api.modules.errors import DownloadFailed
from tnaflix_api.modules.sorting import Sort, SortDate

logger = get_logger(__name__)

HELPER_RETRY = RetryPolicy(max_attempts=4, base_delay=0.5, max_delay=8.0)
_is_resource_gone = is_resource_gone
on_error = default_on_error

BASE_URL = "https://www.tnaflix.com"


async def get_html_content(core: BaseCore, url: str, *, owner=None) -> str:
    return await fetch_content(core, url, logger=logger, owner=owner, error_types=provider_errors)


@dataclass(slots=True, kw_only=True)
class Video(BaseMedia):
    url: str
    core: BaseCore
    video_id: str | None = media_field("html")
    title: str | None = media_field("html")
    description: str | None = media_field("html")
    thumbnail_url: str | None = media_field("html")
    mosaic_url_template: str | None = media_field("html")
    preview_video_url: str | None = media_field("html")
    publish_date: str | None = media_field("html")
    publish_date_relative: str | None = media_field("html")
    duration: int | None = media_field("html")
    length: str | None = media_field("html")
    author_name: str | None = media_field("html")
    author_link: str | None = media_field("html")
    author_verified: bool | None = media_field("html")
    pornstars: list[dict[str, str]] | None = media_field("html")
    pornstars_urls: list[str] | None = media_field("html")
    categories: list[dict[str, str]] | None = media_field("html")
    tags: list[str] | None = media_field("html")
    views: str | None = media_field("html")
    likes: str | None = media_field("html")
    dislikes: str | None = media_field("html")
    rating: str | None = media_field("html")
    rating_percent: str | None = media_field("html")
    rating_votes: str | None = media_field("html")

    embed_url: str | None = media_field("html")
    direct_download_urls: dict[int, str] | None = media_field("html")
    video_qualities: list[int] | None = media_field("html")

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(core=self.core, url=self.url, owner=self)
        return await asyncio.to_thread(self._extract_html, html_content, self.url)

    @staticmethod
    def _extract_html(html_content: str, url: str | None = None, base_url: str = BASE_URL) -> dict:
        parser = LexborHTMLParser(html_content)

        # 1. JSON-LD metadata
        json_ld = {}
        for s in parser.css('script[type="application/ld+json"]'):
            if s.text():
                try:
                    json_ld.update(json.loads(s.text()))
                except (ValueError, TypeError):
                    continue

        # 2. Main video element
        video_node = parser.css_first("#video-player")

        # Video ID
        video_id = None
        if video_node and video_node.attributes.get("data-vid"):
            video_id = str(video_node.attributes["data-vid"])
        elif url and (m := re.search(r"video(\d+)", url)):
            video_id = m.group(1)

        # Title
        title = None
        if raw_title := json_ld.get("name"):
            title = html.unescape(raw_title)
        elif h1_node := parser.css_first("h1"):
            title = h1_node.text(strip=True)
        elif og_title := parser.css_first('meta[property="og:title"]'):
            title = og_title.attributes.get("content")

        # Description
        description = None
        if raw_desc := json_ld.get("description"):
            description = html.unescape(raw_desc)
        elif desc_node := parser.css_first("p.video-detail-description"):
            t = desc_node.text(strip=True)
            if t.lower().startswith("description:"):
                t = t[len("description:"):].strip()
            description = t
        elif og_desc := parser.css_first('meta[property="og:description"]'):
            description = og_desc.attributes.get("content")

        # Duration (seconds)
        duration = None
        if video_node and video_node.attributes.get("data-duration"):
            try:
                duration = int(video_node.attributes["data-duration"])
            except (ValueError, TypeError):
                pass

        # Formatted length (e.g. 08:00 or 01:24:18)
        length = None
        if duration is not None:
            mins, secs = divmod(duration, 60)
            hours, mins = divmod(mins, 60)
            if hours > 0:
                length = f"{hours:02d}:{mins:02d}:{secs:02d}"
            else:
                length = f"{mins:02d}:{secs:02d}"
        elif raw_dur := json_ld.get("duration"):
            if m := re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", raw_dur):
                h = int(m.group(1) or 0)
                mn = int(m.group(2) or 0)
                s = int(m.group(3) or 0)
                duration = h * 3600 + mn * 60 + s
                length = f"{h:02d}:{mn:02d}:{s:02d}" if h else f"{mn:02d}:{s:02d}"

        # Thumbnail URL
        thumbnail_url = None
        if video_node and video_node.attributes.get("poster"):
            thumbnail_url = video_node.attributes["poster"]
        elif raw_thumb := json_ld.get("thumbnailUrl"):
            thumbnail_url = raw_thumb
        elif og_img := parser.css_first('meta[property="og:image"]'):
            thumbnail_url = og_img.attributes.get("content")

        # Mosaic storyboard URL template
        mosaic_url_template = video_node.attributes.get("data-mosaic") if video_node else None

        # Publish date
        publish_date = json_ld.get("uploadDate")

        # Relative publish date
        clock_icon = parser.css_first(".video-detail-badges i.icon-clock-o")
        publish_date_relative = clock_icon.parent.text(strip=True) if (clock_icon and clock_icon.parent) else None

        # Embed URL
        embed_url = json_ld.get("embedUrl")
        if not embed_url and video_id:
            domain_part = base_url.split("//")[-1].replace("www.", "")
            embed_url = f"https://player.{domain_part}/video/{video_id}"

        # Author / Uploader
        author_node = parser.css_first('.video-detail-badges a[href*="/profile/"]:not(.badge-kiss)')
        author_name = author_node.text(strip=True) if author_node else None
        author_link = urljoin(base_url, author_node.attributes.get("href", "")) if author_node else None
        author_verified = ("badge-verified" in (author_node.attributes.get("class") or "")) if author_node else False

        # Models / Pornstars
        pornstars = []
        pornstars_urls = []
        for m_node in parser.css(".video-detail-badges a.badge-kiss"):
            m_name = m_node.text(strip=True)
            m_url = urljoin(base_url, m_node.attributes.get("href", ""))
            pornstars.append({"name": m_name, "url": m_url})
            pornstars_urls.append(m_url)

        # Categories & Tags
        categories = []
        tags = []
        for c_node in parser.css('.video-detail-badges a.badge-video:not([href*="/profile/"])'):
            c_name = c_node.text(strip=True)
            c_url = urljoin(base_url, c_node.attributes.get("href", ""))
            categories.append({"name": c_name, "url": c_url})
            tags.append(c_name)

        # Engagement stats
        likes_node = parser.css_first("#thumbs-up .thumb-count")
        likes = likes_node.text(strip=True) if likes_node else "0"

        dislikes_node = parser.css_first("#thumbs-down .thumb-count")
        dislikes = dislikes_node.text(strip=True) if dislikes_node else "0"

        rate_icon = parser.css_first(".video-detail-badges i.icon-thumb-up")
        rating_percent = rate_icon.parent.text(strip=True) if (rate_icon and rate_icon.parent) else None

        try:
            rating_votes = str(int(likes) + int(dislikes))
        except (ValueError, TypeError):
            rating_votes = None

        eye_icon = parser.css_first(".video-detail-badges i.icon-eye")
        views = eye_icon.parent.text(strip=True) if (eye_icon and eye_icon.parent) else None

        # Download stream sources
        direct_download_urls: dict[int, str] = {}
        if video_node:
            for s in video_node.css("source"):
                src = s.attributes.get("src")
                size_str = s.attributes.get("size")
                if src and size_str:
                    try:
                        direct_download_urls[int(size_str)] = src
                    except ValueError:
                        continue

        video_qualities = sorted(direct_download_urls.keys())

        # Preview trailer video URL
        preview_video_url = None
        first_trailer = parser.css_first("a[data-trailer]")
        if first_trailer:
            preview_video_url = first_trailer.attributes.get("data-trailer")

        return {
            "video_id": video_id,
            "title": title,
            "description": description,
            "duration": duration,
            "length": length,
            "thumbnail_url": thumbnail_url,
            "mosaic_url_template": mosaic_url_template,
            "preview_video_url": preview_video_url,
            "publish_date": publish_date,
            "publish_date_relative": publish_date_relative,
            "embed_url": embed_url,
            "author_name": author_name,
            "author_link": author_link,
            "author_verified": author_verified,
            "pornstars": pornstars,
            "pornstars_urls": pornstars_urls,
            "categories": categories,
            "tags": tags,
            "likes": likes,
            "dislikes": dislikes,
            "rating": rating_percent,
            "rating_percent": rating_percent,
            "rating_votes": rating_votes,

            "views": views,
            "direct_download_urls": direct_download_urls,
            "video_qualities": video_qualities,
        }

    @download_errors(DownloadFailed)
    async def download(self, configuration: DownloadConfigRAW) -> bool:
        await self.load_fields("direct_download_urls", "video_qualities", "title")
        config = prepare_download_config(configuration, self.title)
        cdn_urls = self.direct_download_urls or {}
        quals = self.video_qualities or []

        if not cdn_urls or not quals:
            logger.error("No download URLs or qualities available for %s", self.url)
            raise DownloadFailed(f"No download URLs available for {self.url}")

        qn = normalize_quality_value(config.quality)
        chosen_height = choose_quality_from_list(quals, qn)

        download_url = cdn_urls.get(chosen_height)
        if not download_url:
            logger.error("Chosen quality %s not found in available URLs for %s", chosen_height, self.url)
            raise DownloadFailed(f"Quality {chosen_height} not found for {self.url}")

        return await self.core.legacy_download(url=download_url, configuration=config)

    @property
    async def get_author(self, load_html: bool = True) -> Profile | Channel | None:
        url = await self.get_field("author_link")
        if url:
            if "/channel/" in url:
                channel = Channel(url=url, core=self.core)
                if load_html:
                    await channel.load_sources("html")
                return channel
            profile = Profile(url=url, core=self.core)
            if load_html:
                await profile.load_sources("html")
            return profile
        return None

    @property
    async def get_pornstars(self, load_html: bool = True) -> AsyncGenerator[Profile, None]:
        pornstars_urls = await self.get_field("pornstars_urls")
        for url in (pornstars_urls or []):
            star = Profile(url=url, core=self.core)
            if load_html:
                await star.load_sources("html")
            yield star

    async def get_related_videos(self) -> list[dict]:
        """
        Parses and returns related videos embedded on this video's page.
        """
        html_content = await get_html_content(core=self.core, url=self.url, owner=self)
        return await asyncio.to_thread(extractor_video_list, html_content, BASE_URL)


def _parse_count(val: str | None) -> int | None:
    if not val:
        return None
    raw = val.strip().upper().replace(",", "")
    if "K" in raw:
        try:
            return int(float(raw.replace("K", "")) * 1000)
        except ValueError:
            return None
    if "M" in raw:
        try:
            return int(float(raw.replace("M", "")) * 1000000)
        except ValueError:
            return None
    try:
        return int(float(raw))
    except ValueError:
        return None


@dataclass(kw_only=True, slots=True)
class BaseProfileChannel(BaseMedia):
    url: str
    core: BaseCore
    name: str | None = media_field("html")
    thumbnail_url: str | None = media_field("html")
    banner_url: str | None = media_field("html")
    total_videos: int | None = media_field("html")
    total_videos_str: str | None = media_field("html")
    subscribers: str | None = media_field("html")
    subscribers_count: int | None = media_field("html")
    entity_id: str | None = media_field("html")

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    def videos(
        self,
        pages: int = 1,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult[Video], None]:
        p = urlparse(self.url)
        qs = parse_qs(p.query)

        page_urls = []
        for page in range(1, pages + 1):
            qs_page = qs.copy()
            qs_page["page"] = [str(page)]
            new_query = urlencode(qs_page, doseq=True)
            page_urls.append(urlunparse(p._replace(query=new_query)))

        if iterator_config is None:
            iterator_config = make_iterator_config()

        return scrape_stream(
            core=self.core,
            constructor=Video,
            target_page_urls=page_urls,
            item_extractor=extractor_video_list,
            iterator_config=iterator_config,
        )


@dataclass(kw_only=True, slots=True)
class Profile(BaseProfileChannel):
    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(core=self.core, url=self.url, owner=self)
        return await asyncio.to_thread(self._extract_html, html_content, self.url)

    @staticmethod
    def _extract_html(html_content: str, url: str | None = None, base_url: str = BASE_URL) -> dict:
        parser = LexborHTMLParser(html_content)

        name = None
        if name_node := parser.css_first(".ph-title h1, h1"):
            name = name_node.text(strip=True)

        avatar_url = None
        if img_node := parser.css_first(".ph-avatar img"):
            avatar_url = img_node.attributes.get("src") or img_node.attributes.get("data-src-mobile")
            if avatar_url and avatar_url.startswith("/"):
                avatar_url = urljoin(base_url, avatar_url)

        banner_url = None
        if banner_node := parser.css_first("img.ph-canvas, .profile-header > img"):
            banner_url = banner_node.attributes.get("src") or banner_node.attributes.get("data-src-mobile")
            if banner_url and banner_url.startswith("/"):
                banner_url = urljoin(base_url, banner_url)

        total_videos_str = None
        if tabs_active := parser.css_first(".ph-tabs a.active, .ph-tabs a"):
            t = tabs_active.text(strip=True)
            if m := re.search(r"Videos\s*\(([\d.,KkMm]+)\)", t):
                total_videos_str = m.group(1)
        total_videos = _parse_count(total_videos_str)

        subscribers = None
        if sub_node := parser.css_first("#subscribe-counter"):
            subscribers = sub_node.text(strip=True)
        subscribers_count = _parse_count(subscribers)

        entity_id = None
        if sub_cont := parser.css_first("#subscribe-container"):
            on_load = sub_cont.attributes.get("data-onload", "")
            if m := re.search(r"Subscribe\.(?:user|channel)\|\|(\d+)", on_load):
                entity_id = m.group(1)

        return {
            "name": name,
            "thumbnail_url": avatar_url,
            "banner_url": banner_url,
            "total_videos": total_videos,
            "total_videos_str": total_videos_str,
            "subscribers": subscribers,
            "subscribers_count": subscribers_count,
            "entity_id": entity_id,
        }


# Pornstar is the same structure as Profile on both EMPFlix and TNAFlix
@dataclass(kw_only=True, slots=True)
class Pornstar(Profile):
    pass


@dataclass(kw_only=True, slots=True)
class Channel(BaseProfileChannel):
    rank: str | None = media_field("html")
    logo_url: str | None = media_field("html")
    description: str | None = media_field("html")
    last_update: str | None = media_field("html")
    manager_name: str | None = media_field("html")
    manager_url: str | None = media_field("html")
    manager_avatar_url: str | None = media_field("html")
    external_website: str | None = media_field("html")
    related_channels: list[dict] | None = media_field("html")

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(core=self.core, url=self.url, owner=self)
        return await asyncio.to_thread(self._extract_html, html_content, self.url)

    @staticmethod
    def _extract_html(html_content: str, url: str | None = None, base_url: str = BASE_URL) -> dict:
        parser = LexborHTMLParser(html_content)

        name = None
        if name_node := parser.css_first(".ph-title h1, h1"):
            name = name_node.text(strip=True)

        rank = None
        if rank_node := parser.css_first(".ph-rating, .rating"):
            rank = rank_node.text(strip=True)

        avatar_url = None
        if img_node := parser.css_first(".ph-avatar > img"):
            avatar_url = img_node.attributes.get("src") or img_node.attributes.get("data-src-mobile")
            if avatar_url and avatar_url.startswith("/"):
                avatar_url = urljoin(base_url, avatar_url)

        banner_url = None
        if banner_node := parser.css_first(".profile-header > img:not(.ph-avatar img), img.ph-canvas"):
            banner_url = banner_node.attributes.get("src") or banner_node.attributes.get("data-src-mobile")
            if banner_url and banner_url.startswith("/"):
                banner_url = urljoin(base_url, banner_url)

        logo_url = None
        if logo_node := parser.css_first(".channel-info img, img.thumb-logo"):
            logo_url = logo_node.attributes.get("src")
            if logo_url and logo_url.startswith("/"):
                logo_url = urljoin(base_url, logo_url)

        total_videos_str = None
        if vid_btn := parser.css_first(".btn-info + .input-group-text, .ph-btns .btn-info ~ div"):
            total_videos_str = vid_btn.text(strip=True)
        elif tabs_active := parser.css_first(".ph-tabs a.active, .ph-tabs a"):
            t = tabs_active.text(strip=True)
            if m := re.search(r"Videos\s*\(([\d.,KkMm]+)\)", t):
                total_videos_str = m.group(1)
        total_videos = _parse_count(total_videos_str)

        subscribers = None
        if sub_node := parser.css_first("#subscribe-counter"):
            subscribers = sub_node.text(strip=True)
        subscribers_count = _parse_count(subscribers)

        entity_id = None
        if sub_cont := parser.css_first("#subscribe-container"):
            on_load = sub_cont.attributes.get("data-onload", "")
            if m := re.search(r"Subscribe\.channel\|\|(\d+)", on_load):
                entity_id = m.group(1)

        manager_name = None
        manager_url = None
        manager_avatar_url = None
        last_update = None
        description = None
        external_website = None

        about_box = parser.css_first("div.container.text-break")
        if about_box:
            for row in about_box.css("div.row"):
                text = row.text(strip=True)
                if "Manager:" in text:
                    a_mgr = row.css_first("a")
                    if a_mgr:
                        manager_name = a_mgr.text(strip=True)
                        manager_url = a_mgr.attributes.get("href")
                        if manager_url and manager_url.startswith("/"):
                            manager_url = urljoin(base_url, manager_url)
                        img_mgr = a_mgr.css_first("img")
                        if img_mgr:
                            manager_avatar_url = img_mgr.attributes.get("src")
                elif "Last update:" in text:
                    cols = row.css("div.col-6")
                    if len(cols) >= 2:
                        last_update = cols[1].text(strip=True)

            desc_node = about_box.css_first("p.text-sm3")
            if desc_node:
                description = desc_node.text(strip=True)

            ext_link = about_box.css_first('a[href*="/track/goto"]')
            if ext_link:
                raw_href = ext_link.attributes.get("href", "")
                parsed_href = urlparse(raw_href)
                qs = parse_qs(parsed_href.query)
                if "url" in qs:
                    external_website = qs["url"][0]
                else:
                    external_website = raw_href

        related_channels = []
        if about_box:
            for card in about_box.css('a.thumb[href*="/channel/"]'):
                c_url = urljoin(base_url, card.attributes.get("href", ""))
                c_title = card.css_first(".thumb-title")
                c_name = c_title.text(strip=True) if c_title else None
                c_rank_node = card.css_first(".thumb-icon.rating")
                c_rank = c_rank_node.text(strip=True) if c_rank_node else None
                c_img = card.css_first("img:not(.thumb-logo)")
                c_thumb = c_img.attributes.get("src") if c_img else None
                c_logo_node = card.css_first("img.thumb-logo")
                c_logo = c_logo_node.attributes.get("src") if c_logo_node else None

                parent_col = card.parent
                v_count = None
                s_count = None
                if parent_col:
                    v_icon = parent_col.css_first("i.icon-video-camera")
                    if v_icon and v_icon.parent:
                        v_count = v_icon.parent.text(strip=True)
                    r_icon = parent_col.css_first("i.icon-rss")
                    if r_icon and r_icon.parent:
                        s_count = r_icon.parent.text(strip=True)

                related_channels.append({
                    "name": c_name,
                    "url": c_url,
                    "rank": c_rank,
                    "thumbnail_url": c_thumb,
                    "logo_url": c_logo,
                    "total_videos": v_count,
                    "subscribers": s_count,
                })

        return {
            "name": name,
            "rank": rank,
            "thumbnail_url": avatar_url,
            "banner_url": banner_url,
            "logo_url": logo_url,
            "total_videos": total_videos,
            "total_videos_str": total_videos_str,
            "subscribers": subscribers,
            "subscribers_count": subscribers_count,
            "entity_id": entity_id,
            "manager_name": manager_name,
            "manager_url": manager_url,
            "manager_avatar_url": manager_avatar_url,
            "last_update": last_update,
            "description": description,
            "external_website": external_website,
            "related_channels": related_channels,
        }


class Client:
    def __init__(self, core: BaseCore | None = None):
        if core is None:
            core = BaseCore()
        self.core = core
        self.core.initialize_session()
        self.core.session.headers.update(headers)
        self.helper = Helper(core=self.core, constructor=Video)
        logger.info("Client initialized")

    async def get_video(self, url: str, load_html: bool = True) -> Video:
        if not url.startswith(("http://", "https://")):
            clean = url.strip("/")
            url = f"{BASE_URL}/{clean}" if clean.startswith("video") else f"{BASE_URL}/video/{clean}"
        video = Video(url=url, core=self.core)
        if load_html:
            await video.load_sources("html")
        return video

    async def get_profile(self, url: str, load_html: bool = True) -> Profile:
        if not url.startswith(("http://", "https://")):
            url = f"{BASE_URL}/profile/{url.strip('/')}"
        profile = Profile(url=url, core=self.core)
        if load_html:
            await profile.load_sources("html")
        return profile

    async def get_pornstar(self, url: str, load_html: bool = True) -> Profile:
        return await self.get_profile(url=url, load_html=load_html)

    async def get_channel(self, url: str, load_html: bool = True) -> Channel:
        if not url.startswith(("http://", "https://")):
            url = f"{BASE_URL}/channel/{url.strip('/')}"
        channel = Channel(url=url, core=self.core)
        if load_html:
            await channel.load_sources("html")
        return channel


    def search(
        self,
        query: str,
        sorting_sort: str | Sort = Sort.Sort_relevance,
        sorting_date: str | SortDate = SortDate.Sort_all,
        pages: int = 1,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult[Video], None]:
        p = urlparse(f"{BASE_URL}/search")
        qs = parse_qs(p.query)
        qs["what"] = [query]
        if sorting_sort and sorting_sort != Sort.Sort_relevance:
            qs["sort"] = [str(sorting_sort)]
        if sorting_date and sorting_date != SortDate.Sort_all:
            qs["date"] = [str(sorting_date)]

        new_query = urlencode(qs, doseq=True)
        search_url = urlunparse(p._replace(query=new_query))

        page_urls = [f"{search_url}&page={page}" for page in range(1, pages + 1)] if pages > 0 else []

        if iterator_config is None:
            iterator_config = make_iterator_config()

        return scrape_stream(
            core=self.core,
            constructor=Video,
            target_page_urls=page_urls,
            item_extractor=extractor_video_list,
            iterator_config=iterator_config,
        )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TNAFlix API Command Line Interface")
    parser.add_argument("--download", metavar="URL", type=str, help="URL to download from")
    parser.add_argument(
        "--quality",
        metavar="best|half|worst",
        type=str,
        default="best",
        help="The video quality (best, half, worst, 1080p, 720p, etc.)",
    )
    parser.add_argument("--file", metavar="FILE", type=str, help="(Optional) File containing URLs (one per line)")
    parser.add_argument("--output", metavar="DIR", type=str, required=True, help="Output file path or directory")
    parser.add_argument(
        "--no-title",
        metavar="True,False",
        type=str,
        nargs="?",
        const="True",
        default="False",
        help="Whether to skip applying video title to output filename",
    )
    return parser


async def run_main(args_list: list[str] | None = None):
    parser = create_parser()
    args = parser.parse_args(args_list)
    no_title = str_to_bool(args.no_title) if isinstance(args.no_title, str) else bool(args.no_title)
    config = DownloadConfigRAW(
        quality=args.quality,
        path=args.output,
        no_title=no_title,
    )

    urls: list[str] = []
    if args.download:
        urls.append(args.download)
    if args.file:
        with open(args.file, "r") as f:
            urls.extend([line.strip() for line in f if line.strip()])

    if not urls:
        parser.print_help()
        return

    client = Client()
    for url in urls:
        print(f"Fetching video information for: {url}")
        try:
            video = await client.get_video(url, load_html=True)
            title = getattr(video, "title", None) or url
            print(f"Starting download for: {title}")
            await video.download(configuration=config)
            print(f"Download complete: {title}")
        except Exception as e:
            logger.exception("CLI failed while processing %s", url)
            print(f"Error downloading {url}: {e}")


def main():
    configure_app_logging(level=logging.INFO)
    try:
        asyncio.run(run_main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")


if __name__ == "__main__":
    main()
