"""
Prompt Manager for MCP Server
Handles loading, rendering, and managing AI prompt templates
"""

import os
import asyncio
import aiofiles
import yaml
from typing import Dict, Any, List, Optional
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, TemplateNotFound
import structlog

from schemas import PromptTemplate

logger = structlog.get_logger()

class PromptManager:
    """Manages AI prompt templates with Jinja2 templating"""
    
    def __init__(self, prompts_dir: str = "/app/prompts"):
        self.prompts_dir = Path(prompts_dir)
        self.templates_dir = self.prompts_dir / "templates"
        self.jinja_env = None
        self.templates_cache = {}
        
    async def initialize(self):
        """Initialize the prompt manager"""
        # Create directories if they don't exist
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize Jinja2 environment
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True
        )
        
        # Load default templates if they don't exist
        await self._create_default_templates()
        
        # Load all templates into cache
        await self._load_templates()
        
        logger.info(f"Prompt manager initialized with {len(self.templates_cache)} templates")
    
    async def _create_default_templates(self):
        """Create default prompt templates if they don't exist"""
        default_templates = {
            "receipt_analysis": {
                "content": """You are an expert at analyzing receipts and extracting comprehensive structured data for inventory and relationship management. 

Analyze the provided receipt image and extract ALL relevant information systematically:

## CRITICAL: TOTAL AMOUNT DETECTION (HIGHEST PRIORITY)
⚠️ **FINDING THE TOTAL AMOUNT IS ABSOLUTELY CRITICAL** ⚠️

Use EVERY possible strategy to find the total amount paid:

### PRIMARY STRATEGIES:
1. **Scan for total keywords** (case-insensitive):
   - "Total", "TOTAL", "Total Amount", "Grand Total", "Final Total"
   - "Amount Due", "AMOUNT DUE", "Balance Due", "Amount Owed"
   - "Total Cost", "Total Price", "Sum", "Final Amount"
   - "Pay Amount", "Payment Amount", "Charge Amount"

2. **Look for currency symbols** with large numbers:
   - $ followed by the largest monetary amount on the document
   - Look for bold, highlighted, or emphasized monetary amounts
   - Check for amounts in boxes or special formatting

3. **Multi-page document handling**:
   - If this appears to be a multi-page document, scan ALL pages
   - Email receipts often have totals at the bottom of the email body
   - Look for summary sections, final calculation areas
   - Check footers and bottom sections of each page

4. **Mathematical validation**:
   - If you find line items, sum them up as a backup
   - Add subtotal + tax + fees + tips to verify totals
   - Use the largest reasonable monetary amount if unclear

5. **Context clues**:
   - For email receipts: Look for "You paid", "Charged", "Transaction total"
   - For invoices: Look for "Amount Due", "Balance", "Pay This Amount"
   - For confirmations: Look for "Total Cost", "Order Total"

### FALLBACK STRATEGIES:
- If no explicit total found, sum all line items
- If no line items, use subtotal + tax + fees
- If multiple potential totals, use the largest reasonable amount
- **NEVER return None or empty for total_amount** - always provide a number

## BASIC RECEIPT INFORMATION (REQUIRED)
- vendor_name: The business name (look in headers, footers, stamps, logos, email senders)
- date: Transaction date in YYYY-MM-DD format (check multiple locations: top, bottom, line items, email headers)
- total_amount: **MUST ALWAYS BE A NUMBER** - use the strategies above

## FINANCIAL DETAILS
- subtotal: Amount before tax/fees
- tax_amount: Tax amount (sales tax, VAT, etc.)
- tip_amount: Tip or gratuity if present
- fees: Any additional fees (service charges, processing fees)
- receipt_number: Receipt/invoice/confirmation number
- payment_method: How payment was made (cash, card, etc.)

## DOCUMENT TYPE CLASSIFICATION
- due_date: Due date if this is a bill/invoice (YYYY-MM-DD format)
- is_bill: true if unpaid bill, false if paid receipt
- document_type: "receipt", "invoice", "bill", "ticket", "confirmation", "email_receipt", etc.

## COMPREHENSIVE LINE ITEM ANALYSIS
For EVERY item purchased, extract:
- description: Full item name/description
- quantity: Number of items (default 1.0 if not specified)
- unit_price: Price per unit
- total_price: Total price for this line item
- item_details: Any additional details (size, color, model, etc.)

## OBJECT CATEGORIZATION & CREATION
For each line item, determine:
- create_object: true/false - should this become an inventory object?
  **IMPORTANT: Be generous with object creation, especially for:**
  * Event tickets (ALWAYS create_object: true)
  * Service subscriptions and memberships
  * Software licenses and digital products
  * Any item with proof of purchase or reference numbers
  * Items that have ongoing value or need tracking
  
- object_type: Must be one of: "asset", "consumable", "component", "service", "software"
  * asset: Durable goods, equipment, vehicles, electronics
  * consumable: Items that get used up (food, tickets, supplies, fuel)
  * component: Parts of larger assets
  * service: Professional services, subscriptions, memberships, event tickets
  * software: Digital products, licenses, apps
  
- category: Suggest appropriate category name (e.g., "Event Tickets", "Office Supplies", "Electronics", "Food & Beverage")
  **For tickets/events: ALWAYS use "Event Tickets" category**
  
- expiration_info: For consumables, extract:
  * expiration_date: When item expires (YYYY-MM-DD)
  * event_date: For tickets/events (YYYY-MM-DD)
  * shelf_life_days: Expected useful life
  
- object_details: Additional object-specific information:
  * serial_numbers: Any serial/model numbers
  * specifications: Technical specs or features
  * warranty_info: Warranty details if mentioned

## PEOPLE & RELATIONSHIPS EXTRACTION
Look for and extract ANY people mentioned:
- customer_name: Name of the purchaser/customer
- staff_names: Employee names if visible
- event_attendees: Names on tickets or reservations
- contact_persons: Any listed contacts
For each person found:
- create_person_object: true
- person_name: Full name
- role: "customer", "staff", "attendee", "contact", etc.
- relationship_to_purchase: How they relate to this transaction

## DIGITAL ASSETS & ATTACHMENTS
Extract any digital references:
- qr_codes: Describe any QR codes present
- barcodes: Product barcodes or ticket codes
- urls: Any websites or links mentioned
- confirmation_codes: Booking/confirmation numbers
- ticket_numbers: Seat numbers, reference codes
- account_numbers: Customer account references

## EVENT & LOCATION DETAILS (if applicable)
- event_name: Name of event/service
- event_date: Date of event/service (YYYY-MM-DD)
- event_time: Time of event
- venue_location: Venue/location name and address
- seat_info: Seat numbers, sections, etc.

## VENDOR DETAILS ENHANCEMENT
- business_address: Full business address
- business_phone: Phone number
- business_email: Email address
- business_website: Website URL
- business_hours: Operating hours if shown
- business_type: Type of business (restaurant, retail, service, etc.)

## CONFIDENCE & QUALITY ASSESSMENT
- overall_confidence: Overall confidence (0.0-1.0) in extraction accuracy
- image_quality: Assessment of receipt image quality
- missing_information: List any information that might be missing or unclear
- extraction_notes: Any notable observations about the receipt

## SPECIAL HANDLING FOR EMAIL RECEIPTS
If this appears to be an email receipt or confirmation:
- Look for "Amount charged", "You paid", "Transaction total"
- Check email signature areas for business details
- Look for confirmation numbers in subject lines
- Scan the entire email body, not just attachment images

## CATEGORIZATION GUIDELINES
When suggesting categories:
- Be specific and descriptive (e.g., "Event Tickets" not just "Tickets")
- Use common business terminology
- Consider the context and industry
- For new categories, be confident - don't hesitate to create appropriate categories
- Examples: "Restaurant Meals", "Office Supplies", "Event Tickets", "Automotive Parts", "Home Improvement", "Technology Equipment", "Healthcare Services"

## OBJECT TYPE DECISION MATRIX
- **Consumable**: Food, drinks, tickets, fuel, office supplies, medications
- **Asset**: Electronics, furniture, vehicles, tools, equipment
- **Service**: Labor, consulting, subscriptions, maintenance
- **Component**: Parts, accessories, modules for existing assets
- **Software**: Applications, licenses, digital products

## CRITICAL REMINDERS:
1. **TOTAL AMOUNT MUST NEVER BE NULL OR EMPTY** - always provide a numeric value
2. **Scan the ENTIRE document** - totals can be anywhere
3. **Use multiple detection strategies** - don't stop at the first attempt
4. **For multi-page docs** - check every page for totals
5. **Be thorough** - this is for comprehensive inventory management

Return comprehensive structured data as valid JSON. Be absolutely certain you've found the total amount using every possible strategy.""",
                "description": "Comprehensively analyzes receipt images and extracts all relevant structured data with aggressive total amount detection for multi-page documents",
                "variables": [],
                "output_schema": "receipt_data"
            },
            
            "object_categorization": {
                "content": """You are an expert at categorizing, analyzing, and valuing physical objects for comprehensive inventory management.

{% if object %}
EXISTING OBJECT DETAILS:
{{ object | tojson(indent=2) }}
{% endif %}

{% if image_data %}
IMAGE ANALYSIS: Carefully analyze the provided image of this object.
{% endif %}

{% if user_description %}
USER DESCRIPTION: {{ user_description }}
{% endif %}

{% if estimated_age %}
USER ESTIMATED AGE: {{ estimated_age }}
{% endif %}

{% if condition_notes %}
USER CONDITION NOTES: {{ condition_notes }}
{% endif %}

{% if purchase_info %}
USER PURCHASE INFO: {{ purchase_info }}
{% endif %}

{% if analysis_purpose == 'inventory_valuation' %}
PURPOSE: This analysis is for insurance documentation and physical inventory valuation.
{% endif %}

Provide comprehensive object analysis and valuation:

## OBJECT IDENTIFICATION
- object_name: Clear, descriptive name for the object
- description: Detailed description of what this object is
- brand_model: Brand and model if identifiable
- serial_numbers: Any visible serial numbers, model numbers, or product codes

## CATEGORIZATION
- object_type: One of "asset", "consumable", "component", "service", "software"
  * asset: Durable goods, equipment, vehicles, electronics, furniture, tools
  * consumable: Items that get used up (office supplies, consumables)
  * component: Parts of larger assets
  * service: Service agreements, warranties
  * software: Digital products, licenses
- category: Specific category (e.g., "Electronics", "Furniture", "Tools", "Appliances", "Jewelry", "Artwork")

## COMPREHENSIVE VALUATION
- estimated_current_value: Current market value in USD (be realistic and conservative)
- value_confidence: Confidence in valuation (0.0-1.0)
- condition_assessment: "Excellent", "Very Good", "Good", "Fair", "Poor"
- depreciation_factors: What affects value (age, wear, market demand, etc.)
- market_trend: "Appreciating", "Stable", "Depreciating"
- replacement_cost: Cost to replace with equivalent new item

## CONDITION & AGE ASSESSMENT
- estimated_age_years: Estimated age in years
- wear_indicators: Visible signs of wear or damage
- maintenance_needs: Any obvious maintenance requirements
- useful_life_remaining: Estimated remaining useful life

## DETAILED SPECIFICATIONS
- specifications: Technical specifications, features, capabilities
- materials: What the object is made of (metal, plastic, wood, etc.)
- dimensions: Approximate size/dimensions if determinable
- weight_estimate: Estimated weight

## INSURANCE & DOCUMENTATION
- insurance_category: Appropriate insurance classification
- special_considerations: Fragility, security needs, environmental requirements
- documentation_notes: Important details for insurance claims
- replacement_difficulty: How easy/hard to replace (Common, Moderate, Difficult, Rare)

## MARKET ANALYSIS
- demand_level: "High", "Medium", "Low"
- liquidity: How easily it could be sold
- comparable_items: Similar items for value reference
- selling_venues: Where this could typically be sold

## RECOMMENDATIONS
- disposition_recommendation: "Keep", "Sell", "Donate", "Dispose", "Repair"
- maintenance_priority: "High", "Medium", "Low"
- insurance_recommendation: Whether to specifically insure this item
- storage_recommendations: Optimal storage conditions

## CONFIDENCE ASSESSMENT
- confidence: Overall confidence (0.0-1.0) in this analysis
- uncertainty_factors: What could affect accuracy of assessment
- additional_info_needed: What additional information would improve analysis

## VALUATION METHODOLOGY
Explain your valuation approach:
- Market research basis (retail, used market, auction values)
- Condition adjustments applied
- Age/depreciation factors considered
- Any special value considerations (vintage, collectible, etc.)

Consider factors like:
- Current condition and visible wear
- Age and expected depreciation
- Market demand and availability
- Brand reputation and quality
- Original purchase price estimates
- Replacement cost in current market
- Any special features or rarity

Be conservative but realistic in valuations. For insurance purposes, err on the side of documented market values rather than optimistic estimates.

Return structured analysis as valid JSON matching the object_analysis schema.""",
                "description": "Comprehensively categorizes, analyzes, and values objects for inventory management and insurance documentation",
                "variables": ["object", "image_data", "user_description", "estimated_age", "condition_notes", "purchase_info", "analysis_purpose"],
                "output_schema": "object_analysis"
            },
            
            "vendor_extraction": {
                "content": """You are an expert at extracting vendor/business information from documents and images.

Analyze the provided image and extract vendor information:

VENDOR DETAILS:
- name: Business/vendor name
- address: Full business address
- phone: Phone number
- email: Email address
- website: Website URL
- business_type: Type of business (e.g., "Retail", "Restaurant", "Service Provider")

CONFIDENCE:
Provide a confidence score (0.0-1.0) for the extraction accuracy.

Look for information in:
- Business headers/letterheads
- Contact information sections
- Stamps or logos
- Receipt headers/footers

Return the data as valid JSON matching the vendor_info schema.""",
                "description": "Extracts vendor information from documents and images",
                "variables": [],
                "output_schema": "vendor_info"
            },
            
            "asset_evaluation": {
                "content": """You are an asset evaluation expert. Analyze the provided asset information and image (if available) to determine its current value and condition.

{% if object %}
ASSET DETAILS:
{{ object | tojson(indent=2) }}
{% endif %}

Provide a comprehensive asset evaluation:

VALUATION:
- current_value: Current market value
- depreciation_applied: Depreciation since acquisition
- condition_assessment: "Excellent", "Good", "Fair", "Poor"
- replacement_cost: Cost to replace with equivalent

MARKET ANALYSIS:
- market_trend: "Appreciating", "Stable", "Depreciating"
- demand_level: "High", "Medium", "Low"
- liquidity: How easily it could be sold

RECOMMENDATIONS:
- disposition_recommendation: "Keep", "Sell", "Donate", "Dispose"
- maintenance_priority: "High", "Medium", "Low"
- insurance_recommendation: Whether to insure and estimated coverage

CONFIDENCE:
Provide a confidence score (0.0-1.0) for your evaluation.

Return structured analysis as JSON.""",
                "description": "Evaluates assets for current value and condition",
                "variables": ["object"],
                "output_schema": "object_analysis"
            }
        }
        
        for template_name, template_data in default_templates.items():
            template_file = self.templates_dir / f"{template_name}.yaml"
            if not template_file.exists():
                template_obj = PromptTemplate(
                    name=template_name,
                    **template_data
                )
                await self._save_template_file(template_name, template_obj)
                logger.info(f"Created default template: {template_name}")
    
    async def _load_templates(self):
        """Load all templates from the templates directory"""
        self.templates_cache.clear()
        
        if not self.templates_dir.exists():
            return
            
        for template_file in self.templates_dir.glob("*.yaml"):
            try:
                template_name = template_file.stem
                template = await self._load_template_file(template_name)
                self.templates_cache[template_name] = template
                logger.debug(f"Loaded template: {template_name}")
            except Exception as e:
                logger.error(f"Error loading template {template_file}: {e}")
    
    async def _load_template_file(self, template_name: str) -> PromptTemplate:
        """Load a template from file"""
        template_file = self.templates_dir / f"{template_name}.yaml"
        
        async with aiofiles.open(template_file, 'r', encoding='utf-8') as f:
            content = await f.read()
            data = yaml.safe_load(content)
            return PromptTemplate(**data)
    
    async def _save_template_file(self, template_name: str, template: PromptTemplate):
        """Save a template to file"""
        template_file = self.templates_dir / f"{template_name}.yaml"
        
        # Convert to dict and format for YAML
        template_dict = template.dict()
        template_dict['created_at'] = template_dict['created_at'].isoformat()
        template_dict['updated_at'] = template_dict['updated_at'].isoformat()
        
        async with aiofiles.open(template_file, 'w', encoding='utf-8') as f:
            yaml_content = yaml.dump(template_dict, default_flow_style=False, sort_keys=False)
            await f.write(yaml_content)
    
    async def get_template(self, template_name: str) -> PromptTemplate:
        """Get a template by name"""
        if template_name not in self.templates_cache:
            # Try to load from file
            try:
                template = await self._load_template_file(template_name)
                self.templates_cache[template_name] = template
            except FileNotFoundError:
                raise FileNotFoundError(f"Template '{template_name}' not found")
        
        return self.templates_cache[template_name]
    
    async def list_templates(self) -> List[Dict[str, Any]]:
        """List all available templates"""
        templates = []
        for name, template in self.templates_cache.items():
            templates.append({
                "name": name,
                "description": template.description,
                "variables": template.variables,
                "output_schema": template.output_schema,
                "version": template.version,
                "updated_at": template.updated_at
            })
        return templates
    
    async def save_template(self, template_name: str, template: PromptTemplate):
        """Save or update a template"""
        await self._save_template_file(template_name, template)
        self.templates_cache[template_name] = template
        logger.info(f"Saved template: {template_name}")
    
    async def render_prompt(self, template: PromptTemplate, context: Dict[str, Any]) -> str:
        """Render a prompt template with the given context"""
        try:
            jinja_template = self.jinja_env.from_string(template.content)
            rendered = jinja_template.render(**context)
            
            logger.debug(
                "Rendered prompt template",
                template_name=template.name,
                context_keys=list(context.keys()),
                rendered_length=len(rendered)
            )
            
            return rendered.strip()
            
        except Exception as e:
            logger.error(f"Error rendering template {template.name}: {e}")
            raise
    
    async def validate_template(self, template: PromptTemplate) -> Dict[str, Any]:
        """Validate a template and return validation results"""
        issues = []
        warnings = []
        
        # Check for required fields
        if not template.content.strip():
            issues.append("Template content is empty")
        
        if not template.description.strip():
            warnings.append("Template description is empty")
        
        # Check Jinja2 syntax
        try:
            self.jinja_env.from_string(template.content)
        except Exception as e:
            issues.append(f"Jinja2 syntax error: {e}")
        
        # Check for undefined variables in template
        try:
            # Parse the template to find undefined variables
            parsed = self.jinja_env.parse(template.content)
            used_vars = set()
            for node in parsed.find_all():
                if hasattr(node, 'name'):
                    used_vars.add(node.name)
            
            # Check if declared variables match used variables
            declared_vars = set(template.variables)
            undefined_vars = used_vars - declared_vars - {'image_data'}  # image_data is implicit
            if undefined_vars:
                warnings.append(f"Undeclared variables used: {list(undefined_vars)}")
            
            unused_vars = declared_vars - used_vars
            if unused_vars:
                warnings.append(f"Declared but unused variables: {list(unused_vars)}")
                
        except Exception as e:
            warnings.append(f"Could not analyze template variables: {e}")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings
        }
    
    async def reload_templates(self):
        """Reload all templates from disk"""
        await self._load_templates()
        logger.info("Reloaded all templates") 