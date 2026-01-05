# rag_engine.py - Fixed version without circular imports and proper JSON
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import psycopg2
import json  # Added for proper JSON serialization
from database import get_db_connection
from datetime import datetime, timedelta
import uuid

# Import shared dependencies
from shared_dependencies import chat_client, budget_tracker, create_embedding

router = APIRouter(prefix="/chat", tags=["rag engine"])

# Pydantic model for chat request
class ChatRequest(BaseModel):
    user_id: str
    question: str
    use_public_data: bool = True

def search_similar_chunks(query_embedding: list, user_id: str, use_public_data: bool = True, limit: int = 3):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        embedding_array = "[" + ",".join(map(str, query_embedding)) + "]"
        
        if use_public_data:
            query = """
                SELECT chunk_id, chunk_text,
                       embedding <-> %s::vector as similarity
                FROM document_chunks
                WHERE user_id = %s 
                   OR document_id IN (SELECT document_id FROM documents WHERE is_public = true)
                ORDER BY similarity
                LIMIT %s
            """
            params = (embedding_array, user_id, limit)
        else:
            query = """
                SELECT chunk_id, chunk_text,
                       embedding <-> %s::vector as similarity
                FROM document_chunks
                WHERE user_id = %s
                ORDER BY similarity
                LIMIT %s
            """
            params = (embedding_array, user_id, limit)
        
        cursor.execute(query, params)
        return cursor.fetchall()
        
    finally:
        cursor.close()
        conn.close()

def get_recent_conversation_history(user_id: str, hours: int = 24):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        time_threshold = datetime.utcnow() - timedelta(hours=hours)
        
        cursor.execute("""
            SELECT user_message, ai_response 
            FROM chat_history 
            WHERE user_id = %s AND created_at >= %s
            ORDER BY created_at DESC
            LIMIT 10
        """, (user_id, time_threshold))
        
        history = cursor.fetchall()
        
        history_text = ""
        for user_msg, ai_resp in reversed(history):
            history_text += f"User: {user_msg}\nAssistant: {ai_resp}\n"
        
        return history_text
        
    finally:
        cursor.close()
        conn.close()

@router.post("/ask")
def chat_with_rag(chat_request: ChatRequest):
    try:
        # 1. Create embedding for the question
        query_embedding = create_embedding(chat_request.question)
        
        # 2. Search for similar chunks
        similar_chunks = search_similar_chunks(
            query_embedding, 
            chat_request.user_id, 
            chat_request.use_public_data
        )
        
        if not similar_chunks:
            context = "No relevant documents found."
            chunk_ids = []
        else:
            context = "\n\n".join([chunk[1] for chunk in similar_chunks])
            chunk_ids = [chunk[0] for chunk in similar_chunks]
        
        # 3. Get recent conversation history
        recent_history = get_recent_conversation_history(chat_request.user_id)
        
        # 4. Prepare the prompt
        prompt = f"""You are a helpful assistant. Use the following context to answer the question.

Recent conversation history:
{recent_history}

Relevant context from documents:
{context}

Question: {chat_request.question}

Provide a helpful answer based on the context above. If the context doesn't contain relevant information, say so."""
        
        # 5. Generate response using Azure OpenAI
        response = chat_client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT"),
            messages=[
                {"role": "system", "content": "You are a helpful assistant that answers questions based on provided context."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500
        )
        
        ai_response = response.choices[0].message.content
        
        # 6. Store the conversation
        conn = get_db_connection()
        cursor = conn.cursor()
        
        chat_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO chat_history (chat_id, user_id, user_message, ai_response, context_chunk_ids, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (chat_id, chat_request.user_id, chat_request.question, ai_response, chunk_ids, datetime.utcnow()))
        
        # Log activity with proper JSON serialization
        details = json.dumps({
            "question_length": len(chat_request.question),
            "chunks_used": len(chunk_ids)
        })
        cursor.execute("""
            INSERT INTO activity_log (user_id, activity_type, details)
            VALUES (%s, %s, %s)
        """, (chat_request.user_id, 'CHAT', details))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return {
            "answer": ai_response,
            "chunks_used": len(chunk_ids),
            "chat_id": chat_id,
            "budget_status": budget_tracker.get_status()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

@router.post("/cleanup/{user_id}")
def cleanup_old_conversations(user_id: str, days_old: int = 30):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        cursor.execute("""
            DELETE FROM chat_history 
            WHERE user_id = %s AND created_at < %s
            RETURNING COUNT(*)
        """, (user_id, cutoff_date))
        
        deleted_count = cursor.fetchone()[0]
        conn.commit()
        
        return {"message": f"Deleted {deleted_count} old conversations"}
        
    finally:
        cursor.close()
        conn.close()

@router.get("/budget")
def get_chat_budget():
    return {
        "chat_budget": budget_tracker.get_status(),
        "max_budget": budget_tracker.max_budget
    }