#!/usr/bin/env python3
"""
mcp_server.py
=============
FastMCP server that exposes EFTA research capabilities as MCP tools.

Tools exposed (11 total, all read-only):
  Purpose-built (the common case — full_text_corpus/doc_search):
    efta_search          — Substring search across ~1.4M documents, with total-count + paging
    efta_filter_email     — Filter by sender/recipient/date/subject, with total-count + paging
    efta_known_docs        — List pre-verified, fact-checked known documents
    efta_get_url          — Convert an EFTA number -> official DOJ PDF URL
    efta_verify_url        — HEAD-check whether a DOJ PDF URL is live
    efta_lookup            — Full document metadata from the Datasette index

  Generic (every one of the 20 Datasette databases, no hardcoding per table):
    efta_list_databases    — List every Datasette database (images, transcripts, OCR, ...)
    efta_list_tables       — List every table in one database, with columns + row counts
    efta_describe_table    — Column list + row count for one table
    efta_query_table       — Filter-suffix query against any table, with total-count + paging
    efta_run_sql           — Arbitrary read-only SQL against one database (joins, aggregation, ...)

Run standalone:
  python mcp_server.py

Install as Claude Code MCP:
  Add to .mcp.json:
  {
    "epstein-files-plugin": {
      "type": "stdio",
      "command": "python",
      "args": ["PATH_TO/mcp_server.py"]
    }
  }
"""

import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).parent))

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
except ImportError:
    print("MCP SDK not installed. Run: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

from efta_core         import (KNOWN_DOCUMENTS, get_by_category, efta_to_url,
                                get_dataset, all_categories)
from epstein_datasette  import (search_by_sender_recipient_page, fulltext_search_page,
                                 get_document_by_efta, list_databases, list_tables,
                                 describe_table, query_table, run_sql, DatasetteError)
from doj_auth           import verify_pdf_accessible

# All 11 tools are read-only: none of them create, modify, or delete anything.
# efta_known_docs / efta_get_url are pure local computation (no network call);
# everything else reaches epstein-data.com or justice.gov, so openWorldHint=True.
_LOCAL_READONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
_REMOTE_READONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)

mcp = FastMCP("epstein-files-plugin")


def _page_footer(total: Optional[int], shown: int, next_cursor: Optional[str]) -> list[str]:
    """Shared truncation/pagination notice for every paged tool below.
    Without this, a query matching e.g. 233 documents silently returns the
    first `limit` with no indication ~200 more exist or how to reach them.

    NOTE: Datasette's own `truncated` field does NOT mean "more pages exist"
    (confirmed empirically: a 233-total/3-shown query still reported
    truncated=false) — it flags something else internal to the query engine.
    "More results" must be inferred from total vs. shown count instead.
    """
    out = []
    has_more = total is not None and total > shown
    if total is not None:
        out.append(f"  ({shown} of {total} total match(es) shown)")
    if has_more and next_cursor:
        out.append(f"  More results available — call again with cursor={next_cursor!r} to continue.")
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  PURPOSE-BUILT TOOLS — the common case (full_text_corpus/doc_search)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool(annotations=_REMOTE_READONLY)
def efta_search(query: str, limit: int = 10, cursor: str = "") -> str:
    """
    Substring search across ~1.4M DOJ Epstein documents via the epstein-data.com
    Datasette API (search_text LIKE %query%). The corpus has no FTS index, so this
    is phrase/substring search, not tokenized full-text.

    Returns EFTA numbers, senders, recipients, dates, subjects, and DOJ URLs, plus
    the true total match count and a cursor for paging past the first `limit`.
    For anything this can't express (images, transcripts, joins, aggregation),
    see efta_query_table / efta_run_sql.

    Args:
        query: Search terms (e.g. "roger schank shipping goyim")
        limit: Maximum results to return (default 10, max 50)
        cursor: Continuation cursor from a previous call's "More results available" notice
    """
    limit = min(limit, 50)
    try:
        page = fulltext_search_page(query, limit=limit, cursor=cursor or None)
    except Exception as e:
        return f"Search failed (Datasette API unreachable?): {e}"
    if not page.results:
        return f"No results found for: {query!r}"

    out = [f"Found {len(page.results)} result(s) for '{query}':\n"]
    for r in page.results:
        out.append(f"  EFTA: {r.efta_number}  DS{r.dataset}  {r.email_date or '?'}")
        out.append(f"  From: {r.sender or '?'} -> To: {r.recipient or '?'}")
        if r.subject:
            out.append(f"  Subj: {r.subject}")
        snippet = (r.search_text or "").replace("\n", " ")[:200]
        if snippet:
            out.append(f"  Text: {snippet}...")
        out.append(f"  URL:  {r.doj_url}")
        out.append("")
    out.extend(_page_footer(page.total, len(page.results), page.next_cursor))
    return "\n".join(out)


