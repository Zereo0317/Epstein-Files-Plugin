#!/usr/bin/env python3
"""
efta_researcher.py
==================
Main CLI — combines all modules into a unified research tool.

USAGE
─────
  python efta_researcher.py --list
  python efta_researcher.py --search "schank shipping"
  python efta_researcher.py --sender epstein --recipient schank --date 2009-10-23
  python efta_researcher.py --category pizza
  python efta_researcher.py --category bill_gates
  python efta_researcher.py --efta EFTA00741068
  python efta_researcher.py --verify
  python efta_researcher.py --download --category pizza --output ./downloads/
  python efta_researcher.py --json all_known.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

try:
    from efta_core        import KNOWN_DOCUMENTS, KnownDoc, get_by_category, efta_to_url, all_categories
    from epstein_datasette import (search_by_sender_recipient, fulltext_search,
                                    get_document_by_efta, list_databases, list_tables,
                                    describe_table, query_table, run_sql, DatasetteError)
    from doj_auth          import get_authenticated_session, verify_pdf_accessible, download_pdf
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from efta_core        import KNOWN_DOCUMENTS, KnownDoc, get_by_category, efta_to_url, all_categories
    from epstein_datasette import (search_by_sender_recipient, fulltext_search,
                                    get_document_by_efta, list_databases, list_tables,
                                    describe_table, query_table, run_sql, DatasetteError)
    from doj_auth          import get_authenticated_session, verify_pdf_accessible, download_pdf


SEP = "─" * 72


def print_doc(doc: KnownDoc):
    print(f"\n  EFTA{doc.efta:08d}  DS{doc.dataset}  {doc.date or '?'}")
    print(f"  {doc.description}")
    print(f"  From : {doc.sender or '?'}")
    print(f"  To   : {doc.recipient or '?'}")
    if doc.subject:
        print(f"  Subj : {doc.subject}")
    if doc.fact_check:
        print(f"  ✓    : {doc.fact_check[:80]}")
    print(f"  URL  : {doc.url}")


def print_search_result(r):
    print(f"\n  {r.efta_number}  DS{r.dataset}  {r.email_date or '?'}")
    print(f"  From: {r.sender or '?'}  ->  To: {r.recipient or '?'}")
    if r.subject:
        print(f"  Subj: {r.subject}")
    snippet = (r.search_text or "").replace("\n", " ")[:150]
    if snippet:
        print(f"  Text: {snippet}...")
    print(f"  URL : {r.doj_url}")


def cmd_list(args):
    print(f"\n{'='*72}")
    print(f"  EFTA KNOWN DOCUMENTS  ({len(KNOWN_DOCUMENTS)} entries, {len(all_categories())} categories)")
    print(f"{'='*72}")
    for cat in all_categories():
        docs = get_by_category(cat)
        print(f"\n[{cat.upper()}] — {len(docs)} document(s)")
        for doc in docs:
            print_doc(doc)


def cmd_search(args):
    try:
        if args.search:
            print(f"\nFull-text search: '{args.search}'")
            results = fulltext_search(args.search, limit=args.limit)
        elif args.sender or args.recipient:
            print(f"\nSender/recipient filter: {args.sender or '*'} -> {args.recipient or '*'}")
            results = search_by_sender_recipient(
                sender     = args.sender,
                recipient  = args.recipient,
                date_exact = args.date,
                date_prefix= args.date_prefix,
                subject    = args.subject,
                limit      = args.limit,
            )
        else:
            print("Provide --search TERM or --sender / --recipient filters")
            return
    except Exception as e:
        print(f"Datasette search failed (network/API unreachable?): {e}")
        return

    print(f"Found {len(results)} result(s):\n{SEP}")
    for r in results:
        print_search_result(r)
    print()


def cmd_category(args):
    docs = get_by_category(args.category)
    if not docs:
        print(f"Unknown category '{args.category}'. Available: {all_categories()}")
        return
    print(f"\n[{args.category.upper()}] — {len(docs)} document(s)\n{SEP}")
    for doc in docs:
        print_doc(doc)
    print()


def cmd_efta(args):
    import re as _re
    m = _re.search(r"\d{4,}", args.efta or "")
    if not m:
        print(f"Invalid --efta value: {args.efta!r}. Expected e.g. EFTA00741068 or 741068.")
        return
    efta_num = int(m.group())
    known = next((d for d in KNOWN_DOCUMENTS if d.efta == efta_num), None)
    if known:
        print(f"\n[KNOWN DOCUMENT]\n{SEP}")
        print_doc(known)
    else:
        print(f"\nLooking up EFTA{efta_num:08d} via Datasette...")
        try:
            result = get_document_by_efta(efta_num)
        except Exception as e:
            result = None
            print(f"(Datasette lookup failed: {e})")
        if result:
            print_search_result(result)
        else:
            url = efta_to_url(efta_num)
            print(f"Not in Datasette index. Computed URL:\n  {url}")


def cmd_verify(args):
    print(f"\nVerifying {len(KNOWN_DOCUMENTS)} known document URLs...")
    sess = get_authenticated_session()
    failed = []
    for doc in KNOWN_DOCUMENTS:
        ok, code = verify_pdf_accessible(doc.url, sess)
        status = "OK" if ok else "FAIL"
        print(f"  {status} HTTP {code:3}  EFTA{doc.efta:08d}  {doc.url}")
        if not ok:
            failed.append(doc)
        time.sleep(0.5)
    if failed:
        print(f"\n{len(failed)} failed:")
        for d in failed:
            print(f"   {d.url}")
    else:
        print(f"\nAll {len(KNOWN_DOCUMENTS)} links returned HTTP 200")


def cmd_download(args):
    if args.category:
        docs = [d for d in KNOWN_DOCUMENTS if d.category == args.category]
    else:
        docs = KNOWN_DOCUMENTS

    out_dir = Path(args.output or "./efta_downloads")
    print(f"\nDownloading {len(docs)} documents to {out_dir}/")
    sess = get_authenticated_session()

    for doc in docs:
        cat_dir = out_dir / doc.category
        cat_dir.mkdir(parents=True, exist_ok=True)
        dest = cat_dir / f"EFTA{doc.efta:08d}.pdf"
        if dest.exists():
            print(f"  already exists: {dest.name}")
            continue
        ok = download_pdf(doc.url, str(dest), sess)
        print(f"  {'OK' if ok else 'FAIL'} {dest.name}")
        time.sleep(1.0)


def cmd_databases(args):
    print(f"\nDatasette databases at epstein-data.com:\n{SEP}")
    for db in list_databases():
        size = db.get("size")
        print(f"  {db['name']}" + (f"  ({size:,} bytes)" if size else ""))
    print()


def cmd_tables(args):
    tables = list_tables(args.tables)
    visible = [t for t in tables if not t.get("hidden")]
    hidden_n = len(tables) - len(visible)
    print(f"\nTables in '{args.tables}'"
          + (f" ({hidden_n} internal/hidden not shown)" if hidden_n else "") + f":\n{SEP}")
    for t in visible:
        print(f"  {t['name']}  ({t['count']} rows)")
        print(f"    columns: {', '.join(t['columns'])}")
    print()


def cmd_sql(args):
    if not args.database:
        print("Provide --database with --sql (which Datasette database to query)")
        return
    try:
        result = run_sql(args.database, args.sql, limit=args.limit)
    except DatasetteError as e:
        print(f"Query rejected: {e}")
        return
    except Exception as e:
        print(f"Query failed: {e}")
        return
    cols, rows = result["columns"], result["rows"]
    print(f"\n{len(rows)} row(s). Columns: {', '.join(cols)}\n{SEP}")
    for row in rows:
        print("  " + " | ".join(str(v) for v in row))
    if result.get("truncated"):
        print(f"\n(truncated at limit={args.limit})")
    print()


def cmd_json_export(args):
    data = {}
    for cat in all_categories():
        docs = get_by_category(cat)
        data[cat] = [{
            "efta":        f"EFTA{d.efta:08d}",
            "dataset":     d.dataset,
            "url":         d.url,
            "date":        d.date,
            "sender":      d.sender,
            "recipient":   d.recipient,
            "subject":     d.subject,
            "description": d.description,
            "fact_check":  d.fact_check,
            "source":      d.source,
        } for d in docs]

    out = args.json
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Exported {sum(len(v) for v in data.values())} documents to {out}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="efta_researcher",
        description="DOJ Epstein EFTA document research tool",
    )
    action = p.add_mutually_exclusive_group()
    action.add_argument("--list",     action="store_true")
    action.add_argument("--search",   metavar="TERM")
    action.add_argument("--category", metavar="CAT")
    action.add_argument("--efta",     metavar="EFTA#")
    action.add_argument("--verify",   action="store_true")
    action.add_argument("--download", action="store_true")
    action.add_argument("--json",     metavar="FILE")
    action.add_argument("--databases", action="store_true",
                         help="List all 20 Datasette databases (images, transcripts, OCR, ...)")
    action.add_argument("--tables",   metavar="DATABASE",
                         help="List tables + columns in one database (see --databases)")
    action.add_argument("--sql",      metavar="SELECT_STATEMENT",
                         help="Run read-only SQL against one database (requires --database)")

    p.add_argument("--sender",      metavar="NAME")
    p.add_argument("--recipient",   metavar="NAME")
    p.add_argument("--date",        metavar="YYYY-MM-DD")
    p.add_argument("--date-prefix", metavar="YYYY-MM", dest="date_prefix")
    p.add_argument("--subject",     metavar="TEXT")
    p.add_argument("--limit",       type=int, default=20)
    p.add_argument("--output",      metavar="DIR", default="./efta_downloads")
    p.add_argument("--database",    metavar="NAME", help="Datasette database name, for use with --sql")
    return p


def main():
    # Ensure non-ASCII glyphs (─ ✓ → —) print on legacy consoles (e.g. Windows cp950).
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = build_parser()
    args = parser.parse_args()

    if args.list:
        cmd_list(args)
    elif args.search or args.sender or args.recipient:
        cmd_search(args)
    elif args.category:
        cmd_category(args)
    elif args.efta:
        cmd_efta(args)
    elif args.verify:
        cmd_verify(args)
    elif args.download:
        cmd_download(args)
    elif args.json:
        cmd_json_export(args)
    elif args.databases:
        cmd_databases(args)
    elif args.tables:
        cmd_tables(args)
    elif args.sql:
        cmd_sql(args)
    else:
        print(f"\nEFTA Researcher — {len(KNOWN_DOCUMENTS)} known documents, {len(all_categories())} categories")
        print(f"Categories: {', '.join(all_categories())}")
        print("\nQuick commands:")
        print("  --list                         All known documents with URLs")
        print("  --search 'schank goyim'        Full-text Datasette search")
        print("  --sender epstein --recipient schank --date 2009-10-23")
        print("  --category pizza               Show pizza-related documents")
        print("  --category bill_gates          Show Gates/BGC3 documents")
        print("  --efta EFTA00741068            Look up one document")
        print("  --verify                       Check all DOJ links are live")
        print("  --download --output ./pdfs/    Download all known PDFs")
        print("  --json known_docs.json         Export to JSON")
        print("  --databases                    List all 20 Datasette databases")
        print("  --tables image_analysis        List tables in one database")
        print("  --sql \"select ...\" --database full_text_corpus")
        print("                                 Read-only SQL against one database")
        print()


if __name__ == "__main__":
    main()
