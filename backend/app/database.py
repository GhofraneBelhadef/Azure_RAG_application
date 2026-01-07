# database.py
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    """Establishes and returns a connection to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            database=os.getenv("DB_NAME", "citus"),  # Default to "citus" if not set
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            port=os.getenv("DB_PORT", 5432),
            sslmode="require"  # Explicitly set sslmode
        )
        return conn
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        print(f"   Host: {os.getenv('DB_HOST')}")
        print(f"   Database: {os.getenv('DB_NAME')}")
        print(f"   User: {os.getenv('DB_USER')}")
        raise

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