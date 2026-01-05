# blob_storage.py - Azure Blob Storage operations
from azure.storage.blob import BlobServiceClient
import os
import uuid
from datetime import datetime

class BlobStorageManager:
    def __init__(self):
        self.connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        self.container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "pdf-documents")
        self.blob_service_client = BlobServiceClient.from_connection_string(self.connection_string)
        self._ensure_container_exists()
    
    def _ensure_container_exists(self):
        """Create container if it doesn't exist"""
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            if not container_client.exists():
                container_client.create_container()
                print(f"✅ Created container: {self.container_name}")
        except Exception as e:
            print(f"⚠️  Error checking container: {e}")
            raise
    
    def upload_pdf(self, file_content: bytes, user_id: str, original_filename: str) -> dict:
        """
        Upload PDF to Azure Blob Storage
        
        Returns: {
            "blob_url": "https://...",
            "blob_name": "user_id/filename_uuid.pdf",
            "container": "container_name"
        }
        """
        try:
            # Generate unique blob name
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            file_extension = original_filename.split('.')[-1] if '.' in original_filename else 'pdf'
            blob_name = f"{user_id}/{timestamp}_{unique_id}.{file_extension}"
            
            # Get blob client and upload
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            
            blob_client.upload_blob(file_content, overwrite=True)
            
            # Return blob information
            return {
                "blob_url": blob_client.url,
                "blob_name": blob_name,
                "container": self.container_name,
                "file_size": len(file_content),
                "content_type": "application/pdf"
            }
            
        except Exception as e:
            raise Exception(f"Failed to upload to blob storage: {str(e)}")
    
    def download_pdf(self, blob_name: str) -> bytes:
        """Download PDF from Azure Blob Storage"""
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            download_stream = blob_client.download_blob()
            return download_stream.readall()
        except Exception as e:
            raise Exception(f"Failed to download from blob storage: {str(e)}")
    
    def delete_pdf(self, blob_name: str) -> bool:
        """Delete PDF from Azure Blob Storage"""
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            blob_client.delete_blob()
            return True
        except Exception as e:
            raise Exception(f"Failed to delete from blob storage: {str(e)}")
    
    def list_user_blobs(self, user_id: str) -> list:
        """List all blobs for a specific user"""
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            blobs = container_client.list_blobs(name_starts_with=f"{user_id}/")
            
            result = []
            for blob in blobs:
                blob_client = container_client.get_blob_client(blob.name)
                result.append({
                    "name": blob.name,
                    "url": blob_client.url,
                    "size": blob.size,
                    "last_modified": blob.last_modified
                })
            
            return result
        except Exception as e:
            raise Exception(f"Failed to list blobs: {str(e)}")
    
    def get_blob_info(self, blob_name: str) -> dict:
        """Get information about a specific blob"""
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            properties = blob_client.get_blob_properties()
            
            return {
                "name": blob_name,
                "url": blob_client.url,
                "size": properties.size,
                "content_type": properties.content_settings.content_type,
                "last_modified": properties.last_modified,
                "creation_time": properties.creation_time
            }
        except Exception as e:
            raise Exception(f"Failed to get blob info: {str(e)}")

# Create global instance
blob_manager = BlobStorageManager()