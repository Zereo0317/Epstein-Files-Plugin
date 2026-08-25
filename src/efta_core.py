"""
efta_core.py
============
Core EFTA dataset mapping, URL construction, and known-document registry.

EFTA numbers are PAGE identifiers (not document IDs).
A 10-page PDF consumes 10 consecutive EFTA numbers.

DataSet boundaries are the forensic per-file ranges from
rhowardstone/Epstein-research-data (efta_dataset_mapping.csv), cross-checked
against the DOJ disclosure pages and epstein-data.com.
"""

from __future__ import annotations
import os
import re
from dataclasses import dataclass
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
#  DATASET BOUNDARY TABLE
# ─────────────────────────────────────────────────────────────────────────────

# Verified per-DataSet EFTA Bates ranges (start, end inclusive).
# Source: rhowardstone/Epstein-research-data `efta_dataset_mapping.csv` (forensic
# count of all ~1.38M released PDFs), cross-checked against the DOJ disclosure
# pages' first-listed file per DataSet. HIGH confidence on all boundaries except
# the internal DS10/DS11 split (CSV 2205654 vs a second analysis 2212882); the CSV
# value is used here and does not affect any registered document. Inter-DataSet
# gaps exist (some EFTA numbers are legitimately unassigned), so get_dataset()
# resolves a gap to the preceding DataSet.
DATASET_RANGES: list[tuple[int, int, int]] = [
    # (dataset_num, efta_start, efta_end_inclusive)
    ( 1,        1,     3158),   # Photos / physical scans
    ( 2,     3159,     3857),   # Photos / seized scans
    ( 3,     3858,     5586),   # Grand jury exhibits
    ( 4,     5705,     8320),   # Records, court filings
    ( 5,     8409,     8528),   # Seized scans / depositions
    ( 6,     8529,     8998),   # Depositions / indictments
    ( 7,     9016,     9664),   # Transcripts
    ( 8,     9676,    39023),   # Emails, police reports, mixed
    ( 9,    39025,  1262781),   # ★ MAIN EMAIL CORPUS — emails, travel, financial
    (10,  1262782,  2205654),   # Emails, financial
    (11,  2205655,  2730264),   # Emails, device data
    (12,  2730265,  2858497),   # Court filings, FBI material + post-release expansion
]

# Overridable so a future DOJ URL-scheme or domain change (plausible over a
# 2026-2031 horizon) doesn't require a code edit. doj_auth.py imports this
# rather than redefining its own DOJ domain constant.
DOJ_ROOT = os.environ.get("EFTA_DOJ_BASE_URL", "https://www.justice.gov").rstrip("/")
DOJ_BASE = f"{DOJ_ROOT}/epstein/files"


def get_dataset(efta: int) -> int:
    """Return DataSet number for a given EFTA page number."""
    for ds, lo, hi in DATASET_RANGES:
        if lo <= efta <= hi:
            return ds
    # Fallback: highest dataset whose start <= efta
    best = 9
    for ds, lo, _ in DATASET_RANGES:
        if lo <= efta:
            best = ds
    return best


def efta_to_url(efta: int | str) -> str:
    """Build the official DOJ PDF URL for an EFTA Bates page number, or a string
    like 'EFTA00741068'. Raises ValueError for non-EFTA identifiers (e.g. the
    'DOJ-OGR-...' court-filing series), which do NOT live under the EFTA path —
    callers must not fabricate an EFTA URL for them."""
    if isinstance(efta, str):
        s = efta.strip().upper().replace(" ", "")
        m = re.fullmatch(r"(?:EFTA)?0*(\d+)", s)
        if not m:
            raise ValueError(f"Not an EFTA Bates number: {efta!r}")
        efta = int(m.group(1))
    ds = get_dataset(efta)
    return f"{DOJ_BASE}/DataSet%20{ds}/EFTA{efta:08d}.pdf"


# ─────────────────────────────────────────────────────────────────────────────
#  KNOWN-DOCUMENT REGISTRY
#  Sources: Snopes, EuvsDisinfo, Tempo, Epstein Exposed,
#           DDF, Kevin Bass, epstein-data.com Datasette API queries
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class KnownDoc:
    efta: int
    category: str
    description: str
    date: Optional[str] = None
    sender: Optional[str] = None
    recipient: Optional[str] = None
    subject: Optional[str] = None
    fact_check: Optional[str] = None
    source: Optional[str] = None

    @property
    def url(self) -> str:
        return efta_to_url(self.efta)

    @property
    def dataset(self) -> int:
        return get_dataset(self.efta)


