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
    """Schema for comprehensive receipt analysis output"""
    # Basic receipt information
    vendor_name: str
    date: str
    total_amount: float
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    tip_amount: Optional[float] = None
    fees: Optional[float] = None
    receipt_number: Optional[str] = None
    payment_method: Optional[str] = None
    
    # Document classification
    due_date: Optional[str] = None
    is_bill: bool = False
    document_type: Optional[str] = None
    description: Optional[str] = None
    
    # Line items with enhanced object suggestions
    line_items: List[Dict[str, Any]] = Field(default_factory=list)
    
    # People mentioned in receipt
    people_found: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Digital assets and attachments
    digital_assets: Dict[str, Any] = Field(default_factory=dict)
    
    # Event details (if applicable)
    event_details: Optional[Dict[str, Any]] = None
    
    # Enhanced vendor information
    vendor_details: Dict[str, Any] = Field(default_factory=dict)
    
    # Quality assessment
    overall_confidence: float = Field(ge=0.0, le=1.0)
    image_quality: Optional[str] = None
    missing_information: List[str] = Field(default_factory=list)
    extraction_notes: Optional[str] = None

class PersonFound(BaseModel):
    """Schema for people found in receipts"""
    create_person_object: bool = True
    person_name: str
    role: str  # customer, staff, attendee, contact, etc.
    relationship_to_purchase: str
    contact_info: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)

class DigitalAssets(BaseModel):
    """Schema for digital assets found in receipts"""
    qr_codes: List[str] = Field(default_factory=list)
    barcodes: List[str] = Field(default_factory=list)
    urls: List[str] = Field(default_factory=list)
    confirmation_codes: List[str] = Field(default_factory=list)
    ticket_numbers: List[str] = Field(default_factory=list)
    account_numbers: List[str] = Field(default_factory=list)

class EventDetails(BaseModel):
    """Schema for event information"""
    event_name: Optional[str] = None
    event_date: Optional[str] = None  # YYYY-MM-DD
    event_time: Optional[str] = None
    venue_location: Optional[str] = None
    seat_info: Optional[str] = None
    additional_details: Dict[str, Any] = Field(default_factory=dict)

