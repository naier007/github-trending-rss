"""Offline smoke test: build an RSS feed from sample repos and validate it."""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.getcwd())

from github_trending.fetcher import Repo
from github_trending.rss import build_feed

repos = [
    Repo(
        full_name="torvalds/linux",
        url="https://github.com/torvalds/linux",
        description="Linux kernel source tree",
        summary="Linux kernel source tree & resources",
        stars=200000,
        forks=47000,
        language="C",
        created_at="2011-09-04T22:48:12Z",
        topics=["kernel", "linux"],
        license="GPL-2.0",
        source="search-api",
    ),
    Repo(
        full_name='acme/tool <&> "quotes"',
        url="https://github.com/acme/tool",
        description='A tool with <html> & chars',
        summary="",
        stars=1234,
        forks=56,
        language="Python",
        created_at="",
        source="search-api",
    ),
]

xml = build_feed(
    repos,
    title="GitHub Trending Repositories",
    link="https://github.com/trending",
    description="Test feed",
    self_link="https://example.com/feed.xml",
)
with open("smoke.xml", "w", encoding="utf-8") as fh:
    fh.write(xml)

root = ET.parse("smoke.xml").getroot()
assert root.tag == "rss" and root.get("version") == "2.0", "root tag/version"
ch = root.find("channel")
items = ch.findall("item")
assert len(items) == 2, f"items={len(items)}"
for it in items:
    for field in ("title", "link", "description", "guid", "pubDate"):
        el = it.find(field)
        assert el is not None and (el.text or "").strip(), f"missing {field}"
    assert it.find("guid").get("isPermaLink") == "true"
assert ch.find("lastBuildDate") is not None
assert ch.find("{http://www.w3.org/2005/Atom}link") is not None
enc = items[0].find("{http://purl.org/rss/1.0/modules/content/}encoded")
assert enc is not None and "<p>" in (enc.text or ""), "content:encoded"
# Check XML-escaping in the raw document (ElementTree re-parse unescapes)
assert "&amp;" in xml
assert "<html>" not in xml
assert "&lt;html&gt;" in xml
assert "ns0:" not in xml and "ns1:" not in xml
print(f"RSS offline smoke test OK; {len(xml)} bytes")
