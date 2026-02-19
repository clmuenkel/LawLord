"""
Fetch Texas DWI case opinions from CourtListener REST API.

CourtListener is the primary source for Texas appellate court opinions
related to DWI/DUI cases. The data comes from both the Free Law Project's
own scraping and the Harvard Caselaw Access Project (CAP).

Usage:
    python -m data.fetch_courtlistener              # uses .env config
    python -m data.fetch_courtlistener --dry-run     # preview without saving

Requirements:
    - CourtListener API token (free: courtlistener.com/sign-in/)
    - DATABASE_URL in .env pointing to Neon
    - psycopg2 installed

Texas Courts of Interest:
    texcrimapp  — Texas Court of Criminal Appeals (highest criminal court)
    texapp      — Texas Courts of Appeals (14 intermediate appellate districts)
    tex         — Texas Supreme Court (rare for criminal, but occasionally relevant)
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv

load_dotenv()

API_BASE = "https://www.courtlistener.com/api/rest/v4"

TEXAS_CRIMINAL_COURTS = [
    "texcrimapp",
    "texapp",
]

DWI_SEARCH_QUERIES = [
    "DWI",
    "driving while intoxicated",
    "intoxication manslaughter",
    "intoxication assault",
    "blood alcohol",
    "breathalyzer",
    "field sobriety",
    "implied consent",
]

PARKING_SEARCH_QUERIES = [
    "parking violation",
    "parking ticket",
    "handicap parking",
    "disabled parking placard",
    "parking fine",
]

STATUTE_PATTERNS_DWI = [
    r"49\.04",
    r"49\.045",
    r"49\.07",
    r"49\.08",
    r"49\.09",
    r"49\.01",
]


def fetch_opinions(
    token: str,
    query: str,
    courts: list[str],
    after_date: str = "2005-01-01",
    max_pages: int = 100,
) -> list[dict]:
    """Fetch opinions from CourtListener search API."""
    # v4 API uses fielded search in the q parameter
    court_clause = " OR ".join(f"court_id:{c}" for c in courts)
    full_query = f'({query}) AND ({court_clause}) AND dateFiled:[{after_date} TO *]'

    all_results = []
    url = f"{API_BASE}/search/"

    params = {
        "q": full_query,
        "type": "o",
        "order_by": "dateFiled desc",
        "stat_Published": "on",
        "page_size": 20,
    }

    headers = {"Authorization": f"Token {token}"}

    page = 0
    while url and page < max_pages:
        page += 1
        print(f"  Fetching page {page} for query '{query}'...")

        try:
            resp = requests.get(url, params=params if page == 1 else None, headers=headers)
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 30))
                print(f"  Rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)
                continue
            print(f"  HTTP error: {e}")
            break

        data = resp.json()
        results = data.get("results", [])
        all_results.extend(results)
        print(f"  Got {len(results)} results (total so far: {len(all_results)})")

        url = data.get("next")
        params = None

        time.sleep(1.5)

    return all_results


def fetch_opinion_detail(token: str, opinion_id: int) -> dict | None:
    """Fetch full opinion text for a single opinion."""
    url = f"{API_BASE}/opinions/{opinion_id}/"
    headers = {"Authorization": f"Token {token}"}

    try:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  Error fetching opinion {opinion_id}: {e}")
        return None


def classify_case(case_name: str, text: str) -> str | None:
    """Classify a case as 'dwi' or 'parking_ticket' based on content."""
    combined = (case_name + " " + (text or "")[:5000]).lower()

    for pattern in STATUTE_PATTERNS_DWI:
        if re.search(pattern, combined):
            return "dwi"

    dwi_keywords = ["dwi", "dui", "driving while intoxicated", "intoxication",
                     "blood alcohol", "bac", "breathalyzer", "field sobriety",
                     "implied consent", "intoxication manslaughter",
                     "intoxication assault"]
    if any(kw in combined for kw in dwi_keywords):
        return "dwi"

    parking_keywords = ["parking violation", "parking ticket", "parking fine",
                        "handicap parking", "disabled parking"]
    if any(kw in combined for kw in parking_keywords):
        return "parking_ticket"

    return None


def extract_outcome(text: str) -> str | None:
    """Try to extract the case outcome from opinion text."""
    if not text:
        return None
    last_paragraphs = text[-2000:].lower()
    outcomes = [
        ("affirmed", ["affirm", "we affirm", "judgment is affirmed", "conviction is affirmed"]),
        ("reversed", ["reverse", "we reverse", "judgment is reversed"]),
        ("remanded", ["remand", "we remand"]),
        ("reversed and remanded", ["reverse and remand", "reversed and remanded"]),
        ("dismissed", ["dismiss", "we dismiss", "appeal is dismissed"]),
        ("abated", ["abated", "appeal abated"]),
    ]
    for outcome, patterns in outcomes:
        if any(p in last_paragraphs for p in patterns):
            return outcome
    return None


def extract_statutes(text: str) -> list[str]:
    """Extract Texas Penal Code statute references from opinion text."""
    if not text:
        return []
    pattern = r"(?:Tex(?:as)?\.?\s*)?(?:Penal|Transp(?:ortation)?|Gov(?:ernment)?)\.?\s*Code\s*(?:Ann(?:otated)?\.?\s*)?§?\s*(\d+\.\d+)"
    matches = re.findall(pattern, text, re.IGNORECASE)
    seen = set()
    statutes = []
    for m in matches:
        key = m.strip()
        if key not in seen:
            seen.add(key)
            statutes.append(f"§ {key}")
    return statutes


def extract_judges(result: dict) -> list[str]:
    """Extract judge names from a search result."""
    judges_str = result.get("judge", "") or ""
    if not judges_str:
        return []
    judges_str = re.sub(r"(?:Chief\s+)?Justice\s+", "", judges_str)
    return [j.strip() for j in re.split(r"[,;]|and\s+", judges_str) if j.strip()]


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


def process_search_results(
    token: str,
    results: list[dict],
    case_type_hint: str,
    fetch_full_text: bool = True,
) -> list[dict]:
    """Convert CourtListener search results to our schema format."""
    processed = []

    for i, r in enumerate(results):
        case_name = r.get("caseName", "") or r.get("case_name", "") or "Unknown"
        court = r.get("court", "") or r.get("court_id", "") or ""
        court_full = r.get("court_citation_string", "") or ""
        date_filed = r.get("dateFiled") or r.get("date_filed")
        docket_number = r.get("docketNumber") or r.get("docket_number") or ""

        snippet = r.get("snippet", "") or ""
        text = snippet

        opinion_id = r.get("id") or r.get("cluster_id")

        if fetch_full_text and opinion_id:
            if i > 0 and i % 10 == 0:
                print(f"  Fetching full text... ({i}/{len(results)})")
                time.sleep(1)
            detail = fetch_opinion_detail(token, opinion_id)
            if detail:
                text = (
                    detail.get("plain_text")
                    or detail.get("html_with_citations")
                    or detail.get("html")
                    or snippet
                )
                if text and text.startswith("<"):
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"\s+", " ", text).strip()

        case_type = classify_case(case_name, text) or case_type_hint
        outcome = extract_outcome(text)
        statutes = extract_statutes(text)
        judges = extract_judges(r)

        citations = []
        if r.get("citation"):
            citations = r["citation"] if isinstance(r["citation"], list) else [r["citation"]]
        elif r.get("citations"):
            citations = [c.get("cite", str(c)) for c in r["citations"]] if isinstance(r["citations"], list) else []

        record = {
            "source": "courtlistener",
            "source_id": f"cl-{opinion_id}" if opinion_id else f"cl-{hash(case_name + str(date_filed))}",
            "case_name": case_name,
            "court": court,
            "court_full_name": court_full,
            "date_filed": date_filed,
            "docket_number": docket_number,
            "citations": citations,
            "case_type": case_type,
            "opinion_type": r.get("type", "majority"),
            "opinion_text": text[:500000] if text else None,
            "summary": (text[:500] + "...") if text and len(text) > 500 else text,
            "outcome": outcome,
            "judges": judges,
            "statutes_cited": statutes,
            "tags": [case_type] if case_type else [],
            "metadata": json.dumps({
                "courtlistener_url": f"https://www.courtlistener.com/opinion/{opinion_id}/",
                "court_id": court,
                "date_filed": date_filed,
            }),
        }
        processed.append(record)

    return processed


def main():
    parser = argparse.ArgumentParser(description="Fetch Texas DWI cases from CourtListener")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving to DB")
    parser.add_argument("--no-full-text", action="store_true", help="Skip fetching full opinion text (faster)")
    parser.add_argument("--max-pages", type=int, default=50, help="Max pages per query (20 results/page)")
    parser.add_argument("--after", type=str, default="2005-01-01", help="Only cases filed after this date")
    args = parser.parse_args()

    token = os.getenv("COURTLISTENER_API_TOKEN", "")
    db_url = os.getenv("DATABASE_URL", "")

    if not token:
        print("ERROR: COURTLISTENER_API_TOKEN not set in .env")
        print("Get a free token at: https://www.courtlistener.com/sign-in/")
        print("Then go to: https://www.courtlistener.com/profile/api/")
        sys.exit(1)

    if not db_url and not args.dry_run:
        print("ERROR: DATABASE_URL not set in .env")
        sys.exit(1)

    print("=" * 60)
    print("LawLord — CourtListener Data Fetch")
    print(f"Courts: {', '.join(TEXAS_CRIMINAL_COURTS)}")
    print(f"Date range: {args.after} → present")
    print(f"Max pages per query: {args.max_pages}")
    print(f"Fetch full text: {not args.no_full_text}")
    print(f"Dry run: {args.dry_run}")
    print("=" * 60)

    all_processed = []

    # --- DWI cases ---
    print("\n--- Fetching DWI cases ---")
    for query in DWI_SEARCH_QUERIES:
        results = fetch_opinions(
            token, query, TEXAS_CRIMINAL_COURTS,
            after_date=args.after, max_pages=args.max_pages,
        )
        if results:
            processed = process_search_results(
                token, results, "dwi",
                fetch_full_text=not args.no_full_text,
            )
            all_processed.extend(processed)
        print(f"  '{query}': {len(results)} results")

    # --- Parking cases (will likely be sparse) ---
    print("\n--- Fetching parking violation cases ---")
    for query in PARKING_SEARCH_QUERIES:
        results = fetch_opinions(
            token, query, TEXAS_CRIMINAL_COURTS,
            after_date=args.after, max_pages=args.max_pages,
        )
        if results:
            processed = process_search_results(
                token, results, "parking_ticket",
                fetch_full_text=not args.no_full_text,
            )
            all_processed.extend(processed)
        print(f"  '{query}': {len(results)} results")

    # Deduplicate by source_id
    seen_ids = set()
    unique = []
    for op in all_processed:
        if op["source_id"] not in seen_ids:
            seen_ids.add(op["source_id"])
            unique.append(op)

    print(f"\nTotal unique opinions: {len(unique)}")
    dwi_count = sum(1 for o in unique if o["case_type"] == "dwi")
    parking_count = sum(1 for o in unique if o["case_type"] == "parking_ticket")
    print(f"  DWI: {dwi_count}")
    print(f"  Parking: {parking_count}")

    if args.dry_run:
        print("\nDRY RUN — not saving to database.")
        if unique:
            print("\nSample case:")
            sample = unique[0]
            print(f"  Name: {sample['case_name']}")
            print(f"  Court: {sample['court']}")
            print(f"  Date: {sample['date_filed']}")
            print(f"  Type: {sample['case_type']}")
            print(f"  Outcome: {sample['outcome']}")
            print(f"  Statutes: {sample['statutes_cited']}")
            text_preview = (sample.get('opinion_text') or '')[:200]
            print(f"  Text preview: {text_preview}...")
    else:
        print(f"\nInserting {len(unique)} opinions into database...")
        inserted = insert_opinions(db_url, unique)
        print(f"Inserted {inserted} new opinions ({len(unique) - inserted} duplicates skipped).")

    print("\nDone.")


if __name__ == "__main__":
    main()