class EnhancedLineItem(BaseModel):
    """Schema for enhanced line items with comprehensive object suggestions"""
    description: str
    quantity: Optional[float] = 1.0
    unit_price: Optional[float] = None
    total_price: float
    item_details: Optional[str] = None
    
    # Object creation suggestions
    create_object: bool = False
    object_type: Optional[str] = None  # asset, consumable, component, service, software
    category: Optional[str] = None
    
    # Expiration and lifecycle info
    expiration_info: Optional[Dict[str, Any]] = None
    
    # Object details
    object_details: Dict[str, Any] = Field(default_factory=dict)
    
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
    """Schema for comprehensive object categorization and valuation output"""
    # Object identification
    object_name: Optional[str] = None
    description: Optional[str] = None
    brand_model: Optional[str] = None
    serial_numbers: List[str] = Field(default_factory=list)
    
    # Categorization
    object_type: str  # asset, consumable, component, service, software
    category: str
    
    # Comprehensive valuation
    estimated_current_value: Optional[float] = None
    value_confidence: Optional[float] = Field(default=0.7, ge=0.0, le=1.0)
    condition_assessment: Optional[str] = None  # Excellent, Very Good, Good, Fair, Poor
    depreciation_factors: Optional[str] = None
    market_trend: Optional[str] = None  # Appreciating, Stable, Depreciating
    replacement_cost: Optional[float] = None
    
    # Condition & age assessment
    estimated_age_years: Optional[int] = None
    wear_indicators: Optional[str] = None
    maintenance_needs: Optional[str] = None
    useful_life_remaining: Optional[str] = None
    
    # Detailed specifications
    specifications: Dict[str, Any] = Field(default_factory=dict)
    materials: Optional[str] = None
    dimensions: Optional[str] = None
    weight_estimate: Optional[str] = None
    
    # Insurance & documentation
    insurance_category: Optional[str] = None
    special_considerations: Optional[str] = None
    documentation_notes: Optional[str] = None
    replacement_difficulty: Optional[str] = None  # Common, Moderate, Difficult, Rare
    
    # Market analysis
    demand_level: Optional[str] = None  # High, Medium, Low
    liquidity: Optional[str] = None
    comparable_items: Optional[str] = None
    selling_venues: Optional[str] = None
    
    # Recommendations
    disposition_recommendation: Optional[str] = None  # Keep, Sell, Donate, Dispose, Repair
    maintenance_priority: Optional[str] = None  # High, Medium, Low
    insurance_recommendation: Optional[str] = None
    storage_recommendations: Optional[str] = None
    
    # Confidence assessment
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty_factors: Optional[str] = None
    additional_info_needed: Optional[str] = None
    
    # Valuation methodology
    valuation_methodology: Optional[str] = None
    
    # Legacy fields for backward compatibility
    suggested_type: Optional[str] = None  # Maps to object_type
    suggested_categories: List[str] = Field(default_factory=list)  # Maps to [category]
    estimated_value: Optional[float] = None  # Maps to estimated_current_value
    useful_life_years: Optional[int] = None
    depreciation_rate: Optional[float] = None
    maintenance_schedule: Optional[str] = None
    storage_requirements: Optional[str] = None
    safety_considerations: List[str] = Field(default_factory=list)

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
            # Basic receipt information
            "vendor_name": {"type": "string"},
            "date": {"type": "string", "format": "date"},
            "total_amount": {"type": "number"},
            "subtotal": {"type": "number"},
            "tax_amount": {"type": "number"},
            "tip_amount": {"type": "number"},
            "fees": {"type": "number"},
            "receipt_number": {"type": "string"},
            "payment_method": {"type": "string"},
            
            # Document classification
            "due_date": {"type": "string", "format": "date"},
            "is_bill": {"type": "boolean"},
            "document_type": {"type": "string"},
            "description": {"type": "string"},
            
            # Enhanced line items
            "line_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "quantity": {"type": "number"},
                        "unit_price": {"type": "number"},
                        "total_price": {"type": "number"},
                        "item_details": {"type": "string"},
                        "create_object": {"type": "boolean"},
                        "object_type": {
                            "type": "string",
                            "enum": ["asset", "consumable", "component", "service", "software"]
                        },
                        "category": {"type": "string"},
                        "expiration_info": {
                            "type": "object",
                            "properties": {
                                "expiration_date": {"type": "string", "format": "date"},
                                "event_date": {"type": "string", "format": "date"},
                                "shelf_life_days": {"type": "integer"}
                            }
                        },
                        "object_details": {
                            "type": "object",
                            "properties": {
                                "serial_numbers": {"type": "array", "items": {"type": "string"}},
                                "specifications": {"type": "object"},
                                "warranty_info": {"type": "string"}
                            }
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
                    },
                    "required": ["description", "total_price", "confidence"]
                }
            },
            
            # People found in receipt
            "people_found": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "create_person_object": {"type": "boolean"},
                        "person_name": {"type": "string"},
                        "role": {"type": "string"},
                        "relationship_to_purchase": {"type": "string"},
                        "contact_info": {"type": "object"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
                    },
                    "required": ["person_name", "role", "relationship_to_purchase"]
                }
            },
            
            # Digital assets
            "digital_assets": {
                "type": "object",
                "properties": {
                    "qr_codes": {"type": "array", "items": {"type": "string"}},
                    "barcodes": {"type": "array", "items": {"type": "string"}},
                    "urls": {"type": "array", "items": {"type": "string"}},
                    "confirmation_codes": {"type": "array", "items": {"type": "string"}},
                    "ticket_numbers": {"type": "array", "items": {"type": "string"}},
                    "account_numbers": {"type": "array", "items": {"type": "string"}}
                }
            },
            
            # Event details
            "event_details": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string"},
                    "event_date": {"type": "string", "format": "date"},
                    "event_time": {"type": "string"},
                    "venue_location": {"type": "string"},
                    "seat_info": {"type": "string"},
                    "additional_details": {"type": "object"}
                }
            },
            
            # Enhanced vendor information
            "vendor_details": {
                "type": "object",
                "properties": {
                    "business_address": {"type": "string"},
                    "business_phone": {"type": "string"},
                    "business_email": {"type": "string"},
                    "business_website": {"type": "string"},
                    "business_hours": {"type": "string"},
                    "business_type": {"type": "string"}
                }
            },
            
            # Quality assessment
            "overall_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "image_quality": {"type": "string"},
            "missing_information": {"type": "array", "items": {"type": "string"}},
            "extraction_notes": {"type": "string"}
        },
        "required": ["vendor_name", "date", "total_amount", "overall_confidence"]
    },
    
    "object_analysis": {
        "type": "object",
        "properties": {
            # Object identification
            "object_name": {"type": "string"},
            "description": {"type": "string"},
            "brand_model": {"type": "string"},
            "serial_numbers": {"type": "array", "items": {"type": "string"}},
            
            # Categorization
            "object_type": {
                "type": "string",
                "enum": ["asset", "consumable", "component", "service", "software"]
            },
            "category": {"type": "string"},
            
            # Comprehensive valuation
            "estimated_current_value": {"type": "number"},
            "value_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "condition_assessment": {
                "type": "string",
                "enum": ["Excellent", "Very Good", "Good", "Fair", "Poor"]
            },
            "depreciation_factors": {"type": "string"},
            "market_trend": {
                "type": "string", 
                "enum": ["Appreciating", "Stable", "Depreciating"]
            },
            "replacement_cost": {"type": "number"},
            
            # Condition & age assessment
            "estimated_age_years": {"type": "integer"},
            "wear_indicators": {"type": "string"},
            "maintenance_needs": {"type": "string"},
            "useful_life_remaining": {"type": "string"},
            
            # Detailed specifications
            "specifications": {"type": "object"},
            "materials": {"type": "string"},
            "dimensions": {"type": "string"},
            "weight_estimate": {"type": "string"},
            
            # Insurance & documentation
            "insurance_category": {"type": "string"},
            "special_considerations": {"type": "string"},
            "documentation_notes": {"type": "string"},
            "replacement_difficulty": {
                "type": "string",
                "enum": ["Common", "Moderate", "Difficult", "Rare"]
            },
            
            # Market analysis
            "demand_level": {
                "type": "string",
                "enum": ["High", "Medium", "Low"]
            },
            "liquidity": {"type": "string"},
            "comparable_items": {"type": "string"},
            "selling_venues": {"type": "string"},
            
            # Recommendations
            "disposition_recommendation": {
                "type": "string",
                "enum": ["Keep", "Sell", "Donate", "Dispose", "Repair"]
            },
            "maintenance_priority": {
                "type": "string",
                "enum": ["High", "Medium", "Low"]
            },
            "insurance_recommendation": {"type": "string"},
            "storage_recommendations": {"type": "string"},
            
            # Confidence assessment
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "uncertainty_factors": {"type": "string"},
            "additional_info_needed": {"type": "string"},
            
            # Valuation methodology
            "valuation_methodology": {"type": "string"},
            
            # Legacy fields for backward compatibility
            "suggested_type": {"type": "string"},
            "suggested_categories": {
                "type": "array",
                "items": {"type": "string"}
            },
            "estimated_value": {"type": "number"},
            "useful_life_years": {"type": "integer"},
            "depreciation_rate": {"type": "number"},
            "maintenance_schedule": {"type": "string"},
            "storage_requirements": {"type": "string"},
            "safety_considerations": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": ["object_type", "category", "confidence"]
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