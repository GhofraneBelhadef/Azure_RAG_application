# frontend/app_simple.py - Complete with JWT Authentication
import streamlit as st
import requests
import json
import time
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# Initialize session state
def init_session_state():
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'user_id' not in st.session_state:
        st.session_state.user_id = None
    if 'username' not in st.session_state:
        st.session_state.username = None
    if 'is_admin' not in st.session_state:
        st.session_state.is_admin = False
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []
    if 'confirm_delete' not in st.session_state:
        st.session_state.confirm_delete = None
    if 'user_max_documents' not in st.session_state:
        st.session_state.user_max_documents = 5
    if 'registration_message' not in st.session_state:
        st.session_state.registration_message = None
    if 'expanded_chunks' not in st.session_state:
        st.session_state.expanded_chunks = {}
    if 'expanded_full_chunks' not in st.session_state:
        st.session_state.expanded_full_chunks = {}
    if 'processing_question' not in st.session_state:
        st.session_state.processing_question = None
    if 'last_processed_question' not in st.session_state:
        st.session_state.last_processed_question = None
    if 'access_token' not in st.session_state:
        st.session_state.access_token = None
    if 'refresh_token' not in st.session_state:
        st.session_state.refresh_token = None
    if 'token_expiry' not in st.session_state:
        st.session_state.token_expiry = None

init_session_state()

# API Helper with token management
def api_call(endpoint, method="GET", data=None, files=None, require_auth=True):
    """Make API call with automatic token refresh"""
    try:
        url = f"{BACKEND_URL}{endpoint}"
        
        # Prepare headers
        headers = {}
        
        # Add authorization header if required
        if require_auth and st.session_state.access_token:
            headers["Authorization"] = f"Bearer {st.session_state.access_token}"
        
        # Check token expiry and refresh if needed
        if require_auth and st.session_state.token_expiry:
            try:
                expiry_time = datetime.fromisoformat(st.session_state.token_expiry)
                if datetime.now() > expiry_time - timedelta(minutes=5):  # Refresh 5 minutes before expiry
                    refresh_response = refresh_token_call()
                    if refresh_response and not refresh_response.get("error"):
                        st.session_state.access_token = refresh_response.get("access_token")
                        headers["Authorization"] = f"Bearer {st.session_state.access_token}"
                        # Set new expiry (25 minutes from now for 30-minute tokens)
                        st.session_state.token_expiry = (datetime.now() + timedelta(minutes=25)).isoformat()
            except:
                pass
        
        # Make the request
        if method == "GET":
            response = requests.get(url, headers=headers)
        elif method == "POST" and files:
            response = requests.post(url, files=files, data=data, headers=headers)
        elif method == "POST":
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"
            response = requests.post(url, json=data, headers=headers)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers)
        else:
            return None
        
        # Handle response
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 401 and require_auth:
            # Token might be expired, try to refresh
            refresh_response = refresh_token_call()
            if refresh_response and not refresh_response.get("error"):
                # Retry the request with new token
                st.session_state.access_token = refresh_response.get("access_token")
                headers["Authorization"] = f"Bearer {st.session_state.access_token}"
                
                if method == "GET":
                    response = requests.get(url, headers=headers)
                elif method == "POST" and files:
                    response = requests.post(url, files=files, data=data, headers=headers)
                elif method == "POST":
                    response = requests.post(url, json=data, headers=headers)
                elif method == "DELETE":
                    response = requests.delete(url, headers=headers)
                
                if response.status_code == 200:
                    return response.json()
        
        # Return error response
        error_detail = {"detail": f"HTTP {response.status_code}"}
        try:
            if response.text:
                error_detail = response.json()
        except:
            pass
            
        return {
            "status_code": response.status_code,
            "error": True,
            "detail": error_detail
        }
    except Exception as e:
        return {
            "status_code": 0,
            "error": True,
            "detail": {"detail": f"Connection error: {str(e)}"}
        }

def refresh_token_call():
    """Refresh access token using refresh token"""
    if not st.session_state.refresh_token:
        return None
    
    try:
        url = f"{BACKEND_URL}/auth/refresh"
        data = {"refresh_token": st.session_state.refresh_token}
        headers = {"Content-Type": "application/json"}
        
        response = requests.post(url, json=data, headers=headers)
        
        if response.status_code == 200:
            return response.json()
        else:
            # Refresh token expired, force logout
            st.session_state.logged_in = False
            st.session_state.access_token = None
            st.session_state.refresh_token = None
            st.session_state.token_expiry = None
            return {
                "error": True,
                "detail": {"detail": "Session expired. Please login again."}
            }
    except Exception as e:
        return {
            "error": True,
            "detail": {"detail": f"Refresh failed: {str(e)}"}
        }

