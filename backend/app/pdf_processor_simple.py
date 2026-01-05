# pdf_processor_simple.py - FINAL WORKING VERSION
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
import os
import psycopg2
from database import get_db_connection
import uuid
from datetime import datetime
import io
import tempfile
import json  # Added for proper JSON serialization

# Minimal LangChain imports
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader

# Import shared dependencies
from shared_dependencies import budget_tracker, create_embedding

# Import blob storage manager
from blob_storage import blob_manager

router = APIRouter(prefix="/pdf", tags=["pdf processing"])

# Constants
DEFAULT_MAX_PDFS_PER_USER = 5

# Chunk size settings - UPDATED
CHUNK_SIZE = 300
CHUNK_OVERLAP = 30

# Better text splitter using LangChain
def get_text_splitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP):
    """Get LangChain text splitter"""
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", " ", ""]
    )

# Document loader based on file type
def load_document(file_content: bytes, filename: str):
    """Load document using appropriate LangChain loader"""
    file_extension = filename.split('.')[-1].lower()
    
    # Create a temporary file
    with tempfile.NamedTemporaryFile(suffix=f".{file_extension}", delete=False) as tmp_file:
        tmp_file.write(file_content)
        tmp_file_path = tmp_file.name
    
    try:
        # Use appropriate loader based on file extension
        if file_extension == "pdf":
            loader = PyPDFLoader(tmp_file_path)
        elif file_extension in ["docx", "doc"]:
            loader = Docx2txtLoader(tmp_file_path)
        elif file_extension in ["txt", "md"]:
            loader = TextLoader(tmp_file_path)
        else:
            # Default to text loader for unknown types
            loader = TextLoader(tmp_file_path)
        
        # Load and split documents
        documents = loader.load()
        return documents
    
    finally:
        # Clean up temporary file
        try:
            os.unlink(tmp_file_path)
        except:
            pass

