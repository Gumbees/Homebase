"""
AI Providers Manager for MCP Server
Handles integration with multiple AI services (OpenAI, Anthropic, LLM Studio)
"""

import os
import asyncio
import time
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
import base64

import httpx
import structlog
from schemas import AIResponse, OUTPUT_SCHEMAS

logger = structlog.get_logger()

class AIProviderManager:
    """Manages multiple AI providers with failover and load balancing"""
    
    def __init__(self):
        self.providers = {}
        self.metrics = {
            "total_requests": 0,
            "requests_by_provider": {},
            "requests_by_type": {},
            "response_times": {},
            "errors": {},
            "costs": {}
        }
        
    async def initialize(self):
        """Initialize all available AI providers"""
        # Initialize providers based on available API keys
        if os.environ.get("ANTHROPIC_API_KEY"):
            self.providers["claude"] = ClaudeProvider()
            
        if os.environ.get("OPENAI_API_KEY"):
            self.providers["openai"] = OpenAIProvider()
            
        if os.environ.get("LLM_STUDIO_ENDPOINT"):
            self.providers["llm_studio"] = LLMStudioProvider()
        
        # Initialize each provider
        for name, provider in self.providers.items():
            try:
                await provider.initialize()
                logger.info(f"Initialized AI provider: {name}")
            except Exception as e:
                logger.error(f"Failed to initialize provider {name}: {e}")
                
        if not self.providers:
            logger.warning("No AI providers available - check your API keys")
    
    async def process_request(
        self,
        provider: str,
        prompt: str,
        image_data: Optional[str] = None,
        schema: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.1
    ) -> AIResponse:
        """Process an AI request with the specified provider"""
        start_time = time.time()
        
        if provider not in self.providers:
            raise ValueError(f"Provider '{provider}' not available")
        
        try:
            # Get the provider instance
            provider_instance = self.providers[provider]
            
            # Prepare the schema if specified
            output_schema = OUTPUT_SCHEMAS.get(schema) if schema else None
            
            # Process the request
            result = await provider_instance.process_request(
                prompt=prompt,
                image_data=image_data,
                output_schema=output_schema,
                max_tokens=max_tokens,
                temperature=temperature
            )
            
            processing_time = time.time() - start_time
            
            # Update metrics
            self._update_metrics(provider, "success", processing_time, result.get("tokens_used"))
            
            # Create response
            response = AIResponse(
                content=result["content"],
                provider=provider,
                prompt_type=result.get("prompt_type", "unknown"),
                confidence=result.get("confidence"),
                processing_time=processing_time,
                timestamp=datetime.utcnow(),
                tokens_used=result.get("tokens_used"),
                cost_estimate=result.get("cost_estimate")
            )
            
            logger.info(
                "AI request processed",
                provider=provider,
                processing_time=processing_time,
                tokens_used=result.get("tokens_used")
            )
            
            return response
            
        except Exception as e:
            processing_time = time.time() - start_time
            self._update_metrics(provider, "error", processing_time, 0)
            
            logger.error(
                "AI request failed",
                provider=provider,
                error=str(e),
                processing_time=processing_time
            )
            raise
    
    async def check_all_providers(self) -> Dict[str, bool]:
        """Check the status of all providers"""
        status = {}
        
        for name, provider in self.providers.items():
            try:
                await provider.health_check()
                status[name] = True
            except Exception:
                status[name] = False
                
        return status
    
    async def test_provider(self, provider_name: str) -> Dict[str, Any]:
        """Test a specific provider with a simple request"""
        if provider_name not in self.providers:
            raise ValueError(f"Provider '{provider_name}' not available")
            
        provider = self.providers[provider_name]
        test_prompt = "Respond with a simple JSON object containing 'status': 'ok'"
        
        start_time = time.time()
        result = await provider.process_request(
            prompt=test_prompt,
            max_tokens=50,
            temperature=0.0
        )
        response_time = time.time() - start_time
        
        return {
            "response_time": response_time,
            "result": result,
            "status": "ok"
        }
    
    async def get_provider_info(self) -> List[Dict[str, Any]]:
        """Get information about all available providers"""
        info = []
        
        for name, provider in self.providers.items():
            provider_info = {
                "name": name,
                "type": provider.__class__.__name__,
                "available": True,
                "capabilities": provider.get_capabilities(),
                "cost_per_token": provider.get_cost_info()
            }
            
            try:
                await provider.health_check()
            except Exception as e:
                provider_info["available"] = False
                provider_info["error"] = str(e)
                
            info.append(provider_info)
            
        return info
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get usage metrics"""
        return {
            **self.metrics,
            "providers_available": list(self.providers.keys()),
            "period_start": datetime.utcnow().replace(hour=0, minute=0, second=0),
            "period_end": datetime.utcnow()
        }
    
    def _update_metrics(self, provider: str, status: str, processing_time: float, tokens_used: int):
        """Update internal metrics"""
        self.metrics["total_requests"] += 1
        
        if provider not in self.metrics["requests_by_provider"]:
            self.metrics["requests_by_provider"][provider] = 0
        self.metrics["requests_by_provider"][provider] += 1
        
        if provider not in self.metrics["response_times"]:
            self.metrics["response_times"][provider] = []
        self.metrics["response_times"][provider].append(processing_time)
        
        if status == "error":
            if provider not in self.metrics["errors"]:
                self.metrics["errors"][provider] = 0
            self.metrics["errors"][provider] += 1
    
    async def cleanup(self):
        """Cleanup all providers"""
        for provider in self.providers.values():
            try:
                await provider.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up provider: {e}")


class BaseAIProvider:
    """Base class for AI providers"""
    
    def __init__(self):
        self.client = None
        
    async def initialize(self):
        """Initialize the provider"""
        pass
        
    async def process_request(
        self,
        prompt: str,
        image_data: Optional[str] = None,
        output_schema: Optional[Dict] = None,
        max_tokens: int = 1000,
        temperature: float = 0.1
    ) -> Dict[str, Any]:
        """Process an AI request"""
        raise NotImplementedError
        
    async def health_check(self):
        """Check if the provider is available"""
        raise NotImplementedError
        
    def get_capabilities(self) -> List[str]:
        """Get provider capabilities"""
        return ["text"]
        
    def get_cost_info(self) -> Dict[str, float]:
        """Get cost information"""
        return {"input_tokens": 0.0, "output_tokens": 0.0}
        
    async def cleanup(self):
        """Cleanup resources"""
        if hasattr(self.client, 'close'):
            await self.client.close()


class ClaudeProvider(BaseAIProvider):
    """Anthropic Claude provider"""
    
    async def initialize(self):
        import anthropic
        self.client = anthropic.AsyncAnthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
        
    async def process_request(
        self,
        prompt: str,
        image_data: Optional[str] = None,
        output_schema: Optional[Dict] = None,
        max_tokens: int = 1000,
        temperature: float = 0.1
    ) -> Dict[str, Any]:
        
        messages = []
        
        if image_data:
            # Handle image data
            if image_data.startswith('data:image/'):
                # Extract base64 data from data URI
                _, base64_data = image_data.split(',', 1)
                media_type = image_data.split(';')[0].split(':')[1]
            else:
                base64_data = image_data
                media_type = "image/jpeg"  # Default assumption
                
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64_data
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            })
        else:
            messages.append({
                "role": "user",
                "content": prompt
            })
        
        # Add JSON schema instruction if provided
        if output_schema:
            schema_prompt = f"\n\nRespond with valid JSON that matches this schema:\n{json.dumps(output_schema, indent=2)}"
            if image_data:
                messages[-1]["content"][-1]["text"] += schema_prompt
            else:
                messages[-1]["content"] += schema_prompt
        
        response = await self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages
        )
        
        content_text = response.content[0].text
        
        # Try to parse JSON response
        try:
            content = json.loads(content_text)
        except json.JSONDecodeError:
            # If not JSON, return as text
            content = {"response": content_text}
        
        return {
            "content": content,
            "tokens_used": response.usage.input_tokens + response.usage.output_tokens,
            "cost_estimate": self._calculate_cost(response.usage.input_tokens, response.usage.output_tokens)
        }
    
    async def health_check(self):
        """Check Claude API availability"""
        try:
            await self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}]
            )
        except Exception as e:
            raise Exception(f"Claude health check failed: {e}")
    
    def get_capabilities(self) -> List[str]:
        return ["text", "vision", "json_output"]
    
    def get_cost_info(self) -> Dict[str, float]:
        return {
            "input_tokens": 0.003,  # per 1K tokens
            "output_tokens": 0.015   # per 1K tokens
        }
    
    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate estimated cost for Claude usage"""
        cost_info = self.get_cost_info()
        return (input_tokens / 1000 * cost_info["input_tokens"]) + \
               (output_tokens / 1000 * cost_info["output_tokens"])


