# CLAUDE.md — Epstein Files Plugin (standalone plugin)

> **Standalone research plugin — NOT part of the Salecraft enterprise suite.**
> Own repo: `Zereo0317/Epstein-Files-Plugin` (public — verified 2026-08-25; renamed 2026-08-24, twice, same day —
> `efta-system`/`efta-researcher` → `epstein-files-mcp` → `Epstein-Files-Plugin` — see the naming
> note below). It does **not** share the suite's
> `sc_live_*` identity, per-`sub` memory, or legal-before-publish gate; it is **not** in
> `Plugin/.claude-plugin/marketplace.json` and is **not** wired into the orchestration
> conductor. Treat it like `Legal-Engineering-System/` — a self-contained neighbor that
> happens to live under `Plugin/`.

## What this is

A research toolkit for the **public DOJ Epstein Files Transparency Act release**
(EFTA = Epstein Files Transparency Act, Public Law 119-38, signed 2025-11-19). The DOJ
published ~1.4M documents / ~2.8-2.9M pages (verified against epstein-data.com's live stats
2026-08-24; re-verify before citing — DOJ's total *collected* is ~6M pages, of which this is the
portion published so far) across **12 DataSets** at `https://www.justice.gov/epstein`, indexed by
the third-party mirror epstein-data.com as **20 Datasette databases** (also verified live
2026-08-24 — call `efta_list_databases()`/`list_databases()` for the current list, this is a
snapshot). This plugin helps **find, verify, and locate** a specific filing — by
sender/recipient/date, full text, EFTA number, or an arbitrary query against any of the 20
databases (images, transcripts, OCR, handwriting, depositions, the knowledge graph, ...) — and
turns an EFTA number into its official DOJ PDF URL.

It is an **OSINT / source-location tool over already-public court records**. It does not host,
re-host, or expose any private data.

## Module map

| Path | Role |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest (`epstein-files-plugin`) |
| `.mcp.json` | Local **stdio** MCP server config (auto-discovered at plugin root) |
| `src/mcp_server.py` | FastMCP entrypoint — exposes 11 read-only tools (6 purpose-built + 5 generic) |
| `src/efta_core.py` | DataSet boundary table, EFTA→URL (env-overridable DOJ base), verified known-document registry |
| `src/epstein_datasette.py` | Client for the epstein-data.com Datasette JSON API — purpose-built search + a generic introspection/query/SQL layer covering all 20 databases |
| `src/doj_auth.py` | Access helper: solves justice.gov's **public** anti-bot cookie challenge to fetch public PDFs; HEAD-verify + download. Retry messages go to **stderr** — this module is imported by an MCP stdio server, and stdout is reserved for the JSON-RPC protocol stream |
| `src/efta_researcher.py` | Unified CLI (`--search`, `--filter`, `--category`, `--efta`, `--verify`, `--download`, `--json`, `--databases`, `--tables`, `--sql`) |
| `skills/efta-research/` | Claude skill: research methodology (find a document) |
| `skills/doj-auth/` | Claude skill: the justice.gov public anti-bot challenge details |
| `requirements.txt` | `requests`, `mcp<2.0` (pinned — see Repository & development below) |

## Architecture: purpose-built + generic, not per-table hardcoding

Two layers, deliberately:

1. **Purpose-built** (`efta_search`, `efta_filter_email`, `efta_lookup`, `efta_known_docs`,
   `efta_get_url`, `efta_verify_url`) — ergonomic wrappers over the single most common table
   (`full_text_corpus/doc_search`: text + email metadata), with proper pagination (true total
   count + continuation cursor, not a silent truncation).
2. **Generic** (`efta_list_databases`, `efta_list_tables`, `efta_describe_table`,
   `efta_query_table`, `efta_run_sql`) — reach any of the other 19 databases (images, transcripts,
   OCR, handwriting, depositions, spreadsheets, the knowledge graph, ...) via Datasette's own
   filter-suffix query syntax and a read-only raw-SQL passthrough, without a dedicated tool per
   table. **This is the deliberate answer to "can everything be queried":** hardcoding a wrapper
   per database is a maintenance trap that goes stale as epstein-data.com's schema evolves through
   2031 (tables get added, renamed, or restructured); the generic layer instead reflects whatever
   schema is live *right now*, discoverable via `efta_list_databases`/`efta_list_tables` before
   any query is built.