KNOWN_DOCUMENTS: list[KnownDoc] = [

    # ── PIZZA / CHILD / BABY ─────────────────────────────────────────────────

    KnownDoc(
        efta=1616214,
        category="pizza",
        description="Pizza & grape soda thread — 22-page document (EFTA01616214–01616235)",
        date="2018-03-01 to 2018-06-17",
        sender="Harry Fisch (Dr. Harry Fisch, NYC urologist)",
        recipient="Jeffrey Epstein",
        fact_check="Confirmed LITERAL FOOD by Epstein Exposed (2026). 'No one else can understand' = inside joke about junk food, not code.",
        source="Epstein Exposed (2026)",
    ),
    *[KnownDoc(
        efta=n,
        category="pizza",
        description=f"Pizza & grape soda thread — page {n - 1616214 + 1}/22",
        date="2018",
        sender="Harry Fisch / Epstein",
        recipient="Epstein / Harry Fisch",
        fact_check="Literal food. Epstein Exposed confirmed.",
        source="Epstein Exposed (2026)",
    ) for n in range(1616215, 1616236)],

    KnownDoc(
        efta=841659,
        category="pizza",
        description="'Chinese cookie / VERU' viral email — April 6 2018",
        date="2018-04-06",
        sender="Harry Fisch",
        recipient="Jeffrey Epstein",
        subject="VERU",
        fact_check="Email contains Veru Inc equity research PDF attachment. 'Chinese cookie' = fortune cookie at Chinese restaurant. Epstein Exposed confirmed.",
        source="Epstein Exposed (2026)",
    ),

    # ── ROGER SCHANK / GOYIM / SHIPPING FUTURES ──────────────────────────────

    KnownDoc(
        efta=741068,
        category="schank_shipping",
        description="Epstein → Roger Schank shipping futures / goyim email (PRIMARY)",
        date="2009-10-23",
        sender="Jeffrey Epstein <jeevacation@gmail.com>",
        recipient="roger schank",
        subject="(blank)",
        fact_check="Confirmed via epstein-data.com Datasette API query. Exact timestamp 12:01:12 +0000 matches screenshot. Roger Schank was AI researcher / Epstein Palm Beach neighbor.",
        source="epstein-data.com Datasette API (2026)",
    ),
    KnownDoc(
        efta=885615,
        category="schank_shipping",
        description="Epstein → Roger Schank shipping futures / goyim email (DS9 DUPLICATE — OCR reads 'grnail.com')",
        date="2009-10-23",
        sender="Jeffrey Epstein <jeevacation@gmail.com>",
        recipient="roger schank",
        subject="(blank)",
        fact_check="Duplicate of EFTA00741068. OCR error on From field.",
        source="epstein-data.com Datasette API (2026)",
    ),
    KnownDoc(
        efta=1821140,
        category="schank_shipping",
        description="Epstein → Roger Schank shipping futures / goyim email (DS10 COPY)",
        date="2009-10-23",
        sender="Jeffrey Epstein",
        recipient="roger schank",
        subject="(blank)",
        fact_check="Third copy of same email chain in DS10.",
        source="epstein-data.com Datasette API (2026)",
    ),

    # ── BILL GATES / BGC3 / COVID / VACCINE ──────────────────────────────────

    KnownDoc(
        efta=2381427,
        category="bill_gates",
        description="BGC3 'Deliverables & Scope' — pandemic simulation, March 3 2017 (DS11)",
        date="2017-03-03",
        sender="Larry Cohen (BGC3/Gates Ventures)",
        recipient="Jeffrey Epstein",
        subject="bgc3 Deliverables and Scope",
        fact_check="Fact-checked by Tempo, Fact Crescendo, Reuters. Point 5 mentions 'strain pandemic simulation' as legitimate global health planning — NO connection to COVID-19.",
        source="Tempo fact-check (Feb 2026)",
    ),
    KnownDoc(
        efta=2657725,
        category="bill_gates",
        description="BGC3 'Deliverables & Scope' forwarded to Epstein — Epstein replied 'okay' (DS11 copy)",
        date="2017-03-03",
        sender="Jeffrey Epstein (forwarded)",
        recipient="Jeffrey Epstein (self)",
        subject="bgc3 Deliverables and Scope",
        fact_check="Same document forwarded. Epstein's terse 'okay' reply has no significance per fact-checkers.",
        source="Tempo fact-check (Feb 2026)",
    ),
]


def get_by_category(cat: str) -> list[KnownDoc]:
    return [d for d in KNOWN_DOCUMENTS if d.category == cat]


def get_by_efta(efta: int) -> Optional[KnownDoc]:
    return next((d for d in KNOWN_DOCUMENTS if d.efta == efta), None)


def all_categories() -> list[str]:
    return sorted(set(d.category for d in KNOWN_DOCUMENTS))


if __name__ == "__main__":
    print("=== EFTA Known Documents ===\n")
    for cat in all_categories():
        docs = get_by_category(cat)
        print(f"\n[{cat.upper()}] — {len(docs)} document(s)")
        for doc in docs:
            print(f"  EFTA{doc.efta:08d}  DS{doc.dataset}  {doc.date or '?'}")
            print(f"    {doc.description}")
            print(f"    URL: {doc.url}")
            if doc.fact_check:
                print(f"    ✓ {doc.fact_check[:80]}")
