"""CLI: python -m ingest <github-url>."""

from __future__ import annotations

import argparse
import logging
import sys

from config import get_settings
from ingest.pipeline import run


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m ingest",
        description="Index a public GitHub repo (clone, chunk, embed, store).",
    )
    parser.add_argument("url", help="https://github.com/owner/name")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        run(args.url, get_settings())
    except ValueError as exc:
        # Bad URL or missing API key: the user can fix these.
        logging.error("error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