`run_sql`'s safety model: Datasette's own API only accepts a `SELECT` statement through the
`?sql=` endpoint — a non-`SELECT` is rejected with HTTP 400 before it ever reaches SQLite
(verified live 2026-08-24 with a `CREATE TABLE` probe). The client-side `SELECT`-only check in
`epstein_datasette.run_sql()` is defense-in-depth for a clearer error message, not the actual
security boundary — that boundary is the third-party server's, identical to what anyone browsing
epstein-data.com directly already has.

## Ethics & scope (read before extending)

- Operates **only** on already-public DOJ releases at `justice.gov/epstein` and a public
  third-party full-text mirror (epstein-data.com). No private data, no paywalled sources.
- Intended use: **research, fact-checking, and source-location** — given a claim or a
  screenshot, find and verify the underlying public document and surface its provenance/URL.
- The subject matter attracts conspiracy framings. The registry and skills deliberately take a
  **fact-checking, non-amplifying stance**: a "connection" is labeled for what the documents
  actually show (business / philanthropy / membership / inbound crank mail), and sensational
  versions ("coup", "COVID planning", "Illuminati membership") are explicitly debunked. Keep
  that posture in any change. Mark confidence on every claim.
- Not for re-identification, harassment, or doxxing.
- `efta_run_sql` broadens *what* can be queried, not the ethical posture above — it still only
  reaches already-public, already-indexed data on the same third-party mirror; it grants no new
  access epstein-data.com doesn't already expose to anyone browsing its site.

