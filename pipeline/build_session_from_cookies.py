#!/usr/bin/env python3
"""Build x_session.json (Playwright storage_state) from cookies exported by a
browser where you're already logged into X.

Use this when the automated Chromium can't log in (e.g. Google OAuth blocks it).
Export your x.com cookies from Opera/Chrome/Edge with a cookie-export extension,
then run:

    py -3 build_session_from_cookies.py cookies.json
    py -3 build_session_from_cookies.py cookies.txt --out x_session.json

Accepts either:
  * Cookie-Editor / EditThisCookie JSON export (an array of cookie objects), or
  * a Netscape 'cookies.txt' file (Get cookies.txt LOCALLY).

Only cookies for x.com / twitter.com are kept. The important ones are
auth_token, ct0 and twid — if those are present you're logged in.
"""
import argparse
import json
import sys

WANT_DOMAINS = ("x.com", "twitter.com")
_SAMESITE = {"no_restriction": "None", "unspecified": "Lax", "none": "None",
             "lax": "Lax", "strict": "Strict", None: "Lax", "": "Lax"}


def _keep(domain):
    d = (domain or "").lstrip(".").lower()
    return any(d == w or d.endswith("." + w) for w in WANT_DOMAINS)


def _samesite(v):
    if isinstance(v, str):
        return _SAMESITE.get(v.lower(), "Lax")
    return _SAMESITE.get(v, "Lax")


def _expires(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return -1


def from_json(raw):
    data = json.loads(raw)
    if isinstance(data, dict) and "cookies" in data:   # already storage_state-ish
        data = data["cookies"]
    out = []
    for c in data:
        if not _keep(c.get("domain")):
            continue
        out.append({
            "name": c.get("name"),
            "value": c.get("value", ""),
            "domain": c.get("domain"),
            "path": c.get("path", "/"),
            "expires": _expires(c.get("expirationDate", c.get("expires", -1))),
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure": bool(c.get("secure", True)),
            "sameSite": _samesite(c.get("sameSite")),
        })
    return out


def from_netscape(raw):
    out = []
    for line in raw.splitlines():
        if not line.strip() or line.startswith("#"):
            # '#HttpOnly_' prefixed lines are still data
            if not line.startswith("#HttpOnly_"):
                continue
        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line[len("#HttpOnly_"):]
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, _flag, path, secure, expires, name, value = parts
        if not _keep(domain):
            continue
        out.append({
            "name": name, "value": value, "domain": domain, "path": path or "/",
            "expires": _expires(expires), "httpOnly": http_only,
            "secure": secure.upper() == "TRUE", "sameSite": "Lax",
        })
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("infile", help="cookies.json or cookies.txt exported from your browser")
    ap.add_argument("--out", default="x_session.json")
    args = ap.parse_args(argv)

    raw = open(args.infile, "r", encoding="utf-8").read().strip()
    cookies = from_json(raw) if raw[:1] in "[{" else from_netscape(raw)

    if not cookies:
        print("No x.com / twitter.com cookies found in that export. "
              "Make sure you exported while on x.com.", file=sys.stderr)
        return 1

    names = {c["name"] for c in cookies}
    have = [n for n in ("auth_token", "ct0", "twid") if n in names]
    state = {"cookies": cookies, "origins": []}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    print(f"Wrote {args.out} with {len(cookies)} cookie(s).")
    print("Key auth cookies present:", ", ".join(have) if have else "NONE (!)")
    if "auth_token" not in names:
        print("WARNING: no auth_token — you likely aren't logged in / didn't export from x.com.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
