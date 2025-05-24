"""
Pydantic schemas for the MCP server
Defines request/response models and data validation
"""

from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from pydantic import BaseModel, Field, validator
from enum import Enum

class AIProvider(str, Enum):
    CLAUDE = "claude"
    OPENAI = "openai"
    LLM_STUDIO = "llm_studio"

class PromptType(str, Enum):
    RECEIPT_ANALYSIS = "receipt_analysis"
    OBJECT_CATEGORIZATION = "object_categorization"
    VENDOR_EXTRACTION = "vendor_extraction"
    ASSET_EVALUATION = "asset_evaluation"
    LINE_ITEM_EXTRACTION = "line_item_extraction"
    CATEGORY_SUGGESTION = "category_suggestion"

class OutputSchema(str, Enum):
    RECEIPT_DATA = "receipt_data"
    OBJECT_ANALYSIS = "object_analysis"
    VENDOR_INFO = "vendor_info"
    LINE_ITEMS = "line_items"
    CATEGORIES = "categories"

class AIRequest(BaseModel):
    """Request model for AI processing"""
    prompt_type: PromptType
    provider: AIProvider = AIProvider.CLAUDE
    context: Dict[str, Any] = Field(default_factory=dict)
    image_data: Optional[str] = None  # Base64 encoded image
    output_schema: Optional[OutputSchema] = None
    max_tokens: Optional[int] = Field(default=1000, ge=1, le=4000)
    temperature: Optional[float] = Field(default=0.1, ge=0.0, le=2.0)
    
    @validator('image_data')
    def validate_image_data(cls, v):
        if v and not v.startswith('data:image/'):
            # If it's just base64 without the data URI prefix, add it
            if v.startswith('/9j/') or v.startswith('iVBORw0KGgo'):  # JPEG or PNG
                return f"data:image/jpeg;base64,{v}"
        return v

class AIResponse(BaseModel):
    """Response model for AI processing"""
    content: Dict[str, Any]
    provider: str
    prompt_type: str
    confidence: Optional[float] = None
    processing_time: float
    timestamp: datetime
    tokens_used: Optional[int] = None
    cost_estimate: Optional[float] = None

class PromptTemplate(BaseModel):
    """Model for prompt templates"""
    name: str
    content: str
    description: str
    variables: List[str] = Field(default_factory=list)
    output_schema: Optional[str] = None
    version: str = "1.0"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

# Output schema models for structured responses

class ReceiptData(BaseModel):
    """Schema for receipt analysis output"""
    vendor_name: str
    date: str
    total_amount: float
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    receipt_number: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    is_bill: bool = False
    line_items: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

class LineItem(BaseModel):
    """Schema for individual line items"""
    description: str
    quantity: Optional[float] = 1.0
    unit_price: Optional[float] = None
    total_price: float
    category: Optional[str] = None
    suggested_object_type: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)

class ObjectAnalysis(BaseModel):
    """Schema for object categorization output"""
    suggested_type: str  # asset, consumable, component, etc.
    suggested_categories: List[str]
    estimated_value: Optional[float] = None
    useful_life_years: Optional[int] = None
    depreciation_rate: Optional[float] = None
    specifications: Dict[str, Any] = Field(default_factory=dict)
    maintenance_schedule: Optional[str] = None
    storage_requirements: Optional[str] = None
    safety_considerations: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

class VendorInfo(BaseModel):
    """Schema for vendor information extraction"""
    name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    business_type: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)

class CategorySuggestion(BaseModel):
    """Schema for category suggestions"""
    category: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    icon_suggestion: Optional[str] = None
    color_suggestion: Optional[str] = None

class ProviderStatus(BaseModel):
    """Schema for provider status information"""
    name: str
    available: bool
    last_check: datetime
    error_message: Optional[str] = None
    response_time: Optional[float] = None
    rate_limit_remaining: Optional[int] = None

class UsageMetrics(BaseModel):
    """Schema for usage metrics"""
    total_requests: int
    requests_by_provider: Dict[str, int]
    requests_by_type: Dict[str, int]
    average_response_time: float
    error_rate: float
    cost_total: float
    cost_by_provider: Dict[str, float]
    period_start: datetime
    period_end: datetime

# JSON Schema definitions for structured outputs
OUTPUT_SCHEMAS = {
    "receipt_data": {
        "type": "object",
        "properties": {
            "vendor_name": {"type": "string"},
            "date": {"type": "string", "format": "date"},
            "total_amount": {"type": "number"},
            "subtotal": {"type": "number"},
            "tax_amount": {"type": "number"},
            "receipt_number": {"type": "string"},
            "description": {"type": "string"},
            "due_date": {"type": "string", "format": "date"},
            "is_bill": {"type": "boolean"},
            "line_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "quantity": {"type": "number"},
                        "unit_price": {"type": "number"},
                        "total_price": {"type": "number"},
                        "category": {"type": "string"},
                        "suggested_object_type": {"type": "string"}
                    },
                    "required": ["description", "total_price"]
                }
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1}
        },
        "required": ["vendor_name", "date", "total_amount", "confidence"]
    },
    
    "object_analysis": {
        "type": "object",
        "properties": {
            "suggested_type": {"type": "string"},
            "suggested_categories": {
                "type": "array",
                "items": {"type": "string"}
            },
            "estimated_value": {"type": "number"},
            "useful_life_years": {"type": "integer"},
            "depreciation_rate": {"type": "number"},
            "specifications": {"type": "object"},
            "maintenance_schedule": {"type": "string"},
            "storage_requirements": {"type": "string"},
            "safety_considerations": {
                "type": "array",
                "items": {"type": "string"}
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1}
        },
        "required": ["suggested_type", "suggested_categories", "confidence"]
    },
    
    "vendor_info": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "address": {"type": "string"},
            "phone": {"type": "string"},
            "email": {"type": "string", "format": "email"},
            "website": {"type": "string", "format": "uri"},
            "business_type": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1}
        },
        "required": ["name", "confidence"]
    }
} 