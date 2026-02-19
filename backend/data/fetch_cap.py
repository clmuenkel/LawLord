"""
Fetch Texas DWI case opinions from the Caselaw Access Project (CAP).

CAP (case.law) provides free bulk access to all US case law digitized by
the Harvard Law Library. As of March 2024, all data is freely available
without restrictions.

This script uses the CAP API to search for Texas criminal appellate
opinions related to DWI/DUI.

Usage:
    python -m data.fetch_cap                  # uses .env config
    python -m data.fetch_cap --dry-run        # preview without saving

Note: CAP data extends through ~2018 for most jurisdictions.
      For more recent cases, use fetch_courtlistener.py instead.

CAP API docs: https://api.case.law/v1/
"""

import argparse
import json
import os
import re
import sys
import time

import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv()

CAP_API_BASE = "https://api.case.law/v1"

TEXAS_JURISDICTIONS = ["tex"]

DWI_SEARCH_TERMS = [
    "driving while intoxicated",
    "DWI",
    "intoxication manslaughter",
    "intoxication assault",
    "blood alcohol concentration",
]


def search_cases(
    query: str,
    jurisdiction: str = "tex",
    decision_date_min: str = "2000-01-01",
    max_pages: int = 50,
) -> list[dict]:
    """Search CAP for cases matching a query in a jurisdiction."""
    all_cases = []
    url = f"{CAP_API_BASE}/cases/"

    params = {
        "search": query,
        "jurisdiction": jurisdiction,
        "decision_date_min": decision_date_min,
        "ordering": "-decision_date",
        "page_size": 100,
        "full_case": "true",
    }

    page = 0
    while url and page < max_pages:
        page += 1
        print(f"  Page {page} for '{query}'...")

        try:
            resp = requests.get(url, params=params if page == 1 else None)
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if resp.status_code == 429:
                print("  Rate limited. Waiting 60s...")
                time.sleep(60)
                continue
            print(f"  HTTP error: {e}")
            break

        data = resp.json()
        results = data.get("results", [])
        all_cases.extend(results)
        print(f"  Got {len(results)} results (total: {len(all_cases)})")

        url = data.get("next")
        params = None
        time.sleep(0.5)

    return all_cases


def extract_opinion_text(case_data: dict) -> str | None:
    """Extract the main opinion text from a CAP case record."""
    casebody = case_data.get("casebody", {})
    if isinstance(casebody, dict):
        data = casebody.get("data", {})
        if isinstance(data, dict):
            opinions = data.get("opinions", [])
            if opinions:
                texts = [op.get("text", "") for op in opinions if op.get("type") == "majority"]
                if not texts:
                    texts = [op.get("text", "") for op in opinions]
                return "\n\n".join(texts) if texts else None
        elif isinstance(data, str):
            return data
    return None


def extract_outcome(text: str) -> str | None:
    """Try to extract the case outcome."""
    if not text:
        return None
    tail = text[-2000:].lower()
    for outcome, patterns in [
        ("reversed and remanded", ["reverse and remand", "reversed and remanded"]),
        ("affirmed", ["affirm", "we affirm", "judgment is affirmed"]),
        ("reversed", ["reverse", "we reverse", "judgment is reversed"]),
        ("remanded", ["remand", "we remand"]),
        ("dismissed", ["dismiss", "we dismiss"]),
    ]:
        if any(p in tail for p in patterns):
            return outcome
    return None


def extract_statutes(text: str) -> list[str]:
    """Extract statute references."""
    if not text:
        return []
    pattern = r"§\s*(\d+\.\d+)"
    matches = re.findall(pattern, text)
    return list(dict.fromkeys(f"§ {m}" for m in matches))


def classify_dwi(case_name: str, text: str) -> str | None:
    """Check if the case is DWI-related."""
    combined = (case_name + " " + (text or "")[:5000]).lower()
    dwi_signals = [
        "dwi", "dui", "driving while intoxicated", "intoxication",
        "blood alcohol", "49.04", "49.045", "49.07", "49.08",
        "breathalyzer", "field sobriety",
    ]
    if any(s in combined for s in dwi_signals):
        return "dwi"
    return None


