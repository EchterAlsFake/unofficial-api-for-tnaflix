from __future__ import annotations

import re
from urllib.parse import urljoin
from selectolax.lexbor import LexborHTMLParser

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.tnaflix.com/",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
}

cookies = None


def extractor_video_list(html: str, base_url: str = "https://www.tnaflix.com") -> list[dict]:
    """
    Extracts video item metadata from video list pages or related video containers.
    """
    videos = []
    tree = LexborHTMLParser(html)
    seen_ids = set()

    cards = tree.css("div[data-vid]")
    for card in cards:
        video_id = card.attributes.get("data-vid")
        if not video_id or video_id in seen_ids:
            continue
        seen_ids.add(video_id)

        a_thumb = card.css_first("a.video-thumb, a.thumb")
        if not a_thumb:
            continue
        video_url = urljoin(base_url, a_thumb.attributes.get("href", ""))
        trailer_url = a_thumb.attributes.get("data-trailer")

        img = card.css_first("img")
        thumbnail_url = None
        if img:
            thumbnail_url = img.attributes.get("data-src") or img.attributes.get("src")
            if thumbnail_url and thumbnail_url.startswith("/"):
                thumbnail_url = urljoin(base_url, thumbnail_url)

        dur_node = card.css_first(".video-duration, .thumb-icon")
        duration = dur_node.text(strip=True) if dur_node else None

        title_node = card.css_first("a.video-title") or card.css_first(".video-title")
        title = title_node.text(strip=True) if title_node else (img.attributes.get("alt") if img else None)

        author_node = card.css_first('a[href*="/profile/"]')
        author_name = author_node.text(strip=True) if author_node else None
        author_link = urljoin(base_url, author_node.attributes.get("href", "")) if author_node else None

        views = None
        rating = None
        eye_icon = card.css_first("i.icon-eye")
        if eye_icon and eye_icon.parent:
            views = eye_icon.parent.text(strip=True)

        thumb_icon = card.css_first("i.icon-thumb-up")
        if thumb_icon and thumb_icon.parent:
            rating = thumb_icon.parent.text(strip=True)

        videos.append({
            "video_id": video_id,
            "title": title,
            "url": video_url,
            "thumbnail_url": thumbnail_url,
            "preview_video_url": trailer_url,
            "length": duration,
            "author_name": author_name,
            "author_link": author_link,
            "views": views,
            "rating": rating,
            "rating_percent": rating,
        })


    return videos


def is_next_page(html_content: str, current_page: int | None = None) -> bool:
    """
    Checks if another page is available for automatic pagination.
    """
    tree = LexborHTMLParser(html_content)
    if next_btn := tree.css_first(".pagination .pagination-next:not(.disabled) a, a[rel='next']"):
        return bool(next_btn)
    if current_page is not None:
        for page_link in tree.css(".pagination a.page-link"):
            try:
                num = int(page_link.text(strip=True))
                if num > current_page:
                    return True
            except ValueError:
                pass
    return False