# Login Page
def login_page():
    st.title("🔐 Azure RAG Chatbot Login")
    
    # Show registration message if available
    if st.session_state.registration_message:
        if st.session_state.registration_message.get("success"):
            st.success(st.session_state.registration_message["message"])
        else:
            st.error(st.session_state.registration_message["message"])
        # Clear the message after showing it
        st.session_state.registration_message = None
    
    tab1, tab2 = st.tabs(["Login", "Complete Registration"])
    
    with tab1:
        st.subheader("Login")
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Login")
            
            if submit and username and password:
                data = {"username": username, "password": password}
                response = api_call("/auth/login", method="POST", data=data, require_auth=False)
                
                if response and not response.get("error"):
                    st.session_state.logged_in = True
                    st.session_state.user_id = response.get("user_id")
                    st.session_state.username = username
                    st.session_state.is_admin = response.get("is_admin", False)
                    st.session_state.access_token = response.get("access_token")
                    st.session_state.refresh_token = response.get("refresh_token")
                    st.session_state.token_expiry = (datetime.now() + timedelta(minutes=25)).isoformat()
                    
                    # Get user's document limit
                    reg_response = api_call(f"/auth/check-registration/{username}", require_auth=False)
                    if reg_response and not reg_response.get("error"):
                        st.session_state.user_max_documents = reg_response.get("max_documents", 5)
                    
                    st.success(f"Welcome {username}! ({'Admin' if st.session_state.is_admin else 'User'})")
                    time.sleep(1)
                    st.rerun()
                elif response and response.get("error"):
                    error_msg = response.get('detail', {}).get('detail', 'Unknown error')
                    st.error(f"Login failed: {error_msg}")
    
    with tab2:
        st.subheader("Complete Registration")
        st.info("📋 You need a temporary password from admin to complete registration")
        
        with st.form("complete_registration_form"):
            username = st.text_input("Username")
            temp_password = st.text_input("Temporary Password (from admin)", type="password")
            new_password = st.text_input("Your New Password", type="password")
            confirm_password = st.text_input("Confirm New Password", type="password")
            
            submit = st.form_submit_button("Complete Registration")
            
            if submit:
                if not all([username, temp_password, new_password, confirm_password]):
                    st.error("All fields are required")
                elif new_password != confirm_password:
                    st.error("Passwords don't match")
                else:
                    data = {
                        "username": username,
                        "registration_password": temp_password,
                        "new_password": new_password
                    }
                    response = api_call("/auth/complete-registration", method="POST", data=data, require_auth=False)
                    
                    if response:
                        if response.get("error"):
                            error_detail = response.get('detail', {})
                            error_message = error_detail.get('detail', 'Registration failed')
                            
                            # Check if it's a "user already registered" error
                            if "already registered" in error_message.lower() or response.get('status_code') == 400:
                                # This is actually a success case - the user is already registered
                                st.session_state.registration_message = {
                                    "success": True,
                                    "message": f"✅ User '{username}' is already registered! You can now login with your password."
                                }
                                st.rerun()
                            else:
                                st.error(f"Registration failed: {error_message}")
                        else:
                            # Successful registration
                            st.session_state.registration_message = {
                                "success": True,
                                "message": "✅ Registration completed successfully!"
                            }
                            st.info(f"You can now login as **{username}** with your new password.")
                            # Auto-switch to login tab
                            st.rerun()
                    else:
                        st.error("Registration failed. Please check your temporary password.")

