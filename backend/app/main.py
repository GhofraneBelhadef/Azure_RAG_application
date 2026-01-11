# main.py - Fixed version with correct imports and CORS for authentication
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
    version="4.0.0"  # Updated version for security implementation
)

# Configure CORS with authentication headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],  # Allow Authorization header
    expose_headers=["Authorization"]  # Expose Authorization header to frontend
)

# Import routers
try:
    from auth import router as auth_router
    app.include_router(auth_router)
    print("✅ Auth router loaded with JWT security")
except Exception as e:
    print(f"⚠️  Auth router not loaded: {e}")

try:
    from pdf_processor_simple import router as pdf_router
    app.include_router(pdf_router)
    print("✅ PDF processor router loaded with authentication")
except Exception as e:
    print(f"⚠️  PDF processor router not loaded: {e}")

try:
    from rag_engine import router as rag_router
    app.include_router(rag_router)
    print("✅ RAG engine router loaded with authentication")
except Exception as e:
    print(f"⚠️  RAG engine router not loaded: {e}")

@app.get("/")
def read_root():
    return {
        "message": "Welcome to Azure RAG Chatbot API",
        "version": "4.0.0",
        "security": "JWT Authentication Enabled",
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
            "security": "jwt_enabled",
            "budget": budget_tracker.get_status()
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

@app.get("/test")
def test_endpoint():
    """Simple test endpoint - No authentication required"""
    return {
        "message": "API is working",
        "timestamp": datetime.utcnow().isoformat(),
        "security": "JWT Authentication Required for Protected Endpoints"
    }

if __name__ == "__main__":
    import uvicorn
    
    print("🚀 Starting Azure RAG Chatbot Backend with JWT Security")
    print("=" * 50)
    
    # Check essential configurations
    print("Configuration Check:")
    
    config_vars = [
        ("DB_HOST", os.getenv("DB_HOST")),
        ("DB_NAME", os.getenv("DB_NAME")),
        ("AZURE_OPENAI_CHAT_DEPLOYMENT", os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")),
        ("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")),
        ("AZURE_STORAGE_CONTAINER_NAME", os.getenv("AZURE_STORAGE_CONTAINER_NAME", "pdf-documents")),
        ("JWT_SECRET_KEY", "✅ Set" if os.getenv("JWT_SECRET_KEY") else "❌ NOT SET - Using default")
    ]
    
    for var_name, var_value in config_vars:
        status = "✅" if var_value else "❌"
        display_value = var_value[:30] + "..." if var_value and len(var_value) > 30 else var_value or "NOT SET"
        print(f"  {status} {var_name}: {display_value}")
    
    print("-" * 50)
    print("Security Features:")
    print("  ✅ JWT Token Authentication")
    print("  ✅ Role-Based Access Control")
    print("  ✅ Token Refresh System")
    print("  ✅ Password Hashing with bcrypt")
    print("-" * 50)
    print("Server starting on http://0.0.0.0:8000")
    print("=" * 50)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )