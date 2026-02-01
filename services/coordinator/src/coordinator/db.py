import os
import psycopg

def get_conn():
    dsn = os.getenv("DB_DSN")
    if not dsn:
        raise RuntimeError("DB_DSN is not set")
    return psycopg.connect(dsn)