# Chat Interface with Chunk Display
def chat_page():
    st.title("💬 Chat with Your Documents")
    
    # Initialize session state for expanded chunks
    if 'expanded_chunks' not in st.session_state:
        st.session_state.expanded_chunks = {}
    if 'expanded_full_chunks' not in st.session_state:
        st.session_state.expanded_full_chunks = {}
    
    # Sidebar
    with st.sidebar:
        st.header("Settings")
        use_public_data = st.checkbox("Use public documents", value=True)
        
        if st.button("Clear Chat"):
            st.session_state.chat_history = []
            st.session_state.expanded_chunks = {}
            st.session_state.expanded_full_chunks = {}
            st.session_state.processing_question = None
            st.session_state.last_processed_question = None
            st.rerun()
        
        # Show PDF count
        if st.session_state.user_id:
            response = api_call("/pdf/user/count", require_auth=True)
            if response and not response.get("error"):
                count = response.get("pdf_count", 0)
                max_allowed = response.get("max_allowed", 5)
                if max_allowed == "unlimited":
                    st.info(f"📊 PDFs: {count} (Unlimited)")
                else:
                    st.info(f"📊 PDFs: {count}/{max_allowed}")
        
        if st.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.user_id = None
            st.session_state.username = None
            st.session_state.is_admin = False
            st.session_state.chat_history = []
            st.session_state.expanded_chunks = {}
            st.session_state.expanded_full_chunks = {}
            st.session_state.confirm_delete = None
            st.session_state.user_max_documents = 5
            st.session_state.processing_question = None
            st.session_state.last_processed_question = None
            st.session_state.access_token = None
            st.session_state.refresh_token = None
            st.session_state.token_expiry = None
            st.rerun()
        
        # Health check
        if st.button("Check System Health"):
            health = api_call("/health", require_auth=False)
            if health and not health.get("error"):
                st.success("✅ System is healthy")
                st.json(health)
    
    # Main chat area
    chat_container = st.container()
    
    with chat_container:
        # Display chat history
        for i, chat in enumerate(st.session_state.chat_history):
            if chat["role"] == "user":
                with st.chat_message("user"):
                    st.write(chat["content"])
            else:
                with st.chat_message("assistant"):
                    st.write(chat["content"])
                    
                    # Display chunks used with expandable sections
                    if chat.get("chunks_used", 0) > 0:
                        # Create a container for chunk information
                        chunk_container = st.container()
                        
                        with chunk_container:
                            # Button to show/hide chunks
                            col1, col2, col3 = st.columns([2, 1, 1])
                            with col1:
                                expand_key = f"show_chunks_{i}"
                                show_chunks = st.session_state.expanded_chunks.get(expand_key, False)
                                
                                if st.button(
                                    f"{'📖 Hide' if show_chunks else '📖 Show'} chunks used ({chat['chunks_used']})",
                                    key=expand_key
                                ):
                                    st.session_state.expanded_chunks[expand_key] = not show_chunks
                                    st.rerun()
                            
                            # Show chunk details if expanded
                            if st.session_state.expanded_chunks.get(expand_key, False):
                                st.markdown("---")
                                st.subheader("📑 Document Chunks Used")
                                
                                # Check if we have chunk details in the response
                                if chat.get("chunks"):
                                    for j, chunk in enumerate(chat["chunks"]):
                                        # Create a unique key for this specific chunk
                                        chunk_key = f"chunk_{i}_{j}"
                                        
                                        # Create expander for each chunk
                                        with st.expander(
                                            f"📄 Chunk {j+1} (Similarity: {chunk.get('similarity_score', 0):.3f})",
                                            expanded=False
                                        ):
                                            # Show chunk content preview
                                            st.markdown("**Content Preview:**")
                                            preview_text = chunk.get("content_preview", "No content available")
                                            st.markdown(f"```\n{preview_text}\n```")
                                            
                                            # Show source info if available
                                            if chat.get("sources") and j < len(chat["sources"]):
                                                source = chat["sources"][j]
                                                st.markdown("**Source Information:**")
                                                st.markdown(f"- **File:** {source.get('filename', 'Unknown')}")
                                                st.markdown(f"- **Uploaded by:** {source.get('uploaded_by', 'Unknown')}")
                                                
                                                # Button to view full chunk content
                                                full_key = f"view_full_{i}_{j}"
                                                if st.button("📝 View Full Content", key=full_key):
                                                    # Toggle full content view
                                                    if full_key not in st.session_state.expanded_full_chunks:
                                                        st.session_state.expanded_full_chunks[full_key] = True
                                                    else:
                                                        st.session_state.expanded_full_chunks[full_key] = not st.session_state.expanded_full_chunks[full_key]
                                                    st.rerun()
                                                
                                                # Show full content if expanded
                                                if st.session_state.expanded_full_chunks.get(full_key, False):
                                                    st.markdown("**Full Content:**")
                                                    full_content = source.get('content', 'No full content available')
                                                    st.markdown(f"```\n{full_content}\n```")
                                                    
                                                    # Add copy button (Streamlit doesn't have native copy, but we can show the text)
                                                    st.markdown("**Copy this chunk:**")
                                                    st.code(full_content, language=None)
                                            else:
                                                st.info("No source information available.")
                                                
                                                # Fallback to basic info
                                                if chunk.get("document_id"):
                                                    st.markdown(f"**Document ID:** `{chunk['document_id']}`")
                                    
                                    # Add summary of sources used
                                    st.markdown("---")
                                    st.subheader("📋 Summary of Sources")
                                    source_set = set()
                                    if chat.get("sources"):
                                        for source in chat["sources"]:
                                            source_set.add(f"{source.get('filename', 'Unknown')} (by {source.get('uploaded_by', 'Unknown')})")
                                        
                                        for source_name in sorted(source_set):
                                            st.markdown(f"• {source_name}")
                                else:
                                    st.info("No detailed chunk information available for this response.")
    
    # Chat input
    chat_input_container = st.container()
    
    with chat_input_container:
        if "chat_input" not in st.session_state:
            st.session_state.chat_input = ""
        
        question = st.chat_input("Ask a question about your documents...", key="chat_input_widget")
        
        if question:
            # Check if this is the same question that's already being processed
            if (st.session_state.processing_question == question or 
                st.session_state.last_processed_question == question):
                # This question is already being processed or was just processed
                # Skip to avoid duplicate requests
                pass
            else:
                # Store that we're processing this question
                st.session_state.processing_question = question
                
                # Add user message to chat history
                st.session_state.chat_history.append({"role": "user", "content": question})
                
                # Show user message immediately
                with st.chat_message("user"):
                    st.write(question)
                
                # Clear the processing flag and mark as last processed
                st.session_state.processing_question = None
                st.session_state.last_processed_question = question
                
                # Get AI response
                with st.chat_message("assistant"):
                    with st.spinner("Thinking..."):
                        data = {
                            "question": question,
                            "use_public_data": use_public_data
                        }
                        response = api_call("/chat/ask", method="POST", data=data, require_auth=True)
                        
                        if response and not response.get("error"):
                            answer = response.get("answer", "No response")
                            st.write(answer)
                            
                            # Store all response data including chunks
                            chat_data = {
                                "role": "assistant",
                                "content": answer,
                                "chunks_used": response.get("chunks_used", 0),
                                "chunks": response.get("chunks", []),
                                "sources": response.get("sources", []),
                                "chat_id": response.get("chat_id")
                            }
                            
                            # Add to chat history
                            st.session_state.chat_history.append(chat_data)
                            
                            # Show budget info
                            budget = response.get("budget_status", {})
                            st.sidebar.info(f"💰 Budget used: ${budget.get('used_budget', 0):.4f}")
                            
                            # Force a rerun to update the UI with the new message
                            st.rerun()
                        else:
                            st.error("Failed to get response")
                            # Clear the last processed question if there was an error
                            st.session_state.last_processed_question = None

