---
name: efta-research
description: "This skill should be used when the user asks to find an Epstein file, look up an EFTA number, search DOJ Epstein documents by sender/recipient/date or full text, identify a specific email or document from a screenshot, verify a DOJ document URL, or understand the EFTA numbering system and DataSet structure. Trigger on: \"find epstein file\", \"EFTA number\", \"DOJ epstein search\", \"jeevacation email\", \"epstein files\", any mention of specific people + epstein (Rothschild, Gates, Schank, etc.), \"justice.gov/epstein\", \"multimedia-search\", \"epstein-data.com\", \"DataSet 9\" or any DataSet reference. Also trigger when shown a screenshot of an Epstein email and asked to find the source document."
version: 1.0.0
---

# EFTA Document Research Skill

## Purpose

Find specific documents in the **~2.8M-page (~1.4M-document) DOJ Epstein EFTA release** efficiently
(figures verified against epstein-data.com's live stats 2026-08-24 — re-verify before citing, this
release has grown over time and DOJ's total collection is larger still, ~6M pages).

EFTA = Epstein Files Transparency Act (Public Law 119-38, signed Nov 19 2025).
DOJ released files in 12 DataSets at `https://www.justice.gov/epstein`.

---

## Critical Facts

### EFTA Numbers Are PAGE Numbers, Not Document Numbers
A 10-page PDF consumes 10 consecutive EFTA numbers.
`EFTA00741068` = page 741,068 of the entire release corpus.

### DataSet Mapping (verified per-file ranges)

Source: forensic `rhowardstone/Epstein-research-data` mapping, cross-checked against the DOJ
disclosure pages. EFTA numbers are page (Bates) ids; small inter-DataSet gaps exist.

| DataSet | EFTA Range            | Contents                        |
|---------|-----------------------|---------------------------------|
| DS01    | 1 – 3,158             | Photos, physical scans          |
| DS02    | 3,159 – 3,857         | Photos, seized scans            |
| DS03    | 3,858 – 5,586         | Grand jury exhibits             |
| DS04    | 5,705 – 8,320         | Records, court filings          |
| DS05    | 8,409 – 8,528         | Seized scans, depositions       |
| DS06    | 8,529 – 8,998         | Depositions, indictments        |
| DS07    | 9,016 – 9,664         | Transcripts                     |
| DS08    | 9,676 – 39,023        | Emails, police reports          |
| **DS09**| **39,025 – 1,262,781**| **★ Main email corpus**         |
| DS10    | 1,262,782 – 2,205,654 | Emails, financial               |
| DS11    | 2,205,655 – 2,730,264 | Emails, device data             |
| DS12    | 2,730,265 – 2,858,497 | Court filings, FBI + expansion  |

### DOJ URL Pattern
```
https://www.justice.gov/epstein/files/DataSet%20{N}/EFTA{08d}.pdf
```

---

## Research Methodology

### Step 1 — Identify What You're Looking For
Collect from the user or screenshot:
- Date (YYYY-MM-DD)
- Sender (partial name or email OK)
- Recipient (partial name OK)  
- Subject line (may be blank)
- Key words from body text
- Time in email header (helps disambiguate multiple emails same date)

### Step 2 — Query epstein-data.com Datasette API (PRIMARY METHOD)

The Datasette API is the most reliable search method.
The DOJ's own `/multimedia-search` API is blocked by Akamai WAF for headless clients.

**Filter by metadata** (fastest):
```python
# Example: find Roger Schank emails Oct 23, 2009
GET https://epstein-data.com/full_text_corpus/doc_search.json
  ?sender__contains=epstein
  &recipient__contains=schank
  &email_date=2009-10-23
  &_shape=objects
  &_size=20
```

**Full-text search** (when metadata unknown):
```python
GET https://epstein-data.com/full_text_corpus/doc_search.json
  ?search_text__contains=shipping+futures+goyim
  &_shape=objects
  &_size=10
```
Note: `_search=` is silently ignored (no FTS index). Use `search_text__contains=` for real
`WHERE search_text LIKE %query%` filtering.

**Available filter suffixes** (Datasette standard):
- `field__contains`    — partial match (case-insensitive)
- `field__exact`       — exact match
- `field__startswith`  — prefix match
- `field`              — exact match (shorthand)

**Key columns in `full_text_corpus/doc_search`**:
```
efta_number, sender, recipient, email_date, subject,
search_text, dataset, doc_type, stamp_type,
epstein_is_sender, has_attachments
```

### Step 3 — Cross-Reference Multiple Copies

The same email often appears in multiple EFTA numbers (OCR duplicates, forwarded copies).
Compare timestamps to find the primary copy:
- Earliest EFTA number in the same DataSet = primary
- Other DataSets = copies from different processing batches

**Roger Schank example (confirmed)**:
```
EFTA00741068  DS9  12:01:12  PRIMARY (exact match to screenshot)
EFTA00885615  DS9  12:01:12  Duplicate (OCR reads 'grnail.com')
EFTA01821140 DS10  12:01:12  Third copy
```

### Step 4 — Construct DOJ URL

```python
def efta_to_url(efta: int) -> str:
    ds = get_dataset(efta)   # from DataSet boundary table
    return f"https://www.justice.gov/epstein/files/DataSet%20{ds}/EFTA{efta:08d}.pdf"
```

### Step 5 — Verify URL is Live

```bash
curl -I "https://www.justice.gov/epstein/files/DataSet%209/EFTA00741068.pdf"
# Expect: HTTP/2 200 or 302 -> PDF
```

**DOJ Bot Protection**: justice.gov gates every PDF behind an age-verify + Akamai
challenge, so a raw HTTP status can't reliably distinguish a live file from a missing one.
Trust the verified DataSet boundary table + the third-party index for URL correctness — not HEAD probes.

---

## Known Verified Documents

### schank_shipping — Roger Schank Email (Oct 23, 2009)
**PRIMARY**: `EFTA00741068` -> DS9
```
https://www.justice.gov/epstein/files/DataSet%209/EFTA00741068.pdf
```
Content: "This is the way the jew make money.. and made a fortune in the past ten years,, selling short the shippping futures,, let the goyim deal in the real world."
Found via: epstein-data.com Datasette `?sender__contains=epstein&recipient__contains=schank&email_date=2009-10-23`

### rothschild_ukraine — Ariane de Rothschild / Ukraine (Mar 18, 2014)
**PRIMARY**: `EFTA01930285` -> DS10
```
https://www.justice.gov/epstein/files/DataSet%2010/EFTA01930285.pdf
```
Content: "ukraine upheaval should provide many opportunites, many"
Fact-check: EuvsDisinfo confirmed word is "upheaval" NOT "coup"

### pizza — Harry Fisch / Pizza & Grape Soda Thread (2018)
**Range**: `EFTA01616214–EFTA01616235` -> DS10 (22 pages)
Fact-check: Epstein Exposed (2026) confirmed LITERAL FOOD discussion between Epstein and Dr. Harry Fisch (NYC urologist)

### bill_gates — BGC3 Pandemic Simulation Document (Mar 3, 2017)
`EFTA02381427` -> DS11  
`EFTA02657725` -> DS11
Fact-check: Tempo, Fact Crescendo, Reuters — legitimate global health planning, NO COVID connection.

---

## Authentication (for downloading PDFs)

See the `doj-auth` skill for full details. Brief summary:

### Layer 1: SHA256 Cookie Challenge
```python
import hashlib, re, requests

r = requests.get("https://www.justice.gov/epstein/search")
salt  = re.search(r'public_salt\s*=\s*"([^"]+)"', r.text).group(1)
cands = re.search(r'candidates\s*=\s*"([^"]+)"\.split', r.text).group(1).split("/")
auth1 = hashlib.sha256((salt + cands[0]).encode()).hexdigest().upper()
auth2 = hashlib.sha256((salt + cands[1]).encode()).hexdigest().upper()
session.cookies.set("authorization_1", auth1, domain="www.justice.gov")
session.cookies.set("authorization_2", auth2, domain="www.justice.gov")
```

### Why /multimedia-search Is Blocked
The DOJ search API (`/multimedia-search?keys=QUERY`) requires Akamai's `_abck` cookie,
which is computed by JavaScript browser fingerprinting. Headless clients cannot generate it.
**Use epstein-data.com Datasette instead** — it has the same data, fully indexed, no auth.

---

## Third-Party Research Tools

| Tool | URL | Description |
|------|-----|-------------|
| epstein-data.com | https://epstein-data.com/search | Datasette — ~1.4M docs, substring search (no FTS index) |
| Jmail | https://jmail.world | Gmail-style email browser |
| EpsteinExposed | https://epsteinexposed.com | Cross-referenced database |
| epstein.academy | https://epstein.academy | Kevin Bass Gates compendium |
| DOJ Library | https://www.justice.gov/epstein | Official source |

---

## Common Mistakes to Avoid

1. **EFTA numbers are pages, not documents** — a 10-page PDF = 10 EFTA numbers
2. **Multiple copies exist** — same email often in DS9, DS10, DS11 separately
3. **"pizza" = 233 results as of 2026-08-24 (moves as the corpus grows — use efta_search's live
   total, don't trust this number), mostly literal food** — don't claim code without evidence
4. **"goyim/coup" emails** — Epstein wrote "upheaval" not "coup"; confirm before citing
5. **Gates/COVID** — BGC3 pandemic simulation document is legitimate health work, NOT COVID planning
6. **DOJ search returns 403 for headless XHR** — use epstein-data.com instead

---

## MCP Tools (epstein-files-plugin)

When the Epstein Files Plugin's MCP server is running, 11 read-only tools are available:

**Purpose-built** (full_text_corpus/doc_search — the common case):
```
efta_search(query, limit, cursor)   — substring search across ~1.4M docs, with total-count + paging
efta_filter_email(sender, recipient, date_exact, date_prefix, subject, limit, cursor)
efta_known_docs(category)           — pre-verified documents
efta_get_url(efta_number)           — EFTA -> DOJ URL
efta_verify_url(efta_number)        — check if URL is live
efta_lookup(efta_number)            — full metadata from Datasette
```

**Generic** (every one of the 20 Datasette databases — images, transcripts, OCR, handwriting,
depositions, the knowledge graph, and more — no dedicated tool needed per table):
```
efta_list_databases()                                   — all 20 databases, live
efta_list_tables(database)                               — tables + columns + row counts in one database
efta_describe_table(database, table)                      — columns + row count for one table
efta_query_table(database, table, filters, limit, cursor) — filter-suffix query against any table
efta_run_sql(database, sql, params, limit)                — read-only SQL: joins, aggregation, GROUP BY
```
Use the generic tools whenever a question isn't about the main email corpus — e.g. "find an image
showing X", "how many documents per DataSet", "search the knowledge graph for entity Y". Call
`efta_list_databases()`/`efta_list_tables()` first if you don't already know the schema.

---

## Quick Reference: Finding a Screenshot Email

When shown a screenshot of an Epstein email:

1. Read: **From**, **To**, **Date**, **Subject**, key body words
2. Build Datasette query: `?sender__contains=X&recipient__contains=Y&email_date=YYYY-MM-DD`
3. If multiple blank-subject matches: compare exact HH:MM:SS timestamp
4. Verify: `GET DOJ_URL` returns PDF content
5. Report: primary EFTA, dataset, DOJ URL, any duplicate copies
