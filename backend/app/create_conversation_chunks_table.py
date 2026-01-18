# create_conversation_chunks_table.py
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def create_conversation_chunks_table():
    """Create a new table for conversation chunks (optional - we can use in-memory)"""
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME", "citus"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT", 5432),
        sslmode="require"
    )
    
    cursor = conn.cursor()
    
    try:
        # Create table for conversation chunks (if you want persistent storage)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_chunks (
                chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                conversation_text TEXT NOT NULL,
                embedding vector(1536),
                source_chat_ids UUID[],
                created_at TIMESTAMPTZ DEFAULT now(),
                expires_at TIMESTAMPTZ DEFAULT (now() + INTERVAL '7 days')
            )
        """)
        
        # Create index for similarity search
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS conversation_chunks_embedding_idx 
            ON conversation_chunks 
            USING hnsw (embedding vector_cosine_ops)
        """)
        
        # Create index for user_id
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS conversation_chunks_user_id_idx 
            ON conversation_chunks (user_id)
        """)
        
        # Create index for expiration
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS conversation_chunks_expires_idx 
            ON conversation_chunks (expires_at)
        """)
        
        conn.commit()
        print("✅ Created conversation_chunks table (optional storage)")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error creating table: {e}")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    create_conversation_chunks_table()