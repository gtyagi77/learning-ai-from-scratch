"""Interactive helper for the Breeze login flow -> today's session token.

ICICI Direct's Breeze API issues session tokens through a browser login,
valid until ~midnight IST. This walks you through it in ~1 minute:

    python scripts/get_breeze_token.py

You need a (free) Breeze API app first: https://api.icicidirect.com/apiuser/register.html
(needs an ICICI Direct trading/demat account) — note the API Key and API
Secret it shows you.

Heads-up: the session token expires by midnight IST, so a long-running
server needs a fresh one each trading day. Re-run this and update the
BREEZE_SESSION_TOKEN env var (on Render: Environment tab -> edit -> save
redeploys automatically).
"""

import urllib.parse

LOGIN_URL = "https://api.icicidirect.com/apiuser/login"


def main() -> None:
    api_key = input("Breeze API Key: ").strip()

    params = urllib.parse.urlencode({"api_key": api_key})
    print("\n1. Open this URL in your browser and log in to ICICI Direct:\n")
    print(f"   {LOGIN_URL}?{params}\n")
    print("2. After login the browser redirects to your app's redirect URL —")
    print("   the page itself may not load; that's fine. Copy the 'API_Session'")
    print("   value from the address bar or request payload (…API_Session=THIS_PART…).\n")
    session_token = input("Paste the API_Session value here: ").strip()

    print("\nSet these environment variables where the app runs:\n")
    print("   QUOTE_PROVIDER=breeze")
    print(f"   BREEZE_API_KEY={api_key}")
    print("   BREEZE_API_SECRET=<your Breeze API Secret>")
    print(f"   BREEZE_SESSION_TOKEN={session_token}")
    print("\nThen build the symbol map (needs the three vars above set):")
    print("   python scripts/build_instrument_map.py --provider breeze")
    print("   INSTRUMENT_MAP_PATH=instruments.json")
    print("\nSession token expires by midnight IST — re-run this script each trading day.")


if __name__ == "__main__":
    main()