# Documents Page
def documents_page():
    st.title("📁 My Documents")
    
    # Clear delete confirmation if we're just viewing
    if st.session_state.confirm_delete and not st.button("Cancel Delete", key="cancel_delete"):
        st.session_state.confirm_delete = None
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Show PDF count with user's limit
        response = api_call("/pdf/user/count", require_auth=True)
        if response and not response.get("error"):
            count = response.get("pdf_count", 0)
            max_allowed = response.get("max_allowed", 5)
            can_upload = response.get("can_upload_more", True)
            user_max_docs = response.get("user_max_documents", 5)
            
            if max_allowed == "unlimited":
                st.success(f"📊 You have {count} PDFs (Unlimited storage)")
            elif can_upload:
                st.success(f"📊 You have {count}/{max_allowed} PDFs")
                st.caption(f"Your document limit: {user_max_docs}")
            else:
                st.warning(f"📊 You have {count}/{max_allowed} PDFs (LIMIT REACHED)")
                st.caption(f"Your document limit: {user_max_docs}")
        
        # List documents
        response = api_call("/pdf/user/documents", require_auth=True)
        
        if response and not response.get("error"):
            documents = response.get("documents", [])
            total_docs = response.get("total_documents", 0)
            max_allowed = response.get("max_allowed", 5)
            
            if documents:
                for doc in documents:
                    with st.expander(f"📄 {doc['filename']}", expanded=False):
                        st.write(f"**ID:** `{doc['document_id']}`")
                        st.write(f"**Uploaded:** {doc['uploaded_at']}")
                        st.write(f"**Chunks:** {doc.get('chunk_count', 0)}")
                        st.write(f"**Visibility:** {'Public' if doc['is_public'] else 'Private (only you)'}")
                        
                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.button("📥 Download", key=f"dl_{doc['document_id']}"):
                                download_response = api_call(f"/pdf/download/{doc['document_id']}", require_auth=True)
                                if download_response and not download_response.get("error"):
                                    st.success(f"Download initiated for {doc['filename']}")
                                    st.info("In a production app, this would trigger a file download")
                        with col_b:
                            # Check if this is the document we're confirming to delete
                            if st.session_state.confirm_delete == doc['document_id']:
                                st.warning(f"⚠️ Are you SURE you want to delete '{doc['filename']}'?")
                                confirm_col1, confirm_col2 = st.columns(2)
                                with confirm_col1:
                                    if st.button(f"🗑️ Yes, Delete", key=f"confirm_del_{doc['document_id']}"):
                                        with st.spinner(f"Deleting {doc['filename']}..."):
                                            result = api_call(f"/pdf/delete/{doc['document_id']}", method="DELETE", require_auth=True)
                                            if result and not result.get("error"):
                                                st.success(f"✅ Deleted '{doc['filename']}'!")
                                                st.session_state.confirm_delete = None
                                                time.sleep(1)
                                                st.rerun()
                                with confirm_col2:
                                    if st.button("❌ Cancel", key=f"cancel_del_{doc['document_id']}"):
                                        st.session_state.confirm_delete = None
                                        st.rerun()
                            else:
                                if st.button("🗑️ Delete", key=f"del_{doc['document_id']}"):
                                    st.session_state.confirm_delete = doc['document_id']
                                    st.rerun()
            else:
                st.info("No documents found. Upload some PDFs!")
    
    with col2:
        # Upload new document
        st.subheader("Upload PDF")
        
        # Check if can upload more
        can_upload_response = api_call("/pdf/user/count", require_auth=True)
        can_upload = True
        max_allowed = "unlimited"
        
        if can_upload_response and not can_upload_response.get("error"):
            can_upload = can_upload_response.get("can_upload_more", True)
            max_allowed = can_upload_response.get("max_allowed", 5)
        
        if not can_upload and max_allowed != "unlimited":
            st.warning(f"⚠️ You've reached your limit of {max_allowed} PDFs!")
            st.info("Delete some PDFs before uploading new ones.")
        else:
            uploaded_file = st.file_uploader("Choose PDF", type="pdf", key="pdf_uploader")
            
            # Only show public option for admins
            if st.session_state.is_admin:
                is_public = st.checkbox("Make public", key="is_public_check", help="Only admins can make documents public")
            else:
                # Regular users: documents are always private
                is_public = False
                st.info("📝 Your documents are private (only you can access them)")
            
            if uploaded_file is not None:
                st.write(f"Selected: {uploaded_file.name}")
                
                if st.button("📤 Upload PDF", key="upload_btn"):
                    with st.spinner(f"Uploading {uploaded_file.name}..."):
                        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
                        data = {
                            "is_public": str(is_public).lower(),
                            "admin_upload": str(st.session_state.is_admin).lower()
                        }
                        
                        response = api_call(
                            "/pdf/upload",
                            method="POST",
                            files=files,
                            data=data,
                            require_auth=True
                        )
                        
                        if response and not response.get("error"):
                            st.success("✅ Uploaded successfully!")
                            if response.get('is_public'):
                                st.info("📢 Document is PUBLIC (visible to all users)")
                            else:
                                st.info("🔒 Document is PRIVATE (only you can access)")
                            
                            st.balloons()
                            time.sleep(1)
                            st.rerun()

