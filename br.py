import os
import sqlite3
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

# Load env
load_dotenv()

SQLITE_DB_PATH = "/mnt/mukoil/MY PROJECTS 2025/airport_destinations/db.sqlite3"
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("Missing DATABASE_URL in .env file!")

def connect_sqlite():
    return sqlite3.connect(SQLITE_DB_PATH)

def connect_postgres():
    return psycopg2.connect(DATABASE_URL)

def get_sqlite_tables(cur):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    return [row[0] for row in cur.fetchall() if not row[0].startswith("sqlite_")]

def get_postgres_tables(cur):
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public';")
    return [row[0] for row in cur.fetchall()]

def get_postgres_column_types(pg_cur, table_name):
    """
    Return dict {col_name: data_type} for a Postgres table
    """
    pg_cur.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        """,
        (table_name,)
    )
    return {row[0]: row[1] for row in pg_cur.fetchall()}

def create_table_in_postgres(pg_cur, table_name, sqlite_cur):
    sqlite_cur.execute(f"PRAGMA table_info({table_name});")
    columns = sqlite_cur.fetchall()
    col_defs = []
    for col in columns:
        col_name = col[1]
        col_type = col[2].upper()
        if "INT" in col_type:
            pg_type = "INTEGER"
        elif "CHAR" in col_type or "CLOB" in col_type or "TEXT" in col_type:
            pg_type = "TEXT"
        elif "BLOB" in col_type:
            pg_type = "BYTEA"
        elif "REAL" in col_type or "FLOA" in col_type or "DOUB" in col_type:
            pg_type = "DOUBLE PRECISION"
        else:
            pg_type = "TEXT"
        col_defs.append(f"{col_name} {pg_type}")

    create_stmt = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(col_defs)});'
    pg_cur.execute(create_stmt)

def cast_row_for_postgres(row, cols, pg_types):
    """
    Convert SQLite row values to types Postgres expects
    """
    new_row = []
    for col, val in zip(cols, row):
        pg_type = pg_types.get(col)
        if pg_type == "boolean":
            if val in (0, 1):
                new_row.append(bool(val))
            else:
                new_row.append(None if val is None else bool(val))
        else:
            new_row.append(val)
    return tuple(new_row)

def sync_data(sqlite_cur, pg_cur, pg_conn, table_name):
    sqlite_cur.execute(f"SELECT * FROM {table_name}")
    rows = sqlite_cur.fetchall()
    if not rows:
        return

    sqlite_cur.execute(f"PRAGMA table_info({table_name});")
    cols = [col[1] for col in sqlite_cur.fetchall()]
    col_placeholders = ", ".join(["%s"] * len(cols))
    col_names = ", ".join([f'"{c}"' for c in cols])

    # Get Postgres column types
    pg_types = get_postgres_column_types(pg_cur, table_name)

    insert_stmt = sql.SQL(
        f'INSERT INTO "{table_name}" ({col_names}) VALUES ({col_placeholders}) ON CONFLICT DO NOTHING'
    )

    for row in rows:
        try:
            new_row = cast_row_for_postgres(row, cols, pg_types)
            pg_cur.execute(insert_stmt, new_row)
        except Exception as e:
            print(f"[ERROR] inserting into {table_name}: {e}")
    pg_conn.commit()

def main():
    sqlite_conn = connect_sqlite()
    sqlite_cur = sqlite_conn.cursor()
    pg_conn = connect_postgres()
    pg_cur = pg_conn.cursor()

    sqlite_tables = get_sqlite_tables(sqlite_cur)
    pg_tables = get_postgres_tables(pg_cur)

    priority_tables = [
        "auth_user", "auth_group", "auth_permission",
        "django_content_type", "django_migrations",
        "auth_user_groups", "auth_user_user_permissions", "auth_group_permissions",
        "django_admin_log",
    ]

    for table in priority_tables:
        if table in sqlite_tables:
            if table not in pg_tables:
                print(f"[INFO] Creating missing table: {table}")
                create_table_in_postgres(pg_cur, table, sqlite_cur)
                pg_conn.commit()
            print(f"[INFO] Syncing {table} ...")
            sync_data(sqlite_cur, pg_cur, pg_conn, table)

    for table in sqlite_tables:
        if table in priority_tables:
            continue
        if table not in pg_tables:
            print(f"[INFO] Creating missing table: {table}")
            create_table_in_postgres(pg_cur, table, sqlite_cur)
            pg_conn.commit()
        print(f"[INFO] Syncing {table} ...")
        sync_data(sqlite_cur, pg_cur, pg_conn, table)

    sqlite_conn.close()
    pg_cur.close()
    pg_conn.close()
    print("[SUCCESS] Sync complete!")

if __name__ == "__main__":
    main()