class OpenAIProvider(BaseAIProvider):
    """OpenAI GPT provider"""
    
    async def initialize(self):
        import openai
        self.client = openai.AsyncOpenAI(
            api_key=os.environ.get("OPENAI_API_KEY")
        )
        
    async def process_request(
        self,
        prompt: str,
        image_data: Optional[str] = None,
        output_schema: Optional[Dict] = None,
        max_tokens: int = 1000,
        temperature: float = 0.1
    ) -> Dict[str, Any]:
        
        messages = []
        
        if image_data:
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_data if image_data.startswith('data:') else f"data:image/jpeg;base64,{image_data}"
                        }
                    }
                ]
            })
        else:
            messages.append({
                "role": "user",
                "content": prompt
            })
        
        # Add JSON schema instruction if provided
        if output_schema:
            schema_prompt = f"\n\nRespond with valid JSON that matches this schema:\n{json.dumps(output_schema, indent=2)}"
            if image_data:
                messages[-1]["content"][0]["text"] += schema_prompt
            else:
                messages[-1]["content"] += schema_prompt
        
        model = "gpt-4o" if image_data else "gpt-4"
        
        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature
        )
        
        content_text = response.choices[0].message.content
        
        # Try to parse JSON response
        try:
            content = json.loads(content_text)
        except json.JSONDecodeError:
            content = {"response": content_text}
        
        return {
            "content": content,
            "tokens_used": response.usage.total_tokens,
            "cost_estimate": self._calculate_cost(response.usage.prompt_tokens, response.usage.completion_tokens, model)
        }
    
    async def health_check(self):
        """Check OpenAI API availability"""
        try:
            await self.client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5
            )
        except Exception as e:
            raise Exception(f"OpenAI health check failed: {e}")
    
    def get_capabilities(self) -> List[str]:
        return ["text", "vision", "json_output"]
    
    def get_cost_info(self) -> Dict[str, float]:
        return {
            "gpt-4": {"input": 0.03, "output": 0.06},
            "gpt-4o": {"input": 0.005, "output": 0.015}
        }
    
    def _calculate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        """Calculate estimated cost for OpenAI usage"""
        cost_info = self.get_cost_info().get(model, {"input": 0.03, "output": 0.06})
        return (input_tokens / 1000 * cost_info["input"]) + \
               (output_tokens / 1000 * cost_info["output"])


