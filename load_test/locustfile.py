from locust import HttpUser, task, between, TaskSet, tag
import random
import json
from datetime import datetime

# Sample test data
SAMPLE_QUESTIONS = [
    "What is artificial intelligence?",
    "How does machine learning work?",
    "Explain neural networks in simple terms",
    "What are the benefits of cloud computing?",
    "Describe the RAG architecture",
    "How does vector search work?",
    "What are embeddings in machine learning?",
    "Explain the transformer architecture",
    "What is Azure OpenAI?",
    "How to implement a chatbot?"
]

SAMPLE_USERS = [
    {"user_id": "test_user_1", "username": "test1", "password": "test123"},
    {"user_id": "test_user_2", "username": "test2", "password": "test456"},
    {"user_id": "test_user_3", "username": "test3", "password": "test789"},
    {"user_id": "admin_user", "username": "admin", "password": "admin123"},
]

class AuthenticationTasks(TaskSet):
    
    def on_start(self):
        """Called when a user starts"""
        self.user_data = random.choice(SAMPLE_USERS)
        self.token = None
        
    @task(3)
    def login(self):
        """Test login endpoint"""
        with self.client.post("/auth/login", 
            json={
                "username": self.user_data["username"],
                "password": self.user_data["password"]
            },
            catch_response=True
        ) as response:
            if response.status_code == 200:
                data = response.json()
                self.token = data.get("token")
                response.success()
            else:
                response.failure(f"Login failed: {response.status_code}")
    
    @task(1)
    def register_user(self):
        """Test user registration"""
        username = f"loadtest_{random.randint(1000, 9999)}"
        with self.client.post("/auth/register",
            json={
                "username": username,
                "password": f"Password{random.randint(1000, 9999)}!",
                "email": f"{username}@test.com"
            },
            catch_response=True
        ) as response:
            if response.status_code in [200, 201, 409]:  # 409 = already exists
                response.success()
            else:
                response.failure(f"Registration failed: {response.status_code}")

class DocumentTasks(TaskSet):
    
    @task(5)
    def get_user_documents(self):
        """Test getting user documents"""
        user_id = random.choice(["test_user_1", "test_user_2", "test_user_3"])
        with self.client.get(f"/pdf/user/{user_id}/documents",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Get documents failed: {response.status_code}")
    
    @task(1)
    def get_pdf_count(self):
        """Test PDF count endpoint"""
        user_id = random.choice(["test_user_1", "test_user_2", "test_user_3"])
        with self.client.get(f"/pdf/user/{user_id}/count",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"PDF count failed: {response.status_code}")
    
    @task(1)
    def list_all_documents(self):
        """Test admin document listing"""
        with self.client.get("/pdf/admin/all-documents",
            catch_response=True
        ) as response:
            if response.status_code in [200, 403]:  # 403 = not admin
                response.success()
            else:
                response.failure(f"List all docs failed: {response.status_code}")

class ChatTasks(TaskSet):
    
    @task(10)
    def chat_with_rag(self):
        """Test RAG chat endpoint (main functionality)"""
        user_id = random.choice(["test_user_1", "test_user_2", "test_user_3"])
        question = random.choice(SAMPLE_QUESTIONS)
        
        with self.client.post("/chat/ask",
            json={
                "user_id": user_id,
                "question": question,
                "use_public_data": random.choice([True, False])
            },
            catch_response=True
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if data.get("answer"):
                    response.success()
                else:
                    response.failure("No answer in response")
            else:
                response.failure(f"Chat failed: {response.status_code}")
    
    @task(2)
    def get_chat_budget(self):
        """Test budget endpoint"""
        with self.client.get("/chat/budget",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Budget check failed: {response.status_code}")

class HealthCheckTasks(TaskSet):
    
    @task(20)
    def health_check(self):
        """Test health endpoint (high frequency)"""
        with self.client.get("/health",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Health check failed: {response.status_code}")
    
    @task(10)
    def root_endpoint(self):
        """Test root endpoint"""
        with self.client.get("/",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Root endpoint failed: {response.status_code}")
    
    @task(5)
    def test_endpoint(self):
        """Test /test endpoint"""
        with self.client.get("/test",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Test endpoint failed: {response.status_code}")

class RAGLoadTest(HttpUser):
    """Main load test user"""
    host = "http://localhost:8000"  # Change to your server URL
    wait_time = between(1, 5)  # Wait 1-5 seconds between tasks
    
    tasks = [
        HealthCheckTasks: 40,    # 40% probability
        AuthenticationTasks: 10, # 10% probability  
        DocumentTasks: 20,       # 20% probability
        ChatTasks: 30,           # 30% probability
    ]
    
    def on_start(self):
        """Print test start info"""
        print(f"🚀 Starting load test for {self.host}")
        print(f"📊 User count will be controlled by Locust")
    
    def on_stop(self):
        """Print test end info"""
        print(f"✅ Load test completed for {self.host}")