# Admin Page
def admin_page():
    st.title("👑 Admin Dashboard")
    
    tab1, tab2, tab3, tab4 = st.tabs(["Users", "Documents", "System", "Registration Management"])
    
    with tab1:
        st.subheader("User Management")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("👥 List All Users", key="list_users_btn"):
                response = api_call("/auth/admin/users", require_auth=True)
                if response and not response.get("error"):
                    users = response.get("users", [])
                    
                    st.write(f"**Total Users:** {len(users)}")
                    
                    for user in users:
                        with st.expander(f"👤 {user['username']} ({'Admin' if user['is_admin'] else 'User'}) - {user['registration_status'].upper()}"):
                            st.write(f"**ID:** `{user['user_id']}`")
                            st.write(f"**Email:** {user['email']}")
                            st.write(f"**Created:** {user['created_at']}")
                            st.write(f"**Status:** {user['registration_status']}")
                            st.write(f"**Document Limit:** {'Unlimited' if user['max_documents'] in [0, -1] else user['max_documents']}")
                            st.write(f"**Current Documents:** {user['document_count']}")
                            if user['registration_status'] == 'pending':
                                if user['registration_expires']:
                                    st.write(f"**Expires:** {user['registration_expires']}")
                                else:
                                    st.write("**Expires:** Never")
                            # Add renew button for pending or expired users
                            if user['registration_status'] in ['pending', 'expired']:
                                if st.button(f"🔄 Renew Password", key=f"renew_{user['user_id']}"):
                                    # Show form to renew password
                                    st.session_state['renew_user_id'] = user['user_id']
                                    st.session_state['renew_username'] = user['username']
                                    st.rerun()
        
        with col2:
            st.subheader("➕ Create New User")
            with st.form("create_user_form"):
                username = st.text_input("Username", key="new_username")
                email = st.text_input("Email", key="new_email")
                temp_password = st.text_input("Temporary Password", type="password", key="temp_password")
                expires = st.checkbox("Password expires in 1 day", value=False, key="expires_check")
                
                col_role, col_docs = st.columns(2)
                with col_role:
                    is_admin = st.checkbox("Make Admin", key="make_admin")
                with col_docs:
                    if is_admin:
                        st.info("Admins have unlimited documents")
                        max_documents = -1
                    else:
                        max_documents = st.number_input(
                            "Max Documents",
                            min_value=1,
                            max_value=1000,
                            value=5,
                            step=1,
                            help="Enter 0 or -1 for unlimited"
                        )
                
                if st.form_submit_button("👤 Create User"):
                    if not all([username, email, temp_password]):
                        st.error("Username, email and temporary password are required")
                    else:
                        data = {
                            "username": username,
                            "email": email,
                            "temporary_password": temp_password,
                            "password_expires": expires,
                            "is_admin": is_admin,
                            "max_documents": max_documents
                        }
                        response = api_call("/auth/admin/create-user", method="POST", data=data, require_auth=True)
                        if response and not response.get("error"):
                            st.success(f"✅ User {username} created successfully!")
                            st.info(f"**Temporary Password:** `{temp_password}`")
                            st.info(f"**Document Limit:** {'Unlimited' if max_documents in [0, -1] else max_documents}")
                            st.warning("⚠️ Give this temporary password to the user!")
                        else:
                            st.error(f"Failed to create user: {response.get('detail', {}).get('detail', 'Unknown error') if response else 'Unknown error'}")
    
    with tab2:
        st.subheader("Document Management")
        
        # Admin upload for other users
        st.subheader("Upload PDF for User")
        with st.form("admin_upload_form"):
            target_user_id = st.text_input("User ID to upload for", key="target_user_id")
            admin_uploaded_file = st.file_uploader("Choose PDF", type="pdf", key="admin_pdf_uploader")
            admin_is_public = st.checkbox("Make document public", key="admin_is_public", value=True)
            
            if st.form_submit_button("Upload for User"):
                if not target_user_id or not admin_uploaded_file:
                    st.error("User ID and PDF file are required")
                else:
                    with st.spinner(f"Uploading {admin_uploaded_file.name} for user {target_user_id}..."):
                        files = {"file": (admin_uploaded_file.name, admin_uploaded_file.getvalue(), "application/pdf")}
                        data = {
                            "is_public": str(admin_is_public).lower(),
                            "admin_upload": "true"
                        }
                        
                        response = api_call(
                            f"/pdf/admin/upload-for-user/{target_user_id}",
                            method="POST",
                            files=files,
                            data=data,
                            require_auth=True
                        )
                        
                        if response and not response.get("error"):
                            st.success("✅ Uploaded successfully!")
                            if response.get('is_public'):
                                st.info("📢 Document is PUBLIC (visible to all users)")
                            else:
                                st.info("🔒 Document is PRIVATE (only the target user can access)")
                            
                            # Show chunk settings
                            chunk_settings = response.get('chunk_settings', {})
                            if chunk_settings:
                                st.info(f"📝 Chunk size: {chunk_settings.get('chunk_size', 300)} characters")
                                st.info(f"📝 Chunk overlap: {chunk_settings.get('chunk_overlap', 30)} characters")
                        else:
                            st.error(f"Upload failed: {response.get('detail', {}).get('detail', 'Unknown error') if response else 'Unknown error'}")
        
        if st.button("📋 List All Documents", key="list_all_docs"):
            response = api_call("/pdf/admin/all-documents", require_auth=True)
            if response and not response.get("error"):
                documents = response.get("documents", [])
                
                st.write(f"**Total Documents:** {len(documents)}")
                
                for doc in documents:
                    with st.expander(f"📄 {doc['filename']} (by {doc['username']})"):
                        st.write(f"**ID:** `{doc['document_id']}`")
                        st.write(f"**User:** {doc['username']} (`{doc['user_id']}`)")
                        st.write(f"**Uploaded:** {doc['uploaded_at']}")
                        st.write(f"**Public:** {'Yes' if doc['is_public'] else 'No'}")
                        st.write(f"**Chunks:** {doc['chunk_count']}")
                        
                        col_del, _ = st.columns([1, 3])
                        with col_del:
                            if st.button("🗑️ Delete", key=f"admin_del_{doc['document_id']}"):
                                st.session_state['admin_confirm_delete'] = doc['document_id']
                                st.session_state['admin_delete_filename'] = doc['filename']
                                st.rerun()
                
                # Handle delete confirmation
                if 'admin_confirm_delete' in st.session_state:
                    st.warning(f"⚠️ Are you SURE you want to delete '{st.session_state['admin_delete_filename']}'?")
                    confirm_col1, confirm_col2 = st.columns(2)
                    with confirm_col1:
                        if st.button(f"🗑️ Yes, Delete", key="admin_confirm_delete_btn"):
                            with st.spinner(f"Deleting {st.session_state['admin_delete_filename']}..."):
                                result = api_call(f"/pdf/delete/{st.session_state['admin_confirm_delete']}", method="DELETE", require_auth=True)
                                if result and not result.get("error"):
                                    st.success(f"✅ Deleted '{st.session_state['admin_delete_filename']}'!")
                                    del st.session_state['admin_confirm_delete']
                                    del st.session_state['admin_delete_filename']
                                    time.sleep(1)
                                    st.rerun()
                    with confirm_col2:
                        if st.button("❌ Cancel", key="admin_cancel_delete_btn"):
                            del st.session_state['admin_confirm_delete']
                            del st.session_state['admin_delete_filename']
                            st.rerun()
    
    with tab3:
        st.subheader("System Status")
        
        if st.button("🩺 Check Health", key="health_check"):
            health = api_call("/health", require_auth=False)
            if health and not health.get("error"):
                st.success("✅ System is healthy")
                st.json(health)
        
        st.subheader("💰 Budget Status")
        budget = api_call("/chat/budget", require_auth=True)
        if budget and not budget.get("error"):
            st.json(budget)
        
        # Clear all chat history button
        st.subheader("🔧 Maintenance")
        if st.button("🗑️ Clear All Chat History", key="clear_all_chats"):
            st.warning("This will clear ALL chat history for ALL users!")
            if st.button("⚠️ Confirm Clear All", key="confirm_clear_all"):
                response = api_call("/chat/admin/cleanup-all", method="POST", data={"days_old": 0}, require_auth=True)
                if response and not response.get("error"):
                    st.success("✅ All chat history cleared!")
                else:
                    st.error("Failed to clear chat history")
    
    with tab4:
        st.subheader("📋 Registration Management")
        
        # Show pending registrations
        if st.button("⏳ Show Pending Registrations", key="show_pending"):
            response = api_call("/auth/admin/pending-registrations", require_auth=True)
            if response and not response.get("error"):
                pending = response.get("pending_registrations", [])
                count = response.get("count", 0)
                
                if pending:
                    st.write(f"**Pending Registrations:** {count}")
                    for user in pending:
                        status = "⏳ Pending" if not user['registration_expired'] else "❌ Expired"
                        col1, col2, col3 = st.columns([3, 2, 2])
                        with col1:
                            st.write(f"{status} - **{user['username']}**")
                            st.write(f"Email: {user['email']}")
                            st.write(f"Document Limit: {'Unlimited' if user['max_documents'] in [0, -1] else user['max_documents']}")
                        with col2:
                            if user['expires_in']:
                                st.write(f"Expires in: {user['expires_in']}")
                            else:
                                st.write("No expiration")
                        with col3:
                            if st.button("🔄 Renew", key=f"renew_pending_{user['user_id']}"):
                                st.session_state['renew_user_id'] = user['user_id']
                                st.session_state['renew_username'] = user['username']
                                st.rerun()
                else:
                    st.info("No pending registrations")
        
        # Renew password form (if a user is selected)
        if 'renew_user_id' in st.session_state:
            st.subheader(f"🔄 Renew Password for {st.session_state['renew_username']}")
            with st.form("renew_password_form"):
                new_temp_password = st.text_input("New Temporary Password", type="password")
                expires = st.checkbox("Password expires in 1 day", value=True)
                
                if st.form_submit_button("Renew Password"):
                    data = {
                        "temporary_password": new_temp_password,
                        "password_expires": expires
                    }
                    response = api_call(f"/auth/admin/renew-password/{st.session_state['renew_user_id']}", 
                                      method="POST", data=data, require_auth=True)
                    if response and not response.get("error"):
                        st.success("✅ Password renewed successfully!")
                        st.info(f"**New Temporary Password:** `{new_temp_password}`")
                        st.warning("⚠️ Give this new temporary password to the user!")
                        # Clear the renewal state
                        del st.session_state['renew_user_id']
                        del st.session_state['renew_username']
                        st.rerun()
            
            if st.button("❌ Cancel Renewal"):
                del st.session_state['renew_user_id']
                del st.session_state['renew_username']
                st.rerun()
        
        # Check registration status
        st.subheader("🔍 Check Registration Status")
        with st.form("check_registration_form"):
            check_username = st.text_input("Username to check")
            
            if st.form_submit_button("Check Status"):
                if check_username:
                    response = api_call(f"/auth/check-registration/{check_username}", require_auth=False)
                    if response and not response.get("error"):
                        status = response.get('status', 'unknown')
                        if status == 'completed':
                            st.success(f"✅ Registration completed")
                        elif status == 'pending':
                            expires_in = response.get('expires_in', '')
                            if expires_in:
                                st.warning(f"⏳ Registration pending - expires in {expires_in}")
                            else:
                                st.warning(f"⏳ Registration pending - no expiration")
                        elif status == 'expired':
                            st.error(f"❌ Registration expired - contact admin for new temporary password")
                        else:
                            st.info(f"❓ Unknown status: {status}")
                        
                        # Show additional info
                        st.write(f"**User ID:** {response.get('user_id')}")
                        st.write(f"**Email:** {response.get('email')}")
                        st.write(f"**Is Admin:** {response.get('is_admin')}")
                        st.write(f"**Document Limit:** {'Unlimited' if response.get('max_documents') in [0, -1] else response.get('max_documents')}")
                        st.write(f"**Created:** {response.get('registration_created')}")

