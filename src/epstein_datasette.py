"""
epstein_datasette.py
====================
Search and query layer for DOJ Epstein EFTA documents via epstein-data.com's
Datasette REST API.

Datasette (https://datasette.io) exposes SQLite databases as a JSON API.
epstein-data.com indexes ~1.4M documents, ~2.8-2.9M pages across **20 databases**
(verified live 2026-08-24 via /-/databases.json — this release has grown over
time and the DOJ's total collection is larger still; re-verify before citing an
exact figure). Two layers are exposed here:

  1. Purpose-built helpers (search_by_sender_recipient*, fulltext_search*,
     get_document_by_efta) — ergonomic wrappers over the single most common
     table (full_text_corpus/doc_search: text + email metadata).
  2. Generic introspection + query (list_databases, list_tables, describe_table,
     query_table, run_sql) — reach any of the other 19 databases (images,
     transcripts, knowledge graph, OCR, handwriting, spreadsheets, depositions,
     concordance, native files, ...) without new code every time epstein-data.com
     adds or renames one. This is deliberate: hardcoding a wrapper per database
     is a maintenance trap that goes stale as the corpus evolves through 2031;
     the generic layer instead reflects whatever schema is live *right now*.

DATABASES AVAILABLE (verified live 2026-08-24 via /-/databases.json)
──────────────────────────────────────────────────────────────────────
  full_text_corpus, redaction_analysis_v2, image_analysis, knowledge_graph,
  communications, transcripts, ocr_database, spreadsheet_corpus,
  deposition_transcripts, handwriting_transcriptions, document_status,
  concordance_complete, secondary_stamps, native_files, search_index,
  page_classifications, email_metadata, report_mentions, external_mentions,
  related_docs
  (call list_databases() for the live, current list — this comment is a
  snapshot, not a contract; epstein-data.com can add/remove databases.)

HOW THIS MODULE WAS DISCOVERED
───────────────────────────────
1. DOJ /multimedia-search API found via JS bundle analysis but blocked by Akamai WAF
2. epstein-data.com page HTML contained comment "Kill Datasette chrome"
3. Datasette /-/databases.json confirmed 20 databases
4. full_text_corpus/doc_search table has: efta_number, sender, recipient,
   email_date, subject, search_text columns — exactly what we need
5. Datasette's SQL passthrough (GET /{database}.json?sql=...) is read-only by
   construction: a non-SELECT statement is rejected with HTTP 400 before it
   ever reaches SQLite (verified live 2026-08-24 with a CREATE TABLE probe),
   so run_sql() below carries no write/DDL risk against the third-party host.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional
import ast
import os
import time
import requests

# Overridable so a future change of mirror (domain move, epstein-data.com
# going away, a self-hosted replacement) doesn't require a code edit — just
# an environment variable. Defaults preserve today's behavior exactly.
_BASE = os.environ.get("EFTA_DATASETTE_BASE_URL", "https://epstein-data.com").rstrip("/")
_HEADERS = {
    "User-Agent": "Mozilla/5.0 Chrome/120.0",
    "Accept": "application/json",
}
_TIMEOUT = 30
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 1.5


class DatasetteError(RuntimeError):
    """Raised when the Datasette API returns a well-formed error response
    (e.g. a rejected non-SELECT statement) rather than a network failure."""


def _request_json(path: str, params: dict, timeout: int = _TIMEOUT) -> dict:
    """GET {_BASE}/{path} with a small retry/backoff for transient network
    failures (DNS blips, connection resets) — the raw `requests` calls this
    replaces had no retry at all, so a single dropped packet would surface
    as a hard tool failure instead of quietly succeeding on attempt 2."""
    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            r = requests.get(f"{_BASE}/{path}", params=params, headers=_HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def _get(path: str, params: dict) -> dict:
    """Row-query endpoints (…/table.json): force _shape=objects so rows come
    back as dicts, and preserve the caller's _size. Does not mutate `params`."""
    size = params.get("_size", 10)
    query = {k: v for k, v in params.items() if k != "_size"}
    query["_shape"] = "objects"
    query["_size"] = size
    return _request_json(path, query)


