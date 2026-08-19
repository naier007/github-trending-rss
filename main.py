#!/usr/bin/env python3
"""GitHub Trending RSS — fetch trending GitHub repositories and generate an RSS 2.0 feed.

Primary source : github.com/trending (daily/weekly/monthly window), with the
                 GitHub Search API as fallback — see docs/RESEARCH.md.

Examples
--------
    python main.py                                  # today's GitHub Trending, top 30 -> feed.xml
    python main.py -l python --since weekly -n 50 -o python-feed.xml
    GITHUB_TOKEN=ghp_xxx python main.py --limit 100
    python main.py --no-fallback -n 20              # trending page only, no Search API fallback
"""

from __future__ import annotations

import argparse
import os
import sys

from github_trending import __version__
from github_trending.fetcher import (
    FetchError,
    enrich_readme_summaries,
    fetch_trending_repos,
)
from github_trending.rss import build_feed

DEFAULT_LIMIT = 30
DEFAULT_DAYS = 7
DEFAULT_OUTPUT = "feed.xml"
MAX_SEARCH_LIMIT = 100  # GitHub Search API per_page cap


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="github-trending-rss",
        description="Fetch trending GitHub repositories and generate an RSS 2.0 feed.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-l", "--language", metavar="LANG",
                        help="Filter by primary language, e.g. python, typescript, go (optional).")
    parser.add_argument("--since", choices=("daily", "weekly", "monthly"), default="daily",
                        help="Trending window of the github.com/trending page (primary source).")
    parser.add_argument("-d", "--days", type=int, default=DEFAULT_DAYS, metavar="N",
                        help="Time window for the Search API fallback: repositories created "
                             "within the last N days.")
    parser.add_argument("-n", "--limit", type=int, default=DEFAULT_LIMIT, metavar="N",
                        help=f"Maximum number of repositories (1..{MAX_SEARCH_LIMIT}).")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT, metavar="FILE",
                        help="Output path for the RSS feed file.")
    parser.add_argument("--sort", choices=("stars", "forks", "updated"), default="stars",
                        help="Sort order used by the Search API fallback.")
    parser.add_argument("--min-stars", type=int, default=0, metavar="N",
                        help="Drop repositories with fewer stars than N.")
    parser.add_argument("--token", metavar="TOKEN",
                        help="GitHub personal access token (overrides the GITHUB_TOKEN env var).")
    parser.add_argument("--no-fallback", action="store_true",
                        help="Do not fall back to the GitHub Search API when the trending page fails.")
    parser.add_argument("--no-readme-summary", action="store_true",
                        help="Skip README summaries; use the repository description instead.")
    parser.add_argument("--feed-title", default="GitHub Trending Repositories",
                        help="RSS channel title.")
    parser.add_argument("--feed-link", default="https://github.com/trending",
                        help="RSS channel link.")
    parser.add_argument("--feed-description",
                        default="Trending and hot open-source repositories on GitHub, updated daily.",
                        help="RSS channel description.")
    parser.add_argument("--self-link", metavar="URL",
                        help="Public URL of this feed, emitted as atom:link rel=self.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print progress details to stderr.")
    args = parser.parse_args(argv)

    if args.days < 1:
        parser.error("--days must be >= 1")
    if not 1 <= args.limit <= MAX_SEARCH_LIMIT:
        parser.error(f"--limit must be between 1 and {MAX_SEARCH_LIMIT}")
    if args.min_stars < 0:
        parser.error("--min-stars must be >= 0")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    token = args.token or os.environ.get("GITHUB_TOKEN") or None

    if args.verbose:
        print(f"github-trending-rss {__version__} | since={args.since} limit={args.limit} "
              f"language={args.language or 'any'} "
              f"token={'yes' if token else 'no'}",
              file=sys.stderr)

    try:
        repos = fetch_trending_repos(
            language=args.language,
            days=args.days,
            limit=args.limit,
            token=token,
            sort=args.sort,
            use_fallback=not args.no_fallback,
            since=args.since,
        )
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not repos:
        print("error: no repositories found for the given filters.", file=sys.stderr)
        return 1

    if args.min_stars:
        repos = [r for r in repos if r.stars >= args.min_stars]
        if not repos:
            print("error: no repositories passed the --min-stars filter.", file=sys.stderr)
            return 1

    if not args.no_readme_summary:
        repos = enrich_readme_summaries(repos, token=token)
        if args.verbose:
            print(f"README summaries filled for {len(repos)} repositories", file=sys.stderr)

    # Keep the trending semantics: sort by stars gained in the window first
    # (Search API fallback repos have stars_today=0, so they fall back to
    # total stars, matching their API sort order).
    repos.sort(key=lambda r: (r.stars_today, r.stars), reverse=True)

    xml = build_feed(
        repos,
        title=args.feed_title,
        link=args.feed_link,
        description=args.feed_description,
        self_link=args.self_link,
    )

    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(xml)

    if args.verbose:
        print(f"wrote {len(repos)} items to {args.output} ({len(xml)} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
