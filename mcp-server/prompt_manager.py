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
                "content": """You are an expert at analyzing receipts and extracting structured data. 

Analyze the provided receipt image and extract the following information:

REQUIRED FIELDS:
- vendor_name: The business name
- date: Transaction date in YYYY-MM-DD format  
- total_amount: Total amount paid (numeric)

OPTIONAL FIELDS:
- subtotal: Subtotal before tax
- tax_amount: Tax amount
- receipt_number: Receipt/invoice number
- description: Brief description of purchase
- due_date: Due date if this is a bill (YYYY-MM-DD format)
- is_bill: true if this is an unpaid bill, false if it's a paid receipt

LINE ITEMS:
For each item purchased, extract:
- description: Item name/description
- quantity: Number of items (default 1.0)
- unit_price: Price per unit
- total_price: Total price for this line item
- category: Suggested category (e.g., "groceries", "electronics", "tools")
- suggested_object_type: "asset", "consumable", "component", or "service"

CONFIDENCE:
Provide a confidence score (0.0-1.0) for the overall extraction accuracy.

Return the data as valid JSON matching the receipt_data schema.""",
                "description": "Analyzes receipt images and extracts structured data",
                "variables": [],
                "output_schema": "receipt_data"
            },
            
            "object_categorization": {
                "content": """You are an expert at categorizing and analyzing physical objects for inventory management.

{% if object %}
OBJECT DETAILS:
{{ object | tojson(indent=2) }}
{% endif %}

{% if image_data %}
IMAGE: Analyze the provided image of this object.
{% endif %}

Analyze this object and provide the following categorization and analysis:

CATEGORIZATION:
- suggested_type: One of "asset", "consumable", "component", "person", "pet", "service", "software"
- suggested_categories: Array of relevant categories (e.g., ["Electronics", "Computing", "Office Equipment"])

VALUATION (if applicable):
- estimated_value: Current estimated value in USD
- useful_life_years: Expected useful life in years
- depreciation_rate: Annual depreciation rate (0.0-1.0)

SPECIFICATIONS:
- specifications: Object with technical specifications and details

MAINTENANCE:
- maintenance_schedule: Recommended maintenance schedule
- storage_requirements: Special storage requirements
- safety_considerations: Array of safety considerations

CONFIDENCE:
Provide a confidence score (0.0-1.0) for your analysis.

Consider factors like:
- Item condition and age
- Market value and depreciation
- Maintenance requirements
- Safety and storage needs

Return the data as valid JSON matching the object_analysis schema.""",
                "description": "Categorizes and analyzes objects for inventory management",
                "variables": ["object", "image_data"],
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