def _clean_person_field(value):
    """Normalize a sender/recipient field from the Datasette API.

    The API is documented to return these as JSON lists, but in practice
    upstream sometimes serializes them as the *Python repr* of a list
    (e.g. "['roger schank', None]") stored as a plain string. Detect that
    shape and safely parse it with ast.literal_eval so the raw repr syntax
    never leaks into user-facing output; otherwise fall back to the
    original (real-list or plain-string/None) handling.
    """
    if isinstance(value, list):
        return ", ".join(str(x) for x in value if x is not None)
    if isinstance(value, str) and value.startswith("[") and value.endswith("]"):
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value
        if isinstance(parsed, list):
            return ", ".join(str(x) for x in parsed if x is not None)
    return value


@dataclass
class EFTASearchResult:
    efta_number: str
    dataset: Optional[int]
    sender: Optional[str]
    recipient: Optional[str]
    email_date: Optional[str]
    subject: Optional[str]
    search_text: Optional[str]
    doc_type: Optional[str]

    @property
    def doj_url(self) -> str:
        from efta_core import efta_to_url
        try:
            return efta_to_url(self.efta_number)
        except Exception:
            return f"(non-EFTA id {self.efta_number}; no direct EFTA URL)"

    def snippet(self, chars: int = 200) -> str:
        return (self.search_text or "")[:chars]


@dataclass
class SearchPage:
    """One page of doc_search results plus the pagination metadata the plain
    list-returning search functions below silently discard (Datasette's JSON
    API reports the true total match count in `filtered_table_rows_count` and
    a `next` cursor for continuation — without these, a caller has no way to
    tell "10 of 10 shown" from "10 of 2,300 shown")."""
    results: list[EFTASearchResult]
    total: Optional[int]
    truncated: bool
    next_cursor: Optional[str]


@dataclass
class TablePage:
    """One page of raw rows from the generic query_table()/run_sql() tools.
    Unlike SearchPage, rows are plain dicts — the whole point of the generic
    layer is that it works against tables whose columns aren't known ahead
    of time (image captions, transcript text, knowledge-graph edges, ...)."""
    rows: list[dict]
    total: Optional[int]
    next_cursor: Optional[str]


def _rows_to_results(rows: list[dict]) -> list[EFTASearchResult]:
    results = []
    for row in rows:
        efta = row.get("efta_number", "")
        if not efta:
            continue
        recip = _clean_person_field(row.get("recipient"))
        sender = _clean_person_field(row.get("sender"))
        results.append(EFTASearchResult(
            efta_number   = efta,
            dataset       = row.get("dataset"),
            sender        = sender,
            recipient     = recip,
            email_date    = row.get("email_date"),
            subject       = row.get("subject"),
            search_text   = row.get("search_text"),
            doc_type      = row.get("doc_type"),
        ))
    return results


# ─────────────────────────────────────────────────────────────────────────────
#  PRIMARY SEARCH FUNCTIONS — the common case (full_text_corpus/doc_search)
# ─────────────────────────────────────────────────────────────────────────────

def search_by_sender_recipient(
    sender:    Optional[str] = None,
    recipient: Optional[str] = None,
    date_exact: Optional[str] = None,
    date_prefix: Optional[str] = None,
    subject:   Optional[str] = None,
    limit:     int = 20,
) -> list[EFTASearchResult]:
    """Filter doc_search table by sender/recipient/date/subject."""
    return search_by_sender_recipient_page(
        sender=sender, recipient=recipient, date_exact=date_exact,
        date_prefix=date_prefix, subject=subject, limit=limit,
    ).results


def search_by_sender_recipient_page(
    sender:      Optional[str] = None,
    recipient:   Optional[str] = None,
    date_exact:  Optional[str] = None,
    date_prefix: Optional[str] = None,
    subject:     Optional[str] = None,
    limit:       int = 20,
    cursor:      Optional[str] = None,
) -> SearchPage:
    """Same metadata filter as search_by_sender_recipient(), but returns the
    full SearchPage (true total match count, truncation flag, next-page
    cursor) instead of silently discarding everything past `limit` rows."""
    params: dict = {"_size": limit}
    if sender:
        params["sender__contains"] = sender
    if recipient:
        params["recipient__contains"] = recipient
    if date_exact:
        params["email_date"] = date_exact
    elif date_prefix:
        params["email_date__startswith"] = date_prefix
    if subject:
        params["subject__contains"] = subject
    if cursor:
        params["_next"] = cursor

    data = _get("full_text_corpus/doc_search.json", params)
    return SearchPage(
        results=_rows_to_results(data.get("rows", [])),
        total=data.get("filtered_table_rows_count"),
        truncated=bool(data.get("truncated")),
        next_cursor=data.get("next"),
    )


