"""Interactive helper for the Upstox OAuth flow -> access token.

Upstox issues access tokens through a browser login. This walks you through
it in ~1 minute:

    python scripts/get_upstox_token.py

You need a (free) Upstox developer app first: https://account.upstox.com/developer/apps
- set its Redirect URL to  https://127.0.0.1  (must match exactly below)
- note the API Key and API Secret it shows you

Heads-up: Upstox access tokens expire daily (around 3:30 AM IST), so a
long-running server needs a fresh token each trading day. Re-run this and
update the UPSTOX_ACCESS_TOKEN env var (on Render: Environment tab -> edit
-> save redeploys automatically).
"""

import sys
import urllib.parse

import requests

AUTH_URL = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"


def main() -> None:
    api_key = input("Upstox API Key: ").strip()
    api_secret = input("Upstox API Secret: ").strip()
    redirect = input("Redirect URL [https://127.0.0.1]: ").strip() or "https://127.0.0.1"

    params = urllib.parse.urlencode(
        {"response_type": "code", "client_id": api_key, "redirect_uri": redirect}
    )
    print("\n1. Open this URL in your browser and log in to Upstox:\n")
    print(f"   {AUTH_URL}?{params}\n")
    print("2. After login the browser lands on your redirect URL — the page")
    print("   itself may not load; that's fine. Copy the 'code' value from")
    print("   the address bar (…?code=THIS_PART&…).\n")
    code = input("Paste the code here: ").strip()

    resp = requests.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": api_key,
            "client_secret": api_secret,
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
        },
        headers={"Accept": "application/json"},
        timeout=30,
    )
    if not resp.ok:
        print(f"\nToken exchange failed ({resp.status_code}): {resp.text[:300]}")
        sys.exit(1)

    token = resp.json().get("access_token")
    if not token:
        print(f"\nNo access_token in response: {resp.text[:300]}")
        sys.exit(1)

    print("\nSuccess! Set these environment variables where the app runs:\n")
    print("   QUOTE_PROVIDER=upstox")
    print(f"   UPSTOX_ACCESS_TOKEN={token}")
    print("   INSTRUMENT_MAP_PATH=instruments.json   # from build_instrument_map.py")
    print("\nToken expires ~3:30 AM IST daily — re-run this script each trading day.")


if __name__ == "__main__":
    main()
