# Azure RAG Chatbot System

## Overview
A full-stack **Retrieval-Augmented Generation (RAG) Chatbot** that enables users to upload documents, process them into vector embeddings, and engage in intelligent conversations using document-based context. Built with enterprise-grade Azure services and featuring admin-controlled user management with configurable document limits.

## Features

### Advanced Security & User Management
- **Admin-controlled registration** - No public sign-ups, all users created by administrators
- **Temporary password system** with configurable expiration (1 day or permanent)
- **Role-based access control** (Admin/Regular User with distinct permissions)
- **Per-user document limits** (configurable: unlimited, 0-1000 documents)
- **Comprehensive activity logging** for audit trails

### Smart Document Processing
- **PDF/text processing** with intelligent chunking (300 characters with 30 overlap)
- **Azure Blob Storage integration** for secure, scalable document storage
- **Public/Private document system** - Admins can upload public documents accessible to all users
- **Vector embeddings** using Azure OpenAI text-embedding-3-small
- **Automatic semantic indexing** with pgvector

### Intelligent RAG Engine
- **Semantic search** across personal and public documents
- **Context-aware AI responses** using Azure OpenAI GPT-4
- **Conversation memory** (24-hour history retention)
- **Budget tracking** with real-time cost controls
- **Real-time chat interface** with document context

### Admin Dashboard
- **Complete user management** (create, delete, reset passwords, set limits)
- **Document moderation** (upload documents for users, manage public/private status)
- **System monitoring** (usage analytics, budget tracking, health checks)
- **Vector database management** (ingest, remove, clear operations
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ Streamlit │ │ FastAPI │ │ PostgreSQL │
│ Frontend │◄──►│ Backend │◄──►│ (Azure) │
│ (Port 8501)│ │ (Port 8000)│ │ + pgvector │
└─────────────┘ └─────────────┘ └─────────────┘
│
┌─────────────┐ ┌─────────────┐ │
│ Admin CLI │ │ Azure Blob │◄────────────┘
│ Interface │ │ Storage │
└─────────────┘ └─────────────┘
│
▼
┌─────────────┐
│ Azure OpenAI│
│ Embeddings │
│ & GPT-4 │
└─────────────┘

## Project Structure
azure-rag-chatbot/
├── backend/ # FastAPI Backend
│ ├── auth.py # Authentication & user management
│ ├── pdf_processor_simple.py # PDF processing & embeddings
│ ├── rag_engine.py # RAG chat engine
│ ├── blob_storage.py # Azure Blob Storage operations
│ ├── shared_dependencies.py # Shared AI clients & budget tracker
│ ├── database.py # PostgreSQL connection
│ ├── main.py # FastAPI app entry point
│ ├── cli_interface.py # Admin CLI tool
│ ├── requirements.txt # Python dependencies
│ └── Dockerfile # Container configuration
├── frontend/ # Streamlit Frontend
│ ├── app_simple.py # Web interface
│ ├── requirements.txt # Frontend dependencies
│ └── Dockerfile # Container configuration
├── docker-compose.yml # Local development
├── docker-compose.prod.yml # Production configuration
├── deploy-azure.ps1 # Azure deployment script
└── .env.example # Environment variables template

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Backend API** | FastAPI (Python) | REST API server with async support |
| **Database** | PostgreSQL (Azure Flexible Server) | User data, embeddings, chat history |
| **Vector Store** | pgvector extension | Vector similarity search |
| **File Storage** | Azure Blob Storage | Secure document file storage |
| **AI/ML** | Azure OpenAI (GPT-4 & embeddings) | Chat completion & vector embeddings |
| **Frontend** | Streamlit | Interactive web interface |
| **CLI** | Custom Python CLI | Administrative operations |
| **Authentication** | bcrypt + UUID | Secure password hashing & user management |
| **Deployment** | Docker + Azure App Service | Containerized cloud deployment |
| **Document Processing** | LangChain | PDF/text extraction and chunking |

## Architecture
