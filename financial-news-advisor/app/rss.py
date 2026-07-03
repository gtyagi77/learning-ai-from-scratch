"""Minimal RSS 2.0 / Atom feed parser built on the standard library.

Third-party feed parsers were unavailable in this environment, and the
subset of RSS/Atom that financial news feeds use is small enough to parse
directly with xml.etree.
"""

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional

ATOM_NS = "{http://www.w3.org/2005/Atom}"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass
class FeedItem:
    title: str
    link: str
    summary: str
    published: Optional[datetime]


def _strip_html(text: str) -> str:
    text = _TAG_RE.sub(" ", text or "")
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _parse_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    raw = raw.strip()
    # RFC 822 (RSS pubDate)
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass
    # ISO 8601 (Atom updated/published)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _text(element, *tags: str) -> str:
    for tag in tags:
        node = element.find(tag)
        if node is not None and node.text:
            return node.text
    return ""


def _parse_rss(root: ET.Element) -> List[FeedItem]:
    items = []
    for item in root.iter("item"):
        title = _strip_html(_text(item, "title"))
        link = (_text(item, "link") or "").strip()
        if not title or not link:
            continue
        items.append(
            FeedItem(
                title=title,
                link=link,
                summary=_strip_html(_text(item, "description"))[:1000],
                published=_parse_date(_text(item, "pubDate", "{http://purl.org/dc/elements/1.1/}date")),
            )
        )
    return items


def _parse_atom(root: ET.Element) -> List[FeedItem]:
    items = []
    for entry in root.iter(f"{ATOM_NS}entry"):
        title = _strip_html(_text(entry, f"{ATOM_NS}title"))
        link = ""
        for node in entry.findall(f"{ATOM_NS}link"):
            if node.get("rel") in (None, "alternate"):
                link = node.get("href", "")
                break
        if not title or not link:
            continue
        items.append(
            FeedItem(
                title=title,
                link=link.strip(),
                summary=_strip_html(_text(entry, f"{ATOM_NS}summary", f"{ATOM_NS}content"))[:1000],
                published=_parse_date(
                    _text(entry, f"{ATOM_NS}published", f"{ATOM_NS}updated")
                ),
            )
        )
    return items


def parse_feed(raw_xml: str) -> List[FeedItem]:
    """Parse RSS or Atom XML into feed items. Returns [] on malformed input."""
    try:
        root = ET.fromstring(raw_xml.strip())
    except ET.ParseError:
        return []
    if root.tag == f"{ATOM_NS}feed":
        return _parse_atom(root)
    return _parse_rss(root)
