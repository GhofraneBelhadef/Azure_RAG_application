# shared_dependencies.py
from openai import AzureOpenAI
import os
import httpx
from fastapi import HTTPException

# Initialize Azure OpenAI embedding client
embedding_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_EMBEDDING_KEY"),
    api_version=os.getenv("AZURE_OPENAI_EMBEDDING_API_VERSION", "2023-05-15"),
    azure_endpoint=os.getenv("AZURE_OPENAI_EMBEDDING_ENDPOINT"),
    max_retries=2
)

# Initialize Azure OpenAI chat client
chat_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_CHAT_KEY"),
    api_version=os.getenv("AZURE_OPENAI_CHAT_API_VERSION", "2025-01-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_CHAT_ENDPOINT"),
    max_retries=2
)

# Budget tracker class
class BudgetTracker:
    def __init__(self, max_budget: float = 1.0):
        self.max_budget = max_budget
        self.used_budget = 0.0
        self.costs = {
            "embedding": 0.00002,
            "chat_input": 0.00015,
            "chat_output": 0.00060,
        }
    
    def check_and_add(self, estimated_tokens: int, cost_type: str) -> bool:
        cost_per_token = self.costs.get(cost_type, 0.00015)
        estimated_cost = (estimated_tokens / 1000) * cost_per_token
        
        if self.used_budget + estimated_cost > self.max_budget:
            return False
        
        self.used_budget += estimated_cost
        return True
    
    def get_status(self):
        return {
            "used_budget": round(self.used_budget, 4),
            "remaining_budget": round(self.max_budget - self.used_budget, 4),
            "percentage_used": round((self.used_budget / self.max_budget) * 100, 2)
        }

# Create global instance
budget_tracker = BudgetTracker(float(os.getenv("AZURE_OPENAI_MAX_BUDGET", 1.0)))

def create_embedding(text: str) -> list:
    """Create embeddings using Azure OpenAI"""
    try:
        estimated_tokens = len(text) // 4
        
        if not budget_tracker.check_and_add(estimated_tokens, "embedding"):
            raise HTTPException(
                status_code=402,
                detail=f"Budget limit reached. Used: ${budget_tracker.used_budget:.4f}"
            )
        
        response = embedding_client.embeddings.create(
            model=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
            input=text
        )
        return response.data[0].embedding
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create embedding: {str(e)}"
        )