@mcp.tool(annotations=_REMOTE_READONLY)
def efta_filter_email(
    sender:      str = "",
    recipient:   str = "",
    date_exact:  str = "",
    date_prefix: str = "",
    subject:     str = "",
    limit:       int = 20,
    cursor:      str = "",
) -> str:
    """
    Filter DOJ Epstein emails by metadata fields using the Datasette API.

    Args:
        sender:      Partial sender name/email (e.g. "epstein", "rothschild")
        recipient:   Partial recipient name (e.g. "schank", "gates")
        date_exact:  Exact date YYYY-MM-DD (e.g. "2009-10-23")
        date_prefix: Date prefix YYYY-MM or YYYY (e.g. "2009-10", "2014")
        subject:     Partial subject text
        limit:       Max results (default 20, max 50)
        cursor:      Continuation cursor from a previous call's "More results available" notice
    """
    if not any([sender, recipient, date_exact, date_prefix, subject]):
        return "Provide at least one filter (sender, recipient, date_exact, date_prefix, or subject)."
    limit = min(limit, 50)
    try:
        page = search_by_sender_recipient_page(
            sender     = sender or None,
            recipient  = recipient or None,
            date_exact = date_exact or None,
            date_prefix= date_prefix or None,
            subject    = subject or None,
            limit      = limit,
            cursor     = cursor or None,
        )
    except Exception as e:
        return f"Filter failed (Datasette API unreachable?): {e}"
    if not page.results:
        return "No results found for the given filters."

    out = [f"Found {len(page.results)} email(s):\n"]
    for r in page.results:
        out.append(f"  {r.efta_number}  DS{r.dataset}  {r.email_date}")
        out.append(f"  {r.sender or '?'} -> {r.recipient or '?'}")
        if r.subject:
            out.append(f"  [{r.subject}]")
        snippet = (r.search_text or "").replace("\n", " ")[:150]
        if snippet:
            out.append(f"  {snippet}...")
        out.append(f"  {r.doj_url}")
        out.append("")
    out.extend(_page_footer(page.total, len(page.results), page.next_cursor))
    return "\n".join(out)


@mcp.tool(annotations=_LOCAL_READONLY)
def efta_known_docs(category: str = "") -> str:
    """
    List pre-verified known EFTA documents with direct DOJ URLs.

    Categories: pizza, schank_shipping, bill_gates

    Args:
        category: Filter by category name (leave empty for all)
    """
    if category:
        docs = get_by_category(category)
        if not docs:
            return f"Unknown category '{category}'. Available: {all_categories()}"
    else:
        docs = KNOWN_DOCUMENTS

    out = [f"{len(docs)} known document(s):\n"]
    for doc in docs:
        out.append(f"  EFTA{doc.efta:08d}  DS{doc.dataset}  [{doc.category}]  {doc.date or '?'}")
        out.append(f"  {doc.description}")
        out.append(f"  From: {doc.sender or '?'}  To: {doc.recipient or '?'}")
        if doc.fact_check:
            out.append(f"  ✓ {doc.fact_check[:80]}")
        out.append(f"  URL: {doc.url}")
        out.append("")
    return "\n".join(out)


