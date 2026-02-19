"""
Run the LawLord schema against a Neon PostgreSQL database.

Usage:
    python -m db.setup              # uses DATABASE_URL from .env
    python -m db.setup <url>        # explicit connection string
"""

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

SCHEMA_FILE = Path(__file__).parent / "schema.sql"


def run_schema(database_url: str) -> None:
    print(f"Connecting to database...")
    conn = psycopg2.connect(database_url)
    conn.autocommit = True
    cur = conn.cursor()

    schema_sql = SCHEMA_FILE.read_text()

    print("Running schema...")
    cur.execute(schema_sql)

    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_type = 'BASE TABLE'
        ORDER BY table_name;
    """)
    tables = [row[0] for row in cur.fetchall()]
    print(f"Tables created: {', '.join(tables)}")

    cur.execute("""
        SELECT schemaname, indexname
        FROM pg_indexes
        WHERE schemaname = 'public'
        ORDER BY indexname;
    """)
    indexes = [row[1] for row in cur.fetchall()]
    print(f"Indexes created: {len(indexes)}")

    cur.close()
    conn.close()
    print("Done. Database is ready.")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else os.getenv("DATABASE_URL", "")
    if not url:
        print("ERROR: No DATABASE_URL provided.")
        print("Either set it in .env or pass as argument:")
        print("  python -m db.setup 'postgresql://...'")
        sys.exit(1)
    run_schema(url)
