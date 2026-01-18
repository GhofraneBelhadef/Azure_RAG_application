# rag_engine.py - FIXED VERSION with better document prioritization
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import os
import psycopg2
import json
from database import get_db_connection
from datetime import datetime, timedelta
import uuid
from typing import List, Dict, Any
import math

# Import shared dependencies
from shared_dependencies import chat_client, budget_tracker, create_embedding

# Import security
from security import get_current_active_user, TokenData, require_admin
from langchain_text_splitters import RecursiveCharacterTextSplitter

router = APIRouter(prefix="/chat", tags=["rag engine"])

# Pydantic model for chat request
class ChatRequest(BaseModel):
    question: str
    use_public_data: bool = True

# Constants for chunking
CONVERSATION_CHUNK_SIZE = 150
CONVERSATION_CHUNK_OVERLAP = 40

def get_conversation_text_splitter():
    """Get text splitter for conversation history"""
    return RecursiveCharacterTextSplitter(
        chunk_size=CONVERSATION_CHUNK_SIZE,
        chunk_overlap=CONVERSATION_CHUNK_OVERLAP,
        length_function=len,
        separators=["\n\n", "\n", ". ", "! ", "? ", " ", ""]
    )

def get_recent_conversation_chunks(user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Get the last N conversations, chunk them, and create embeddings
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get last N conversations for this user
        cursor.execute("""
            SELECT user_message, ai_response, created_at 
            FROM chat_history 
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (user_id, limit))
        
        conversations = cursor.fetchall()
        
        if not conversations:
            return []
        
        # Combine conversations into text
        conversation_texts = []
        for user_msg, ai_resp, created_at in reversed(conversations):
            conversation_texts.append(f"[User] {user_msg}")
            conversation_texts.append(f"[Assistant] {ai_resp}")
        
        full_text = "\n".join(conversation_texts)
        
        # Split into chunks
        text_splitter = get_conversation_text_splitter()
        chunks = text_splitter.split_text(full_text)
        
        # Create embeddings for each chunk
        conversation_chunks = []
        for chunk in chunks:
            if chunk.strip():  # Only process non-empty chunks
                try:
                    embedding = create_embedding(chunk)
                    conversation_chunks.append({
                        "text": chunk,
                        "embedding": embedding,
                        "type": "conversation",
                        "source": "conversation"
                    })
                except Exception as e:
                    print(f"Warning: Failed to create embedding for conversation chunk: {str(e)}")
                    continue
        
        return conversation_chunks
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing conversation chunks: {str(e)}")
    finally:
        cursor.close()
        conn.close()

def search_similar_chunks(query_embedding: list, user_id: str, use_public_data: bool = True, limit: int = 5):
    """Search for similar chunks in documents"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        embedding_array = "[" + ",".join(map(str, query_embedding)) + "]"
        
        if use_public_data:
            query = """
                SELECT chunk_id, chunk_text,
                       1 - (embedding <-> %s::vector) as similarity,
                       document_id
                FROM document_chunks
                WHERE user_id = %s 
                   OR document_id IN (SELECT document_id FROM documents WHERE is_public = true)
                ORDER BY similarity DESC
                LIMIT %s
            """
            params = (embedding_array, user_id, limit)
        else:
            query = """
                SELECT chunk_id, chunk_text,
                       1 - (embedding <-> %s::vector) as similarity,
                       document_id
                FROM document_chunks
                WHERE user_id = %s
                ORDER BY similarity DESC
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
                "document_id": chunk[3],
                "type": "document",
                "source": "document"
            })
        
        return chunks
        
    finally:
        cursor.close()
        conn.close()

def cosine_similarity(vec1: list, vec2: list) -> float:
    """Calculate cosine similarity between two vectors WITHOUT numpy"""
    try:
        if len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    except Exception as e:
        print(f"Error in cosine similarity: {e}")
        return 0.0

def is_personal_question(question: str) -> bool:
    """Check if the question is about personal/user information"""
    question_lower = question.lower()
    
    personal_keywords = [
        "my name", "i am", "i'm", "call me", "who am i", "my age", "how old",
        "where do i live", "my address", "my email", "my phone", "my number",
        "remember", "my favorite", "i like", "i love", "i hate", "i prefer",
        "what did i say", "what did we talk about", "our conversation"
    ]
    
    for keyword in personal_keywords:
        if keyword in question_lower:
            return True
    
    # Questions starting with personal pronouns
    if question_lower.startswith(("am i ", "do i ", "have i ", "was i ", "were i ")):
        return True
    
    return False

def is_memory_question(question: str) -> bool:
    """Check if the question is asking about previous conversation"""
    question_lower = question.lower()
    
    memory_keywords = [
        "did i tell", "did i mention", "did we discuss", "did we talk",
        "previous conversation", "earlier you said", "you told me",
        "before you mentioned", "last time", "yesterday we", "previously"
    ]
    
    for keyword in memory_keywords:
        if keyword in question_lower:
            return True
    
    return False

def get_combined_chunks(query_embedding: list, document_chunks: list, conversation_chunks: list, query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Combine document chunks and conversation chunks with intelligent prioritization
    """
    # Check what type of question this is
    is_personal = is_personal_question(query_text)
    is_memory = is_memory_question(query_text)
    
    print(f"Question analysis - Personal: {is_personal}, Memory: {is_memory}")
    
    # If it's a personal/memory question, prioritize conversation chunks
    # Otherwise, prioritize document chunks
    if is_personal or is_memory:
        # Personal questions: More weight to conversation chunks
        conversation_weight = 1.2  # Boost conversation chunks
        document_weight = 0.8      # Slightly reduce document chunks
        min_conversation_chunks = 2  # Ensure at least 2 conversation chunks
    else:
        # Factual questions: Prioritize document chunks
        conversation_weight = 0.7  # Reduce conversation chunks
        document_weight = 1.3      # Boost document chunks
        min_conversation_chunks = 0  # No minimum conversation chunks
    
    all_chunks = []
    
    # Process document chunks with weight
    for doc_chunk in document_chunks:
        weighted_similarity = doc_chunk["similarity"] * document_weight
        all_chunks.append({
            "text": doc_chunk["content"],
            "similarity": weighted_similarity,
            "original_similarity": doc_chunk["similarity"],
            "type": "document",
            "chunk_id": doc_chunk.get("chunk_id"),
            "document_id": doc_chunk.get("document_id"),
            "source": "document",
            "weight_applied": document_weight
        })
    
    # Process conversation chunks with weight
    for conv_chunk in conversation_chunks:
        embedding_similarity = cosine_similarity(query_embedding, conv_chunk["embedding"])
        weighted_similarity = embedding_similarity * conversation_weight
        
        all_chunks.append({
            "text": conv_chunk["text"],
            "similarity": weighted_similarity,
            "original_similarity": embedding_similarity,
            "type": "conversation",
            "source": "conversation",
            "weight_applied": conversation_weight
        })
    
    # Sort by weighted similarity (highest first)
    all_chunks.sort(key=lambda x: x["similarity"], reverse=True)
    
    # Apply selection logic
    selected_chunks = []
    document_chunks_selected = 0
    conversation_chunks_selected = 0
    
    for chunk in all_chunks:
        if len(selected_chunks) >= top_k:
            break
            
        # Check if we need more conversation chunks for personal questions
        if is_personal and chunk["type"] == "conversation" and conversation_chunks_selected < min_conversation_chunks:
            selected_chunks.append(chunk)
            conversation_chunks_selected += 1
        elif chunk["type"] == "document" and document_chunks_selected < (top_k - min_conversation_chunks):
            selected_chunks.append(chunk)
            document_chunks_selected += 1
        elif chunk["type"] == "conversation" and conversation_chunks_selected < min_conversation_chunks:
            selected_chunks.append(chunk)
            conversation_chunks_selected += 1
        elif not is_personal and chunk["type"] == "document":
            # For non-personal questions, prioritize documents
            selected_chunks.append(chunk)
            document_chunks_selected += 1
        else:
            # Add whatever is left
            selected_chunks.append(chunk)
            if chunk["type"] == "document":
                document_chunks_selected += 1
            else:
                conversation_chunks_selected += 1
    
    # If we still don't have enough chunks, fill with whatever is available
    if len(selected_chunks) < top_k:
        remaining_needed = top_k - len(selected_chunks)
        remaining_chunks = [c for c in all_chunks if c not in selected_chunks]
        selected_chunks.extend(remaining_chunks[:remaining_needed])
    
    print(f"Selected chunks - Documents: {document_chunks_selected}, Conversations: {conversation_chunks_selected}")
    
    return selected_chunks

def cleanup_old_conversations(user_id: str, keep_last: int = 5):
    """Delete conversations older than the last N for a user"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            WITH ranked_chats AS (
                SELECT chat_id, ROW_NUMBER() OVER (ORDER BY created_at DESC) as rn
                FROM chat_history
                WHERE user_id = %s
            )
            DELETE FROM chat_history
            WHERE user_id = %s AND chat_id IN (
                SELECT chat_id FROM ranked_chats WHERE rn > %s
            )
            RETURNING COUNT(*)
        """, (user_id, user_id, keep_last))
        
        result = cursor.fetchone()
        deleted_count = result[0] if result else 0
        conn.commit()
        
        return deleted_count
        
    except Exception as e:
        conn.rollback()
        print(f"Error cleaning up old conversations: {str(e)}")
        return 0
    finally:
        cursor.close()
        conn.close()

def get_chunk_source_info(chunk_ids: list):
    """Get source information for document chunks"""
    if not chunk_ids:
        return []
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Convert list to PostgreSQL array format
        chunk_ids_array = "{" + ",".join([f'"{chunk_id}"' for chunk_id in chunk_ids]) + "}"
        
        query = """
            SELECT 
                dc.chunk_id,
                dc.chunk_text,
                d.filename,
                d.document_id,
                u.username
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.document_id
            JOIN users u ON d.user_id = u.user_id
            WHERE dc.chunk_id = ANY(%s)
        """
        
        cursor.execute(query, (chunk_ids_array,))
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
        
    except Exception as e:
        print(f"Error getting chunk source info: {str(e)}")
        return []
    finally:
        cursor.close()
        conn.close()

# Protected endpoint - Chat with RAG using conversation chunking
@router.post("/ask")
def chat_with_rag(
    chat_request: ChatRequest,
    current_user: TokenData = Depends(get_current_active_user)
):
    try:
        print(f"\n{'='*60}")
        print(f"Chat request from user {current_user.user_id}")
        print(f"Question: {chat_request.question}")
        print(f"{'='*60}")
        
        # 1. Create embedding for the question
        query_embedding = create_embedding(chat_request.question)
        print(f"✓ Query embedding created ({len(query_embedding)} dimensions)")
        
        # 2. Get recent conversation chunks (last 5 conversations)
        conversation_chunks = get_recent_conversation_chunks(current_user.user_id, limit=5)
        print(f"✓ Got {len(conversation_chunks)} conversation chunks")
        
        # 3. Search for similar document chunks
        similar_document_chunks = search_similar_chunks(
            query_embedding, 
            current_user.user_id, 
            chat_request.use_public_data,
            limit=5
        )
        print(f"✓ Found {len(similar_document_chunks)} similar document chunks")
        
        # Debug: Show document chunk similarities
        if similar_document_chunks:
            print("Document chunk similarities:")
            for i, chunk in enumerate(similar_document_chunks):
                print(f"  {i+1}. {chunk['content'][:50]}... - Similarity: {chunk['similarity']:.3f}")
        
        # 4. Combine and get top relevant chunks from both sources
        combined_chunks = get_combined_chunks(
            query_embedding=query_embedding,
            document_chunks=similar_document_chunks,
            conversation_chunks=conversation_chunks,
            query_text=chat_request.question,
            top_k=5
        )
        
        print(f"✓ Combined to {len(combined_chunks)} total chunks")
        
        # Debug: Print top chunks with scores
        print("\nTop chunks selected:")
        for i, chunk in enumerate(combined_chunks):
            chunk_type = "📄 DOC" if chunk["type"] == "document" else "💬 CONV"
            weight = chunk.get("weight_applied", 1.0)
            print(f"  {i+1}. {chunk_type} - Weighted: {chunk['similarity']:.3f}, Original: {chunk.get('original_similarity', chunk['similarity']):.3f}, Weight: {weight}")
            print(f"     Preview: {chunk['text'][:80]}...")
        
        if not combined_chunks:
            context = "No relevant context found in documents or conversation history."
            chunk_ids = []
            chunk_details = []
        else:
            # Prepare context for LLM with source labels
            context_chunks = []
            chunk_ids = []
            chunk_details = []
            
            for i, chunk in enumerate(combined_chunks):
                source_type = "📄 Document" if chunk["type"] == "document" else "💬 Conversation History"
                original_sim = chunk.get('original_similarity', chunk['similarity'])
                weight = chunk.get('weight_applied', 1.0)
                context_chunks.append(f"[Source: {source_type}, Relevance: {original_sim:.3f} (weight: {weight})]\n{chunk['text']}")
                
                # Store chunk details for response
                chunk_details.append({
                    "content_preview": chunk["text"][:200] + ("..." if len(chunk["text"]) > 200 else ""),
                    "similarity_score": chunk["similarity"],
                    "original_similarity": chunk.get('original_similarity', chunk['similarity']),
                    "type": chunk["type"],
                    "chunk_id": chunk.get("chunk_id"),
                    "document_id": chunk.get("document_id")
                })
                
                if chunk["type"] == "document" and chunk.get("chunk_id"):
                    chunk_ids.append(chunk["chunk_id"])
            
            context = "\n\n---\n\n".join([f"Context excerpt {i+1}:\n{chunk}" 
                                        for i, chunk in enumerate(context_chunks)])
        
        print(f"\n✓ Context prepared ({len(context)} characters)")
        
        # 5. Prepare the prompt with enhanced instructions
        prompt = f"""You are a helpful assistant with access to the user's document knowledge and conversation history.

CONTEXT INFORMATION:
{context}

QUESTION: {chat_request.question}

IMPORTANT INSTRUCTIONS:
1. For factual questions (dates, numbers, technical information, document content), prioritize information from DOCUMENTS
2. For personal questions (name, preferences, previous conversations), use CONVERSATION HISTORY
3. If information conflicts, trust DOCUMENTS over conversation history for factual information
4. Be clear about your sources - mention if information comes from documents or previous conversations
5. If you're not sure, say so

ANSWER:"""
        
        # 6. Generate response
        response = chat_client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT"),
            messages=[
                {"role": "system", "content": "You are a helpful assistant that prioritizes document information for factual questions and conversation history for personal questions."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.3  # Lower temperature for more factual responses
        )
        
        ai_response = response.choices[0].message.content
        print(f"\n✓ Generated response ({len(ai_response)} characters)")
        
        # 7. Get source document information
        source_info = []
        if chunk_ids:
            source_info = get_chunk_source_info(chunk_ids)
            print(f"✓ Got source info for {len(source_info)} document chunks")
        
        # 8. Store the conversation
        conn = get_db_connection()
        cursor = conn.cursor()
        
        chat_id = str(uuid.uuid4())
        
        # Handle empty chunk_ids array
        if not chunk_ids:
            chunk_ids_array = "{}"
        else:
            chunk_ids_array = "{" + ",".join([f'"{cid}"' for cid in chunk_ids]) + "}"
        
        cursor.execute("""
            INSERT INTO chat_history (chat_id, user_id, user_message, ai_response, context_chunk_ids, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (chat_id, current_user.user_id, chat_request.question, ai_response, chunk_ids_array, datetime.utcnow()))
        
        # 9. Cleanup old conversations (keep only last 5)
        deleted_count = cleanup_old_conversations(current_user.user_id, keep_last=5)
        print(f"✓ Deleted {deleted_count} old conversations")
        
        # 10. Log the activity
        details = json.dumps({
            "question_length": len(chat_request.question),
            "total_chunks_used": len(combined_chunks),
            "document_chunks": len([c for c in combined_chunks if c["type"] == "document"]),
            "conversation_chunks": len([c for c in combined_chunks if c["type"] == "conversation"]),
            "old_conversations_deleted": deleted_count,
            "question_type": "personal" if is_personal_question(chat_request.question) else "factual"
        })
        cursor.execute("""
            INSERT INTO activity_log (user_id, activity_type, details)
            VALUES (%s, %s, %s)
        """, (current_user.user_id, 'CHAT', details))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        # 11. Prepare response
        response_data = {
            "answer": ai_response,
            # Frontend expects these exact keys:
            "chunks_used": len(combined_chunks),
            "chunks": chunk_details,
            "sources": source_info,
            "chat_id": chat_id,
            "budget_status": budget_tracker.get_status(),
            
            # Additional info for debugging
            "total_chunks_used": len(combined_chunks),
            "document_chunks": len([c for c in combined_chunks if c["type"] == "document"]),
            "conversation_chunks": len([c for c in combined_chunks if c["type"] == "conversation"]),
            "old_conversations_deleted": deleted_count,
            "question_type": "personal" if is_personal_question(chat_request.question) else "factual"
        }
        
        print(f"\n✓ Chat request completed successfully")
        print(f"{'='*60}\n")
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"\n✗ Error in chat_with_rag: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

# Protected endpoint - Get conversation statistics
@router.get("/conversation-stats")
def get_conversation_stats(current_user: TokenData = Depends(get_current_active_user)):
    """Get statistics about user's conversation history"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get total conversation count
        cursor.execute("""
            SELECT COUNT(*) as total_conversations,
                   MIN(created_at) as first_conversation,
                   MAX(created_at) as last_conversation
            FROM chat_history 
            WHERE user_id = %s
        """, (current_user.user_id,))
        
        stats = cursor.fetchone()
        
        # Get the most recent conversation content for context
        cursor.execute("""
            SELECT user_message, ai_response
            FROM chat_history 
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (current_user.user_id,))
        
        recent = cursor.fetchone()
        recent_text = ""
        if recent:
            recent_text = f"User: {recent[0]}, Assistant: {recent[1][:50]}..." if len(recent[1]) > 50 else f"User: {recent[0]}, Assistant: {recent[1]}"
        
        return {
            "user_id": current_user.user_id,
            "total_conversations": stats[0] if stats else 0,
            "first_conversation": stats[1].isoformat() if stats and stats[1] else None,
            "last_conversation": stats[2].isoformat() if stats and stats[2] else None,
            "recent_conversations_kept": 5,
            "conversation_chunk_size": CONVERSATION_CHUNK_SIZE,
            "conversation_chunk_overlap": CONVERSATION_CHUNK_OVERLAP,
            "recent_conversation_preview": recent_text,
            "chunking_system": "Last 5 conversations are chunked and used for similarity search"
        }
        
    finally:
        cursor.close()
        conn.close()

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
        
        if not chunk_ids or len(chunk_ids) == 0:
            return {"chunks": [], "sources": []}
        
        # Get chunk details
        chunk_ids_array = "{" + ",".join([f'"{cid}"' for cid in chunk_ids]) + "}"
        
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
        """, (chunk_ids_array,))
        
        chunks = cursor.fetchall()
        
        formatted_chunks = []
        for chunk in chunks:
            formatted_chunks.append({
                "chunk_id": chunk[0],
                "content": chunk[1],
                "created_at": chunk[2].isoformat() if chunk[2] else None,
                "filename": chunk[3],
                "document_id": chunk[4],
                "uploaded_by": chunk[5],
                "type": "document"
            })
        
        return {
            "chat_id": chat_id,
            "chunks": formatted_chunks,
            "total_chunks": len(chunks)
        }
        
    finally:
        cursor.close()
        conn.close()

# Protected endpoint - Get user's conversation history
@router.get("/history")
def get_conversation_history(
    limit: int = 10,
    current_user: TokenData = Depends(get_current_active_user)
):
    """Get user's conversation history"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT chat_id, user_message, ai_response, created_at, context_chunk_ids
            FROM chat_history 
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (current_user.user_id, limit))
        
        conversations = cursor.fetchall()
        
        formatted_conversations = []
        for conv in conversations:
            chat_id, user_msg, ai_resp, created_at, chunk_ids = conv
            
            # Count how many chunks were used
            chunk_count = len(chunk_ids) if chunk_ids else 0
            
            formatted_conversations.append({
                "chat_id": chat_id,
                "user_message": user_msg,
                "ai_response": ai_resp,
                "created_at": created_at.isoformat() if created_at else None,
                "chunks_used": chunk_count,
                "has_context": chunk_count > 0
            })
        
        return {
            "user_id": current_user.user_id,
            "total_conversations": len(formatted_conversations),
            "conversations": formatted_conversations,
            "conversation_memory_system": "Keeps last 5 conversations chunked for context"
        }
        
    finally:
        cursor.close()
        conn.close()

# Protected endpoint - Cleanup old conversations
@router.post("/cleanup")
def cleanup_old_conversations_endpoint(
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
        
        result = cursor.fetchone()
        deleted_count = result[0] if result else 0
        conn.commit()
        
        return {
            "message": f"Deleted {deleted_count} old conversations",
            "kept_last_5": "Always keeping last 5 conversations for chunking system"
        }
        
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
        
        result = cursor.fetchone()
        deleted_count = result[0] if result else 0
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

# Test endpoint for conversation chunking
@router.get("/test-conversation")
def test_conversation_chunking(current_user: TokenData = Depends(get_current_active_user)):
    """Test endpoint to see how conversations are being chunked"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get last 5 conversations
        cursor.execute("""
            SELECT user_message, ai_response, created_at 
            FROM chat_history 
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 5
        """, (current_user.user_id,))
        
        conversations = cursor.fetchall()
        
        # Format for display
        formatted_conversations = []
        for user_msg, ai_resp, created_at in reversed(conversations):
            formatted_conversations.append({
                "user": user_msg,
                "assistant": ai_resp,
                "created": created_at.isoformat() if created_at else None
            })
        
        # Get conversation chunks
        conversation_chunks = get_recent_conversation_chunks(current_user.user_id, limit=5)
        
        chunk_details = []
        for i, chunk in enumerate(conversation_chunks):
            chunk_details.append({
                "chunk_number": i + 1,
                "text": chunk["text"],
                "text_length": len(chunk["text"]),
                "type": chunk["type"]
            })
        
        return {
            "user_id": current_user.user_id,
            "total_conversations": len(conversations),
            "conversations": formatted_conversations,
            "chunks_created": len(conversation_chunks),
            "chunk_details": chunk_details,
            "chunk_settings": {
                "chunk_size": CONVERSATION_CHUNK_SIZE,
                "chunk_overlap": CONVERSATION_CHUNK_OVERLAP
            }
        }
        
    finally:
        cursor.close()
        conn.close()