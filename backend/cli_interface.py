# backend/cli_interface.py - Updated with document limit support and new admin-controlled registration system
import sys
import os
import json
from datetime import datetime
import getpass
from typing import Dict, Any
import requests
from database import get_db_connection
from shared_dependencies import create_embedding
import psycopg2
import glob

class CLIInterface:
    def __init__(self):
        self.current_user_id = None
        self.current_username = None
        self.is_admin = False
        self.backend_url = "http://localhost:8000"
        self.token = None
        self.admin_token = None  # Store admin token for admin operations
    
    def clear_screen(self):
        """Clear console screen"""
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def print_header(self, title):
        """Print formatted header"""
        print("\n" + "="*60)
        print(f" {title}")
        print("="*60)
    
    def api_call(self, endpoint, method="GET", data=None, files=None, headers=None):
        """Make API call to backend"""
        try:
            url = f"{self.backend_url}{endpoint}"
            
            # Prepare headers
            request_headers = {}
            if headers:
                request_headers.update(headers)
            
            if method == "GET":
                response = requests.get(url, headers=request_headers)
            elif method == "POST" and files:
                response = requests.post(url, files=files, data=data, headers=request_headers)
            elif method == "POST":
                if not request_headers.get("Content-Type"):
                    request_headers["Content-Type"] = "application/json"
                response = requests.post(url, json=data, headers=request_headers)
            elif method == "DELETE":
                response = requests.delete(url, headers=request_headers)
            else:
                return None
            
            if response.status_code in [200, 201]:
                return response.json()
            else:
                # Try to parse error message
                try:
                    error_data = response.json()
                    error_msg = error_data.get("detail", response.text)
                except:
                    error_msg = response.text
                print(f"❌ Error {response.status_code}: {error_msg}")
                return None
        except Exception as e:
            print(f"❌ Connection error: {str(e)}")
            return None
    
    def login(self):
        """Login to the system (for regular users)"""
        self.clear_screen()
        self.print_header("LOGIN")
        
        username = input("Username: ").strip()
        password = getpass.getpass("Password: ")
        
        data = {"username": username, "password": password}
        response = self.api_call("/auth/login", method="POST", data=data)
        
        if response:
            self.current_user_id = response.get("user_id")
            self.current_username = username
            self.is_admin = response.get("is_admin", False)
            print(f"\n✅ Welcome {username}!")
            print(f"   Role: {'Admin' if self.is_admin else 'User'}")
            return True
        else:
            print("\n❌ Login failed!")
            return False
    
    def admin_login(self):
        """Admin login to get admin token"""
        self.clear_screen()
        self.print_header("ADMIN LOGIN")
        
        username = input("Admin Username: ").strip()
        password = getpass.getpass("Admin Password: ")
        
        data = {"username": username, "password": password}
        
        response = self.api_call("/auth/login", method="POST", data=data)
        
        if response:
            if response.get("is_admin"):
                self.current_user_id = response.get("user_id")
                self.current_username = username
                self.is_admin = True
                print(f"\n✅ Admin login successful!")
                print(f"   Welcome, {username}!")
                return True
            else:
                print("\n❌ User is not an admin!")
                return False
        else:
            print("\n❌ Login failed!")
            return False
    
    def complete_registration(self):
        """User completes registration with admin-provided temporary password"""
        self.clear_screen()
        self.print_header("COMPLETE REGISTRATION")
        
        username = input("Your Username: ").strip()
        registration_password = getpass.getpass("Temporary password (from admin): ")
        new_password = getpass.getpass("Your new password: ")
        confirm_password = getpass.getpass("Confirm new password: ")
        
        if new_password != confirm_password:
            print("\n❌ New passwords don't match!")
            input("Press Enter to continue...")
            return False
        
        data = {
            "username": username,
            "registration_password": registration_password,
            "new_password": new_password
        }
        
        response = self.api_call("/auth/complete-registration", method="POST", data=data)
        
        if response:
            print(f"\n✅ Registration completed successfully!")
            print(f"   You can now login with your new password.")
            return True
        else:
            input("\nPress Enter to continue...")
            return False
    
    def display_admin_main_menu(self):
        """Admin main menu"""
        while True:
            self.clear_screen()
            self.print_header(f"ADMIN MAIN MENU - {self.current_username}")
            print("1. User Management")
            print("2. Chat Management")
            print("3. Data Management")
            print("4. VectorDB Management")
            print("5. System Status")
            print("0. Logout")
            print("="*60)
            
            choice = input("\nSelect option: ").strip()
            
            if choice == "1":
                self.user_management_menu()
            elif choice == "2":
                self.chat_management_menu()
            elif choice == "3":
                self.data_management_menu()
            elif choice == "4":
                self.vectordb_management_menu()
            elif choice == "5":
                self.system_status()
            elif choice == "0":
                self.logout()
                return
            else:
                input("\n❌ Invalid option. Press Enter to continue...")
    
    def user_management_menu(self):
        """User management submenu"""
        while True:
            self.clear_screen()
            self.print_header("USER MANAGEMENT")
            print("1. List users with registration status")
            print("2. Create new user")
            print("3. Reset user registration (if expired)")
            print("4. View registration status")
            print("5. Renew temporary password for user")
            print("0. Back to main menu")
            print("="*60)
            
            choice = input("\nSelect option: ").strip()
            
            if choice == "1":
                self.list_users_with_status()
            elif choice == "2":
                self.create_user_admin()
            elif choice == "3":
                self.reset_user_registration()
            elif choice == "4":
                self.view_registration_status()
            elif choice == "5":
                self.renew_user_password()
            elif choice == "0":
                return
            else:
                input("\n❌ Invalid option. Press Enter to continue...")
    
    def list_users_with_status(self):
        """List all users with registration status"""
        if not self.is_admin:
            print("❌ Admin access required. Please login as admin first.")
            input("Press Enter to continue...")
            return
        
        response = self.api_call("/auth/admin/users")
        
        if response:
            users = response.get("users", [])
            
            print("\n" + "-"*120)
            print(f"{'Username':<20} {'Status':<15} {'Role':<10} {'Documents':<10} {'Max Docs':<10} {'Created'}")
            print("-"*120)
            
            for user in users:
                username = user['username']
                status = user['registration_status']
                role = 'Admin' if user['is_admin'] else 'User'
                doc_count = user['document_count']
                max_docs = user['max_documents']
                created = user['created_at'][:10] if user['created_at'] else 'N/A'
                
                # Color coding for status
                if status == 'active':
                    status_display = f"✅ {status}"
                elif status == 'pending':
                    status_display = f"⏳ {status}"
                elif status == 'expired':
                    status_display = f"❌ {status}"
                else:
                    status_display = status
                
                # Format max documents display
                if max_docs == -1:
                    max_docs_display = "Unlimited"
                else:
                    max_docs_display = str(max_docs)
                
                # Format documents display
                docs_display = f"{doc_count}/{max_docs_display}"
                if max_docs != -1 and doc_count >= max_docs:
                    docs_display = f"⚠️ {docs_display}"
                
                print(f"{username:<20} {status_display:<15} {role:<10} {docs_display:<10} {max_docs_display:<10} {created}")
            
            print(f"\nTotal users: {len(users)}")
        
        input("\nPress Enter to continue...")
    
    def create_user_admin(self):
        """Admin creates a new user"""
        if not self.is_admin:
            print("❌ Admin access required. Please login as admin first.")
            input("Press Enter to continue...")
            return
        
        print("\n--- Create New User ---")
        username = input("Username: ").strip()
        email = input("Email: ").strip()
        
        # Check if username already exists
        response = self.api_call(f"/auth/check-registration/{username}")
        if response and response.get("detail") != "User not found":
            print(f"❌ Username '{username}' already exists!")
            input("Press Enter to continue...")
            return
        
        temp_password = getpass.getpass("Temporary password: ")
        confirm_password = getpass.getpass("Confirm temporary password: ")
        
        if temp_password != confirm_password:
            print("❌ Passwords don't match!")
            input("Press Enter to continue...")
            return
        
        print("\nPassword Type:")
        print("1. Permanent (never expires)")
        print("2. Temporary (expires in 1 day)")
        token_choice = input("Select (1 or 2): ").strip()
        
        password_expires = False
        if token_choice == "2":
            password_expires = True
        
        print("\nUser Role:")
        print("1. Regular User")
        print("2. Admin User")
        role_choice = input("Select (1 or 2): ").strip()
        
        is_admin = False
        if role_choice == "2":
            is_admin = True
        
        print("\nDocument Limit:")
        print("- Enter -1 for unlimited documents (admins only)")
        print("- Enter 0 for unlimited documents")
        print("- Enter positive number for limit (e.g., 5, 10, 20)")
        max_docs_input = input("Maximum documents user can upload: ").strip()
        
        try:
            max_documents = int(max_docs_input)
            if is_admin:
                print("⚠️  Admin users automatically get unlimited documents")
                max_documents = -1
            elif max_documents == 0 or max_documents == -1:
                print("⚠️  Regular user with unlimited documents!")
        except:
            max_documents = 5
            print(f"⚠️  Invalid input, using default: {max_documents}")
        
        data = {
            "username": username,
            "email": email,
            "temporary_password": temp_password,
            "password_expires": password_expires,
            "is_admin": is_admin,
            "max_documents": max_documents
        }
        
        response = self.api_call("/auth/admin/create-user", method="POST", data=data)
        
        if response:
            print(f"\n✅ User '{username}' created successfully!")
            print(f"   Email: {email}")
            print(f"   Role: {'Admin' if is_admin else 'User'}")
            print(f"   Temporary Password: {temp_password}")
            print(f"   Document Limit: {'Unlimited' if max_documents in [0, -1] else max_documents}")
            
            if password_expires:
                print(f"   ⏰ Password expires in 1 day")
            else:
                print(f"   ✅ Password is permanent")
            
            print(f"\n   📋 Give this information to the user:")
            print(f"   Username: {username}")
            print(f"   Temporary Password: {temp_password}")
            print(f"   Login URL: http://localhost:8000/")
        else:
            print("❌ Failed to create user")
        
        input("\nPress Enter to continue...")
    
    def reset_user_registration(self):
        """Reset user registration (if expired)"""
        if not self.is_admin:
            print("❌ Admin access required. Please login as admin first.")
            input("Press Enter to continue...")
            return
        
        print("\n--- Reset User Registration ---")
        user_id = input("User ID to reset: ").strip()
        
        confirm = input(f"Are you sure you want to reset registration for user {user_id}? (y/n): ").strip().lower()
        
        if confirm == 'y':
            # Get user info first
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT username, email FROM users WHERE user_id = %s", (user_id,))
            user = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if not user:
                print("❌ User not found!")
                input("Press Enter to continue...")
                return
            
            username, email = user
            
            # Generate new temporary password
            import secrets
            import string
            alphabet = string.ascii_letters + string.digits
            new_temp_password = ''.join(secrets.choice(alphabet) for _ in range(12))
            
            print(f"\nGenerating new temporary password for {username}...")
            print(f"New temporary password: {new_temp_password}")
            
            temp_password_hash = self.hash_password(new_temp_password)
            current_time = datetime.utcnow()
            
            # Update database
            conn = get_db_connection()
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    UPDATE users 
                    SET registration_password_hash = %s,
                        registration_created_at = %s,
                        registration_used = false
                    WHERE user_id = %s
                """, (temp_password_hash, current_time, user_id))
                
                # Log activity
                details = json.dumps({
                    "username": username,
                    "email": email,
                    "reason": "admin_reset"
                })
                cursor.execute("""
                    INSERT INTO activity_log (user_id, activity_type, details)
                    VALUES (%s, %s, %s)
                """, (user_id, 'ADMIN_RESET_REGISTRATION', details))
                
                conn.commit()
                print(f"✅ Registration reset successfully!")
                print(f"   New temporary password: {new_temp_password}")
                print(f"   Give this to the user to complete registration.")
            except Exception as e:
                conn.rollback()
                print(f"❌ Failed to reset registration: {e}")
            finally:
                cursor.close()
                conn.close()
        else:
            print("Cancelled")
        
        input("\nPress Enter to continue...")
    
    def hash_password(self, password: str) -> str:
        """Hash password (simplified version for CLI)"""
        import hashlib
        import base64
        # Simple hash for CLI purposes
        return hashlib.sha256(password.encode()).hexdigest()
    
    def renew_user_password(self):
        """Renew temporary password for user"""
        if not self.is_admin:
            print("❌ Admin access required. Please login as admin first.")
            input("Press Enter to continue...")
            return
        
        print("\n--- Renew Temporary Password ---")
        username = input("Username: ").strip()
        
        # Get user info
        response = self.api_call(f"/auth/check-registration/{username}")
        if not response or response.get("detail") == "User not found":
            print("❌ User not found!")
            input("Press Enter to continue...")
            return
        
        user_id = response.get("user_id")
        current_status = response.get("status")
        
        print(f"\nUser: {username}")
        print(f"Status: {current_status}")
        print(f"User ID: {user_id}")
        
        new_temp_password = getpass.getpass("New temporary password: ")
        confirm_password = getpass.getpass("Confirm new temporary password: ")
        
        if new_temp_password != confirm_password:
            print("❌ Passwords don't match!")
            input("Press Enter to continue...")
            return
        
        print("\nPassword Type:")
        print("1. Permanent (never expires)")
        print("2. Temporary (expires in 1 day)")
        token_choice = input("Select (1 or 2): ").strip()
        
        password_expires = False
        if token_choice == "2":
            password_expires = True
        
        data = {
            "temporary_password": new_temp_password,
            "password_expires": password_expires
        }
        
        response = self.api_call(f"/auth/admin/renew-password/{user_id}", method="POST", data=data)
        
        if response:
            print(f"\n✅ Temporary password renewed successfully!")
            print(f"   New temporary password: {new_temp_password}")
            print(f"   Expires: {'1 day' if password_expires else 'Never'}")
            print(f"\n   Give this new temporary password to the user.")
        else:
            print("❌ Failed to renew password")
        
        input("\nPress Enter to continue...")
    
    def view_registration_status(self):
        """View registration status for a username"""
        print("\n--- Check Registration Status ---")
        username = input("Username: ").strip()
        
        response = self.api_call(f"/auth/check-registration/{username}")
        
        if response:
            if response.get("detail") == "User not found":
                print(f"❌ User '{username}' not found")
            else:
                print(f"\nRegistration Status for '{username}':")
                print(f"  User ID: {response.get('user_id')}")
                print(f"  Email: {response.get('email')}")
                print(f"  Status: {response.get('status')}")
                print(f"  Registration Completed: {response.get('registration_completed')}")
                print(f"  Is Admin: {response.get('is_admin')}")
                print(f"  Max Documents: {'Unlimited' if response.get('max_documents') in [0, -1] else response.get('max_documents')}")
                
                expires_at = response.get('registration_expires')
                if expires_at:
                    print(f"  Expires at: {expires_at}")
                    if response.get('registration_expired'):
                        print(f"  ⚠️  Registration has EXPIRED")
                    else:
                        expires_in = response.get('expires_in')
                        if expires_in:
                            print(f"  ✅ Registration valid (expires in {expires_in})")
                else:
                    print(f"  Expires: Never (permanent)")
                
                print(f"  Created: {response.get('registration_created')}")
        else:
            print("❌ Failed to get registration status")
        
        input("\nPress Enter to continue...")
    
    def chat_management_menu(self):
        """Chat management submenu"""
        while True:
            self.clear_screen()
            self.print_header("CHAT MANAGEMENT")
            print("1. View user chat history")
            print("0. Back to main menu")
            print("="*60)
            
            choice = input("\nSelect option: ").strip()
            
            if choice == "1":
                self.view_user_chat_history()
            elif choice == "0":
                return
            else:
                input("\n❌ Invalid option. Press Enter to continue...")
    
    def view_user_chat_history(self):
        """View chat history for a user"""
        user_id = input("\nUser ID: ").strip()
        limit = input("Number of messages to show (default 20): ").strip()
        limit = int(limit) if limit else 20
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT chat_id, user_message, ai_response, created_at
                FROM chat_history 
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (user_id, limit))
            
            chats = cursor.fetchall()
            
            if not chats:
                print("\nNo chat history found for this user")
            else:
                print(f"\nChat History for user {user_id}:")
                print("-"*80)
                
                for chat in chats:
                    chat_id, user_msg, ai_resp, created_at = chat
                    print(f"\n[{created_at.strftime('%Y-%m-%d %H:%M:%S')}]")
                    print(f"User: {user_msg[:100]}{'...' if len(user_msg) > 100 else ''}")
                    print(f"AI: {ai_resp[:100]}{'...' if len(ai_resp) > 100 else ''}")
                    print(f"Chat ID: {chat_id}")
                    print("-"*40)
                
                print(f"\nTotal chats shown: {len(chats)}")
        
        finally:
            cursor.close()
            conn.close()
        
        input("\nPress Enter to continue...")
    
    def data_management_menu(self):
        """Data management submenu"""
        while True:
            self.clear_screen()
            self.print_header("DATA MANAGEMENT")
            print("1. Upload PDF(s) for user")
            print("2. Upload all PDFs from folder for user")
            print("3. List all PDFs")
            print("4. Delete PDF(s)")
            print("5. Delete all public PDFs")
            print("0. Back to main menu")
            print("="*60)
            
            choice = input("\nSelect option: ").strip()
            
            if choice == "1":
                self.upload_pdfs_admin()
            elif choice == "2":
                self.upload_folder_pdfs_admin()
            elif choice == "3":
                self.list_all_pdfs()
            elif choice == "4":
                self.delete_pdfs()
            elif choice == "5":
                self.delete_public_pdfs()
            elif choice == "0":
                return
            else:
                input("\n❌ Invalid option. Press Enter to continue...")
    
    def upload_pdfs_admin(self):
        """Admin upload PDFs for any user"""
        print("\n--- Upload PDFs (Admin) ---")
        user_id = input("User ID to upload for: ").strip()
        
        # Get user info to check if admin
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username, is_admin, max_documents FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not user:
            print("❌ User not found!")
            input("Press Enter to continue...")
            return
        
        username, is_user_admin, max_documents = user
        
        # Check user's current PDF count (only if not admin/unlimited)
        if not is_user_admin and max_documents not in [0, -1]:
            count_response = self.api_call(f"/pdf/user/{user_id}/count")
            if count_response:
                pdf_count = count_response.get("pdf_count", 0)
                if pdf_count >= max_documents:
                    print(f"❌ User already has {pdf_count} PDFs (max: {max_documents})")
                    input("Press Enter to continue...")
                    return
        
        file_path = input("PDF file path: ").strip()
        
        if not os.path.exists(file_path):
            print("❌ File not found!")
            input("Press Enter to continue...")
            return
        
        # Admin can choose public or private
        is_public_input = input("Make document public? (y/n): ").strip().lower()
        is_public = is_public_input == 'y'
        
        print(f"\nUploading {file_path} for user {username}...")
        
        with open(file_path, 'rb') as f:
            files = {"file": (os.path.basename(file_path), f, "application/pdf")}
            data = {
                "is_public": str(is_public).lower(),
                "admin_upload": "true"  # This tells backend it's an admin upload
            }
            
            response = self.api_call(
                f"/pdf/upload/{user_id}",
                method="POST",
                files=files,
                data=data
            )
            
            if response:
                print("✅ Upload successful!")
                print(f"Document ID: {response.get('document_id')}")
                print(f"Chunks created: {response.get('chunks_created')}")
                if response.get('is_public'):
                    print("📢 Document is PUBLIC (visible to all users)")
                else:
                    print("🔒 Document is PRIVATE (only the user can access)")
                print(f"Chunk size: {response.get('chunk_settings', {}).get('chunk_size', 300)}")
                print(f"Chunk overlap: {response.get('chunk_settings', {}).get('chunk_overlap', 30)}")
            else:
                print("❌ Upload failed!")
        
        input("\nPress Enter to continue...")
    
    def upload_folder_pdfs_admin(self):
        """Admin upload all PDFs from folder for any user"""
        print("\n--- Upload Folder PDFs (Admin) ---")
        user_id = input("User ID to upload for: ").strip()
        folder_path = input("Folder path: ").strip()
        
        if not os.path.isdir(folder_path):
            print("❌ Folder not found!")
            input("Press Enter to continue...")
            return
        
        # Get user info to check limits
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username, is_admin, max_documents FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not user:
            print("❌ User not found!")
            input("Press Enter to continue...")
            return
        
        username, is_user_admin, max_documents = user
        
        pdf_files = glob.glob(os.path.join(folder_path, "*.pdf"))
        
        if not pdf_files:
            print("❌ No PDF files found in folder!")
            input("Press Enter to continue...")
            return
        
        print(f"\nFound {len(pdf_files)} PDF files")
        
        # Check current PDF count if user has limits
        current_count = 0
        if not is_user_admin and max_documents not in [0, -1]:
            count_response = self.api_call(f"/pdf/user/{user_id}/count")
            if count_response:
                current_count = count_response.get("pdf_count", 0)
                if current_count >= max_documents:
                    print(f"❌ User already has {current_count} PDFs (max: {max_documents})")
                    input("Press Enter to continue...")
                    return
        
        # Admin can choose public or private for all files
        is_public_input = input("Make all documents public? (y/n): ").strip().lower()
        is_public = is_public_input == 'y'
        
        uploaded_count = 0
        for pdf_file in pdf_files:
            # Check if user can upload more (only for limited users)
            if not is_user_admin and max_documents not in [0, -1]:
                count_response = self.api_call(f"/pdf/user/{user_id}/count")
                if count_response:
                    pdf_count = count_response.get("pdf_count", 0)
                    if pdf_count >= max_documents:
                        print(f"\n⚠️  User reached {max_documents} PDF limit. Stopping upload.")
                        break
            
            print(f"\nUploading: {os.path.basename(pdf_file)}")
            
            with open(pdf_file, 'rb') as f:
                files = {"file": (os.path.basename(pdf_file), f, "application/pdf")}
                data = {
                    "is_public": str(is_public).lower(),
                    "admin_upload": "true"
                }
                
                response = self.api_call(
                    f"/pdf/upload/{user_id}",
                    method="POST",
                    files=files,
                    data=data
                )
                
                if response:
                    visibility = "PUBLIC" if response.get('is_public') else "PRIVATE"
                    print(f"  ✅ Success! (Chunks: {response.get('chunks_created')}, {visibility})")
                    uploaded_count += 1
                else:
                    print(f"  ❌ Failed!")
        
        print(f"\n✅ Uploaded {uploaded_count} out of {len(pdf_files)} PDFs")
        print(f"📊 User {username} now has approximately {current_count + uploaded_count} PDFs")
        input("\nPress Enter to continue...")
    
    def list_all_pdfs(self):
        """List all PDFs in system"""
        response = self.api_call("/pdf/admin/all-documents")
        
        if response:
            documents = response.get("documents", [])
            
            print("\n" + "-"*120)
            print(f"{'Filename':<30} {'User':<15} {'Uploaded':<20} {'Public':<8} {'Chunks':<8} {'User Type'}")
            print("-"*120)
            
            for doc in documents:
                filename = doc['filename'][:28] + '...' if len(doc['filename']) > 28 else doc['filename']
                username = doc['username'][:13] + '...' if len(doc['username']) > 13 else doc['username']
                uploaded = doc['uploaded_at'][:19]
                public_status = 'PUBLIC' if doc['is_public'] else 'PRIVATE'
                
                # Check if user is admin
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT is_admin FROM users WHERE user_id = %s", (doc['user_id'],))
                user_result = cursor.fetchone()
                cursor.close()
                conn.close()
                
                user_type = "Admin" if user_result and user_result[0] else "User"
                
                print(f"{filename:<30} {username:<15} {uploaded:<20} {public_status:<8} {doc['chunk_count']:<8} {user_type}")
            
            print(f"\nTotal documents: {len(documents)}")
        
        input("\nPress Enter to continue...")
    
    def delete_pdfs(self):
        """Delete PDFs"""
        print("\n--- Delete PDFs ---")
        document_id = input("Document ID to delete: ").strip()
        
        confirm = input(f"Delete document {document_id}? (y/n): ").strip().lower()
        
        if confirm == 'y':
            response = self.api_call(f"/pdf/delete/{document_id}", method="DELETE")
            if response:
                print("✅ Document deleted successfully!")
            else:
                print("❌ Failed to delete document")
        
        input("\nPress Enter to continue...")
    
    def delete_public_pdfs(self):
        """Delete all public PDFs"""
        print("\n--- Delete All Public PDFs ---")
        
        # First list public PDFs
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM documents WHERE is_public = true
            """)
            
            count = cursor.fetchone()[0]
            
            if count == 0:
                print("No public PDFs found.")
                input("\nPress Enter to continue...")
                return
            
            confirm = input(f"WARNING: This will delete {count} public PDFs! Continue? (y/n): ").strip().lower()
            
            if confirm == 'y':
                cursor.execute("""
                    SELECT document_id, filename FROM documents WHERE is_public = true
                """)
                
                public_docs = cursor.fetchall()
                deleted_count = 0
                
                for doc_id, filename in public_docs:
                    response = self.api_call(f"/pdf/delete/{doc_id}", method="DELETE")
                    if response:
                        deleted_count += 1
                        print(f"Deleted: {filename}")
                
                print(f"\n✅ Deleted {deleted_count} out of {count} public PDFs")
            else:
                print("Cancelled")
        
        finally:
            cursor.close()
            conn.close()
        
        input("\nPress Enter to continue...")
    
    def vectordb_management_menu(self):
        """VectorDB management submenu"""
        while True:
            self.clear_screen()
            self.print_header("VECTORDB MANAGEMENT")
            print("1. Ingest all public PDFs")
            print("2. Ingest PDF by filename (public or specific user)")
            print("3. Remove PDF data by filename")
            print("4. Remove PDF data by user")
            print("5. List available PDF data")
            print("6. Clear all users' memory")
            print("7. Clear user memory by user ID")
            print("0. Back to main menu")
            print("="*60)
            
            choice = input("\nSelect option: ").strip()
            
            if choice == "1":
                self.ingest_all_public_pdfs()
            elif choice == "2":
                self.ingest_pdf_by_filename()
            elif choice == "3":
                self.remove_pdf_by_filename()
            elif choice == "4":
                self.remove_pdf_by_user()
            elif choice == "5":
                self.list_pdf_data()
            elif choice == "6":
                self.clear_all_memory()
            elif choice == "7":
                self.clear_user_memory()
            elif choice == "0":
                return
            else:
                input("\n❌ Invalid option. Press Enter to continue...")
    
    def ingest_all_public_pdfs(self):
        """Ingest all public PDFs (re-process)"""
        print("\n--- Ingest All Public PDFs ---")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT document_id, filename, user_id FROM documents WHERE is_public = true
            """)
            
            public_docs = cursor.fetchall()
            
            if not public_docs:
                print("No public PDFs found.")
                input("\nPress Enter to continue...")
                return
            
            print(f"Found {len(public_docs)} public PDFs to re-ingest")
            confirm = input("Continue? (y/n): ").strip().lower()
            
            if confirm != 'y':
                print("Cancelled")
                input("\nPress Enter to continue...")
                return
            
            # Note: This would need a re-processing endpoint
            print("⚠️  Re-ingestion endpoint not implemented yet")
            print("PDFs are automatically ingested on upload")
            print(f"Current chunk size: 300")
            print(f"Current chunk overlap: 30")
            
        finally:
            cursor.close()
            conn.close()
        
        input("\nPress Enter to continue...")
    
    def ingest_pdf_by_filename(self):
        """Ingest PDF by filename"""
        print("\n--- Ingest PDF by Filename ---")
        filename = input("Filename: ").strip()
        user_id = input("User ID (leave empty for all users): ").strip() or None
        
        if user_id:
            # Ingest for specific user
            conn = get_db_connection()
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    SELECT document_id FROM documents 
                    WHERE filename = %s AND user_id = %s
                """, (filename, user_id))
                
                doc = cursor.fetchone()
                
                if doc:
                    print(f"Found document: {doc[0]}")
                    print("⚠️  Re-ingestion endpoint not implemented yet")
                    print("PDFs are automatically ingested on upload")
                else:
                    print("Document not found for this user")
            
            finally:
                cursor.close()
                conn.close()
        else:
            # Ingest for all users with this filename
            print(f"Would ingest PDF '{filename}' for all users")
            print("⚠️  This feature requires additional implementation")
        
        input("\nPress Enter to continue...")
    
    def remove_pdf_by_filename(self):
        """Remove PDF data by filename"""
        print("\n--- Remove PDF by Filename ---")
        filename = input("Filename: ").strip()
        user_id = input("User ID (leave empty for all): ").strip() or None
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            if user_id:
                cursor.execute("""
                    SELECT document_id FROM documents 
                    WHERE filename = %s AND user_id = %s
                """, (filename, user_id))
            else:
                cursor.execute("""
                    SELECT document_id FROM documents WHERE filename = %s
                """, (filename,))
            
            docs = cursor.fetchall()
            
            if not docs:
                print("No documents found with that filename")
                input("\nPress Enter to continue...")
                return
            
            print(f"Found {len(docs)} document(s) with filename '{filename}'")
            
            confirm = input("Remove vector data for these documents? (y/n): ").strip().lower()
            
            if confirm == 'y':
                deleted_count = 0
                for doc in docs:
                    cursor.execute("""
                        DELETE FROM document_chunks WHERE document_id = %s
                    """, (doc[0],))
                    deleted_count += 1
                
                conn.commit()
                print(f"✅ Removed vector data for {deleted_count} document(s)")
            else:
                print("Cancelled")
        
        finally:
            cursor.close()
            conn.close()
        
        input("\nPress Enter to continue...")
    
    def remove_pdf_by_user(self):
        """Remove PDF data by user"""
        print("\n--- Remove PDF by User ---")
        user_id = input("User ID: ").strip()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM document_chunks WHERE user_id = %s
            """, (user_id,))
            
            count = cursor.fetchone()[0]
            
            if count == 0:
                print("No vector data found for this user")
                input("\nPress Enter to continue...")
                return
            
            confirm = input(f"Remove {count} vector chunks for user {user_id}? (y/n): ").strip().lower()
            
            if confirm == 'y':
                cursor.execute("""
                    DELETE FROM document_chunks WHERE user_id = %s
                """, (user_id,))
                conn.commit()
                print(f"✅ Removed {count} vector chunks")
            else:
                print("Cancelled")
        
        finally:
            cursor.close()
            conn.close()
        
        input("\nPress Enter to continue...")
    
    def list_pdf_data(self):
        """List PDF data in vector store"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT COUNT(*) as total_chunks,
                       COUNT(DISTINCT document_id) as unique_documents,
                       COUNT(DISTINCT user_id) as unique_users
                FROM document_chunks
            """)
            
            stats = cursor.fetchone()
            
            print("\n--- Vector Database Statistics ---")
            print(f"Total chunks: {stats[0]}")
            print(f"Unique documents: {stats[1]}")
            print(f"Unique users: {stats[2]}")
            
            cursor.execute("""
                SELECT u.username, COUNT(dc.chunk_id) as chunk_count
                FROM document_chunks dc
                JOIN users u ON dc.user_id = u.user_id
                GROUP BY u.username
                ORDER BY chunk_count DESC
                LIMIT 10
            """)
            
            print("\nTop 10 users by chunk count:")
            print("-"*40)
            for row in cursor.fetchall():
                print(f"{row[0]:<20} {row[1]} chunks")
        
        finally:
            cursor.close()
            conn.close()
        
        input("\nPress Enter to continue...")
    
    def clear_all_memory(self):
        """Clear all memory"""
        print("\n--- Clear All Memory ---")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT COUNT(*) FROM document_chunks")
            count = cursor.fetchone()[0]
            
            if count == 0:
                print("No vector data to clear")
                input("\nPress Enter to continue...")
                return
            
            confirm = input(f"WARNING: This will delete ALL {count} vector embeddings! Continue? (y/n): ").strip().lower()
            
            if confirm == 'y':
                cursor.execute("TRUNCATE TABLE document_chunks RESTART IDENTITY CASCADE")
                conn.commit()
                print("✅ All vector data cleared")
            else:
                print("Cancelled")
        
        finally:
            cursor.close()
            conn.close()
        
        input("\nPress Enter to continue...")
    
    def clear_user_memory(self):
        """Clear user memory"""
        print("\n--- Clear User Memory ---")
        user_id = input("User ID: ").strip()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM document_chunks WHERE user_id = %s
            """, (user_id,))
            
            count = cursor.fetchone()[0]
            
            if count == 0:
                print("No vector data found for this user")
                input("\nPress Enter to continue...")
                return
            
            confirm = input(f"Clear {count} vector chunks for user {user_id}? (y/n): ").strip().lower()
            
            if confirm == 'y':
                cursor.execute("""
                    DELETE FROM document_chunks WHERE user_id = %s
                """, (user_id,))
                conn.commit()
                print(f"✅ Cleared {count} vector chunks")
            else:
                print("Cancelled")
        
        finally:
            cursor.close()
            conn.close()
        
        input("\nPress Enter to continue...")
    
    def system_status(self):
        """Display system status"""
        print("\n--- System Status ---")
        
        # Check backend health
        health_response = self.api_call("/health")
        if health_response:
            print("✅ Backend: Healthy")
            print(f"   Database: {health_response.get('database', 'unknown')}")
            budget = health_response.get('budget', {})
            if budget:
                print(f"   Budget used: ${budget.get('used_budget', 0):.4f}")
                print(f"   Budget remaining: ${budget.get('remaining_budget', 0):.4f}")
        else:
            print("❌ Backend: Unreachable")
        
        # Check database statistics
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT COUNT(*) FROM users")
            user_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM documents")
            doc_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM document_chunks")
            chunk_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM chat_history")
            chat_count = cursor.fetchone()[0]
            
            print(f"\n📊 Database Statistics:")
            print(f"   Users: {user_count}")
            print(f"   Documents: {doc_count}")
            print(f"   Vector chunks: {chunk_count}")
            print(f"   Chat messages: {chat_count}")
            
            # Show users by document limit
            cursor.execute("""
                SELECT 
                    CASE 
                        WHEN max_documents = -1 THEN 'Unlimited (Admins)'
                        WHEN max_documents = 0 THEN 'Unlimited'
                        ELSE 'Limited'
                    END as limit_type,
                    COUNT(*) as user_count
                FROM users 
                GROUP BY limit_type
            """)
            print(f"\n👥 Users by Document Limit:")
            for limit_type, count in cursor.fetchall():
                print(f"   {limit_type}: {count}")
            
            # Show average chunks per document
            if doc_count > 0:
                avg_chunks = chunk_count / doc_count
                print(f"   Average chunks per document: {avg_chunks:.1f}")
            
            # Show chunk settings
            print(f"\n⚙️  Current Settings:")
            print(f"   Chunk size: 300 characters")
            print(f"   Chunk overlap: 30 characters")
            
        finally:
            cursor.close()
            conn.close()
        
        input("\nPress Enter to continue...")
    
    def display_user_main_menu(self):
        """User main menu"""
        while True:
            self.clear_screen()
            self.print_header(f"USER MENU - {self.current_username}")
            print("1. Upload PDFs")
            print("2. Upload all PDFs from folder")
            print("3. List my PDFs")
            print("4. Ingest a PDF")
            print("5. Ingest all my PDFs")
            print("6. List my ingested PDFs")
            print("7. Delete a PDF from storage")
            print("8. Delete all my PDFs from storage")
            print("9. Remove a PDF from vectordb")
            print("10. Remove all my PDFs from vectordb")
            print("11. Chat with documents")
            print("12. View my chat history")
            print("13. Check my PDF count")
            print("0. Logout")
            print("="*60)
            
            choice = input("\nSelect option: ").strip()
            
            if choice == "1":
                self.user_upload_pdfs()
            elif choice == "2":
                self.user_upload_folder()
            elif choice == "3":
                self.user_list_my_pdfs()
            elif choice == "4":
                self.user_ingest_pdf()
            elif choice == "5":
                self.user_ingest_all_pdfs()
            elif choice == "6":
                self.user_list_ingested_pdfs()
            elif choice == "7":
                self.user_delete_pdf()
            elif choice == "8":
                self.user_delete_all_pdfs()
            elif choice == "9":
                self.user_remove_pdf_vectordb()
            elif choice == "10":
                self.user_remove_all_pdfs_vectordb()
            elif choice == "11":
                self.user_chat()
            elif choice == "12":
                self.user_view_chat_history()
            elif choice == "13":
                self.user_check_pdf_count()
            elif choice == "0":
                self.logout()
                return
            else:
                input("\n❌ Invalid option. Press Enter to continue...")
    
    def user_upload_pdfs(self):
        """User upload PDFs - ALWAYS PRIVATE for regular users"""
        print("\n--- Upload PDFs ---")
        
        # Check PDF count first with proper limit
        count_response = self.api_call(f"/pdf/user/{self.current_user_id}/count")
        if count_response:
            can_upload_more = count_response.get("can_upload_more", True)
            pdf_count = count_response.get("pdf_count", 0)
            max_allowed = count_response.get("max_allowed", 5)
            user_max_docs = count_response.get("user_max_documents", 5)
            
            if not can_upload_more and max_allowed != "unlimited":
                print(f"❌ You already have {pdf_count} PDFs (max: {max_allowed})")
                print("Please delete some PDFs before uploading new ones.")
                input("\nPress Enter to continue...")
                return
        
        file_path = input("PDF file path: ").strip()
        
        if not os.path.exists(file_path):
            print("❌ File not found!")
            input("Press Enter to continue...")
            return
        
        # Check PDF count again before upload
        count_response = self.api_call(f"/pdf/user/{self.current_user_id}/count")
        if count_response:
            can_upload_more = count_response.get("can_upload_more", True)
            max_allowed = count_response.get("max_allowed", 5)
            
            if not can_upload_more and max_allowed != "unlimited":
                print(f"❌ You reached your limit of {max_allowed} PDFs!")
                input("Press Enter to continue...")
                return
        
        print(f"\nUploading {file_path}...")
        print("Note: Your documents are always private (only you can access them)")
        
        with open(file_path, 'rb') as f:
            files = {"file": (os.path.basename(file_path), f, "application/pdf")}
            data = {
                "is_public": "false",  # Always false for regular users
                "admin_upload": "false"  # Not an admin upload
            }
            
            response = self.api_call(
                f"/pdf/upload/{self.current_user_id}",
                method="POST",
                files=files,
                data=data
            )
            
            if response:
                print("✅ Upload successful!")
                print(f"Document ID: {response.get('document_id')}")
                print(f"Chunks created: {response.get('chunks_created')}")
                print(f"Chunk size: {response.get('chunk_settings', {}).get('chunk_size', 300)}")
                print(f"Chunk overlap: {response.get('chunk_settings', {}).get('chunk_overlap', 30)}")
                
                # Get updated count
                count_response = self.api_call(f"/pdf/user/{self.current_user_id}/count")
                if count_response:
                    new_count = count_response.get("pdf_count", 0)
                    max_allowed = count_response.get("max_allowed", 5)
                    print(f"You now have {new_count} PDFs (limit: {max_allowed})")
                
                print("🔒 Document is PRIVATE (only you can access)")
            else:
                print("❌ Upload failed!")
        
        input("\nPress Enter to continue...")
    
    def user_upload_folder(self):
        """User upload folder - ALWAYS PRIVATE for regular users"""
        print("\n--- Upload Folder ---")
        folder_path = input("Folder path: ").strip()
        
        if not os.path.isdir(folder_path):
            print("❌ Folder not found!")
            input("Press Enter to continue...")
            return
        
        # Check PDF count first
        count_response = self.api_call(f"/pdf/user/{self.current_user_id}/count")
        if count_response:
            can_upload_more = count_response.get("can_upload_more", True)
            pdf_count = count_response.get("pdf_count", 0)
            max_allowed = count_response.get("max_allowed", 5)
            
            if not can_upload_more and max_allowed != "unlimited":
                print(f"❌ You already have {pdf_count} PDFs (max: {max_allowed})")
                input("Press Enter to continue...")
                return
        
        pdf_files = glob.glob(os.path.join(folder_path, "*.pdf"))
        
        if not pdf_files:
            print("❌ No PDF files found in folder!")
            input("Press Enter to continue...")
            return
        
        print(f"\nFound {len(pdf_files)} PDF files")
        print("Note: All documents will be private (only you can access them)")
        print(f"Current chunk size: 300, overlap: 30")
        
        uploaded_count = 0
        for pdf_file in pdf_files:
            # Check if user can upload more
            count_response = self.api_call(f"/pdf/user/{self.current_user_id}/count")
            if count_response:
                can_upload_more = count_response.get("can_upload_more", True)
                max_allowed = count_response.get("max_allowed", 5)
                
                if not can_upload_more and max_allowed != "unlimited":
                    print(f"\n⚠️  You reached your limit of {max_allowed} PDFs. Stopping upload.")
                    break
            
            print(f"\nUploading: {os.path.basename(pdf_file)}")
            
            with open(pdf_file, 'rb') as f:
                files = {"file": (os.path.basename(pdf_file), f, "application/pdf")}
                data = {
                    "is_public": "false",  # Always false for regular users
                    "admin_upload": "false"  # Not an admin upload
                }
                
                response = self.api_call(
                    f"/pdf/upload/{self.current_user_id}",
                    method="POST",
                    files=files,
                    data=data
                )
                
                if response:
                    print(f"  ✅ Success! (Chunks: {response.get('chunks_created')}, PRIVATE)")
                    uploaded_count += 1
                else:
                    print(f"  ❌ Failed!")
        
        print(f"\n✅ Uploaded {uploaded_count} out of {len(pdf_files)} PDFs")
        
        # Show final count
        count_response = self.api_call(f"/pdf/user/{self.current_user_id}/count")
        if count_response:
            new_count = count_response.get("pdf_count", 0)
            max_allowed = count_response.get("max_allowed", 5)
            print(f"You now have {new_count} PDFs (limit: {max_allowed})")
        
        input("\nPress Enter to continue...")
    
    def user_list_my_pdfs(self):
        """User list their PDFs"""
        response = self.api_call(f"/pdf/user/{self.current_user_id}/documents")
        
        if response:
            documents = response.get("documents", [])
            total = response.get("total_documents", 0)
            max_allowed = response.get("max_allowed", 5)
            user_max_docs = response.get("user_max_documents", 5)
            is_admin = response.get("is_admin", False)
            
            print(f"\nMy Documents ({total}/{max_allowed}):")
            print(f"Document limit: {user_max_docs}")
            print(f"Account type: {'Admin' if is_admin else 'User'}")
            print("-"*80)
            
            if not documents:
                print("No documents found.")
            else:
                for doc in documents:
                    visibility = "PUBLIC" if doc['is_public'] else "PRIVATE"
                    visibility_icon = "📢" if doc['is_public'] else "🔒"
                    print(f"\n{visibility_icon} {doc['filename']}")
                    print(f"   ID: {doc['document_id']}")
                    print(f"   Uploaded: {doc['uploaded_at'][:19]}")
                    print(f"   Visibility: {visibility}")
                    print(f"   Chunks: {doc.get('chunk_count', 0)}")
                    print(f"   Blob URL: {doc['blob_url'][:50]}...")
        
        input("\nPress Enter to continue...")
    
    def user_ingest_pdf(self):
        """User ingest PDF"""
        print("\n--- Ingest PDF ---")
        document_id = input("Document ID: ").strip()
        
        # Note: PDFs are automatically ingested on upload
        print("⚠️  PDFs are automatically ingested on upload")
        print("Current chunk settings:")
        print("  - Chunk size: 300 characters")
        print("  - Chunk overlap: 30 characters")
        print("This feature would re-process the PDF if needed")
        
        input("\nPress Enter to continue...")
    
    def user_ingest_all_pdfs(self):
        """User ingest all PDFs"""
        print("\n--- Ingest All My PDFs ---")
        
        # Note: PDFs are automatically ingested on upload
        print("⚠️  PDFs are automatically ingested on upload")
        print("Current chunk settings:")
        print("  - Chunk size: 300 characters")
        print("  - Chunk overlap: 30 characters")
        print("This feature would re-process all your PDFs")
        
        input("\nPress Enter to continue...")
    
    def user_list_ingested_pdfs(self):
        """User list ingested PDFs"""
        # Same as list my PDFs
        self.user_list_my_pdfs()
    
    def user_delete_pdf(self):
        """User delete PDF"""
        print("\n--- Delete PDF ---")
        document_id = input("Document ID: ").strip()
        
        # First check if document belongs to user
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT filename FROM documents 
                WHERE document_id = %s AND user_id = %s
            """, (document_id, self.current_user_id))
            
            result = cursor.fetchone()
            
            if not result:
                print("❌ Document not found or you don't have permission to delete it")
                input("\nPress Enter to continue...")
                return
            
            filename = result[0]
            
            confirm = input(f"Delete document '{filename}'? (y/n): ").strip().lower()
            
            if confirm == 'y':
                response = self.api_call(f"/pdf/delete/{document_id}", method="DELETE")
                if response:
                    print("✅ Document deleted successfully!")
                else:
                    print("❌ Failed to delete document")
        
        finally:
            cursor.close()
            conn.close()
        
        input("\nPress Enter to continue...")
    
    def user_delete_all_pdfs(self):
        """User delete all PDFs"""
        print("\n--- Delete All My PDFs ---")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT document_id, filename FROM documents 
                WHERE user_id = %s
            """, (self.current_user_id,))
            
            docs = cursor.fetchall()
            
            if not docs:
                print("No documents found.")
                input("\nPress Enter to continue...")
                return
            
            print(f"Found {len(docs)} documents:")
            for doc_id, filename in docs:
                print(f"  - {filename}")
            
            confirm = input(f"\nDelete ALL {len(docs)} documents? (y/n): ").strip().lower()
            
            if confirm == 'y':
                deleted_count = 0
                for doc_id, filename in docs:
                    response = self.api_call(f"/pdf/delete/{doc_id}", method="DELETE")
                    if response:
                        deleted_count += 1
                        print(f"Deleted: {filename}")
                
                print(f"\n✅ Deleted {deleted_count} out of {len(docs)} documents")
            else:
                print("Cancelled")
        
        finally:
            cursor.close()
            conn.close()
        
        input("\nPress Enter to continue...")
    
    def user_remove_pdf_vectordb(self):
        """User remove PDF from vector DB"""
        print("\n--- Remove PDF from VectorDB ---")
        document_id = input("Document ID: ").strip()
        
        # First check if document belongs to user
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT filename FROM documents 
                WHERE document_id = %s AND user_id = %s
            """, (document_id, self.current_user_id))
            
            result = cursor.fetchone()
            
            if not result:
                print("❌ Document not found or you don't have permission")
                input("\nPress Enter to continue...")
                return
            
            filename = result[0]
            
            # Count vector chunks for this document
            cursor.execute("""
                SELECT COUNT(*) FROM document_chunks 
                WHERE document_id = %s AND user_id = %s
            """, (document_id, self.current_user_id))
            
            chunk_count = cursor.fetchone()[0]
            
            if chunk_count == 0:
                print("No vector data found for this document")
                input("\nPress Enter to continue...")
                return
            
            confirm = input(f"Remove {chunk_count} vector chunks for '{filename}'? (y/n): ").strip().lower()
            
            if confirm == 'y':
                cursor.execute("""
                    DELETE FROM document_chunks 
                    WHERE document_id = %s AND user_id = %s
                """, (document_id, self.current_user_id))
                conn.commit()
                print(f"✅ Removed {chunk_count} vector chunks")
            else:
                print("Cancelled")
        
        finally:
            cursor.close()
            conn.close()
        
        input("\nPress Enter to continue...")
    
    def user_remove_all_pdfs_vectordb(self):
        """User remove all PDFs from vector DB"""
        print("\n--- Remove All My PDFs from VectorDB ---")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM document_chunks 
                WHERE user_id = %s
            """, (self.current_user_id,))
            
            chunk_count = cursor.fetchone()[0]
            
            if chunk_count == 0:
                print("No vector data found")
                input("\nPress Enter to continue...")
                return
            
            confirm = input(f"Remove ALL {chunk_count} vector chunks? (y/n): ").strip().lower()
            
            if confirm == 'y':
                cursor.execute("""
                    DELETE FROM document_chunks WHERE user_id = %s
                """, (self.current_user_id,))
                conn.commit()
                print(f"✅ Removed {chunk_count} vector chunks")
            else:
                print("Cancelled")
        
        finally:
            cursor.close()
            conn.close()
        
        input("\nPress Enter to continue...")
    
    def user_chat(self):
        """User chat interface"""
        print("\n" + "="*60)
        print("CHAT WITH YOUR DOCUMENTS")
        print("Type 'quit' to exit, 'public on/off' to toggle public docs")
        print("="*60)
        
        use_public = True
        
        while True:
            question = input("\nYou: ").strip()
            
            if question.lower() == 'quit':
                break
            elif question.lower() == 'public on':
                use_public = True
                print("✅ Using public documents (admin-uploaded only)")
                continue
            elif question.lower() == 'public off':
                use_public = False
                print("✅ Using only your documents")
                continue
            
            if not question:
                continue
            
            print("Thinking...")
            
            data = {
                "user_id": self.current_user_id,
                "question": question,
                "use_public_data": use_public
            }
            
            response = self.api_call("/chat/ask", method="POST", data=data)
            
            if response:
                answer = response.get("answer", "No response")
                print(f"\n🤖 Assistant: {answer}")
                print(f"   (Used {response.get('chunks_used', 0)} document chunks)")
                budget = response.get("budget_status", {})
                if budget:
                    print(f"   Budget used: ${budget.get('used_budget', 0):.4f}")
            else:
                print("❌ Failed to get response.")
    
    def user_view_chat_history(self):
        """User view their chat history"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT chat_id, user_message, ai_response, created_at
                FROM chat_history 
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 20
            """, (self.current_user_id,))
            
            chats = cursor.fetchall()
            
            if not chats:
                print("\nNo chat history found")
            else:
                print(f"\nYour Recent Chats ({len(chats)}):")
                print("-"*80)
                
                for chat in chats:
                    chat_id, user_msg, ai_resp, created_at = chat
                    print(f"\n[{created_at.strftime('%Y-%m-%d %H:%M:%S')}]")
                    print(f"You: {user_msg[:80]}{'...' if len(user_msg) > 80 else ''}")
                    print(f"AI: {ai_resp[:80]}{'...' if len(ai_resp) > 80 else ''}")
        
        finally:
            cursor.close()
            conn.close()
        
        input("\nPress Enter to continue...")
    
    def user_check_pdf_count(self):
        """User check their PDF count"""
        response = self.api_call(f"/pdf/user/{self.current_user_id}/count")
        
        if response:
            count = response.get("pdf_count", 0)
            max_allowed = response.get("max_allowed", 5)
            can_upload_more = response.get("can_upload_more", True)
            user_max_docs = response.get("user_max_documents", 5)
            is_admin = response.get("is_admin", False)
            
            print(f"\n📊 Your PDF Statistics:")
            print(f"   Current PDFs: {count}")
            print(f"   Maximum allowed: {max_allowed}")
            print(f"   Your document limit: {user_max_docs}")
            print(f"   Can upload more: {'Yes' if can_upload_more else 'No'}")
            print(f"   Account type: {'Admin' if is_admin else 'User'}")
            
            if max_allowed != "unlimited" and count >= int(max_allowed):
                print("\n⚠️  You've reached your document limit!")
                print("   Delete some PDFs before uploading new ones.")
        else:
            print("❌ Failed to get PDF count")
        
        input("\nPress Enter to continue...")
    
    def logout(self):
        """Logout current user"""
        self.current_user_id = None
        self.current_username = None
        self.is_admin = False
        self.token = None
        self.admin_token = None
        print("\n✅ Logged out successfully!")
    
    def run(self):
        """Main CLI entry point"""
        while True:
            self.clear_screen()
            self.print_header("AZURE RAG CHATBOT - CLI INTERFACE")
            
            print("1. Login (User)")
            print("2. Complete Registration (New Users)")
            print("3. Admin Login")
            print("4. Exit")
            print("="*60)
            
            choice = input("\nSelect: ").strip()
            
            if choice == "1":
                if self.login():
                    if self.is_admin:
                        self.display_admin_main_menu()
                    else:
                        self.display_user_main_menu()
                else:
                    input("\nPress Enter to continue...")
            elif choice == "2":
                self.complete_registration()
            elif choice == "3":
                if self.admin_login():
                    self.display_admin_main_menu()
            elif choice == "4":
                print("\nGoodbye!")
                sys.exit(0)
            else:
                print("\n❌ Invalid choice!")
                input("Press Enter to continue...")

if __name__ == "__main__":
    cli = CLIInterface()
    cli.run()