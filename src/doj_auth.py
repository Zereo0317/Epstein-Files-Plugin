"""
doj_auth.py
===========
Solve the two-layer bot-protection on www.justice.gov to obtain an
authenticated session capable of reaching the real Epstein Library pages.

Layer 1 — SHA256 cookie challenge (custom DOJ mechanism)
Layer 2 — Akamai Bot Manager interstitial with proof-of-work

The multimedia-search API (/multimedia-search?keys=QUERY) also requires
Akamai's _abck JavaScript fingerprint cookie, which cannot be computed
without a real browser. Use epstein-data.com Datasette instead for search.
"""

from __future__ import annotations
import hashlib
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).parent))
from efta_core import DOJ_ROOT as _DOJ  # single source of truth for the DOJ domain

_SEARCH_PAGE = f"{_DOJ}/epstein/search"
_VERIFY = f"{_DOJ}/_sec/verify?provider=interstitial"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
}


def _solve_sha256(session: requests.Session, html: str) -> bool:
    """Extract and set SHA256 auth cookies from challenge page."""
    salt_m  = re.search(r'public_salt\s*=\s*"([^"]+)"', html)
    cands_m = re.search(r'candidates\s*=\s*"([^"]+)"\.split', html)
    if not (salt_m and cands_m):
        return False
    salt   = salt_m.group(1)
    cands  = cands_m.group(1).split("/")
    auth1  = hashlib.sha256((salt + cands[0]).encode()).hexdigest().upper()
    auth2  = hashlib.sha256((salt + cands[1]).encode()).hexdigest().upper()
    session.cookies.set("authorization_1", auth1, domain="www.justice.gov")
    session.cookies.set("authorization_2", auth2, domain="www.justice.gov")
    return True


def _solve_akamai_pow(session: requests.Session, html: str) -> Optional[str]:
    """
    Solve Akamai PoW, POST the token, and return the redirect URL.
    Returns None if the challenge fields are not found.
    """
    bm_m = re.search(r'"bm-verify":\s*"([^"]+)"', html)
    pi_m = re.search(r'var i\s*=\s*(\d+)', html)
    pn_m = re.search(r'Number\("(\d+)"\s*\+\s*"(\d+)"\)', html)
    if not (bm_m and pi_m and pn_m):
        return None

    bm_token = bm_m.group(1)
    i        = int(pi_m.group(1))
    n        = int(pn_m.group(1) + pn_m.group(2))
    pow_val  = i + n

    session.post(
        _VERIFY,
        json={"bm-verify": bm_token, "pow": pow_val},
        headers={"Content-Type": "application/json",
                 "Referer": _SEARCH_PAGE},
        timeout=20,
    )

    redir_m = re.search(r"URL='([^']+)'", html)
    return (_DOJ + redir_m.group(1)) if redir_m else _SEARCH_PAGE


def get_authenticated_session(retries: int = 2) -> requests.Session:
    """
    Return a requests.Session with DOJ auth cookies set.

    This session can:
      - Fetch any https://www.justice.gov/epstein/files/DataSet%20N/EFTA*.pdf
      - Navigate the Epstein Library pages
      - NOT call /multimedia-search (requires JS fingerprint _abck cookie)

    Use epstein_datasette.py for full-text search instead.
    """
    for attempt in range(retries):
        try:
            session = requests.Session()
            session.headers.update(_HEADERS)

            r1 = session.get(_SEARCH_PAGE, timeout=20)
            if not _solve_sha256(session, r1.text):
                raise RuntimeError("SHA256 challenge page not found")

            r2 = session.get(_SEARCH_PAGE, timeout=20)
            redirect_url = _solve_akamai_pow(session, r2.text)

            if redirect_url:
                session.get(redirect_url, timeout=20)

            cookie_keys = list(session.cookies.keys())
            if "authorization_1" not in cookie_keys:
                raise RuntimeError("Auth cookies missing after challenge")

            return session

        except Exception as exc:
            if attempt >= retries - 1:
                raise
            # stderr, never stdout: this module is imported by mcp_server.py,
            # an MCP *stdio* server — anything written to stdout corrupts the
            # JSON-RPC framing and breaks the whole connection. This path
            # isn't reachable from the MCP server today (only
            # verify_pdf_accessible() is imported there, which never calls
            # get_authenticated_session()), but a future tool wiring this in
            # without noticing the original stdout print would have silently
            # broken the server on its very first retry.
            print(f"[doj_auth] Retry {attempt+1}/{retries} after: {exc}", file=sys.stderr)
            time.sleep(2)

    raise RuntimeError("Failed to obtain DOJ session")


def verify_pdf_accessible(efta_url: str, session: Optional[requests.Session] = None) -> tuple[bool, int]:
    """HEAD-check a DOJ PDF URL. Returns (accessible, http_status_code)."""
    s = session or requests.Session()
    s.headers.update(_HEADERS)
    try:
        r = s.head(efta_url, timeout=20, allow_redirects=True)
        return r.status_code == 200, r.status_code
    except requests.RequestException:
        return False, -1


def download_pdf(efta_url: str, dest_path: str,
                 session: Optional[requests.Session] = None) -> bool:
    """Download a DOJ PDF to dest_path. Returns True on success."""
    import pathlib
    s = session or get_authenticated_session()
    try:
        r = s.get(efta_url, timeout=60, stream=True)
        if r.status_code != 200:
            return False
        pathlib.Path(dest_path).write_bytes(r.content)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    print("Testing DOJ auth...")
    sess = get_authenticated_session()
    print(f"Cookies: {list(sess.cookies.keys())}")

    test_url = "https://www.justice.gov/epstein/files/DataSet%209/EFTA00741068.pdf"
    ok, code = verify_pdf_accessible(test_url, sess)
    print(f"\nTest PDF (Roger Schank email): HTTP {code} — {'accessible' if ok else 'blocked'}")
    print(f"URL: {test_url}")
