# rag_engine.py - Fixed version with authentication
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import os
import psycopg2
import json
from database import get_db_connection
from datetime import datetime, timedelta
import uuid

# Import shared dependencies
from shared_dependencies import chat_client, budget_tracker, create_embedding

# Import security
from security import get_current_active_user, TokenData, , require_admin

router = APIRouter(prefix="/chat", tags=["rag engine"])

# Pydantic model for chat request
class ChatRequest(BaseModel):
    question: str
    use_public_data: bool = True

def search_similar_chunks(query_embedding: list, user_id: str, use_public_data: bool = True, limit: int = 5):
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

def get_chunk_source_info(chunk_ids: list):
    if not chunk_ids:
        return []
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
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

# Protected endpoint - Chat with RAG
@router.post("/ask")
def chat_with_rag(
    chat_request: ChatRequest,
    current_user: TokenData = Depends(get_current_active_user)
):
    try:
        # 1. Create embedding for the question
        query_embedding = create_embedding(chat_request.question)
        
        # 2. Search for similar chunks
        similar_chunks = search_similar_chunks(
            query_embedding, 
            current_user.user_id, 
            chat_request.use_public_data,
            limit=5
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
        recent_history = get_recent_conversation_history(current_user.user_id)
        
        # 4. Prepare the prompt
        prompt = f"""You are a helpful assistant. Use the following context to answer the question.

Recent conversation history:
{recent_history}

Relevant context from documents:
{context}

Question: {chat_request.question}

Provide a helpful answer based on the context above. If the context doesn't contain relevant information, say so.

After your answer, briefly mention which context excerpts (if any) were most relevant to your response."""

        # 5. Generate response
        response = chat_client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT"),
            messages=[
                {"role": "system", "content": "You are a helpful assistant that answers questions based on provided context."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500
        )
        
        ai_response = response.choices[0].message.content
        
        # 6. Get source document information
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
        """, (chat_id, current_user.user_id, chat_request.question, ai_response, chunk_ids, datetime.utcnow()))
        
        # Log activity
        details = json.dumps({
            "question_length": len(chat_request.question),
            "chunks_used": len(chunk_ids),
            "chunk_ids": chunk_ids
        })
        cursor.execute("""
            INSERT INTO activity_log (user_id, activity_type, details)
            VALUES (%s, %s, %s)
        """, (current_user.user_id, 'CHAT', details))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        # 8. Prepare response
        response_data = {
            "answer": ai_response,
            "chunks_used": len(chunk_ids),
            "chunks": chunk_details,
            "sources": source_info,
            "chat_id": chat_id,
            "budget_status": budget_tracker.get_status()
        }
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

# Protected endpoint - Get chat chunks
@router.get("/chat/{chat_id}/chunks")
def get_chat_chunks(
    chat_id: str,
    current_user: TokenData = Depends(get_current_active_user)
):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get the chat to find chunk IDs
        cursor.execute("""
            SELECT user_id, context_chunk_ids FROM chat_history WHERE chat_id = %s
        """, (chat_id,))
        
        result = cursor.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Chat not found")
        
        chat_user_id, chunk_ids = result
        
        # Check ownership
        if chat_user_id != current_user.user_id and not current_user.is_admin:
            raise HTTPException(status_code=403, detail="You don't have permission to access this chat")
        
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

# Protected endpoint - Cleanup old conversations
@router.post("/cleanup")
def cleanup_old_conversations(
    days_old: int = 30,
    current_user: TokenData = Depends(get_current_active_user)
):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        cursor.execute("""
            DELETE FROM chat_history 
            WHERE user_id = %s AND created_at < %s
            RETURNING COUNT(*)
        """, (current_user.user_id, cutoff_date))
        
        deleted_count = cursor.fetchone()[0]
        conn.commit()
        
        return {"message": f"Deleted {deleted_count} old conversations"}
        
    finally:
        cursor.close()
        conn.close()

# Admin-only endpoint - Cleanup all conversations
@router.post("/admin/cleanup-all")
def cleanup_all_conversations(
    days_old: int = 30,
    current_user: TokenData = Depends(require_admin)
):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        cursor.execute("""
            DELETE FROM chat_history 
            WHERE created_at < %s
            RETURNING COUNT(*)
        """, (cutoff_date,))
        
        deleted_count = cursor.fetchone()[0]
        conn.commit()
        
        return {"message": f"Deleted {deleted_count} old conversations for all users"}
        
    finally:
        cursor.close()
        conn.close()

# Public endpoint - Budget status
@router.get("/budget")
def get_chat_budget():
    return {
        "chat_budget": budget_tracker.get_status(),
        "max_budget": budget_tracker.max_budget
    }
