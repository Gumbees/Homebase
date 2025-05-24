"""
MCP Client for Homebase
Integrates the main application with the MCP server for AI processing
"""

import os
import asyncio
import json
import base64
from typing import Dict, Any, Optional, List
import httpx
import logging

logger = logging.getLogger(__name__)

class MCPClient:
    """Client for communicating with the MCP (Model Context Protocol) server"""
    
    def __init__(self, mcp_url: str = None):
        self.mcp_url = mcp_url or os.environ.get("MCP_SERVER_URL", "http://localhost:8080")
        self.client = None
        
    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=60.0)
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()
    
    def _ensure_client(self):
        """Ensure we have an HTTP client (for sync usage)"""
        if not self.client:
            self.client = httpx.AsyncClient(timeout=60.0)
    
    async def health_check(self) -> Dict[str, Any]:
        """Check MCP server health"""
        self._ensure_client()
        try:
            response = await self.client.get(f"{self.mcp_url}/health")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"MCP health check failed: {e}")
            raise
    
    async def analyze_receipt(
        self,
        image_data: bytes,
        filename: str,
        provider: str = "claude"
    ) -> Dict[str, Any]:
        """
        Analyze a receipt image and extract structured data
        
        Args:
            image_data: Raw image bytes
            filename: Original filename for format detection
            provider: AI provider to use (claude, openai, llm_studio)
            
        Returns:
            Structured receipt data
        """
        self._ensure_client()
        
        # Convert image to base64
        base64_data = base64.b64encode(image_data).decode('utf-8')
        
        # Determine image format
        if filename.lower().endswith('.png'):
            image_url = f"data:image/png;base64,{base64_data}"
        else:
            image_url = f"data:image/jpeg;base64,{base64_data}"
        
        try:
            response = await self.client.post(
                f"{self.mcp_url}/ai/receipt/analyze",
                json={
                    "image_data": image_url,
                    "provider": provider
                }
            )
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Receipt analyzed successfully with {provider}")
            return result
            
        except Exception as e:
            logger.error(f"Receipt analysis failed: {e}")
            raise
    
    async def categorize_object(
        self,
        object_data: Dict[str, Any],
        image_data: Optional[bytes] = None,
        provider: str = "claude"
    ) -> Dict[str, Any]:
        """
        Categorize and analyze an object
        
        Args:
            object_data: Object information
            image_data: Optional image of the object
            provider: AI provider to use
            
        Returns:
            Object analysis and categorization
        """
        self._ensure_client()
        
        image_url = None
        if image_data:
            base64_data = base64.b64encode(image_data).decode('utf-8')
            image_url = f"data:image/jpeg;base64,{base64_data}"
        
        try:
            response = await self.client.post(
                f"{self.mcp_url}/ai/object/categorize",
                json={
                    "object_data": object_data,
                    "image_data": image_url,
                    "provider": provider
                }
            )
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Object categorized successfully with {provider}")
            return result
            
        except Exception as e:
            logger.error(f"Object categorization failed: {e}")
            raise
    
    async def extract_vendor_info(
        self,
        image_data: bytes,
        provider: str = "claude"
    ) -> Dict[str, Any]:
        """
        Extract vendor information from an image
        
        Args:
            image_data: Raw image bytes
            provider: AI provider to use
            
        Returns:
            Vendor information
        """
        self._ensure_client()
        
        base64_data = base64.b64encode(image_data).decode('utf-8')
        image_url = f"data:image/jpeg;base64,{base64_data}"
        
        try:
            response = await self.client.post(
                f"{self.mcp_url}/ai/vendor/extract",
                json={
                    "image_data": image_url,
                    "provider": provider
                }
            )
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Vendor info extracted successfully with {provider}")
            return result
            
        except Exception as e:
            logger.error(f"Vendor extraction failed: {e}")
            raise
    
    async def process_ai_request(
        self,
        prompt_type: str,
        context: Dict[str, Any],
        provider: str = "claude",
        image_data: Optional[bytes] = None,
        output_schema: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.1
    ) -> Dict[str, Any]:
        """
        Generic AI request processing
        
        Args:
            prompt_type: Type of prompt to use
            context: Context variables for the prompt
            provider: AI provider to use
            image_data: Optional image data
            output_schema: Expected output schema
            max_tokens: Maximum tokens to generate
            temperature: Generation temperature
            
        Returns:
            AI response
        """
        self._ensure_client()
        
        image_url = None
        if image_data:
            base64_data = base64.b64encode(image_data).decode('utf-8')
            image_url = f"data:image/jpeg;base64,{base64_data}"
        
        payload = {
            "prompt_type": prompt_type,
            "provider": provider,
            "context": context,
            "image_data": image_url,
            "output_schema": output_schema,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        
        try:
            response = await self.client.post(
                f"{self.mcp_url}/ai/process",
                json=payload
            )
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"AI request processed: {prompt_type} with {provider}")
            return result
            
        except Exception as e:
            logger.error(f"AI request failed: {e}")
            raise
    
    async def get_available_providers(self) -> List[Dict[str, Any]]:
        """Get list of available AI providers"""
        self._ensure_client()
        try:
            response = await self.client.get(f"{self.mcp_url}/providers")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get providers: {e}")
            raise
    
    async def test_provider(self, provider_name: str) -> Dict[str, Any]:
        """Test a specific AI provider"""
        self._ensure_client()
        try:
            response = await self.client.post(f"{self.mcp_url}/providers/{provider_name}/test")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Provider test failed: {e}")
            raise
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get usage metrics from MCP server"""
        self._ensure_client()
        try:
            response = await self.client.get(f"{self.mcp_url}/metrics")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get metrics: {e}")
            raise
    
    async def list_prompt_templates(self) -> List[Dict[str, Any]]:
        """List available prompt templates"""
        self._ensure_client()
        try:
            response = await self.client.get(f"{self.mcp_url}/prompts/templates")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to list templates: {e}")
            raise
    
    async def get_prompt_template(self, template_name: str) -> Dict[str, Any]:
        """Get a specific prompt template"""
        self._ensure_client()
        try:
            response = await self.client.get(f"{self.mcp_url}/prompts/templates/{template_name}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get template: {e}")
            raise

# Synchronous wrapper functions for easy integration with existing Flask app

def create_mcp_client() -> MCPClient:
    """Create an MCP client instance"""
    return MCPClient()

async def analyze_receipt_async(
    image_data: bytes,
    filename: str,
    provider: str = "claude"
) -> Dict[str, Any]:
    """Async wrapper for receipt analysis"""
    async with MCPClient() as client:
        return await client.analyze_receipt(image_data, filename, provider)

async def categorize_object_async(
    object_data: Dict[str, Any],
    image_data: Optional[bytes] = None,
    provider: str = "claude"
) -> Dict[str, Any]:
    """Async wrapper for object categorization"""
    async with MCPClient() as client:
        return await client.categorize_object(object_data, image_data, provider)

async def extract_vendor_info_async(
    image_data: bytes,
    provider: str = "claude"
) -> Dict[str, Any]:
    """Async wrapper for vendor extraction"""
    async with MCPClient() as client:
        return await client.extract_vendor_info(image_data, provider)

# Utility functions for Flask integration

def run_async_in_thread(coro):
    """Run an async coroutine in a thread (for Flask integration)"""
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor
    
    def run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    
    with ThreadPoolExecutor() as executor:
        future = executor.submit(run_in_thread)
        return future.result()

# Flask-friendly sync wrappers
def analyze_receipt_sync(
    image_data: bytes,
    filename: str,
    provider: str = "claude"
) -> Dict[str, Any]:
    """Synchronous wrapper for receipt analysis"""
    return run_async_in_thread(
        analyze_receipt_async(image_data, filename, provider)
    )

def categorize_object_sync(
    object_data: Dict[str, Any],
    image_data: Optional[bytes] = None,
    provider: str = "claude"
) -> Dict[str, Any]:
    """Synchronous wrapper for object categorization"""
    return run_async_in_thread(
        categorize_object_async(object_data, image_data, provider)
    )

def extract_vendor_info_sync(
    image_data: bytes,
    provider: str = "claude"
) -> Dict[str, Any]:
    """Synchronous wrapper for vendor extraction"""
    return run_async_in_thread(
        extract_vendor_info_async(image_data, provider)
    ) 