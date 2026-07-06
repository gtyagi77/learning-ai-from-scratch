"""Build instruments.json: Yahoo-style symbol -> broker instrument id.

Broker quote APIs don't understand "RELIANCE.NS" — Upstox wants an
instrument_key like "NSE_EQ|INE002A01018" and Angel One wants a numeric
symboltoken. Both publish their full instrument lists publicly (no login),
so this script downloads the list and writes the JSON map that
app/prices.py reads via INSTRUMENT_MAP_PATH.

Usage:
    python scripts/build_instrument_map.py --provider upstox
    python scripts/build_instrument_map.py --provider angelone
    python scripts/build_instrument_map.py --provider breeze
    python scripts/build_instrument_map.py --provider upstox --all

By default only the app's watch universe (Nifty 50 + sector baskets) plus
any portfolio holdings are included, which keeps the file tiny. --all maps
every NSE equity the broker lists (~2000 symbols) -- not supported for
breeze, which has no anonymous bulk list and needs BREEZE_API_KEY /
BREEZE_API_SECRET / BREEZE_SESSION_TOKEN set to build even the scoped map.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, instruments, universe  # noqa: E402


def wanted_symbols() -> set:
    symbols = set(universe.watch_symbols())
    symbols.update(t for t, _ in config.DEFAULT_PORTFOLIO)
    try:  # include the live portfolio when a database exists
        from app import database
        database.init()
        symbols.update(h["ticker"] for h in database.get_portfolio())
    except Exception:
        pass
    return {s for s in symbols if s.endswith(".NS")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["upstox", "angelone", "breeze"], required=True)
    parser.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instruments.json"))
    parser.add_argument("--all", action="store_true",
                        help="map every NSE equity, not just the watch universe "
                             "(not supported for breeze)")
    args = parser.parse_args()

    if args.all and args.provider == "breeze":
        parser.error("--all is not supported for breeze (no anonymous bulk list)")

    if args.provider == "breeze":
        missing = [v for v in ("BREEZE_API_KEY", "BREEZE_API_SECRET", "BREEZE_SESSION_TOKEN")
                  if not os.environ.get(v)]
        if missing:
            parser.error(f"breeze needs {', '.join(missing)} set in the environment "
                        f"(session token is regenerated daily -- see README)")
        # download_map("breeze") is already scoped to the watch universe.
        mapping = instruments.download_map("breeze")
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(mapping, fh, indent=1, sort_keys=True)
        print(f"wrote {len(mapping)} symbols to {args.out}")
        print(f"now set: QUOTE_PROVIDER=breeze  INSTRUMENT_MAP_PATH={args.out}")
        return

    print(f"downloading {args.provider} instrument list ...")
    full = instruments.download_map(args.provider)
    if args.all:
        mapping = full
    else:
        want = wanted_symbols()
        mapping = {s: full[s] for s in sorted(want) if s in full}
        missing = sorted(want - set(mapping))
        if missing:
            print(f"note: {len(missing)} watchlist symbols not in the broker list: "
                  + ", ".join(missing))

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, indent=1, sort_keys=True)
    print(f"wrote {len(mapping)} symbols to {args.out}")
    print(f"now set: QUOTE_PROVIDER={args.provider}  INSTRUMENT_MAP_PATH={args.out}")


if __name__ == "__main__":
    main()