# Profile Page
def profile_page():
    st.title("👤 User Profile")
    
    # Get current user info
    response = api_call("/auth/me", require_auth=True)
    
    if response and not response.get("error"):
        st.subheader("Account Information")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.info(f"**User ID:** {response.get('user_id')}")
            st.info(f"**Username:** {response.get('username')}")
            st.info(f"**Email:** {response.get('email')}")
        
        with col2:
            st.info(f"**Role:** {'Admin' if response.get('is_admin') else 'User'}")
            st.info(f"**Document Limit:** {'Unlimited' if response.get('max_documents') in [0, -1] else response.get('max_documents')}")
            st.info(f"**Account Created:** {response.get('created_at', 'N/A')}")
        
        # Change password section
        st.markdown("---")
        st.subheader("Change Password")
        
        with st.form("change_password_form"):
            current_password = st.text_input("Current Password", type="password")
            new_password = st.text_input("New Password", type="password")
            confirm_password = st.text_input("Confirm New Password", type="password")
            
            if st.form_submit_button("Change Password"):
                if not all([current_password, new_password, confirm_password]):
                    st.error("All fields are required")
                elif new_password != confirm_password:
                    st.error("New passwords don't match")
                else:
                    data = {
                        "current_password": current_password,
                        "new_password": new_password
                    }
                    change_response = api_call("/auth/change-password", method="POST", data=data, require_auth=True)
                    
                    if change_response and not change_response.get("error"):
                        st.success("✅ Password changed successfully!")
                    else:
                        st.error(f"Failed to change password: {change_response.get('detail', {}).get('detail', 'Unknown error') if change_response else 'Unknown error'}")
    else:
        st.error("Failed to load profile information")

