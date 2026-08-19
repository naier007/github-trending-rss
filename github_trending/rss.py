"""Generate an RSS 2.0 feed from Repo objects (standard library only).

Output is a valid RSS 2.0 document (https://www.rssboard.org/rss-specification):
channel fields title/link/description/language/lastBuildDate/generator/ttl and
item fields title/link/description/guid/pubDate, plus an atom:link self link
and content:encoded HTML description.
"""

from __future__ import annotations

import email.utils
import html as html_mod
from datetime import datetime, timezone
from typing import List, Optional
import xml.etree.ElementTree as ET
from xml.dom import minidom

from . import __version__
from .fetcher import Repo

ATOM_NS = "http://www.w3.org/2005/Atom"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"

# Make ElementTree serialize with the conventional atom:/content: prefixes
# (instead of auto-generated ns0:/ns1:).
ET.register_namespace("atom", ATOM_NS)
ET.register_namespace("content", CONTENT_NS)


def _escape_html(text: str) -> str:
    return html_mod.escape(text or "", quote=True)


def _rfc822(dt: datetime) -> str:
    """Format a datetime as an RFC 822 date, e.g. 'Sun, 05 Jan 2025 12:00:00 GMT'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return email.utils.format_datetime(dt.astimezone(timezone.utc), usegmt=True)


def _parse_iso(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _item_meta(repo: Repo) -> str:
    """Plain-text metadata line: stars today / stars / forks / language / license / created."""
    parts = []
    if repo.stars_today:
        parts.append(f"+{repo.stars_today:,} stars today")
    if repo.stars:
        parts.append(f"{repo.stars:,} stars")
    if repo.forks:
        parts.append(f"{repo.forks:,} forks")
    if repo.language:
        parts.append(f"Language: {repo.language}")
    if repo.license:
        parts.append(f"License: {repo.license}")
    if repo.created_at:
        parts.append(f"Created: {_rfc822(_parse_iso(repo.created_at))}")
    return " · ".join(parts)


def _item_description(repo: Repo) -> str:
    """Plain-text item description: README summary + metadata."""
    body = repo.summary or repo.description or repo.full_name
    meta = _item_meta(repo)
    return f"{body} — {meta}" if meta else body


def _item_content_html(repo: Repo) -> str:
    """HTML item description (content:encoded) for richer feed readers."""
    parts = []
    if repo.summary or repo.description:
        parts.append(f"<p>{_escape_html(repo.summary or repo.description)}</p>")
    meta = []
    if repo.stars_today:
        meta.append(f"🔥 +{repo.stars_today:,} stars today")
    if repo.stars:
        meta.append(f"⭐ <b>{repo.stars:,}</b> stars")
    if repo.forks:
        meta.append(f"🍴 <b>{repo.forks:,}</b> forks")
    if repo.language:
        meta.append(f"<b>{_escape_html(repo.language)}</b>")
    if repo.license:
        meta.append(_escape_html(repo.license))
    if meta:
        parts.append("<p>" + " · ".join(meta) + "</p>")
    topics = [t for t in repo.topics if t][:10]
    if topics:
        badges = " ".join(f"<code>{_escape_html(t)}</code>" for t in topics)
        parts.append(f"<p>Topics: {badges}</p>")
    parts.append(f'<p><a href="{_escape_html(repo.url)}">View on GitHub</a></p>')
    return "".join(parts)


def build_feed(repos: List[Repo], *, title: str, link: str, description: str,
               language: str = "zh-CN", self_link: Optional[str] = None,
               generator: Optional[str] = None) -> str:
    """Build an RSS 2.0 document from *repos* and return it as a string."""
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")

    def add(parent: ET.Element, tag: str, text: str) -> ET.Element:
        el = ET.SubElement(parent, tag)
        el.text = text
        return el

    add(channel, "title", title)
    add(channel, "link", link)
    add(channel, "description", description)
    add(channel, "language", language)
    add(channel, "generator", generator or f"github-trending-rss/{__version__}")
    add(channel, "ttl", "1440")
    add(channel, "lastBuildDate", _rfc822(datetime.now(timezone.utc)))
    add(channel, "docs", "https://validator.w3.org/feed/docs/rss2.html")
    if self_link:
        atom_link = ET.SubElement(channel, f"{{{ATOM_NS}}}link")
        atom_link.set("rel", "self")
        atom_link.set("type", "application/rss+xml")
        atom_link.set("href", self_link)

    for repo in repos:
        item = ET.SubElement(channel, "item")
        add(item, "title", repo.full_name)
        add(item, "link", repo.url)
        guid = add(item, "guid", repo.url)
        guid.set("isPermaLink", "true")
        # pubDate is the generation time (UTC): the feed is a daily digest,
        # see docs/RESEARCH.md section 2.2.
        add(item, "pubDate", _rfc822(datetime.now(timezone.utc)))
        add(item, "description", _item_description(repo))
        encoded = ET.SubElement(item, f"{{{CONTENT_NS}}}encoded")
        encoded.text = _item_content_html(repo)

    return _serialize(rss)


def _serialize(root: ET.Element) -> str:
    """Serialize to a pretty-printed XML string with an XML declaration."""
    rough = ET.tostring(root, encoding="unicode")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="UTF-8")
    return pretty.decode("utf-8")
