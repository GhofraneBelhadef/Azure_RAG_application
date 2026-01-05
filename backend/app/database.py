import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()  # Loads environment variables from a .env file

def get_db_connection():
    """Establishes and returns a connection to the PostgreSQL database."""
    # Use the connection string from your Azure portal
    # Format: postgresql://citus:{password}@{host}:5432/citus?sslmode=require
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),        # e.g., "c-ragproject.ncyhdykhxaxem5.postgres.cosmos.azure.com"
        database=os.getenv("DB_NAME"),    # "citus"
        user=os.getenv("DB_USER"),        # "citus"
        password=os.getenv("DB_PASSWORD"),# Your password
        port=os.getenv("DB_PORT", 5432),
        sslmode="require"
    )
    return conn

# Test the connection immediately
if __name__ == "__main__":
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        db_version = cursor.fetchone()
        print("✅ Database connection successful!")
        print(f"📊 PostgreSQL version: {db_version[0]}")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"❌ Database connection failed: {e}")