# Main App
def main():
    st.set_page_config(
        page_title="Azure RAG Chatbot",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Custom CSS with chunk display styles
    st.markdown("""
        <style>
        .main-header {
            text-align: center;
            color: #1f77b4;
            padding: 1rem;
        }
        .stButton button {
            width: 100%;
        }
        .warning-box {
            background-color: #fff3cd;
            border-color: #ffeaa7;
            color: #856404;
            padding: 1rem;
            border-radius: 0.5rem;
            margin: 1rem 0;
        }
        .public-badge {
            background-color: #28a745;
            color: white;
            padding: 0.2rem 0.5rem;
            border-radius: 0.25rem;
            font-size: 0.8rem;
            margin-left: 0.5rem;
        }
        .private-badge {
            background-color: #6c757d;
            color: white;
            padding: 0.2rem 0.5rem;
            border-radius: 0.25rem;
            font-size: 0.8rem;
            margin-left: 0.5rem;
        }
        .unlimited-badge {
            background-color: #17a2b8;
            color: white;
            padding: 0.2rem 0.5rem;
            border-radius: 0.25rem;
            font-size: 0.8rem;
            margin-left: 0.5rem;
        }
        .success-box {
            background-color: #d4edda;
            border-color: #c3e6cb;
            color: #155724;
            padding: 1rem;
            border-radius: 0.5rem;
            margin: 1rem 0;
        }
        .info-box {
            background-color: #d1ecf1;
            border-color: #bee5eb;
            color: #0c5460;
            padding: 1rem;
            border-radius: 0.5rem;
            margin: 1rem 0;
        }
        .already-registered {
            background-color: #cce5ff;
            border-color: #b8daff;
            color: #004085;
            padding: 1rem;
            border-radius: 0.5rem;
            margin: 1rem 0;
        }
        
        /* Chunk display styles */
        .chunk-box {
            background-color: #f8f9fa;
            border-left: 4px solid #007bff;
            padding: 1rem;
            margin: 0.5rem 0;
            border-radius: 0.25rem;
        }
        
        .chunk-header {
            font-weight: bold;
            color: #0056b3;
            margin-bottom: 0.5rem;
        }
        
        .chunk-content {
            background-color: white;
            padding: 0.75rem;
            border-radius: 0.25rem;
            border: 1px solid #dee2e6;
            font-family: 'Courier New', monospace;
            font-size: 0.9rem;
            max-height: 300px;
            overflow-y: auto;
        }
        
        .chunk-source {
            font-size: 0.8rem;
            color: #6c757d;
            margin-top: 0.5rem;
            padding-top: 0.5rem;
            border-top: 1px dashed #dee2e6;
        }
        
        .similarity-badge {
            background-color: #28a745;
            color: white;
            padding: 0.2rem 0.5rem;
            border-radius: 0.25rem;
            font-size: 0.8rem;
            float: right;
        }
        
        .chunk-preview {
            font-family: 'Courier New', monospace;
            background-color: #f5f5f5;
            padding: 0.5rem;
            border-radius: 0.25rem;
            font-size: 0.85rem;
            margin: 0.5rem 0;
            border: 1px solid #e0e0e0;
        }
        
        .chunk-full-content {
            font-family: 'Courier New', monospace;
            background-color: #f8f9fa;
            padding: 1rem;
            border-radius: 0.25rem;
            font-size: 0.9rem;
            margin: 0.5rem 0;
            border: 1px solid #dee2e6;
            max-height: 400px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        
        /* Chat message styling */
        .chat-message-user {
            background-color: #e3f2fd;
            border-radius: 10px;
            padding: 10px;
            margin: 5px 0;
        }
        
        .chat-message-assistant {
            background-color: #f1f8e9;
            border-radius: 10px;
            padding: 10px;
            margin: 5px 0;
        }
        
        .chunk-toggle-button {
            background-color: #6c757d;
            color: white;
            border: none;
            padding: 5px 10px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 0.9rem;
        }
        
        .chunk-toggle-button:hover {
            background-color: #5a6268;
        }
        
        /* Token info styling */
        .token-info {
            font-size: 0.8rem;
            color: #6c757d;
            padding: 0.5rem;
            background-color: #f8f9fa;
            border-radius: 0.25rem;
            margin: 0.5rem 0;
            border-left: 3px solid #17a2b8;
        }
        </style>
    """, unsafe_allow_html=True)
    
    # App header
    st.markdown('<h1 class="main-header">🤖 Azure RAG Chatbot</h1>', unsafe_allow_html=True)
    
    # Check login
    if not st.session_state.logged_in:
        login_page()
    else:
        # Navigation based on user role
        st.sidebar.title("Navigation")
        st.sidebar.write(f"Logged in as: **{st.session_state.username}**")
        st.sidebar.write(f"Role: **{'Admin' if st.session_state.is_admin else 'User'}**")
        
        # Show session info
        if st.session_state.token_expiry:
            try:
                expiry_time = datetime.fromisoformat(st.session_state.token_expiry)
                time_left = expiry_time - datetime.now()
                minutes_left = int(time_left.total_seconds() / 60)
                if minutes_left > 0:
                    st.sidebar.markdown(f'<div class="token-info">🔄 Session expires in: {minutes_left} minutes</div>', unsafe_allow_html=True)
                else:
                    st.sidebar.warning("⚠️ Session expired. Please refresh.")
            except:
                pass
        
        # Show document limit in sidebar
        if st.session_state.is_admin:
            st.sidebar.write("📊 Document limit: **Unlimited**")
        else:
            limit_display = "Unlimited" if st.session_state.user_max_documents in [0, -1] else st.session_state.user_max_documents
            st.sidebar.write(f"📊 Document limit: **{limit_display}**")
        
        # Get current PDF count for sidebar
        if st.session_state.user_id:
            response = api_call("/pdf/user/count", require_auth=True)
            if response and not response.get("error"):
                count = response.get("pdf_count", 0)
                max_allowed = response.get("max_allowed", 5)
                if max_allowed == "unlimited":
                    st.sidebar.write(f"📁 PDFs: **{count}** (Unlimited)")
                else:
                    st.sidebar.write(f"📁 PDFs: **{count}/{max_allowed}**")
        
        # Show chunk settings in sidebar
        st.sidebar.markdown("---")
        st.sidebar.subheader("⚙️ RAG Settings")
        st.sidebar.info("Chunk size: **300** characters")
        st.sidebar.info("Chunk overlap: **30** characters")
        st.sidebar.info("Top chunks per query: **5**")
        
        if st.session_state.is_admin:
            menu = ["💬 Chat", "📁 Documents", "👑 Admin", "👤 Profile", "🚪 Logout"]
        else:
            menu = ["💬 Chat", "📁 Documents", "👤 Profile", "🚪 Logout"]
        
        choice = st.sidebar.selectbox("Go to", menu, key="nav_menu")
        
        # Quick actions in sidebar
        st.sidebar.markdown("---")
        st.sidebar.subheader("Quick Actions")
        
        if st.sidebar.button("🔄 Refresh Session", key="refresh_session"):
            refresh_response = refresh_token_call()
            if refresh_response and not refresh_response.get("error"):
                st.sidebar.success("✅ Session refreshed")
                time.sleep(1)
                st.rerun()
            else:
                st.sidebar.error("❌ Failed to refresh session")
        
        if st.sidebar.button("🔌 Test Connection", key="test_conn"):
            health = api_call("/health", require_auth=False)
            if health and not health.get("error"):
                st.sidebar.success("✅ Connected to backend")
            else:
                st.sidebar.error("❌ Cannot connect to backend")
        
        # Main content based on menu choice
        if choice == "💬 Chat":
            chat_page()
        elif choice == "📁 Documents":
            documents_page()
        elif choice == "👑 Admin":
            if st.session_state.is_admin:
                admin_page()
            else:
                st.error("❌ Admin access required!")
                st.info("You need to log in as an administrator to access this page.")
        elif choice == "👤 Profile":
            profile_page()
        elif choice == "🚪 Logout":
            if st.sidebar.button("✅ Confirm Logout", key="confirm_logout"):
                # Clear all session state
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                init_session_state()
                st.success("Logged out successfully!")
                time.sleep(1)
                st.rerun()

if __name__ == "__main__":
    main()