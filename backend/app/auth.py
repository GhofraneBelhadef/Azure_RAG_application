# auth.py - Fixed timezone-aware datetime comparisons with JWT Authentication
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import bcrypt
import psycopg2
from database import get_db_connection
import uuid
from datetime import datetime, timedelta, timezone
import json
from email_validator import validate_email, EmailNotValidError

# Import security module
from security import (
    create_tokens, 
    verify_password, 
    hash_password, 
    get_current_user,
    get_current_active_user,
    require_admin,
    refresh_access_token,
    TokenData
)

router = APIRouter(prefix="/auth", tags=["authentication"])

# Pydantic models for request data
class AdminCreateUser(BaseModel):
    username: str
    email: str
    temporary_password: str
    password_expires: bool = False
    is_admin: bool = False
    max_documents: int = 5

class UserCompleteRegistration(BaseModel):
    username: str
    registration_password: str
    new_password: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserChangePassword(BaseModel):
    current_password: str
    new_password: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str

# Helper function to get current UTC time
def get_current_utc_time():
    return datetime.now(timezone.utc)

# Public endpoint - Admin creates a user registration
@router.post("/admin/create-user")
def admin_create_user(user_data: AdminCreateUser, current_user: TokenData = Depends(require_admin)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 1. Validate email format
        try:
            valid = validate_email(user_data.email)
            email = valid.email
        except EmailNotValidError as e:
            raise HTTPException(status_code=400, detail=f"Invalid email: {str(e)}")
        
        # 2. Check if username already exists
        cursor.execute("SELECT user_id FROM users WHERE username = %s", (user_data.username,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Username already exists")
        
        # 3. Check if email already exists
        cursor.execute("SELECT user_id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # 4. Hash the temporary password
        temp_password_hash = hash_password(user_data.temporary_password)
        
        # 5. Calculate expiration time
        registration_expires_at = None
        if user_data.password_expires:
            registration_expires_at = get_current_utc_time() + timedelta(days=1)
        
        user_id = str(uuid.uuid4())
        registration_created_at = get_current_utc_time()
        
        # For admin users, set max_documents to -1 (unlimited)
        if user_data.is_admin:
            user_data.max_documents = -1
        
        # 6. Insert the new user
        cursor.execute("""
            INSERT INTO users (
                user_id, username, email, 
                registration_password_hash, registration_expires_at,
                registration_created_at, registration_used, is_admin, max_documents
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id, user_data.username, email,
            temp_password_hash, registration_expires_at,
            registration_created_at, False, user_data.is_admin, user_data.max_documents
        ))
        
        # 7. Log the activity
        details = json.dumps({
            "username": user_data.username,
            "email": email,
            "is_admin": user_data.is_admin,
            "expires": user_data.password_expires,
            "expires_at": registration_expires_at.isoformat() if registration_expires_at else None,
            "max_documents": user_data.max_documents
        })
        
        cursor.execute("""
            INSERT INTO activity_log (user_id, activity_type, details)
            VALUES (%s, %s, %s)
        """, (user_id, 'ADMIN_CREATE_USER', details))
        
        conn.commit()
        
        return {
            "message": "User registration created successfully",
            "user_id": user_id,
            "username": user_data.username,
            "email": email,
            "is_admin": user_data.is_admin,
            "max_documents": user_data.max_documents,
            "expires": registration_expires_at.isoformat() if registration_expires_at else "Never",
            "expires_in": "1 day" if registration_expires_at else "Never",
            "instructions": "Give this temporary password to the user to complete registration"
        }
        
    except psycopg2.Error as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
    finally:
        cursor.close()
        conn.close()

# Public endpoint - User completes registration
@router.post("/complete-registration")
def complete_registration(user_data: UserCompleteRegistration):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 1. Find user by username
        cursor.execute("""
            SELECT user_id, registration_password_hash, registration_expires_at, 
                   registration_used, email
            FROM users WHERE username = %s
        """, (user_data.username,))
        
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or registration password")
        
        user_id, reg_password_hash, reg_expires_at, reg_used, email = user
        
        # 2. Check if user already completed registration
        if reg_used:
            raise HTTPException(status_code=400, detail="Registration already completed")
        
        # 3. Check if registration is expired
        current_time = get_current_utc_time()
        if reg_expires_at and current_time > reg_expires_at:
            details = json.dumps({"reason": "registration_expired"})
            cursor.execute("""
                INSERT INTO activity_log (user_id, activity_type, details)
                VALUES (%s, %s, %s)
            """, (user_id, 'REGISTRATION_EXPIRED', details))
            conn.commit()
            raise HTTPException(status_code=400, detail="Registration has expired. Please contact admin for a new temporary password.")
        
        # 4. Verify the temporary password
        if not verify_password(user_data.registration_password, reg_password_hash):
            details = json.dumps({"reason": "wrong_temporary_password"})
            cursor.execute("""
                INSERT INTO activity_log (user_id, activity_type, details)
                VALUES (%s, %s, %s)
            """, (user_id, 'REGISTRATION_FAILED', details))
            conn.commit()
            raise HTTPException(status_code=401, detail="Invalid username or registration password")
        
        # 5. Hash the new password
        new_password_hash = hash_password(user_data.new_password)
        
        # 6. Update user with new password
        cursor.execute("""
            UPDATE users 
            SET password_hash = %s, 
                registration_used = true,
                created_at = %s
            WHERE user_id = %s
        """, (new_password_hash, current_time, user_id))
        
        # 7. Log successful registration
        details = json.dumps({"email": email})
        cursor.execute("""
            INSERT INTO activity_log (user_id, activity_type, details)
            VALUES (%s, %s, %s)
        """, (user_id, 'REGISTRATION_COMPLETED', details))
        
        conn.commit()
        
        return {
            "message": "Registration completed successfully",
            "user_id": user_id,
            "username": user_data.username,
            "email": email,
            "instructions": "You can now login with your new password"
        }
        
    except psycopg2.Error as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
    finally:
        cursor.close()
        conn.close()

# Public endpoint - User login with JWT tokens
@router.post("/login")
def login(user_data: UserLogin):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 1. Fetch user by username including registration status
        cursor.execute("""
            SELECT user_id, password_hash, is_admin, registration_used, email
            FROM users WHERE username = %s
        """, (user_data.username,))
        
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        
        user_id, stored_hash, is_admin, reg_used, email = user
        
        # 2. Check if user has completed registration
        if not reg_used:
            cursor.execute("""
                SELECT registration_expires_at FROM users WHERE user_id = %s
            """, (user_id,))
            expires_at = cursor.fetchone()[0]
            
            current_time = get_current_utc_time()
            if expires_at and current_time > expires_at:
                raise HTTPException(
                    status_code=403, 
                    detail="Your registration has expired. Please contact admin for a new temporary password."
                )
            else:
                raise HTTPException(
                    status_code=403, 
                    detail="Please complete your registration first with the temporary password"
                )
        
        # 3. Verify the provided password
        if not verify_password(user_data.password, stored_hash):
            details = json.dumps({"reason": "wrong_password"})
            cursor.execute("""
                INSERT INTO activity_log (user_id, activity_type, details)
                VALUES (%s, %s, %s)
            """, (user_id, 'LOGIN_FAILED', details))
            conn.commit()
            raise HTTPException(status_code=401, detail="Invalid username or password")
        
        # 4. Create JWT tokens
        tokens = create_tokens(user_id, user_data.username, is_admin)
        
        # 5. Log successful login
        details = json.dumps({"is_admin": is_admin, "email": email})
        cursor.execute("""
            INSERT INTO activity_log (user_id, activity_type, details)
            VALUES (%s, %s, %s)
        """, (user_id, 'LOGIN', details))
        
        conn.commit()
        
        # Return tokens and user info
        return {
            "message": "Login successful", 
            "user_id": user_id, 
            "username": user_data.username,
            "email": email,
            "is_admin": is_admin,
            **tokens
        }
        
    except psycopg2.Error as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
    finally:
        cursor.close()
        conn.close()

# Public endpoint - Refresh access token
@router.post("/refresh")
def refresh_token(request: RefreshTokenRequest):
    """Refresh access token using refresh token"""
    try:
        tokens = refresh_access_token(request.refresh_token)
        return tokens
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token refresh error: {str(e)}")

# Protected endpoint - Get current user info
@router.get("/me")
def get_current_user_info(current_user: TokenData = Depends(get_current_active_user)):
    """Get information about the currently authenticated user"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT username, email, is_admin, max_documents, created_at
            FROM users WHERE user_id = %s
        """, (current_user.user_id,))
        
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        username, email, is_admin, max_documents, created_at = user
        
        return {
            "user_id": current_user.user_id,
            "username": username,
            "email": email,
            "is_admin": is_admin,
            "max_documents": max_documents,
            "created_at": created_at.isoformat() if created_at else None
        }
        
    finally:
        cursor.close()
        conn.close()

# Protected endpoint - Change password
@router.post("/change-password")
def change_password(
    user_data: UserChangePassword,
    current_user: TokenData = Depends(get_current_active_user)
):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 1. Get current password hash
        cursor.execute("""
            SELECT password_hash FROM users WHERE user_id = %s
        """, (current_user.user_id,))
        
        result = cursor.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="User not found")
        
        current_hash = result[0]
        
        # 2. Verify current password
        if not verify_password(user_data.current_password, current_hash):
            raise HTTPException(status_code=401, detail="Current password is incorrect")
        
        # 3. Hash new password
        new_password_hash = hash_password(user_data.new_password)
        
        # 4. Update password
        cursor.execute("""
            UPDATE users 
            SET password_hash = %s
            WHERE user_id = %s
        """, (new_password_hash, current_user.user_id))
        
        # 5. Log password change
        details = json.dumps({"action": "password_change"})
        cursor.execute("""
            INSERT INTO activity_log (user_id, activity_type, details)
            VALUES (%s, %s, %s)
        """, (current_user.user_id, 'PASSWORD_CHANGE', details))
        
        conn.commit()
        
        return {"message": "Password changed successfully"}
        
    except psycopg2.Error as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
    finally:
        cursor.close()
        conn.close()

# Public endpoint - Check registration status
@router.get("/check-registration/{username}")
def check_registration(username: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT user_id, username, email, registration_used, 
                   registration_expires_at, registration_created_at, 
                   is_admin, max_documents
            FROM users WHERE username = %s
        """, (username,))
        
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        (user_id, username, email, reg_used, reg_expires_at, 
         reg_created_at, is_admin, max_documents) = user
        
        current_time = get_current_utc_time()
        is_expired = False
        expires_in = None
        if reg_expires_at:
            is_expired = current_time > reg_expires_at
            if not is_expired:
                time_diff = reg_expires_at - current_time
                hours = time_diff.seconds // 3600
                minutes = (time_diff.seconds % 3600) // 60
                expires_in = f"{hours}h {minutes}m"
        
        return {
            "user_id": user_id,
            "username": username,
            "email": email,
            "registration_completed": reg_used,
            "registration_created": reg_created_at.isoformat() if reg_created_at else None,
            "registration_expires": reg_expires_at.isoformat() if reg_expires_at else None,
            "registration_expired": is_expired,
            "expires_in": expires_in,
            "is_admin": is_admin,
            "max_documents": max_documents,
            "status": "completed" if reg_used else "expired" if is_expired else "pending"
        }
        
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
    finally:
        cursor.close()
        conn.close()

# Admin-only endpoint - Renew password
@router.post("/admin/renew-password/{user_id}")
def admin_renew_password(
    user_id: str, 
    temporary_password: str, 
    password_expires: bool = False,
    current_user: TokenData = Depends(require_admin)
):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT username, email FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        username, email = user
        
        temp_password_hash = hash_password(temporary_password)
        
        registration_expires_at = None
        if password_expires:
            registration_expires_at = get_current_utc_time() + timedelta(days=1)
        
        current_time = get_current_utc_time()
        
        cursor.execute("""
            UPDATE users 
            SET registration_password_hash = %s,
                registration_expires_at = %s,
                registration_created_at = %s,
                registration_used = false,
                password_hash = NULL
            WHERE user_id = %s
        """, (temp_password_hash, registration_expires_at, current_time, user_id))
        
        details = json.dumps({
            "username": username,
            "email": email,
            "expires": password_expires,
            "expires_at": registration_expires_at.isoformat() if registration_expires_at else None
        })
        
        cursor.execute("""
            INSERT INTO activity_log (user_id, activity_type, details)
            VALUES (%s, %s, %s)
        """, (user_id, 'ADMIN_RENEW_PASSWORD', details))
        
        conn.commit()
        
        return {
            "message": "Temporary password renewed successfully",
            "user_id": user_id,
            "username": username,
            "email": email,
            "expires": registration_expires_at.isoformat() if registration_expires_at else "Never",
            "expires_in": "1 day" if registration_expires_at else "Never",
            "instructions": "Give this new temporary password to the user"
        }
        
    except psycopg2.Error as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
    finally:
        cursor.close()
        conn.close()

# Admin-only endpoint - List pending registrations
@router.get("/admin/pending-registrations")
def list_pending_registrations(current_user: TokenData = Depends(require_admin)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT user_id, username, email, registration_created_at, 
                   registration_expires_at, is_admin, max_documents
            FROM users 
            WHERE registration_used = false 
            ORDER BY registration_created_at DESC
        """)
        
        pending_users = cursor.fetchall()
        
        result = []
        current_time = get_current_utc_time()
        
        for user in pending_users:
            user_id, username, email, reg_created, reg_expires, is_admin, max_documents = user
            
            is_expired = False
            expires_in = None
            if reg_expires:
                is_expired = current_time > reg_expires
                if not is_expired:
                    time_diff = reg_expires - current_time
                    hours = time_diff.seconds // 3600
                    minutes = (time_diff.seconds % 3600) // 60
                    expires_in = f"{hours}h {minutes}m"
            
            result.append({
                "user_id": user_id,
                "username": username,
                "email": email,
                "registration_created": reg_created.isoformat() if reg_created else None,
                "registration_expires": reg_expires.isoformat() if reg_expires else None,
                "registration_expired": is_expired,
                "expires_in": expires_in,
                "is_admin": is_admin,
                "max_documents": max_documents,
                "status": "expired" if is_expired else "pending"
            })
        
        return {"pending_registrations": result, "count": len(result)}
        
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
    finally:
        cursor.close()
        conn.close()

# Admin-only endpoint - List all users
@router.get("/admin/users")
def list_all_users(current_user: TokenData = Depends(require_admin)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                user_id, username, email, is_admin, 
                registration_used, registration_created_at, 
                registration_expires_at, created_at, max_documents,
                (SELECT COUNT(*) FROM documents WHERE user_id = users.user_id) as document_count
            FROM users 
            ORDER BY created_at DESC
        """)
        
        users = cursor.fetchall()
        
        result = []
        current_time = get_current_utc_time()
        
        for user in users:
            (user_id, username, email, is_admin, reg_used, reg_created, 
             reg_expires, created_at, max_documents, doc_count) = user
            
            status = "active"
            if not reg_used:
                if reg_expires and current_time > reg_expires:
                    status = "expired"
                else:
                    status = "pending"
            
            result.append({
                "user_id": user_id,
                "username": username,
                "email": email,
                "is_admin": is_admin,
                "registration_status": status,
                "registration_completed": reg_used,
                "registration_created": reg_created.isoformat() if reg_created else None,
                "registration_expires": reg_expires.isoformat() if reg_expires else None,
                "created_at": created_at.isoformat() if created_at else None,
                "max_documents": max_documents,
                "document_count": doc_count
            })
        
        return {"users": result, "total": len(result)}
        
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
    finally:
        cursor.close()
        conn.close()

# Public endpoint - Old registration endpoint (kept for backward compatibility)
@router.post("/register")
def old_register():
    raise HTTPException(
        status_code=410, 
        detail="Self-registration is disabled. Please contact admin for account creation."
    )

# Simple health check - Public
@router.get("/status")
def auth_status():
    return {"status": "auth module is working"}