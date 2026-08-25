---
name: doj-auth
description: "This skill should be used when the user needs to download or verify a DOJ EFTA PDF, access justice.gov/epstein programmatically, or understand why the DOJ multimedia-search API returns 403 for headless requests. Trigger on: \"DOJ blocked\", \"access denied justice.gov\", \"download EFTA PDF\", \"akamai bot\", \"SHA256 cookie\", \"authorization cookie\", \"multimedia-search 403\"."
version: 1.0.0
---

# DOJ Authentication Bypass

## Overview

`www.justice.gov/epstein` is protected by two bot-protection layers:

```
Layer 1: SHA256 cookie challenge (custom DOJ mechanism)
Layer 2: Akamai Bot Manager proof-of-work interstitial
Layer 3: Akamai _abck fingerprint (JS-only — blocks /multimedia-search API)
```

## Layer 1: SHA256 Cookie Challenge

On first GET to any `justice.gov` page, the server returns a challenge page with:

```javascript
var public_salt = "XXXXXXXX";
var candidates = "HASH1/HASH2".split("/");
// Authorization requires:
// authorization_1 = SHA256(salt + candidates[0]).toUpperCase()
// authorization_2 = SHA256(salt + candidates[1]).toUpperCase()
```

**Python solution:**
```python
import hashlib, re, requests

r = session.get("https://www.justice.gov/epstein/search")
salt  = re.search(r'public_salt\s*=\s*"([^"]+)"', r.text).group(1)
cands = re.search(r'candidates\s*=\s*"([^"]+)"\.split', r.text).group(1).split("/")
auth1 = hashlib.sha256((salt + cands[0]).encode()).hexdigest().upper()
auth2 = hashlib.sha256((salt + cands[1]).encode()).hexdigest().upper()
session.cookies.set("authorization_1", auth1, domain="www.justice.gov")
session.cookies.set("authorization_2", auth2, domain="www.justice.gov")
```

## Layer 2: Akamai Proof-of-Work

After the SHA256 cookies are set, the next request serves an Akamai interstitial:

```javascript
var i = 1781077206;
var j = i + Number("7372" + "15460");
// POST: { "bm-verify": TOKEN, "pow": j }
```

**Python solution:**
```python
r2  = session.get("https://www.justice.gov/epstein/search")
bm  = re.search(r'"bm-verify":\s*"([^"]+)"', r2.text).group(1)
i   = int(re.search(r'var i\s*=\s*(\d+)', r2.text).group(1))
ab, bb = re.search(r'Number\("(\d+)"\s*\+\s*"(\d+)"\)', r2.text).groups()
n   = int(ab + bb)
pow_val = i + n

session.post(
    "https://www.justice.gov/_sec/verify?provider=interstitial",
    json={"bm-verify": bm, "pow": pow_val},
    headers={"Content-Type": "application/json"}
)
# Follow the redirect URL from the interstitial page
```

## What the Auth Gives You

✅ Access to all `/epstein/files/DataSet%20N/EFTA*.pdf` direct downloads  
✅ Navigation through the Epstein Library pages  
❌ Access to `/multimedia-search?keys=QUERY` (blocked by `_abck` cookie)

## Why /multimedia-search Is Blocked

The DOJ search API (`/multimedia-search`) is the backend for the JavaScript
search widget on the page. Akamai's WAF only allows XHR to this endpoint when
the `_abck` cookie is present. This cookie is computed by JavaScript running in
a real browser that collects:
- Screen resolution, color depth
- Timezone, language
- Browser plugins
- Mouse movement patterns

**There is no way to generate `_abck` without running JavaScript in a real browser.**

## Alternative: epstein-data.com Datasette

Use `GET https://epstein-data.com/full_text_corpus/doc_search.json?search_text__contains=QUERY`
instead. Same data, no authentication required.
Note: the corpus has **no FTS index**; `_search=` is silently ignored. Use
`search_text__contains=` for real substring filtering.