def process_cap_cases(cases: list[dict], case_type_hint: str) -> list[dict]:
    """Convert CAP case records to our schema."""
    processed = []

    for case in cases:
        case_id = case.get("id", "")
        case_name = case.get("name", "Unknown")
        court = case.get("court", {})
        court_slug = court.get("slug", "") if isinstance(court, dict) else ""
        court_name = court.get("name", "") if isinstance(court, dict) else ""
        date_filed = case.get("decision_date")
        docket_number = case.get("docket_number", "")

        citations = []
        for c in case.get("citations", []):
            if isinstance(c, dict):
                citations.append(c.get("cite", str(c)))
            else:
                citations.append(str(c))

        text = extract_opinion_text(case)
        case_type = classify_dwi(case_name, text) or case_type_hint
        outcome = extract_outcome(text)
        statutes = extract_statutes(text or "")

        record = {
            "source": "cap",
            "source_id": f"cap-{case_id}",
            "case_name": case_name,
            "court": court_slug,
            "court_full_name": court_name,
            "date_filed": date_filed,
            "docket_number": docket_number,
            "citations": citations,
            "case_type": case_type,
            "opinion_type": "majority",
            "opinion_text": text[:500000] if text else None,
            "summary": (text[:500] + "...") if text and len(text) > 500 else text,
            "outcome": outcome,
            "judges": [],
            "statutes_cited": statutes,
            "tags": [case_type] if case_type else [],
            "metadata": json.dumps({
                "cap_id": case_id,
                "cap_url": case.get("url", ""),
                "frontend_url": case.get("frontend_url", ""),
            }),
        }
        processed.append(record)

    return processed


def insert_opinions(db_url: str, opinions: list[dict]) -> int:
    """Insert opinions into the database, skipping duplicates."""
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    inserted = 0

    for op in opinions:
        try:
            cur.execute("""
                INSERT INTO case_opinions
                    (source, source_id, case_name, court, court_full_name,
                     date_filed, docket_number, citations, case_type,
                     opinion_type, opinion_text, summary, outcome,
                     judges, statutes_cited, tags, metadata)
                VALUES
                    (%(source)s, %(source_id)s, %(case_name)s, %(court)s,
                     %(court_full_name)s, %(date_filed)s, %(docket_number)s,
                     %(citations)s, %(case_type)s, %(opinion_type)s,
                     %(opinion_text)s, %(summary)s, %(outcome)s,
                     %(judges)s, %(statutes_cited)s, %(tags)s, %(metadata)s)
                ON CONFLICT (source_id) DO NOTHING
            """, op)
            if cur.rowcount > 0:
                inserted += 1
        except Exception as e:
            print(f"  Error inserting {op.get('case_name', '?')}: {e}")
            conn.rollback()
            continue

    conn.commit()
    cur.close()
    conn.close()
    return inserted


def main():
    parser = argparse.ArgumentParser(description="Fetch Texas DWI cases from CAP")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--after", type=str, default="2000-01-01")
    args = parser.parse_args()

    db_url = os.getenv("DATABASE_URL", "")
    if not db_url and not args.dry_run:
        print("ERROR: DATABASE_URL not set in .env")
        sys.exit(1)

    print("=" * 60)
    print("LawLord — CAP Data Fetch")
    print(f"Jurisdiction: Texas")
    print(f"Date range: {args.after} → 2018 (CAP coverage limit)")
    print(f"Max pages per query: {args.max_pages}")
    print(f"Dry run: {args.dry_run}")
    print("=" * 60)

    all_processed = []

    for term in DWI_SEARCH_TERMS:
        print(f"\nSearching: '{term}'")
        cases = search_cases(
            query=term,
            jurisdiction="tex",
            decision_date_min=args.after,
            max_pages=args.max_pages,
        )
        if cases:
            processed = process_cap_cases(cases, "dwi")
            all_processed.extend(processed)

    seen_ids = set()
    unique = []
    for op in all_processed:
        if op["source_id"] not in seen_ids:
            seen_ids.add(op["source_id"])
            unique.append(op)

    print(f"\nTotal unique cases: {len(unique)}")

    if args.dry_run:
        print("\nDRY RUN — not saving to database.")
        if unique:
            sample = unique[0]
            print(f"\nSample: {sample['case_name']}")
            print(f"  Court: {sample['court']}")
            print(f"  Date: {sample['date_filed']}")
            print(f"  Outcome: {sample['outcome']}")
    else:
        print(f"\nInserting {len(unique)} opinions into database...")
        inserted = insert_opinions(db_url, unique)
        print(f"Inserted {inserted} new opinions.")

    print("\nDone.")


if __name__ == "__main__":
    main()
