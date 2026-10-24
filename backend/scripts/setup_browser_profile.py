"""One-time setup for a TinyFish Browser Context Profile: a saved, signed-in session so live
checks run as a returning logged-in visitor instead of a fresh anonymous one every time.

``BrowserProfile.STEALTH`` is already on for every live check (tinyfish_client.py); this script
fills the other half of "look like a real visitor" — a signed-in session for ``use_profile``.

TinyFish only lets a *person* sign in through a remote browser it opens (there is no API to
upload cookies exported from your own browser — that would also bind the session to the wrong
IP/device fingerprint and look like account takeover to the platform's own fraud checks). So
this script is interactive: it opens the session, you log in once by hand, it saves the result.

Run from backend/ (uses one TinyFish browser-minute; needs TINYFISH_API_KEY):

    python -m scripts.setup_browser_profile --platform zepto
    python -m scripts.setup_browser_profile --platform instamart
    python -m scripts.setup_browser_profile --platform blinkit --proxy-country US

Use a dedicated team test account, never a real seller's personal login — the agent goals are
read-only (they never add to cart or check out), but a signed-in session should still be a
account made for this purpose. Afterwards, put the printed profile id into the matching
TINYFISH_PROFILE_<PLATFORM> variable in backend/.env and restart the backend.

Exit codes: 0 = profile saved, 1 = setup failed or was cancelled, 2 = configuration problem.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx
from tinyfish import AsyncTinyFish

from app.config import get_settings
from app.services.tinyfish.tinyfish_client import AGENT_REST_URL, FLOWS

PLATFORM_DOMAIN = {
    "blinkit": "blinkit.com",
    "zepto": "zepto.com",
    "instamart": "swiggy.com",
}
SETUP_TIMEOUT_SECONDS = 600  # 10 minutes to log in by hand (OTP, CAPTCHA, etc. included)


async def create_profile(api_key: str, name: str, proxy_country: str | None) -> str:
    """POST /v1/profiles: not yet wrapped by the SDK, so called directly."""
    body = {"name": name, "set_as_default": False}
    if proxy_country:
        body["proxy_country_code"] = proxy_country
    async with httpx.AsyncClient(base_url=AGENT_REST_URL, timeout=30.0) as client:
        response = await client.post(
            "/v1/profiles", json=body, headers={"X-API-Key": api_key}
        )
        response.raise_for_status()
        return response.json()["id"]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--platform", required=True, choices=sorted(FLOWS))
    parser.add_argument(
        "--name", help="Profile display name (default: 'shelfsense-<platform>')"
    )
    parser.add_argument(
        "--proxy-country",
        choices=["US", "GB", "CA", "DE", "FR", "JP", "AU"],
        help="TinyFish proxy exit country for this profile (omit for TinyFish's default network; "
        "India is not one of the supported countries, so Indian apps are usually left unset)",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.tinyfish_api_key:
        print("TINYFISH_API_KEY is not set.", file=sys.stderr)
        return 2

    name = args.name or f"shelfsense-{args.platform}"
    sdk = AsyncTinyFish(api_key=settings.tinyfish_api_key, timeout=30.0)

    print(f"Creating profile {name!r}...")
    profile_id = await create_profile(settings.tinyfish_api_key, name, args.proxy_country)
    print(f"Profile id: {profile_id}")

    home_url = FLOWS[args.platform].home_url
    session = await sdk.profiles.setup.start(
        profile_id, url=home_url, timeout_seconds=SETUP_TIMEOUT_SECONDS
    )
    print()
    print("=" * 72)
    print(f"Open this link in your own browser and sign in to {args.platform}:")
    print(f"  {session.base_url}")
    print("Use a dedicated test account, not a real seller's personal login.")
    print(f"You have {SETUP_TIMEOUT_SECONDS // 60} minutes before this session times out.")
    print("=" * 72)

    try:
        input("\nPress Enter here once you're signed in (Ctrl+C to cancel without saving)... ")
    except KeyboardInterrupt:
        print("\nCancelling, nothing saved.")
        await sdk.profiles.setup.cancel(profile_id, session_id=session.session_id)
        return 1

    result = await sdk.profiles.setup.save(
        profile_id,
        session_id=session.session_id,
        signed_in_sites=[PLATFORM_DOMAIN[args.platform]],
    )
    print()
    print(f"Saved: {result.cookie_count} cookie(s) across {len(result.domains_updated)} domain(s).")
    if result.sign_in is not None:
        print(f"Sign-in detected on {result.sign_in.site}: {result.sign_in.status}")
    if result.domains_failed:
        print(f"Warning: failed to save for {result.domains_failed}", file=sys.stderr)
    if result.cookie_count == 0:
        print(
            "No cookies were saved — the sign-in may not have completed before you pressed Enter.",
            file=sys.stderr,
        )
        return 1

    env_var = f"TINYFISH_PROFILE_{args.platform.upper()}"
    print()
    print("Add this to backend/.env, then restart the backend:")
    print(f"  {env_var}={profile_id}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
