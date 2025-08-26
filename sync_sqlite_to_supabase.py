import requests
import psycopg2
import os

# Supabase credentials
SUPABASE_URL = "https://htpopjmdkashvoxlyosn.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imh0cG9wam1ka2FzaHZveGx5b3NuIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1NTU0MjkzNSwiZXhwIjoyMDcxMTE4OTM1fQ.-JdQ-Zzt5raMb7xfzy5iJRSHGYFCi364I24aZR-R0dE"  # ⚠️ Use service_role key for schema changes
DATABASE_URL = "postgresql://postgres:pDCwlxddJGjwSEOi@db.htpopjmdkashvoxlyosn.supabase.co:5432/postgres"

# Example: Your Django models (simplified)
EXPECTED_TABLES = {
    "tours": """
        CREATE TABLE IF NOT EXISTS tours (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            price_per_person NUMERIC,
            duration_days INT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """,
    "bookings": """
        CREATE TABLE IF NOT EXISTS bookings (
            id SERIAL PRIMARY KEY,
            user_name TEXT,
            tour_id INT REFERENCES tours(id),
            created_at TIMESTAMP DEFAULT NOW()
        )
    """
}

def ensure_tables():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        for table, create_sql in EXPECTED_TABLES.items():
            print(f"Ensuring table: {table}")
            cur.execute(create_sql)

        conn.commit()
        cur.close()
        conn.close()
        print("✅ All missing tables have been created in Supabase.")
    except Exception as e:
        print("❌ Error:", e)

if __name__ == "__main__":
    ensure_tables()
