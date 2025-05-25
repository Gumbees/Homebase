#!/usr/bin/env python3
"""
MCP (Model Context Protocol) Server for Homebase
Centralizes AI prompt management, provider abstraction, and structured outputs.
"""

import os
import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

import structlog
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from prompt_manager import PromptManager
from ai_providers import AIProviderManager
from schemas import AIRequest, AIResponse, PromptTemplate

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Initialize FastAPI app
app = FastAPI(
    title="Homebase MCP Server",
    description="Model Context Protocol server for AI prompt management",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global managers
prompt_manager = PromptManager()
ai_provider_manager = AIProviderManager()

class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    version: str
    providers: Dict[str, bool]

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    provider_status = await ai_provider_manager.check_all_providers()
    
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow(),
        version="1.0.0",
        providers=provider_status
    )

@app.post("/ai/process", response_model=AIResponse)
async def process_ai_request(request: AIRequest):
    """
    Main AI processing endpoint.
    Handles prompt templating, provider selection, and structured output.
    """
    try:
        logger.info(
            "Processing AI request",
            prompt_type=request.prompt_type,
            provider=request.provider,
            has_image=bool(request.image_data)
        )
        
        # Get and render the prompt template
        prompt_template = await prompt_manager.get_template(request.prompt_type)
        rendered_prompt = await prompt_manager.render_prompt(
            prompt_template,
            request.context
        )
        
        # Process with selected AI provider
        result = await ai_provider_manager.process_request(
            provider=request.provider,
            prompt=rendered_prompt,
            image_data=request.image_data,
            schema=request.output_schema,
            max_tokens=request.max_tokens,
            temperature=request.temperature
        )
        
        logger.info(
            "AI request processed successfully",
            prompt_type=request.prompt_type,
            provider=request.provider,
            response_length=len(str(result.content))
        )
        
        return result
        
    except Exception as e:
        logger.error(
            "Error processing AI request",
            error=str(e),
            prompt_type=request.prompt_type,
            provider=request.provider
        )
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/prompts/templates")
async def list_prompt_templates():
    """List all available prompt templates"""
    return await prompt_manager.list_templates()

@app.get("/prompts/templates/{template_name}")
async def get_prompt_template(template_name: str):
    """Get a specific prompt template"""
    try:
        template = await prompt_manager.get_template(template_name)
        return template
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Template '{template_name}' not found")

@app.post("/prompts/templates/{template_name}")
async def update_prompt_template(template_name: str, template: PromptTemplate):
    """Update or create a prompt template"""
    await prompt_manager.save_template(template_name, template)
    return {"message": f"Template '{template_name}' updated successfully"}

@app.get("/providers")
async def list_providers():
    """List all available AI providers and their status"""
    return await ai_provider_manager.get_provider_info()

@app.post("/providers/{provider_name}/test")
async def test_provider(provider_name: str):
    """Test a specific AI provider"""
    try:
        result = await ai_provider_manager.test_provider(provider_name)
        return {"provider": provider_name, "status": "ok", "result": result}
    except Exception as e:
        return {"provider": provider_name, "status": "error", "error": str(e)}

@app.get("/metrics")
async def get_metrics():
    """Get usage metrics and statistics"""
    return await ai_provider_manager.get_metrics()

# Specialized endpoints for common Homebase tasks

@app.post("/ai/receipt/analyze")
async def analyze_receipt(
    image_data: str,
    provider: str = "claude",
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """Specialized endpoint for receipt analysis"""
    request = AIRequest(
        prompt_type="receipt_analysis",
        provider=provider,
        image_data=image_data,
        context={},
        output_schema="receipt_data"
    )
    
    # Log request for analytics
    background_tasks.add_task(log_request_analytics, "receipt_analysis", provider)
    
    return await process_ai_request(request)

@app.post("/ai/object/categorize")
async def categorize_object(
    object_data: Dict[str, Any],
    image_data: Optional[str] = None,
    provider: str = "claude"
):
    """Specialized endpoint for object categorization"""
    request = AIRequest(
        prompt_type="object_categorization",
        provider=provider,
        image_data=image_data,
        context={"object": object_data},
        output_schema="object_analysis"
    )
    
    return await process_ai_request(request)

@app.post("/ai/vendor/extract")
async def extract_vendor_info(
    image_data: str,
    provider: str = "claude"
):
    """Specialized endpoint for vendor information extraction"""
    request = AIRequest(
        prompt_type="vendor_extraction",
        provider=provider,
        image_data=image_data,
        context={},
        output_schema="vendor_info"
    )
    
    return await process_ai_request(request)

async def log_request_analytics(prompt_type: str, provider: str):
    """Background task to log request analytics"""
    # This could send metrics to a monitoring system
    logger.info(
        "Request analytics",
        prompt_type=prompt_type,
        provider=provider,
        timestamp=datetime.utcnow()
    )

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("Starting MCP Server")
    
    # Initialize prompt manager
    await prompt_manager.initialize()
    logger.info("Prompt manager initialized")
    
    # Initialize AI providers
    await ai_provider_manager.initialize()
    logger.info("AI provider manager initialized")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down MCP Server")
    await ai_provider_manager.cleanup()

if __name__ == "__main__":
    port = int(os.environ.get("MCP_PORT", 8080))
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info"
    ) 