# main.py - Fixed version with correct imports
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
import sys
from datetime import datetime

load_dotenv()

app = FastAPI(
    title="Azure RAG Chatbot Backend API",
    description="Complete RAG Chatbot System with Azure Blob Storage, OpenAI, and PostgreSQL",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import routers
try:
    from auth import router as auth_router
    app.include_router(auth_router)
    print("✅ Auth router loaded")
except Exception as e:
    print(f"⚠️  Auth router not loaded: {e}")

try:
    from pdf_processor_simple import router as pdf_router
    app.include_router(pdf_router)
    print("✅ PDF processor router loaded")
except Exception as e:
    print(f"⚠️  PDF processor router not loaded: {e}")

try:
    from rag_engine import router as rag_router
    app.include_router(rag_router)
    print("✅ RAG engine router loaded")
except Exception as e:
    print(f"⚠️  RAG engine router not loaded: {e}")

@app.get("/")
def read_root():
    return {
        "message": "Welcome to Azure RAG Chatbot API",
        "version": "3.0.0",
        "endpoints": {
            "auth": "/auth",
            "pdf": "/pdf",
            "chat": "/chat"
        }
    }

@app.get("/health")
def health_check():
    try:
        from database import get_db_connection
        conn = get_db_connection()
        conn.close()
        
        from shared_dependencies import budget_tracker
        
        return {
            "status": "healthy",
            "database": "connected",
            "budget": budget_tracker.get_status()
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

@app.get("/test")
def test_endpoint():
    """Simple test endpoint"""
    return {
        "message": "API is working",
        "timestamp": datetime.utcnow().isoformat(),
        "endpoints": [
            "/auth/register",
            "/pdf/upload/{user_id}",
            "/chat/ask"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    
    print("🚀 Starting Azure RAG Chatbot Backend")
    print("=" * 50)
    
    # Check essential configurations
    print("Configuration Check:")
    
    config_vars = [
        ("DB_HOST", os.getenv("DB_HOST")),
        ("DB_NAME", os.getenv("DB_NAME")),
        ("AZURE_OPENAI_CHAT_DEPLOYMENT", os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")),
        ("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")),
        ("AZURE_STORAGE_CONTAINER_NAME", os.getenv("AZURE_STORAGE_CONTAINER_NAME", "pdf-documents"))
    ]
    
    for var_name, var_value in config_vars:
        status = "✅" if var_value else "❌"
        display_value = var_value[:30] + "..." if var_value and len(var_value) > 30 else var_value or "NOT SET"
        print(f"  {status} {var_name}: {display_value}")
    
    print("-" * 50)
    print("Server starting on http://0.0.0.0:8000")
    print("=" * 50)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )