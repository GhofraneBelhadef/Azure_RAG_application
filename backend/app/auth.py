# auth.py - Fixed timezone-aware datetime comparisons
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import bcrypt
import psycopg2
from database import get_db_connection
import uuid
from datetime import datetime, timedelta, timezone  # Added timezone
import json
from email_validator import validate_email, EmailNotValidError

router = APIRouter(prefix="/auth", tags=["authentication"])

# Pydantic models for request data
class AdminCreateUser(BaseModel):
    username: str
    email: str
    temporary_password: str
    password_expires: bool = False  # False = permanent, True = expires in 1 day
    is_admin: bool = False
    max_documents: int = 5  # Default to 5 documents

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

# Helper function to hash passwords
def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

# Helper function to verify passwords
def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except:
        return False

# Get current UTC time with timezone
def get_current_utc_time():
    return datetime.now(timezone.utc)

# Admin endpoint to create a user registration
@router.post("/admin/create-user")
def admin_create_user(user_data: AdminCreateUser):
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
        
        # 5. Calculate expiration time (using timezone-aware datetime)
        registration_expires_at = None
        if user_data.password_expires:
            registration_expires_at = get_current_utc_time() + timedelta(days=1)
        
        user_id = str(uuid.uuid4())
        registration_created_at = get_current_utc_time()
        
        # For admin users, set max_documents to -1 (unlimited)
        if user_data.is_admin:
            user_data.max_documents = -1
        
        # 6. Insert the new user with temporary registration data
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
            "temporary_password": user_data.temporary_password,
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

# User endpoint to complete registration with temporary password
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
        
        # 3. Check if registration is expired (using timezone-aware comparison)
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
            # Log failed attempt
            details = json.dumps({"reason": "wrong_temporary_password"})
            cursor.execute("""
                INSERT INTO activity_log (user_id, activity_type, details)
                VALUES (%s, %s, %s)
            """, (user_id, 'REGISTRATION_FAILED', details))
            conn.commit()
            raise HTTPException(status_code=401, detail="Invalid username or registration password")
        
        # 5. Hash the new password
        new_password_hash = hash_password(user_data.new_password)
        
        # 6. Update user with new password and mark registration as used
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

# User Login Endpoint
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
            # Check if registration is expired
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
            # Log failed attempt
            details = json.dumps({"reason": "wrong_password"})
            cursor.execute("""
                INSERT INTO activity_log (user_id, activity_type, details)
                VALUES (%s, %s, %s)
            """, (user_id, 'LOGIN_FAILED', details))
            conn.commit()
            raise HTTPException(status_code=401, detail="Invalid username or password")
        
        # 4. Log successful login
        details = json.dumps({"is_admin": is_admin, "email": email})
        cursor.execute("""
            INSERT INTO activity_log (user_id, activity_type, details)
            VALUES (%s, %s, %s)
        """, (user_id, 'LOGIN', details))
        
        conn.commit()
        
        # Return user info including is_admin
        return {
            "message": "Login successful", 
            "user_id": user_id, 
            "username": user_data.username,
            "email": email,
            "is_admin": is_admin
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

# Endpoint to check registration status
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
        
        # Check if registration is expired (using timezone-aware comparison)
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

# Admin endpoint to resend/renew temporary password
@router.post("/admin/renew-password/{user_id}")
def admin_renew_password(user_id: str, temporary_password: str, password_expires: bool = False):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if user exists
        cursor.execute("SELECT username, email FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        username, email = user
        
        # Hash the new temporary password
        temp_password_hash = hash_password(temporary_password)
        
        # Calculate expiration time (using timezone-aware datetime)
        registration_expires_at = None
        if password_expires:
            registration_expires_at = get_current_utc_time() + timedelta(days=1)
        
        current_time = get_current_utc_time()
        
        # Update user with new temporary password
        cursor.execute("""
            UPDATE users 
            SET registration_password_hash = %s,
                registration_expires_at = %s,
                registration_created_at = %s,
                registration_used = false,
                password_hash = NULL
            WHERE user_id = %s
        """, (temp_password_hash, registration_expires_at, current_time, user_id))
        
        # Log the activity
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
            "temporary_password": temporary_password,
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

# Admin endpoint to list pending registrations
@router.get("/admin/pending-registrations")
def list_pending_registrations():
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
            
            # Check if expired (using timezone-aware comparison)
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

# Admin-only endpoint to list all users with registration status
@router.get("/admin/users")
def list_all_users():
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
            
            # Determine registration status (using timezone-aware comparison)
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

# Old registration endpoint (kept for backward compatibility)
@router.post("/register")
def old_register():
    raise HTTPException(
        status_code=410, 
        detail="Self-registration is disabled. Please contact admin for account creation."
    )

# User change password endpoint
@router.post("/change-password")
def change_password(user_data: UserChangePassword):
    # Note: This requires authentication - you'll need to implement proper auth middleware
    # For now, we'll just show the structure
    raise HTTPException(
        status_code=501,
        detail="Password change endpoint requires authentication middleware"
    )

# Simple health check
@router.get("/status")
def auth_status():
    return {"status": "auth module is working"}