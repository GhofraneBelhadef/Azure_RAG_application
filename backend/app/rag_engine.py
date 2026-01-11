# rag_engine.py - Modified to return chunk contents
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import psycopg2
import json
from database import get_db_connection
from datetime import datetime, timedelta
import uuid
from typing import List, Dict, Any

# Import shared dependencies
from shared_dependencies import chat_client, budget_tracker, create_embedding

router = APIRouter(prefix="/chat", tags=["rag engine"])

# Pydantic model for chat request
class ChatRequest(BaseModel):
    user_id: str
    question: str
    use_public_data: bool = True

# Pydantic model for chunk data
class ChunkData(BaseModel):
    chunk_id: str
    content: str
    similarity: float

def search_similar_chunks(query_embedding: list, user_id: str, use_public_data: bool = True, limit: int = 5) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        embedding_array = "[" + ",".join(map(str, query_embedding)) + "]"
        
        if use_public_data:
            query = """
                SELECT chunk_id, chunk_text,
                       embedding <-> %s::vector as similarity,
                       document_id
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
                       embedding <-> %s::vector as similarity,
                       document_id
                FROM document_chunks
                WHERE user_id = %s
                ORDER BY similarity
                LIMIT %s
            """
            params = (embedding_array, user_id, limit)
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        
        chunks = []
        for chunk in results:
            chunks.append({
                "chunk_id": chunk[0],
                "content": chunk[1],
                "similarity": float(chunk[2]),
                "document_id": chunk[3]
            })
        
        return chunks
        
    finally:
        cursor.close()
        conn.close()

def get_chunk_source_info(chunk_ids: List[str]) -> List[Dict[str, Any]]:
    """Get source document information for chunks"""
    if not chunk_ids:
        return []
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Create a string of chunk IDs for SQL IN clause
        chunk_ids_str = ",".join([f"'{chunk_id}'" for chunk_id in chunk_ids])
        
        query = f"""
            SELECT 
                dc.chunk_id,
                dc.chunk_text,
                d.filename,
                d.document_id,
                u.username
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.document_id
            JOIN users u ON d.user_id = u.user_id
            WHERE dc.chunk_id IN ({chunk_ids_str})
        """
        
        cursor.execute(query)
        results = cursor.fetchall()
        
        sources = []
        for result in results:
            sources.append({
                "chunk_id": result[0],
                "content": result[1],
                "filename": result[2],
                "document_id": result[3],
                "uploaded_by": result[4]
            })
        
        return sources
        
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
        
        # 2. Search for similar chunks with more details
        similar_chunks = search_similar_chunks(
            query_embedding, 
            chat_request.user_id, 
            chat_request.use_public_data,
            limit=5  # Get top 5 chunks
        )
        
        if not similar_chunks:
            context = "No relevant documents found."
            chunk_ids = []
            chunk_details = []
        else:
            # Prepare context for LLM
            context_chunks = []
            chunk_ids = []
            chunk_details = []
            
            for chunk in similar_chunks:
                chunk_ids.append(chunk["chunk_id"])
                context_chunks.append(chunk["content"])
                
                # Store chunk details for response
                chunk_details.append({
                    "chunk_id": chunk["chunk_id"],
                    "content_preview": chunk["content"][:200] + ("..." if len(chunk["content"]) > 200 else ""),
                    "similarity_score": chunk["similarity"],
                    "document_id": chunk["document_id"]
                })
            
            context = "\n\n".join([f"Document excerpt {i+1}:\n{chunk}" 
                                 for i, chunk in enumerate(context_chunks)])
        
        # 3. Get recent conversation history
        recent_history = get_recent_conversation_history(chat_request.user_id)
        
        # 4. Prepare the prompt with numbered chunks
        prompt = f"""You are a helpful assistant. Use the following context to answer the question.

Recent conversation history:
{recent_history}

Relevant context from documents:
{context}

Question: {chat_request.question}

Provide a helpful answer based on the context above. If the context doesn't contain relevant information, say so.

After your answer, briefly mention which context excerpts (if any) were most relevant to your response."""

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
        
        # 6. Get source document information for the chunks used
        source_info = []
        if chunk_details:
            source_info = get_chunk_source_info(chunk_ids)
        
        # 7. Store the conversation
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
            "chunks_used": len(chunk_ids),
            "chunk_ids": chunk_ids
        })
        cursor.execute("""
            INSERT INTO activity_log (user_id, activity_type, details)
            VALUES (%s, %s, %s)
        """, (chat_request.user_id, 'CHAT', details))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        # 8. Prepare response with chunk details
        response_data = {
            "answer": ai_response,
            "chunks_used": len(chunk_ids),
            "chunks": chunk_details,  # Basic chunk info with preview
            "sources": source_info,   # Full source information
            "chat_id": chat_id,
            "budget_status": budget_tracker.get_status()
        }
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

# New endpoint to get detailed chunk info
@router.get("/chat/{chat_id}/chunks")
def get_chat_chunks(chat_id: str):
    """Get the chunks used for a specific chat"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get the chat to find chunk IDs
        cursor.execute("""
            SELECT context_chunk_ids FROM chat_history WHERE chat_id = %s
        """, (chat_id,))
        
        result = cursor.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Chat not found")
        
        chunk_ids = result[0] or []
        
        if not chunk_ids:
            return {"chunks": [], "sources": []}
        
        # Get chunk details
        cursor.execute("""
            SELECT 
                dc.chunk_id,
                dc.chunk_text,
                dc.created_at,
                d.filename,
                d.document_id,
                u.username
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.document_id
            JOIN users u ON d.user_id = u.user_id
            WHERE dc.chunk_id = ANY(%s)
            ORDER BY array_position(%s::text[], dc.chunk_id)
        """, (chunk_ids, chunk_ids))
        
        chunks = cursor.fetchall()
        
        formatted_chunks = []
        for chunk in chunks:
            formatted_chunks.append({
                "chunk_id": chunk[0],
                "content": chunk[1],
                "created_at": chunk[2].isoformat() if chunk[2] else None,
                "filename": chunk[3],
                "document_id": chunk[4],
                "uploaded_by": chunk[5]
            })
        
        return {
            "chat_id": chat_id,
            "chunks": formatted_chunks,
            "total_chunks": len(chunks)
        }
        
    finally:
        cursor.close()
        conn.close()

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