def fulltext_search(
    query: str,
    limit: int = 10,
    dataset_filter: Optional[int] = None,
) -> list[EFTASearchResult]:
    """Substring search over document text. The corpus table has no FTS index, so
    this filters on `search_text LIKE %query%` (phrase/substring match) — NOT
    tokenized full-text. For multi-term AND, use search_by_sender_recipient."""
    return fulltext_search_page(query, limit=limit, dataset_filter=dataset_filter).results


def fulltext_search_page(
    query: str,
    limit: int = 10,
    dataset_filter: Optional[int] = None,
    cursor: Optional[str] = None,
) -> SearchPage:
    """Same substring search as fulltext_search(), but returns the full
    SearchPage (true total match count, truncation flag, next-page cursor)
    instead of silently discarding everything past the first `limit` rows."""
    params: dict = {"search_text__contains": query, "_size": limit}
    if dataset_filter:
        params["dataset"] = dataset_filter
    if cursor:
        params["_next"] = cursor
    data = _get("full_text_corpus/doc_search.json", params)
    return SearchPage(
        results=_rows_to_results(data.get("rows", [])),
        total=data.get("filtered_table_rows_count"),
        truncated=bool(data.get("truncated")),
        next_cursor=data.get("next"),
    )


def get_document_by_efta(efta: str | int) -> Optional[EFTASearchResult]:
    """Retrieve metadata for a single document by EFTA number."""
    if isinstance(efta, int):
        efta = f"EFTA{efta:08d}"
    params = {"efta_number": efta, "_size": 1}
    data = _get("full_text_corpus/doc_search.json", params)
    rows = data.get("rows", [])
    return _rows_to_results(rows)[0] if rows else None


# ─────────────────────────────────────────────────────────────────────────────
#  GENERIC INTROSPECTION + QUERY — every database, every table, no hardcoding
# ─────────────────────────────────────────────────────────────────────────────

def list_databases() -> list[dict]:
    """Return every Datasette database on the instance: name, on-disk size,
    and (when reachable) the SHA-256 content hash Datasette publishes for
    integrity verification. This is the live source of truth for "what can
    be queried" — prefer it over the module docstring's snapshot list."""
    data = _request_json("-/databases.json", {})
    return [
        {"name": db.get("name"), "size": db.get("size"), "hash": db.get("hash")}
        for db in data
    ]


def list_tables(database: str) -> list[dict]:
    """Return every table in `database`: name, columns, row count, and
    whether it's a hidden internal table (FTS index shards etc. — usually
    not useful to query directly, included for completeness)."""
    data = _request_json(f"{database}.json", {})
    return [
        {
            "name":         t.get("name"),
            "columns":      t.get("columns", []),
            "count":        t.get("count"),
            "hidden":       t.get("hidden", False),
            "primary_keys": t.get("primary_keys", []),
        }
        for t in data.get("tables", [])
    ]


def describe_table(database: str, table: str) -> dict:
    """Column list and row count for one table — the minimum an agent needs
    before building a query_table() filter or a run_sql() query against a
    table it hasn't seen before."""
    data = _get(f"{database}/{table}.json", {"_size": 1})
    return {
        "database": database,
        "table":    table,
        "columns":  data.get("columns", []),
        "count":    data.get("filtered_table_rows_count") or data.get("total_table_rows_count"),
    }