@mcp.tool(annotations=_LOCAL_READONLY)
def efta_get_url(efta_number: str) -> str:
    """
    Convert an EFTA number to its official DOJ PDF URL.

    Args:
        efta_number: EFTA number as string or integer.
                     Accepts: "EFTA00741068", "741068", 741068
    """
    try:
        url = efta_to_url(efta_number)
        import re
        m = re.search(r"\d{5,}", str(efta_number))
        n = int(m.group()) if m else 0
        ds = get_dataset(n)
        return f"EFTA: {efta_number}\nDataSet: DS{ds}\nURL: {url}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool(annotations=_REMOTE_READONLY)
def efta_verify_url(efta_number: str) -> str:
    """
    HEAD-check a DOJ PDF URL to confirm it is live and accessible.

    Args:
        efta_number: EFTA number (string or int)
    """
    try:
        url = efta_to_url(efta_number)
        ok, code = verify_pdf_accessible(url)
        status = "ACCESSIBLE" if ok else f"BLOCKED (HTTP {code})"
        return f"{status}\nURL: {url}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool(annotations=_REMOTE_READONLY)
def efta_lookup(efta_number: str) -> str:
    """
    Look up a single document's metadata from the Datasette index.

    Args:
        efta_number: EFTA number string like "EFTA00741068" or "741068"
    """
    try:
        result = get_document_by_efta(efta_number)
    except Exception as e:
        return f"Lookup failed (Datasette API unreachable?): {e}"
    if not result:
        return f"EFTA {efta_number} not found in Datasette index."

    return (
        f"EFTA: {result.efta_number}\n"
        f"DataSet: DS{result.dataset}\n"
        f"Date: {result.email_date or '?'}\n"
        f"From: {result.sender or '?'}\n"
        f"To: {result.recipient or '?'}\n"
        f"Subject: {result.subject or '(blank)'}\n"
        f"Type: {result.doc_type or '?'}\n"
        f"Snippet: {result.snippet(300)}\n"
        f"URL: {result.doj_url}"
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GENERIC TOOLS — every one of the 20 databases, no per-table hardcoding.
#  This is what makes images, transcripts, OCR, handwriting, depositions,
#  the knowledge graph, and everything else besides the main email corpus
#  actually reachable, and keeps working as epstein-data.com's schema
#  evolves through 2031 without requiring a new tool per table.
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool(annotations=_REMOTE_READONLY)
def efta_list_databases() -> str:
    """
    List every Datasette database on epstein-data.com (currently 20, including
    full_text_corpus, image_analysis, transcripts, knowledge_graph, ocr_database,
    handwriting_transcriptions, deposition_transcripts, and more). This is the
    live source of truth for what efta_list_tables/efta_query_table/efta_run_sql
    can reach — call it first if you're not sure a database still exists or what
    it's currently named.
    """
    try:
        dbs = list_databases()
    except Exception as e:
        return f"Failed to list databases (Datasette API unreachable?): {e}"
    out = [f"{len(dbs)} database(s):\n"]
    for db in dbs:
        size = db.get("size")
        out.append(f"  {db['name']}" + (f"  ({size:,} bytes)" if size else ""))
    return "\n".join(out)


@mcp.tool(annotations=_REMOTE_READONLY)
def efta_list_tables(database: str) -> str:
    """
    List every table in one Datasette database: name, columns, row count.
    Call efta_list_databases() first if you don't already know the database name.

    Args:
        database: Datasette database name, e.g. "image_analysis", "transcripts",
                  "knowledge_graph", "full_text_corpus" (see efta_list_databases)
    """
    try:
        tables = list_tables(database)
    except Exception as e:
        return f"Failed to list tables (unknown database, or API unreachable?): {e}"
    visible = [t for t in tables if not t.get("hidden")]
    hidden_n = len(tables) - len(visible)
    out = [f"{len(visible)} queryable table(s) in '{database}'"
           + (f" ({hidden_n} internal/hidden not shown)" if hidden_n else "") + ":\n"]
    for t in visible:
        out.append(f"  {t['name']}  ({t['count']} rows)")
        out.append(f"    columns: {', '.join(t['columns'])}")
        out.append("")
    return "\n".join(out)


@mcp.tool(annotations=_REMOTE_READONLY)
def efta_describe_table(database: str, table: str) -> str:
    """
    Column list and row count for one table — check this before building an
    efta_query_table filter or an efta_run_sql query against an unfamiliar table.

    Args:
        database: Datasette database name (see efta_list_databases)
        table:    table name within that database (see efta_list_tables)
    """
    try:
        info = describe_table(database, table)
    except Exception as e:
        return f"Failed to describe table (unknown database/table, or API unreachable?): {e}"
    return (
        f"Database: {info['database']}\n"
        f"Table: {info['table']}\n"
        f"Rows: {info['count']}\n"
        f"Columns: {', '.join(info['columns'])}"
    )


@mcp.tool(annotations=_REMOTE_READONLY)
def efta_query_table(
    database: str,
    table: str,
    filters: Optional[dict[str, Any]] = None,
    limit: int = 20,
    cursor: str = "",
) -> str:
    """
    Filtered query against ANY table in ANY of the 20 Datasette databases —
    the generic counterpart to efta_search/efta_filter_email, reaching image
    captions, transcript text, knowledge-graph edges, OCR text, handwriting
    transcriptions, depositions, spreadsheets, and anything else without a
    dedicated tool per table.

    Args:
        database: Datasette database name (see efta_list_databases)
        table:    table name within that database (see efta_list_tables)
        filters:  Datasette filter-suffix dict, e.g. {"caption__contains": "passport"}
                  or {"efta_number__startswith": "EFTA02"}. Supported suffixes:
                  field, field__exact, field__contains, field__startswith,
                  field__endswith, field__gt/gte/lt/lte, field__isnull,
                  field__notnull, field__in (comma-separated values).
        limit:    max rows per page (default 20, max 100)
        cursor:   continuation token from a previous call's "More results" notice
    """
    limit = min(limit, 100)
    try:
        page = query_table(database, table, filters=filters or {}, limit=limit, cursor=cursor or None)
    except Exception as e:
        return f"Query failed (bad database/table/filter, or API unreachable?): {e}"
    if not page.rows:
        return "No rows matched."
    out = [f"{len(page.rows)} row(s) from {database}/{table}:\n"]
    for row in page.rows:
        out.append(f"  {row}")
    out.append("")
    out.extend(_page_footer(page.total, len(page.rows), page.next_cursor))
    return "\n".join(out)


@mcp.tool(annotations=_REMOTE_READONLY)
def efta_run_sql(database: str, sql: str, params: Optional[dict[str, Any]] = None, limit: int = 200) -> str:
    """
    Arbitrary read-only SQL against one Datasette database — the full-power
    escape hatch for joins, aggregation, GROUP BY, or boolean logic that
    efta_query_table's filter-suffix API can't express (e.g. "count documents
    per DataSet", "find images whose caption matches a knowledge-graph entity").
    Only SELECT is accepted: Datasette itself rejects anything else with
    HTTP 400 before it reaches SQLite, so this carries no write/DDL risk.

    Args:
        database: Datasette database name (see efta_list_databases)
        sql:      one SELECT statement. Use :name placeholders for values,
                  e.g. "select efta_number, subject from doc_search where dataset = :ds limit 10"
        params:   values for the :name placeholders, e.g. {"ds": 9}
        limit:    row cap (default 200)
    """
    try:
        result = run_sql(database, sql, params=params or {}, limit=limit)
    except DatasetteError as e:
        return f"Query rejected: {e}"
    except Exception as e:
        return f"Query failed (bad database/SQL, or API unreachable?): {e}"
    cols = result["columns"]
    rows = result["rows"]
    if not rows:
        return f"Query succeeded, 0 rows. Columns: {', '.join(cols)}"
    out = [f"{len(rows)} row(s). Columns: {', '.join(cols)}\n"]
    for row in rows:
        out.append("  " + " | ".join(str(v) for v in row))
    if result.get("truncated"):
        out.append(f"\n  (truncated at limit={limit} — narrow the query or lower it further)")
    return "\n".join(out)


if __name__ == "__main__":
    mcp.run()