class LLMStudioProvider(BaseAIProvider):
    """Local LLM Studio provider"""
    
    async def initialize(self):
        self.endpoint = os.environ.get("LLM_STUDIO_ENDPOINT", "http://localhost:1234")
        self.client = httpx.AsyncClient(timeout=30.0)
        
    async def process_request(
        self,
        prompt: str,
        image_data: Optional[str] = None,
        output_schema: Optional[Dict] = None,
        max_tokens: int = 1000,
        temperature: float = 0.1
    ) -> Dict[str, Any]:
        
        # LLM Studio typically follows OpenAI API format
        messages = [{"role": "user", "content": prompt}]
        
        # Add JSON schema instruction if provided
        if output_schema:
            schema_prompt = f"\n\nRespond with valid JSON that matches this schema:\n{json.dumps(output_schema, indent=2)}"
            messages[-1]["content"] += schema_prompt
        
        # Note: Local models may not support vision
        if image_data:
            logger.warning("Image processing may not be supported by local LLM")
        
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False
        }
        
        response = await self.client.post(
            f"{self.endpoint}/v1/chat/completions",
            json=payload
        )
        response.raise_for_status()
        
        result = response.json()
        content_text = result["choices"][0]["message"]["content"]
        
        # Try to parse JSON response
        try:
            content = json.loads(content_text)
        except json.JSONDecodeError:
            content = {"response": content_text}
        
        return {
            "content": content,
            "tokens_used": result.get("usage", {}).get("total_tokens", 0),
            "cost_estimate": 0.0  # Local models are free
        }
    
    async def health_check(self):
        """Check LLM Studio availability"""
        try:
            response = await self.client.get(f"{self.endpoint}/health")
            response.raise_for_status()
        except Exception as e:
            raise Exception(f"LLM Studio health check failed: {e}")
    
    def get_capabilities(self) -> List[str]:
        return ["text", "json_output"]
    
    def get_cost_info(self) -> Dict[str, float]:
        return {"input_tokens": 0.0, "output_tokens": 0.0}
    
    async def cleanup(self):
        """Cleanup HTTP client"""
        await self.client.aclose() 