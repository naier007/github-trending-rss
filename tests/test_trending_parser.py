"""Offline test: trending-page parser against a real HTML fixture.

The fixture (tests/fixtures/trending_articles.html) was captured from
https://github.com/trending?since=daily and contains 3 <article class="Box-row">
blocks, so this test is deterministic and needs no network.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from github_trending.fetcher import (  # noqa: E402
    _parse_count,
    _parse_today_count,
    _TrendingParser,
)

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "trending_articles.html")


def test_parse_count():
    assert _parse_count("34.2k") == 34200
    assert _parse_count("1.2m") == 1_200_000
    assert _parse_count("1,234") == 1234
    assert _parse_count("123") == 123
    assert _parse_count("") == 0
    assert _parse_count("n/a") == 0


def test_parse_today_count():
    assert _parse_today_count("2,304 stars today") == 2304
    assert _parse_today_count("120 stars this week") == 120
    assert _parse_today_count("") == 0


def test_parser_extracts_articles():
    with io.open(FIXTURE, "r", encoding="utf-8") as fh:
        html = fh.read()
    parser = _TrendingParser()
    parser.feed(html)
    assert len(parser.repos) == 3, f"expected 3 repos, got {len(parser.repos)}"

    for entry in parser.repos:
        name = entry["name"].replace(" ", "")
        assert "/" in name and len(name.split("/")) >= 2, f"bad name {name!r}"
        assert entry["stars"], f"missing stars for {name!r}"
        assert entry["forks"], f"missing forks for {name!r}"
        assert entry["today"], f"missing stars-today for {name!r}"
        assert entry["language"], f"missing language for {name!r}"
        print(f"  {name}: stars={entry['stars']} forks={entry['forks']} "
              f"today={entry['today']} language={entry['language']}")


if __name__ == "__main__":
    test_parse_count()
    test_parse_today_count()
    test_parser_extracts_articles()
    print("trending parser fixture test OK")
