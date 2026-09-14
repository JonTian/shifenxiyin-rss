#!/usr/bin/env python3
"""Build a complete RSS feed from public shifenxiyin.com episode pages."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import email.utils
import html.parser
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SITE_URL = "https://shifenxiyin.com"
SITEMAP_URL = f"{SITE_URL}/sitemap.xml"
DEFAULT_FEED_URL = "https://jontian.github.io/shifenxiyin-rss/feed.xml"
USER_AGENT = "shifenxiyin-rss/1.0 (+https://github.com/JonTian/shifenxiyin-rss)"
UUID_PATH = re.compile(r"^https://shifenxiyin\.com/[0-9a-f-]{36}$")
MIN_EXPECTED_EPISODES = 78


class JsonLdParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_json_ld = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("type") == "application/ld+json":
            self.in_json_ld = True

    def handle_data(self, data: str) -> None:
        if self.in_json_ld:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.in_json_ld:
            self.in_json_ld = False


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def sitemap_urls() -> list[str]:
    root = ET.fromstring(fetch(SITEMAP_URL))
    urls = [node.text.strip() for node in root.findall("{*}url/{*}loc") if node.text]
    return [url for url in urls if UUID_PATH.match(url)]


def existing_feed_item_count(path: Path) -> int:
    """Return the number of existing RSS items, or zero when no valid feed exists."""
    try:
        return len(ET.parse(path).findall("./channel/item"))
    except (ET.ParseError, OSError):
        return 0


def episodes_from_existing_feed(path: Path) -> list[dict[str, str]]:
    """Read previously published items so a truncated source cannot erase history."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return []

    itunes = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
    episodes: list[dict[str, str]] = []
    for item in root.findall("./channel/item"):
        enclosure = item.find("enclosure")
        image = item.find(f"{itunes}image")
        url = item.findtext("guid") or item.findtext("link") or ""
        published = item.findtext("pubDate") or ""
        if not url or enclosure is None or not enclosure.get("url") or not published:
            continue
        try:
            published = email.utils.parsedate_to_datetime(published).isoformat()
        except (TypeError, ValueError):
            continue
        episodes.append(
            {
                "url": url,
                "title": item.findtext("title") or "",
                "description": item.findtext("description") or "",
                "published": published,
                "duration": item.findtext(f"{itunes}duration") or "",
                "image": image.get("href", "") if image is not None else "",
                "audio": enclosure.get("url", ""),
            }
        )
    return episodes


def episode_from_page(url: str) -> dict[str, str]:
    parser = JsonLdParser()
    parser.feed(fetch(url).decode("utf-8"))
    if not parser.parts:
        raise ValueError(f"No JSON-LD found: {url}")
    payload = json.loads("".join(parser.parts))
    nodes = payload.get("@graph", [payload])
    episode = next(
        node
        for node in nodes
        if "PodcastEpisode" in ([node.get("@type")] if isinstance(node.get("@type"), str) else node.get("@type", []))
    )
    media = episode["associatedMedia"]
    return {
        "url": episode["url"],
        "title": episode["name"],
        "description": episode.get("description", ""),
        "published": episode["datePublished"],
        "duration": episode.get("duration", ""),
        "image": episode.get("image", ""),
        "audio": media["contentUrl"],
    }


def rfc2822(value: str) -> str:
    timestamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return email.utils.format_datetime(timestamp)


def itunes_duration(value: str) -> str:
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        return value
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    total = hours * 3600 + minutes * 60 + seconds
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}" if total >= 3600 else f"{total // 60}:{total % 60:02d}"


def add(parent: ET.Element, name: str, text: str | None = None, **attrs: str) -> ET.Element:
    node = ET.SubElement(parent, name, attrs)
    if text is not None:
        node.text = text
    return node


def build_feed(episodes: list[dict[str, str]], output: Path) -> None:
    ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
    ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
    ET.register_namespace("content", "http://purl.org/rss/1.0/modules/content/")
    root = ET.Element("rss", {"version": "2.0"})
    channel = add(root, "channel")
    feed_url = os.environ.get("FEED_URL", DEFAULT_FEED_URL)
    add(channel, "title", "十分吸引（完整历史归档）")
    add(channel, "link", SITE_URL)
    add(channel, "description", "《十分吸引》公开节目完整历史索引；音频直接引用原发布方公开地址。")
    add(channel, "language", "zh-cn")
    add(channel, "generator", "shifenxiyin-rss")
    add(channel, "{http://www.w3.org/2005/Atom}link", href=feed_url, rel="self", type="application/rss+xml")
    add(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}author", "敏-姐")
    add(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}explicit", "false")
    if episodes:
        add(channel, "lastBuildDate", rfc2822(max(item["published"] for item in episodes)))
        add(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}image", href=episodes[0]["image"])

    for episode in sorted(episodes, key=lambda item: item["published"], reverse=True):
        item = add(channel, "item")
        add(item, "title", episode["title"])
        add(item, "link", episode["url"])
        add(item, "guid", episode["url"], isPermaLink="true")
        add(item, "pubDate", rfc2822(episode["published"]))
        add(item, "description", episode["description"])
        add(item, "{http://purl.org/rss/1.0/modules/content/}encoded", episode["description"])
        add(item, "enclosure", url=episode["audio"], type="audio/mp4", length="0")
        add(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}duration", itunes_duration(episode["duration"]))
        add(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}explicit", "false")
        if episode["image"]:
            add(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}image", href=episode["image"])

    ET.indent(root, space="  ")
    output.write_bytes(b"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" + ET.tostring(root, encoding="utf-8"))


def main() -> int:
    urls = sitemap_urls()
    output = Path(os.environ.get("OUTPUT", "public/feed.xml"))
    existing = episodes_from_existing_feed(output)
    if len(urls) < MIN_EXPECTED_EPISODES and len(existing) < MIN_EXPECTED_EPISODES:
        print(
            f"Source exposes only {len(urls)} episode(s), and no complete existing feed is available.",
            file=sys.stderr,
        )
        return 1
    episodes: list[dict[str, str]] = []
    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        future_urls = {pool.submit(episode_from_page, url): url for url in urls}
        for future in concurrent.futures.as_completed(future_urls):
            url = future_urls[future]
            try:
                episodes.append(future.result())
            except Exception as exc:  # keep all failures visible in CI
                failures.append(f"{url}: {exc}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1

    # The source currently lists only recent episodes.  Refresh those entries while
    # retaining every archived item already in the published feed.
    merged = {episode["url"]: episode for episode in existing}
    merged.update({episode["url"]: episode for episode in episodes})
    if len(merged) < max(MIN_EXPECTED_EPISODES, len(existing)):
        print("Merged feed would lose archived episodes; refusing to publish.", file=sys.stderr)
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    build_feed(list(merged.values()), output)
    print(
        f"Generated {output} with {len(merged)} episodes "
        f"({len(episodes)} refreshed from source, {len(existing)} retained)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