@router.post("/upload/{user_id}")
async def upload_document(
    user_id: str,
    file: UploadFile = File(...),
    is_public: str = Form("false"),  # Changed to Form field, default "false"
    admin_upload: str = Form("false"),  # Changed to Form field, default "false"
    conn = Depends(get_db_connection)
):
    cursor = conn.cursor()
    
    try:
        # Convert string values to boolean
        is_public_bool = is_public.lower() == "true"
        admin_upload_bool = admin_upload.lower() == "true"
        
        print(f"DEBUG: Received parameters - user_id: {user_id}, is_public: {is_public_bool}, admin_upload: {admin_upload_bool}")
        
        # Get user's max_documents limit and check if they're admin
        cursor.execute("""
            SELECT max_documents, is_admin FROM users WHERE user_id = %s
        """, (user_id,))
        
        user_info = cursor.fetchone()
        if not user_info:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_max_documents, is_user_admin = user_info
        
        # Check document count based on user type and limit
        if is_user_admin:
            # Admins have no limit (max_documents = -1)
            can_upload = True
        elif user_max_documents == -1:
            # User has unlimited documents (special case)
            can_upload = True
        else:
            # Check if user already has reached their limit
            cursor.execute("""
                SELECT COUNT(*) FROM documents WHERE user_id = %s
            """, (user_id,))
            
            doc_count = cursor.fetchone()[0]
            
            if doc_count >= user_max_documents:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot upload more than {user_max_documents} PDFs. You already have {doc_count}."
                )
            can_upload = True
        
        # Read file content
        content = await file.read()
        
        # 1. Upload to Azure Blob Storage
        blob_info = blob_manager.upload_pdf(
            file_content=content,
            user_id=user_id,
            original_filename=file.filename
        )
        
        # 2. Extract text using LangChain loader
        documents = load_document(content, file.filename)
        
        if not documents:
            raise HTTPException(
                status_code=400,
                detail="Document appears to be empty or cannot be processed"
            )
        
        # Combine all text from documents
        full_text = "\n\n".join([doc.page_content for doc in documents])
        
        # 3. Split text into chunks using LangChain splitter with new chunk size
        text_splitter = get_text_splitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        chunks = text_splitter.split_text(full_text)
        
        # 4. Store document metadata WITH blob storage path
        
        # SIMPLE AND CORRECT LOGIC:
        # - Document is public ONLY if admin_upload=True AND is_public=True
        # - This means only admins can upload public documents, and they must explicitly choose to
        # - Regular users: admin_upload=False, so document is always private
        final_is_public = is_public_bool and admin_upload_bool
        
        print(f"DEBUG: Document will be public: {final_is_public}")
        
        document_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO documents (document_id, user_id, filename, blob_storage_path, is_public, uploaded_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING document_id
        """, (document_id, user_id, file.filename, blob_info["blob_url"], final_is_public, datetime.utcnow()))
        
        # 5. Process each chunk: create embedding and store
        chunks_processed = 0
        for i, chunk in enumerate(chunks):
            chunk_id = str(uuid.uuid4())
            
            # Create embedding using shared function
            embedding = create_embedding(chunk)
            
            # Store chunk and embedding
            cursor.execute("""
                INSERT INTO document_chunks (chunk_id, document_id, user_id, chunk_text, embedding, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (chunk_id, document_id, user_id, chunk, embedding, datetime.utcnow()))
            
            chunks_processed += 1
        
        # 6. Log the activity with proper JSON serialization
        details = json.dumps({
            "filename": file.filename,
            "chunks": chunks_processed,
            "blob_url": blob_info["blob_url"],
            "file_size": len(content),
            "doc_type": "langchain_processed",
            "is_public": final_is_public,
            "admin_upload": admin_upload_bool,
            "requested_is_public": is_public_bool,
            "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP
        })
        cursor.execute("""
            INSERT INTO activity_log (user_id, activity_type, details)
            VALUES (%s, %s, %s)
        """, (user_id, 'UPLOAD_DOCUMENT', details))
        
        conn.commit()
        
        return {
            "message": "Document processed and stored successfully",
            "document_id": document_id,
            "filename": file.filename,
            "blob_storage": {
                "url": blob_info["blob_url"],
                "container": blob_info["container"],
                "blob_name": blob_info["blob_name"]
            },
            "chunks_created": chunks_processed,
            "text_extracted": len(full_text),
            "file_size_bytes": len(content),
            "budget_status": budget_tracker.get_status(),
            "processing_method": "langchain",
            "chunk_settings": {
                "chunk_size": CHUNK_SIZE,
                "chunk_overlap": CHUNK_OVERLAP
            },
            "is_public": final_is_public,
            "admin_upload": admin_upload_bool,
            "requested_is_public": is_public_bool,
            "debug": {
                "received_is_public": is_public,
                "received_admin_upload": admin_upload,
                "parsed_is_public": is_public_bool,
                "parsed_admin_upload": admin_upload_bool
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Document processing error: {str(e)}")
    finally:
        cursor.close()

# New endpoint to get user's PDF count
@router.get("/user/{user_id}/count")
def get_user_pdf_count(user_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get user's max_documents limit
        cursor.execute("""
            SELECT max_documents, is_admin FROM users WHERE user_id = %s
        """, (user_id,))
        
        user_info = cursor.fetchone()
        if not user_info:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_max_documents, is_user_admin = user_info
        
        cursor.execute("""
            SELECT COUNT(*) FROM documents WHERE user_id = %s
        """, (user_id,))
        
        count = cursor.fetchone()[0]
        
        # For admins, they can upload unlimited documents
        if is_user_admin:
            can_upload_more = True
            max_allowed = "unlimited"
        elif user_max_documents == -1:
            can_upload_more = True
            max_allowed = "unlimited"
        else:
            can_upload_more = count < user_max_documents
            max_allowed = user_max_documents
        
        return {
            "user_id": user_id,
            "pdf_count": count,
            "max_allowed": max_allowed,
            "can_upload_more": can_upload_more,
            "user_max_documents": user_max_documents,
            "is_admin": is_user_admin
        }
        
    finally:
        cursor.close()
        conn.close()

# Keep all other endpoints unchanged
@router.get("/download/{document_id}")
def download_pdf(document_id: str):
    """Download PDF from blob storage"""
    cursor = None
    conn = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get blob storage path from database
        cursor.execute("""
            SELECT blob_storage_path FROM documents WHERE document_id = %s
        """, (document_id,))
        
        result = cursor.fetchone()
        
        if not result or not result[0]:
            raise HTTPException(status_code=404, detail="Document not found or no blob storage path")
        
        blob_url = result[0]
        blob_name = '/'.join(blob_url.split('/')[-2:])
        
        # Download from blob storage
        try:
            pdf_content = blob_manager.download_pdf(blob_name)
            
            # Log activity with proper JSON
            details = json.dumps({"document_id": document_id})
            cursor.execute("""
                INSERT INTO activity_log (user_id, activity_type, details)
            VALUES (%s, %s, %s)
            """, ('system', 'DOWNLOAD_PDF', details))
            
            conn.commit()
            
            return {
                "document_id": document_id,
                "blob_url": blob_url,
                "file_size": len(pdf_content),
                "content": pdf_content.hex()[:100] + "..."
            }
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to download from blob storage: {str(e)}")
            
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@router.delete("/delete/{document_id}")
def delete_pdf(document_id: str):
    """Delete PDF from blob storage and database"""
    cursor = None
    conn = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT user_id, blob_storage_path FROM documents WHERE document_id = %s
        """, (document_id,))
        
        result = cursor.fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Document not found")
        
        user_id, blob_url = result
        
        if not blob_url:
            raise HTTPException(status_code=400, detail="Document has no blob storage path")
        
        blob_name = '/'.join(blob_url.split('/')[-2:])
        
        try:
            blob_manager.delete_pdf(blob_name)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete from blob storage: {str(e)}")
        
        cursor.execute("""
            DELETE FROM documents WHERE document_id = %s RETURNING filename
        """, (document_id,))
        
        filename = cursor.fetchone()[0]
        
        # Log activity with proper JSON
        details = json.dumps({
            "document_id": document_id,
            "filename": filename
        })
        cursor.execute("""
            INSERT INTO activity_log (user_id, activity_type, details)
            VALUES (%s, %s, %s)
        """, (user_id, 'DELETE_PDF', details))
        
        conn.commit()
        
        return {
            "message": "PDF deleted successfully",
            "document_id": document_id,
            "filename": filename,
            "blob_deleted": True
        }
            
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@router.get("/user/{user_id}/documents")
def get_user_documents(user_id: str):
    """Get list of documents for a user with blob info"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get user's max_documents limit
        cursor.execute("""
            SELECT max_documents, is_admin FROM users WHERE user_id = %s
        """, (user_id,))
        
        user_info = cursor.fetchone()
        if not user_info:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_max_documents, is_user_admin = user_info
        
        cursor.execute("""
            SELECT 
                document_id, 
                filename, 
                blob_storage_path,
                is_public, 
                uploaded_at,
                (SELECT COUNT(*) FROM document_chunks WHERE document_id = d.document_id) as chunk_count
            FROM documents d
            WHERE user_id = %s
            ORDER BY uploaded_at DESC
        """, (user_id,))
        
        documents = cursor.fetchall()
        
        result = []
        for doc in documents:
            result.append({
                "document_id": doc[0],
                "filename": doc[1],
                "blob_url": doc[2],
                "is_public": doc[3],
                "uploaded_at": doc[4],
                "chunk_count": doc[5]
            })
        
        # Determine max allowed based on user type
        if is_user_admin:
            max_allowed = "unlimited"
        elif user_max_documents == -1:
            max_allowed = "unlimited"
        else:
            max_allowed = user_max_documents
        
        return {
            "user_id": user_id,
            "total_documents": len(documents),
            "documents": result,
            "max_allowed": max_allowed,
            "user_max_documents": user_max_documents,
            "is_admin": is_user_admin
        }
        
    finally:
        cursor.close()
        conn.close()

@router.get("/blob/list/{user_id}")
def list_user_blobs(user_id: str):
    """List all blobs for a user directly from Azure Blob Storage"""
    try:
        blobs = blob_manager.list_user_blobs(user_id)
        return {
            "user_id": user_id,
            "total_blobs": len(blobs),
            "blobs": blobs
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/budget/status")
def get_budget_status():
    return {
        "status": "active",
        "budget": budget_tracker.get_status(),
        "max_budget": budget_tracker.max_budget
    }

# Admin endpoint to list all PDFs in system
@router.get("/admin/all-documents")
def get_all_documents():
    """Admin endpoint: Get all documents in the system"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                d.document_id,
                d.filename,
                d.user_id,
                u.username,
                d.blob_storage_path,
                d.is_public,
                d.uploaded_at,
                (SELECT COUNT(*) FROM document_chunks WHERE document_id = d.document_id) as chunk_count
            FROM documents d
            JOIN users u ON d.user_id = u.user_id
            ORDER BY d.uploaded_at DESC
        """)
        
        documents = cursor.fetchall()
        
        result = []
        for doc in documents:
            result.append({
                "document_id": doc[0],
                "filename": doc[1],
                "user_id": doc[2],
                "username": doc[3],
                "blob_url": doc[4],
                "is_public": doc[5],
                "uploaded_at": doc[6],
                "chunk_count": doc[7]
            })
        
        return {
            "total_documents": len(documents),
            "documents": result
        }
        
    finally:
        cursor.close()
        conn.close()