def query_table(
    database: str,
    table: str,
    filters: Optional[dict[str, Any]] = None,
    limit: int = 20,
    cursor: Optional[str] = None,
) -> TablePage:
    """Filtered query against ANY table in ANY database, using Datasette's
    standard filter-suffix syntax — the same mechanism the purpose-built
    search functions above use internally, generalized to work regardless
    of what columns a table has. This is what makes every one of the 20
    databases (images, transcripts, knowledge graph, OCR, handwriting,
    depositions, ...) reachable without a new function per table.

    Args:
        database: Datasette database name (see list_databases())
        table:    table name within that database (see list_tables())
        filters:  Datasette filter-suffix dict, e.g.
                  {"caption__contains": "passport", "efta_number__startswith": "EFTA02"}
                  Supported suffixes: field, field__exact, field__contains,
                  field__startswith, field__endswith, field__gt/gte/lt/lte,
                  field__isnull, field__notnull, field__in (comma-separated).
        limit:    max rows per page (Datasette enforces its own server-side cap)
        cursor:   continuation token from a previous TablePage.next_cursor
    """
    params: dict = dict(filters or {})
    params["_size"] = limit
    if cursor:
        params["_next"] = cursor
    data = _get(f"{database}/{table}.json", params)
    return TablePage(
        rows=data.get("rows", []),
        total=data.get("filtered_table_rows_count"),
        next_cursor=data.get("next"),
    )


def run_sql(database: str, sql: str, params: Optional[dict[str, Any]] = None, limit: int = 1000) -> dict:
    """Arbitrary read-only SQL against one database — the "complete query"
    escape hatch for anything the filter-suffix API can't express (joins
    across tables, aggregation, GROUP BY, complex boolean logic).

    Safety: Datasette itself only accepts SELECT statements through this
    endpoint — a non-SELECT is rejected with HTTP 400 before it reaches
    SQLite (verified live 2026-08-24 with a CREATE TABLE probe). The
    client-side check below is defense-in-depth for a clearer error message,
    not the actual security boundary; that boundary is the third-party
    server's, same as it is for anyone browsing epstein-data.com directly.

    Args:
        database: Datasette database name (see list_databases())
        sql:      a single SELECT statement. Use :name placeholders for
                  values, e.g. "select * from doc_search where dataset = :ds"
        params:   values for the :name placeholders in `sql`
        limit:    row cap Datasette applies via row_limit (still bounded by
                  the server's own hard cap regardless of what's requested)

    Returns:
        {"columns": [...], "rows": [[...], ...], "truncated": bool, "query_ms": float}
    """
    stripped = sql.strip().lstrip("(").strip()
    if not stripped[:6].upper().startswith("SELECT"):
        raise DatasetteError(
            "run_sql only accepts a SELECT statement — Datasette's own API "
            "rejects anything else, but checking here gives a clearer error."
        )
    # Datasette maps a :name placeholder in `sql` to a bare `?name=value`
    # query-string parameter (verified live 2026-08-24: ":ds" resolved via
    # a plain "&ds=9"). No prefix, no escaping needed — Datasette parameterizes
    # the query itself, so this is not string-interpolated into the SQL text.
    query: dict[str, Any] = {"sql": sql, "_size": limit, **(params or {})}
    data = _request_json(f"{database}.json", query)
    if data.get("ok") is False:
        raise DatasetteError(data.get("error") or "query rejected by Datasette")
    return {
        "columns":   data.get("columns", []),
        "rows":      data.get("rows", []),
        "truncated": bool(data.get("truncated")),
        "query_ms":  data.get("query_ms"),
    }


if __name__ == "__main__":
    print("=== DATASETTE SEARCH DEMO ===\n")

    print("1. Roger Schank shipping futures email (Oct 23, 2009):")
    for r in search_by_sender_recipient(sender="epstein", recipient="schank", date_exact="2009-10-23"):
        print(f"   {r.efta_number}  DS{r.dataset}  {r.email_date}  [{r.subject or 'no subject'}]")
        if r.search_text and "goyim" in r.search_text.lower():
            print(f"   CONFIRMED SHIPPING EMAIL: {r.snippet(100)}")
        print(f"   URL: {r.doj_url}")

    print("\n2. Databases available:")
    for db in list_databases():
        print(f"   {db['name']}")

    print("\n3. Tables in image_analysis (generic introspection):")
    for t in list_tables("image_analysis"):
        if not t["hidden"]:
            print(f"   {t['name']}  ({t['count']} rows)  columns={t['columns']}")

    print("\n4. Generic query_table() against image_analysis.images:")
    page = query_table("image_analysis", "images", limit=3)
    for row in page.rows:
        print(f"   {row}")
    print(f"   ({len(page.rows)} of {page.total} total)")