## How to run

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
# CLI:
python src/efta_researcher.py --list
python src/efta_researcher.py --search "trilateral commission"
python src/efta_researcher.py --efta EFTA00741068
python src/efta_researcher.py --databases
python src/efta_researcher.py --tables image_analysis
python src/efta_researcher.py --sql "select count(*) from images" --database image_analysis
# MCP: launched automatically by Claude Code via .mcp.json
#   python ${CLAUDE_PLUGIN_ROOT}/src/mcp_server.py
```

Validate the manifest with `claude plugin validate .` when the CLI is available.

## Repository & development

- **Repo:** [`Zereo0317/Epstein-Files-Plugin`](https://github.com/Zereo0317/Epstein-Files-Plugin) (**public** — verified 2026-08-25). Clone: `git clone https://github.com/Zereo0317/Epstein-Files-Plugin.git`.
- **Naming (2026-08-24, two renames the same day):** `efta-system`/plugin name `efta-researcher`
  → `epstein-files-mcp` (repo deleted and recreated fresh, as part of a full history/PR cleanup
  before any public listing) → **`Epstein-Files-Plugin`** (renamed in place via GitHub's rename
  feature — history/commit preserved this time, unlike the first jump). The second rename was a
  deliberate branding call: "MCP" is technically accurate (this is fundamentally an MCP server,
  and the whole design is "MCP-first, not Claude-first" — works identically in Cursor, Windsurf,
  ChatGPT connectors, not just Claude Code) but is a protocol/developer term a non-technical
  audience (journalists, general researchers) won't recognize; "Plugin" is the more broadly
  understood word, at some cost to the "works everywhere, not just Claude Code" positioning that
  "MCP" communicated for free. Tool names kept the `efta_*` prefix throughout (still accurate —
  the EFTA Bates-numbering system, independent of the product's marketing name). Local folder
  renamed to match: `Plugin_System/EFTA-System/` → `Plugin_System/Epstein-Files-Plugin/`. Product
  display name is "Epstein Files Plugin."
- **Install:** `pip install -r requirements.txt` (`requests`, `mcp<2.0`). Local **stdio** MCP server (`src/mcp_server.py`) — no remote, no auth, no API keys; auto-launched by Claude Code via `.mcp.json`.
- **MCP SDK pin (2026-08-24):** `requirements.txt` pins `mcp>=1.29.0,<2.0.0`. The official `mcp`
  package's v2.0.0 (2026-07-28, tracking the 2026-07-28 MCP spec revision) renamed
  `mcp.server.fastmcp.FastMCP` to `mcp.server.mcpserver.MCPServer` — a breaking import change this
  server hasn't been migrated to yet. An unpinned `mcp>=1.0.0` (the state before this date) would
  silently resolve to v2.x on a fresh install and fail to import. Re-evaluate the v2 migration
  deliberately before bumping this pin; the (unrelated) standalone `fastmcp` PyPI package
  (PrefectHQ, now v3.x) is not a dependency — this codebase never imported it, only
  the `FastMCP` class bundled inside the `mcp` package itself.
- **Python version (2026-08-24):** minimum bumped 3.10 → **3.11** — Python 3.10 reaches
  end-of-life 2026-10-31 (about two months from this writing; source: python.org / endoflife.date).
  Dev/test environment is 3.14.7; nothing in this codebase is version-pinned tighter than that.
- **Third-party base URLs are env-overridable, not hardcoded:** `EFTA_DATASETTE_BASE_URL`
  (default `https://epstein-data.com`) and `EFTA_DOJ_BASE_URL` (default
  `https://www.justice.gov`) — both `efta_core.py` and `epstein_datasette.py` read these, and
  `doj_auth.py` imports `efta_core.DOJ_ROOT` rather than redefining its own domain constant. A
  future mirror or DOJ domain change is a config change, not a code change.
- **Validate:** `claude plugin validate .` when the CLI is available. CLI usage is in "How to run" above.
  `clawhub package validate .` also runs clean (`PASS`, 0 breakages) with one known, accepted P2
  warning — see the `openclaw.plugin.json` note directly below.
- **`openclaw.plugin.json`'s `mcpServers` field is informational only — OpenClaw's PLUGIN manifest
  loader does not read it (confirmed 2026-08-25).** Verified two independent ways against the
  real, currently published `openclaw@2026.7.1-2` npm package (not docs, which are unreliable here
  — a WebFetch summary of `docs.openclaw.ai/plugins/manifest` fabricated a plausible-looking but
  nonexistent `mcpServers` schema entry during this same check, caught only by cross-referencing
  the actual compiled type): (1) `clawhub package validate .` flags
  `mcpServers @ openclaw.plugin.json` as `manifest-unknown-fields`; (2) a direct read of the
  cached compiled type declaration (`~/.cache/plugin-inspector/openclaw/<version>/package/dist/
  manifest-registry-*.d.ts`) shows the real `PluginManifest` type has no `mcpServers` field
  anywhere, matching the known open upstream gap `openclaw/clawhub#3513`. Publishing via
  `clawhub package publish --family bundle-plugin` (confirmed working, dry-run tested clean —
  `Plugin Inspector: PASS`, 0 breakages) does **not** auto-wire this plugin's MCP server inside
  OpenClaw as a result.
- **The real, working path for an OpenClaw user is the ROOT config, not the plugin manifest —
  confirmed by reading OpenClaw's actual compiled MCP runtime code
  (`dist/agent-bundle-mcp-runtime-*.js` in the same cache directory), not docs or a WebFetch
  summary.** OpenClaw has genuine, first-class MCP support: a user adds a server entry to their
  own `~/.openclaw/openclaw.json` (or `openclaw config set mcpServers.<name>.command ...`) under
  `mcpServers`, exactly mirroring Claude Code's `.mcp.json` convention. For a local stdio server
  like this one, `command`/`args`/`env` alone are enough — the runtime auto-detects stdio from the
  presence of `command`, no explicit `transport` field required. This is documented in
  [`README.md`](./README.md#use-with-ai-agents)'s OpenClaw row — that's the correct instruction to
  give OpenClaw users, not a fix to the plugin manifest (there isn't one, upstream). `package.json`
  was added (2026-08-25) purely to satisfy the separate `package-json-missing` validator warning
  (metadata-only, no dependencies).
- **Standalone:** NOT part of the Salecraft suite — no `sc_live_` identity, per-`sub` memory, or legal gate; not in the suite marketplace or orchestration.
- **`.gitignore`** excludes secrets, Python caches (`__pycache__/`, `.venv/`), and **downloaded public PDFs / exports** (`downloads/`, `*.pdf`, `exports/`) — fetched artifacts, not source.

## Conventions

- 2-space JSON indent, final newline. Skill `name` frontmatter == directory name (`[a-z0-9-]`).
- No personal data or secrets in the tree; downloaded PDFs and exports are git-ignored.
- Target Python ≥ 3.11 (modules use `from __future__ import annotations`).
- **Never `print()` to stdout from a module `mcp_server.py` imports.** `mcp.run()` speaks
  JSON-RPC over stdio — any stray stdout write corrupts the protocol framing and breaks the whole
  connection. Debug/retry/progress output goes to `file=sys.stderr`. (`doj_auth.py`'s retry
  message was fixed to stderr 2026-08-24 after this was found as a latent bug — not reachable from
  the current tool set, but a real landmine for the next person who wires in a new tool.)
- Prefer the generic tools (`query_table`/`run_sql`) over adding a new hardcoded per-table wrapper
  unless the wrapper earns its keep with real ergonomic value (as `efta_search`/`efta_filter_email`
  do for the single most common table) — see "Architecture" above.

## Relevant skills

Its own `efta-research` and `doj-auth`. For source verification the workspace `deep-research`
and `github-research` skills complement it. It is a single-domain tool — don't over-wire it into
the broader registry.
