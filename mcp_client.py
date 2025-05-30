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
from datetime import datetime

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
        Analyze a receipt image and extract structured data with context from existing object types and categories
        
        Args:
            image_data: Raw image bytes
            filename: Original filename for format detection
            provider: AI provider to use (claude, openai, llm_studio)
            
        Returns:
            Structured receipt data including digital assets like QR codes for event tickets
        """
        self._ensure_client()
        
        # Convert image to base64
        base64_data = base64.b64encode(image_data).decode('utf-8')
        
        # Get existing object types and categories context
        object_types_context = await self._get_object_types_context()
        categories_context = await self._get_categories_context()
        
        try:
            # Enhanced analysis request with comprehensive metadata extraction
            image_url = f"data:image/jpeg;base64,{base64_data}"
            
            request_data = {
                "prompt_type": "receipt_analysis",
                "provider": provider,
                "image_data": image_url,
                "context": {
                    "filename": filename,
                    "enhanced_extraction": True,
                    "existing_object_types": object_types_context,
                    "existing_categories": categories_context,
                    "extract_metadata": {
                        "upc_codes": True,
                        "manufacturer": True,
                        "model_numbers": True,
                        "serial_numbers": True,
                        "event_detection": True,
                        "qr_codes": True,
                        "digital_assets": True,
                        "object_classification": True,
                        "person_detection": True  # Explicitly enable person detection
                    },
                    "instructions": (
                        "Perform comprehensive analysis of this receipt with enhanced metadata extraction using OpenAI's advanced vision capabilities. "
                        "IMPORTANT: When QR codes or UPC/barcode codes are detected, crop and return the actual IMAGE of the code as base64 data. "
                        "Use the provided object types and categories as context for classification. "
                        "For EVERY line item, extract: UPC/barcode codes, manufacturer/brand, model numbers, serial numbers. "
                        "For event tickets/passes: detect QR codes, confirmation codes, venue details, event dates. "
                        "CROP AND RETURN QR CODE IMAGES: When QR codes are found, extract the actual image region and return as base64. "
                        "CROP AND RETURN UPC/BARCODE IMAGES: When barcodes are found, extract the actual code image and return as base64. "
                        "For assets: identify depreciation category, maintenance requirements, serial tracking needs. "
                        "Classify each item using the provided object types: asset, consumable, component, service, software, person, pet. "
                        "Use existing categories when possible, but suggest NEW categories if none fit. "
                        "ALWAYS detect people mentioned in receipts (customers, staff, attendees, contacts). "
                        "For event-related purchases, extract venue location, event date/time, ticket types. "
                        "Include digital asset URLs, QR code data, confirmation codes, and any ticket images. "
                        "Return cropped images for QR codes and UPC codes in the digital_assets section as: "
                        "{'qr_code_image': 'base64_data', 'upc_code_image': 'base64_data', 'qr_code': 'text_data', 'upc_code': 'code_data'}. "
                        "Suggest object creation for line items that represent physical or digital goods."
                    )
                },
                "output_schema": "receipt_data",
                "max_tokens": 1500,
                "temperature": 0.1
            }
            
            response = await self.client.post(
                f"{self.mcp_url}/ai/process",
                json=request_data
            )
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Receipt analyzed successfully with {provider}")
            return result
            
        except Exception as e:
            # Enhanced fallback with metadata extraction
            logger.warning(f"MCP server unavailable, using enhanced fallback: {str(e)}")
            
            # Create comprehensive fallback data with smart classification
            vendor_name = self._extract_basic_vendor_from_filename(filename)
            
            return {
                "content": {
                    "response": json.dumps({
                        "vendor_name": vendor_name,
                        "date": datetime.now().strftime('%Y-%m-%d'),
                        "total_amount": 0.0,
                        "description": f"Receipt analysis from {filename}",
                        "line_items": [
                            {
                                "description": "Receipt item (manual review required)",
                                "quantity": 1,
                                "unit_price": 0.0,
                                "extracted_metadata": {
                                    "upc_code": None,
                                    "manufacturer": vendor_name,
                                    "model": None,
                                    "serial_number": None,
                                    "suggested_object_type": "expense",
                                    "category_suggestions": ["uncategorized"],
                                    "needs_manual_review": True
                                }
                            }
                        ],
                        "enhanced_analysis": True,
                        "metadata_extraction": "fallback",
                        "event_details": None,
                        "digital_assets": {},
                        "overall_confidence": 0.3
                    })
                }
            }
    
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
            # Use the main AI processing endpoint with proper JSON structure
            request_data = {
                "prompt_type": "object_categorization",
                "provider": provider,
                "image_data": image_url,
                "context": {"object": object_data},
                "output_schema": "object_analysis",
                "max_tokens": 1000,
                "temperature": 0.1
            }
            
            response = await self.client.post(
                f"{self.mcp_url}/ai/process",
                json=request_data
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
            # Use the main AI processing endpoint with proper JSON structure
            request_data = {
                "prompt_type": "vendor_extraction",
                "provider": provider,
                "image_data": image_url,
                "context": {},
                "output_schema": "vendor_info",
                "max_tokens": 1000,
                "temperature": 0.1
            }
            
            response = await self.client.post(
                f"{self.mcp_url}/ai/process",
                json=request_data
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
    
    async def analyze_object_photo(
        self,
        image_data: bytes,
        filename: str,
        provider: str = "claude",
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Analyze an object photo for inventory valuation
        
        Args:
            image_data: Raw image bytes
            filename: Original filename for format detection
            provider: AI provider to use (claude, openai, llm_studio)
            context: Additional context (user description, condition notes, etc.)
            
        Returns:
            Object analysis with valuation data
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
            # Use object categorization with enhanced context for valuation
            request_data = {
                "prompt_type": "object_categorization",
                "provider": provider,
                "image_data": image_url,
                "context": context or {},
                "output_schema": "object_analysis",
                "max_tokens": 1000,
                "temperature": 0.1
            }
            
            response = await self.client.post(
                f"{self.mcp_url}/ai/process",
                json=request_data
            )
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Object photo analyzed successfully with {provider}")
            return result
            
        except Exception as e:
            logger.error(f"Object photo analysis failed: {e}")
            raise

    async def _get_object_types_context(self) -> Dict[str, Any]:
        """Get existing object types for AI context from API with sensible defaults as fallback"""
        try:
            # Try to get object types from our API
            api_base = self.mcp_url.replace(':8080', ':5000')  # Convert MCP server URL to Flask app URL
            response = await self.client.get(f"{api_base}/api/object-types")
            
            if response.status_code == 200:
                api_result = response.json()
                if api_result.get('success'):
                    logger.debug("Retrieved object types from API")
                    return api_result['object_types']
            
            # Fall back to defaults (helps bootstrap new installations)
            logger.debug("Using default object types (API unavailable or returned no data)")
            return self._get_default_object_types()
            
        except Exception as e:
            logger.warning(f"Could not get object types from API: {e}, using defaults")
            return self._get_default_object_types()
    
    def _get_default_object_types(self) -> Dict[str, Any]:
        """Default object types for bootstrapping new installations"""
        return {
            'asset': {
                'name': 'asset', 
                'description': 'Durable goods that retain value over time (computers, furniture, equipment)',
                'examples': ['laptop', 'desk', 'printer', 'car', 'machinery']
            },
            'consumable': {
                'name': 'consumable', 
                'description': 'Items that are used up or consumed (food, supplies, tickets)',
                'examples': ['office supplies', 'food', 'event tickets', 'fuel', 'medication']
            },
            'component': {
                'name': 'component', 
                'description': 'Parts that belong to a larger asset (RAM, tires, replacement parts)',
                'examples': ['computer RAM', 'car tires', 'printer cartridge', 'phone battery']
            },
            'service': {
                'name': 'service', 
                'description': 'Intangible services or subscriptions (software licenses, maintenance)',
                'examples': ['software subscription', 'maintenance contract', 'consulting', 'utilities']
            },
            'software': {
                'name': 'software', 
                'description': 'Software applications and digital products',
                'examples': ['Microsoft Office', 'Adobe Creative Suite', 'operating system', 'mobile app']
            },
            'person': {
                'name': 'person', 
                'description': 'People identified in receipts or transactions (customers, staff, contacts)',
                'examples': ['customer', 'staff member', 'vendor contact', 'service technician']
            },
            'pet': {
                'name': 'pet', 
                'description': 'Pet animals and their information',
                'examples': ['dog', 'cat', 'bird', 'fish']
            }
        }
    
    async def _get_categories_context(self) -> Dict[str, Any]:
        """Get existing categories for AI context from API with sensible defaults as fallback"""
        try:
            # Try to get categories from our API
            api_base = self.mcp_url.replace(':8080', ':5000')  # Convert MCP server URL to Flask app URL
            response = await self.client.get(f"{api_base}/api/categories")
            
            if response.status_code == 200:
                api_result = response.json()
                if api_result.get('success'):
                    # Convert API format to simplified format for AI context
                    categories_by_type = api_result.get('categories_by_type', {})
                    
                    # Simplify to just lists of category names
                    simplified_categories = {}
                    for obj_type, categories in categories_by_type.items():
                        simplified_categories[obj_type] = [cat['name'] for cat in categories]
                    
                    # Add common new suggestions for AI to consider
                    simplified_categories['common_new_suggestions'] = [
                        'Entertainment', 'Travel', 'Health', 'Education', 'Sports', 'Hobby',
                        'Automotive', 'Home Improvement', 'Security', 'Communication'
                    ]
                    
                    logger.debug(f"Retrieved {api_result.get('total_categories', 0)} categories from API")
                    return simplified_categories
            
            # Fall back to defaults (helps bootstrap new installations)
            logger.debug("Using default categories (API unavailable or returned no data)")
            return self._get_default_categories()
            
        except Exception as e:
            logger.warning(f"Could not get categories from API: {e}, using defaults")
            return self._get_default_categories()
    
    def _get_default_categories(self) -> Dict[str, Any]:
        """Default categories for bootstrapping new installations"""
        return {
            'asset': [
                'Electronics', 'Furniture', 'Equipment', 'Vehicles', 'Appliances',
                'Tools', 'Infrastructure', 'Art', 'Office Equipment'
            ],
            'consumable': [
                'Office Supplies', 'Cleaning Supplies', 'Food', 'Drinks', 'Medical Supplies',
                'Packaging', 'Paper Products', 'Kitchen Supplies', 'Parts', 'Event Tickets'
            ],
            'component': [
                'Computer Components', 'Mechanical Parts', 'Electrical Components', 
                'Structural Components', 'Electronic Modules', 'Hardware'
            ],
            'service': [
                'Subscription', 'Maintenance', 'Consulting', 'Utilities', 'Internet',
                'Cloud Services', 'Professional Services', 'Communication'
            ],
            'software': [
                'Operating Systems', 'Applications', 'Development Tools', 'Security', 
                'Productivity', 'Creative', 'Enterprise', 'Games', 'Utilities'
            ],
            'person': [
                'Customer', 'Staff', 'Vendor Contact', 'Service Provider', 'Attendee',
                'Business Contact', 'Professional'
            ],
            'pet': [
                'Dog', 'Cat', 'Bird', 'Fish', 'Reptile', 'Small Animal'
            ],
            'common_new_suggestions': [
                'Entertainment', 'Travel', 'Health', 'Education', 'Sports', 'Hobby',
                'Automotive', 'Home Improvement', 'Security', 'Communication'
            ]
        }
    
    def _extract_basic_vendor_from_filename(self, filename: str) -> str:
        """Extract a basic vendor name from the filename using pattern matching"""
        # Remove file extension and clean filename
        base_name = filename.lower().replace('_', ' ').replace('-', ' ')
        if '.' in base_name:
            base_name = base_name.split('.')[0]
        
        # Common vendor patterns
        vendor_patterns = {
            'walmart': 'Walmart',
            'amazon': 'Amazon',
            'target': 'Target',
            'costco': 'Costco',
            'home depot': 'Home Depot',
            'lowes': "Lowe's",
            'best buy': 'Best Buy',
            'apple': 'Apple',
            'microsoft': 'Microsoft',
            'google': 'Google',
            'starbucks': 'Starbucks',
            'mcdonalds': "McDonald's",
            'gas station': 'Gas Station',
            'grocery': 'Grocery Store',
            'restaurant': 'Restaurant',
            'hotel': 'Hotel',
            'blue heron': 'Blue Heron',
            'festival': 'Event Vendor',
            'music': 'Music Venue'
        }
        
        # Try to match patterns
        for pattern, vendor in vendor_patterns.items():
            if pattern in base_name:
                return vendor
        
        # Extract first meaningful word if no pattern matches
        words = base_name.split()
        meaningful_words = [w for w in words if len(w) > 2 and w not in ['receipt', 'img', 'scan', 'photo']]
        
        if meaningful_words:
            return meaningful_words[0].title()
        
        return "Unknown"

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

async def analyze_object_photo_async(
    image_data: bytes,
    filename: str,
    provider: str = "claude",
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Async wrapper for object photo analysis"""
    async with MCPClient() as client:
        return await client.analyze_object_photo(image_data, filename, provider, context)

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

