#!/usr/bin/env python3
"""Kvittokoll — starta den lokala webbappen.

    python3 app.py

Ingen installation, inga beroenden utanför standardbiblioteket.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from kvittokoll.server import serve  # noqa: E402
from kvittokoll.storage import Store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Kvittokoll — avstämning av verifikat")
    parser.add_argument("--port", type=int, default=8420, help="port (0 = välj ledig)")
    parser.add_argument("--host", default="127.0.0.1", help="lyssnaradress")
    parser.add_argument(
        "--no-browser", action="store_true", help="öppna inte webbläsaren automatiskt"
    )
    args = parser.parse_args()

    if args.host != "127.0.0.1":
        print(
            "Varning: Kvittokoll saknar inloggning och är byggt för localhost.\n"
            "         Att lyssna på {} exponerar din bokföring.".format(args.host)
        )

    store = Store(ROOT)
    serve(store, host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