def analyze_object_photo_sync(
    image_data: bytes,
    filename: str,
    provider: str = "claude",
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Synchronous wrapper for object photo analysis"""
    return run_async_in_thread(
        analyze_object_photo_async(image_data, filename, provider, context)
    )

async def analyze_vendor_organization_async(
    vendor_name: str,
    analysis_data: Dict[str, Any],
    provider: str = "claude"
) -> Dict[str, Any]:
    """Async wrapper for vendor organization analysis"""
    async with MCPClient() as client:
        return await client.process_ai_request(
            prompt_type="vendor_organization_analysis",
            context={
                "vendor_name": vendor_name,
                "analysis_data": analysis_data
            },
            provider=provider,
            output_schema="organization_details",
            max_tokens=1500,
            temperature=0.1
        )

def analyze_vendor_organization_sync(
    vendor_name: str,
    analysis_data: Dict[str, Any],
    provider: str = "claude"
) -> Dict[str, Any]:
    """
    Synchronous wrapper for vendor organization analysis
    
    Analyzes vendor data to suggest organizational details like:
    - Business type
    - Contact information
    - Industry classification
    - Business size estimation
    - Relationship type
    
    Args:
        vendor_name: Name of the vendor to analyze
        analysis_data: Receipt and transaction data for analysis
        provider: AI provider to use
        
    Returns:
        Organization analysis with suggestions and confidence scores
    """
    try:
        return run_async_in_thread(
            analyze_vendor_organization_async(vendor_name, analysis_data, provider)
        )
    except Exception as e:
        logger.warning(f"MCP vendor analysis failed for {vendor_name}: {str(e)}")
        
        # Fallback to mock analysis based on vendor name patterns
        business_type = "Unknown"
        confidence = 0.3
        
        # Simple pattern matching for common vendor types
        vendor_lower = vendor_name.lower()
        if any(keyword in vendor_lower for keyword in ['eventeny', 'ticketmaster', 'eventbrite']):
            business_type = "Event Ticketing Platform"
            confidence = 0.8
        elif any(keyword in vendor_lower for keyword in ['amazon', 'walmart', 'target']):
            business_type = "Retail"
            confidence = 0.9
        elif any(keyword in vendor_lower for keyword in ['restaurant', 'cafe', 'pizza', 'burger']):
            business_type = "Food Service"
            confidence = 0.7
        elif any(keyword in vendor_lower for keyword in ['gas', 'fuel', 'shell', 'exxon']):
            business_type = "Gas Station"
            confidence = 0.8
        elif any(keyword in vendor_lower for keyword in ['hotel', 'inn', 'resort']):
            business_type = "Hospitality"
            confidence = 0.7
        
        # Return mock analysis
        return {
            'content': {
                'response': json.dumps({
                    'suggested_business_type': business_type,
                    'confidence': confidence,
                    'ai_available': False,
                    'analysis_method': 'pattern_matching_fallback',
                    'suggested_industry': business_type,
                    'estimated_size': 'Unknown',
                    'ai_analysis_notes': f'Fallback analysis based on vendor name patterns. MCP server unavailable.',
                    'suggested_email': None,
                    'suggested_phone': None,
                    'suggested_website': None,
                    'suggested_address': None
                })
            },
            'provider': 'fallback',
            'confidence': confidence,
            'processing_time': 0.1,
            'timestamp': '2025-05-24T22:30:00.000000',
            'tokens_used': 0,
            'cost_estimate': 0.0
        } 