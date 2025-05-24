"""
LLM Studio utilities for local AI model integration.
This module provides functionality to connect with locally hosted LLM Studio models
for receipt processing, image analysis, and other AI tasks.
"""
import os
import base64
import logging
import json
import io
import requests
from PIL import Image
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

# Default configurations
DEFAULT_ENDPOINT = "http://localhost:8000/v1"
DEFAULT_TIMEOUT = 60  # seconds

def check_llm_studio_connection(api_endpoint=None):
    """
    Test the LLM Studio API connection to verify it's accessible.
    
    Args:
        api_endpoint: Optional custom endpoint URL
        
    Returns:
        dict: Contains success status and information about the connection
    """
    endpoint = api_endpoint or os.environ.get('LLM_STUDIO_ENDPOINT', DEFAULT_ENDPOINT)
    
    try:
        # Simple ping to check if the server is up
        response = requests.get(
            f"{endpoint}/health",
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info("LLM Studio API connection successful")
            return {
                "success": True,
                "message": "LLM Studio API connection is working properly",
                "endpoint": endpoint
            }
        else:
            logger.error(f"LLM Studio API error: {response.status_code}")
            return {
                "success": False,
                "error_type": "connection",
                "message": f"LLM Studio API returned status code {response.status_code}",
                "details": response.text
            }
    except requests.RequestException as e:
        logger.error(f"LLM Studio API connection error: {str(e)}")
        return {
            "success": False,
            "error_type": "connection",
            "message": "Unable to connect to LLM Studio API. Is the server running?",
            "details": str(e)
        }

def extract_receipt_data_with_llm_studio(image_data, api_endpoint=None):
    """
    Extract data from receipt image using local LLM Studio model
    
    Args:
        image_data: Binary image data
        api_endpoint: Custom API endpoint (optional)
        
    Returns:
        dict: Contains extracted receipt data (vendor, date, amount, description)
    """
    endpoint = api_endpoint or os.environ.get('LLM_STUDIO_ENDPOINT', DEFAULT_ENDPOINT)
    
    try:
        # Convert binary image to base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        # Prepare the prompt
        prompt = """
        You are an expert receipt analyzer. 
        Analyze this receipt image and extract the following information:
        - Vendor/store name
        - Date of purchase
        - Total amount
        - Receipt number or transaction ID (if visible)
        - The main items purchased (brief summary)
        
        Return the extracted data in JSON format with these fields:
        {
          "vendor": "Store name",
          "date": "YYYY-MM-DD",
          "amount": numeric value without currency symbol,
          "receipt_number": "receipt identifier",
          "items_summary": "brief description of main items",
          "confidence": 0.0-1.0 (your confidence in the extraction)
        }
        """
        
        # Create the API request payload
        payload = {
            "model": "default",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 1000,
            "temperature": 0.1,  # Low temperature for more deterministic output
            "response_format": {"type": "json_object"}
        }
        
        # Call the LLM Studio API
        response = requests.post(
            f"{endpoint}/chat/completions",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=DEFAULT_TIMEOUT
        )
        
        if response.status_code != 200:
            logger.error(f"LLM Studio API error: {response.status_code}")
            return {
                "success": False,
                "error": f"LLM Studio API returned status code {response.status_code}",
                "details": response.text
            }
        
        # Parse the response
        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        
        # Parse JSON from the content
        receipt_data = json.loads(content)
        
        # Format and validate data
        # Convert date to ISO format if possible
        if "date" in receipt_data and receipt_data["date"]:
            try:
                # Try to parse and standardize the date format
                date_str = receipt_data["date"]
                # Handle various formats here...
                # For now, we'll assume it's already in YYYY-MM-DD format
                receipt_data["date"] = date_str
            except Exception as date_err:
                logger.warning(f"Error standardizing date format: {str(date_err)}")
        
        # Ensure amount is numeric
        if "amount" in receipt_data and receipt_data["amount"]:
            try:
                # Convert to float and handle currency symbols
                amount_str = str(receipt_data["amount"])
                # Remove common currency symbols and commas
                amount_str = amount_str.replace('$', '').replace('£', '').replace('€', '').replace(',', '')
                receipt_data["amount"] = float(amount_str)
            except Exception as amount_err:
                logger.warning(f"Error converting amount to number: {str(amount_err)}")
        
        logger.info(f"Successfully extracted receipt data with LLM Studio")
        
        return {
            "success": True,
            "data": receipt_data,
            "model": "llm_studio_local"
        }
        
    except Exception as e:
        logger.error(f"Error extracting receipt data with LLM Studio: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

def extract_line_items_with_llm_studio(image_data, receipt_data=None, auto_link=False, api_endpoint=None):
    """
    Extract line items from receipt image using local LLM Studio model
    
    Args:
        image_data: Binary image data
        receipt_data: Basic receipt data already extracted (optional)
        auto_link: Whether to suggest linking to existing objects (optional)
        api_endpoint: Custom API endpoint (optional)
        
    Returns:
        list: Contains line item data with object suggestions
    """
    endpoint = api_endpoint or os.environ.get('LLM_STUDIO_ENDPOINT', DEFAULT_ENDPOINT)
    
    try:
        # Convert binary image to base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        # Create context from receipt_data if available
        context = ""
        if receipt_data and isinstance(receipt_data, dict):
            vendor = receipt_data.get('vendor', '')
            date = receipt_data.get('date', '')
            total = receipt_data.get('amount', '')
            if vendor or date or total:
                context = f"Based on the receipt from {vendor} dated {date} with total amount {total},"
        
        # Prepare the prompt
        prompt = f"""
        {context} analyze this receipt image and extract all individual line items.
        
        For each line item, identify:
        1. Item name/description
        2. Quantity
        3. Unit price (if available)
        4. Total price
        5. Category
        6. Suggest what type of object this would be (asset, consumable, component, service, software)
        
        Return the extracted data as a JSON array of objects, with each object containing:
        {{
            "description": "Item description",
            "quantity": number,
            "unit_price": number (if available),
            "total_price": number,
            "category": "Category name",
            "object_type": "asset" | "consumable" | "component" | "service" | "software",
            "confidence": 0.0-1.0 (your confidence in this line item extraction)
        }}
        
        Only include line items that are actual products or services purchased (not taxes, subtotals, etc).
        """
        
        # Create the API request payload
        payload = {
            "model": "default",
            "messages": [
                {
                    "role": "user", 
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 2000,
            "temperature": 0.1,  # Low temperature for more deterministic output
            "response_format": {"type": "json_object"}
        }
        
        # Call the LLM Studio API
        response = requests.post(
            f"{endpoint}/chat/completions",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=DEFAULT_TIMEOUT
        )
        
        if response.status_code != 200:
            logger.error(f"LLM Studio API error: {response.status_code}")
            return []
        
        # Parse the response
        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        
        # Parse JSON from the content
        parsed_result = json.loads(content)
        
        # Ensure we have a list
        line_items = []
        if isinstance(parsed_result, dict) and "line_items" in parsed_result:
            line_items = parsed_result["line_items"]
        elif isinstance(parsed_result, list):
            line_items = parsed_result
        else:
            # Try to find a list in the parsed_result if it's a dictionary
            for key in parsed_result:
                if isinstance(parsed_result[key], list):
                    line_items = parsed_result[key]
                    break
        
        # Add AI model information to each line item
        for item in line_items:
            if isinstance(item, dict):
                item["ai_model"] = "llm_studio_local"
                
                # Ensure numeric values are proper numbers
                for key in ["quantity", "unit_price", "total_price", "confidence"]:
                    if key in item and item[key] is not None:
                        try:
                            item[key] = float(item[key])
                        except (ValueError, TypeError):
                            pass
        
        logger.info(f"Successfully extracted {len(line_items)} line items using LLM Studio")
        return line_items
        
    except Exception as e:
        logger.error(f"Error extracting line items with LLM Studio: {str(e)}")
        return []

def analyze_asset_image_llm_studio(image_data, api_endpoint=None):
    """
    Analyze an image of an asset using local LLM Studio model
    
    Args:
        image_data: Binary image data
        api_endpoint: Custom API endpoint (optional)
        
    Returns:
        dict: Contains detailed asset information
    """
    endpoint = api_endpoint or os.environ.get('LLM_STUDIO_ENDPOINT', DEFAULT_ENDPOINT)
    
    try:
        # Convert binary image to base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        # Create the prompt
        prompt = """
        Analyze this image of a product or asset and extract as much detailed information as possible.
        
        Return a comprehensive JSON object with the following structure:
        
        {
            "name": "Full product name with model number",
            "manufacturer": "Brand/manufacturer name",
            "model": "Specific model identifier",
            "category": "Product category (Computer, Electronics, Office Equipment, Furniture, Vehicle, Software, Tool, or Other)",
            "upc": "Universal Product Code if visible",
            "serial_number": "Serial number if visible",
            "estimated_value": numeric value without currency symbol,
            "useful_life_years": numeric value,
            "description": "Detailed description of the product",
            "specifications": {
                "spec1": "value1",
                "spec2": "value2",
                "etc": "etc"
            },
            "confidence_scores": {
                "name": 0.0-1.0,
                "manufacturer": 0.0-1.0,
                "model": 0.0-1.0,
                "category": 0.0-1.0,
                "upc": 0.0-1.0,
                "serial_number": 0.0-1.0,
                "estimated_value": 0.0-1.0,
                "overall": 0.0-1.0
            }
        }
        
        If you cannot determine a field with confidence, include it with an empty value but provide a confidence score.
        For specifications, include all visible technical details such as processor, memory, storage, dimensions, etc.
        Do not use placeholder values. If you're unsure, set a lower confidence score instead.
        """
        
        # Create the API request payload
        payload = {
            "model": "default",
            "messages": [
                {
                    "role": "user", 
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 2000,
            "temperature": 0.1,  # Low temperature for more deterministic output
            "response_format": {"type": "json_object"}
        }
        
        # Call the LLM Studio API
        response = requests.post(
            f"{endpoint}/chat/completions",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=DEFAULT_TIMEOUT
        )
        
        if response.status_code != 200:
            logger.error(f"LLM Studio API error: {response.status_code}")
            return {
                "success": False,
                "error": f"LLM Studio API returned status code {response.status_code}",
                "details": response.text
            }
        
        # Parse the response
        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        
        # Parse JSON from the content
        asset_data = json.loads(content)
        
        logger.info(f"Successfully analyzed asset image with LLM Studio")
        
        return {
            "success": True,
            "data": asset_data
        }
        
    except Exception as e:
        logger.error(f"Error analyzing asset image with LLM Studio: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

def should_asset_be_serialized_llm_studio(item_name, quantity, price=None, category=None, description=None, api_endpoint=None):
    """
    Use LLM Studio to determine if an asset should be serialized.
    
    Args:
        item_name: Name or title of the asset
        quantity: Quantity purchased
        price: Price of the item (optional)
        category: Category of the item (optional)
        description: Additional description of the item (optional)
        api_endpoint: Custom API endpoint (optional)
        
    Returns:
        dict: Expert assessment of whether asset should be serialized
    """
    endpoint = api_endpoint or os.environ.get('LLM_STUDIO_ENDPOINT', DEFAULT_ENDPOINT)
    
    try:
        # Create strings for optional parameters
        price_str = f"Price: ${price:.2f}" if price else ""
        category_str = f"Category: {category}" if category else ""
        description_str = f"Description: {description}" if description else ""
        
        # Create the prompt
        prompt = f"""
        Evaluate whether the following item should have a unique serial number tracked in an asset management system:
        
        Item: {item_name}
        Quantity: {quantity}
        {price_str}
        {category_str}
        {description_str}
        
        Please analyze considering industry standards, value, warranty needs, and useful lifecycle.
        
        Return your assessment in JSON format with fields for should_be_serialized (boolean), 
        reasoning, confidence (0-1 score), and asset_type.
        """
        
        # Create the API request payload
        payload = {
            "model": "default",
            "messages": [
                {
                    "role": "system", 
                    "content": "You are an expert in asset management with specialized knowledge in equipment tracking and serialization."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            "max_tokens": 1000,
            "temperature": 0.1,  # Low temperature for more deterministic output
            "response_format": {"type": "json_object"}
        }
        
        # Call the LLM Studio API
        response = requests.post(
            f"{endpoint}/chat/completions",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30  # Shorter timeout for this simpler request
        )
        
        if response.status_code != 200:
            logger.error(f"LLM Studio API error: {response.status_code}")
            return {
                "success": False,
                "should_be_serialized": quantity == 1,  # Fallback logic
                "reasoning": f"API error with status code {response.status_code}. Using fallback: single items are more likely to be serialized.",
                "confidence": 0.5,
                "error": response.text
            }
        
        # Parse the response
        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        
        # Parse JSON from the content
        assessment = json.loads(content)
        
        logger.info(f"LLM Studio serialization assessment completed")
        
        return {
            "success": True,
            "should_be_serialized": assessment.get("should_be_serialized", False),
            "reasoning": assessment.get("reasoning", ""),
            "confidence": assessment.get("confidence", 0.5),
            "asset_type": assessment.get("asset_type", "Unknown")
        }
        
    except Exception as e:
        logger.error(f"Error in LLM Studio serialization assessment: {str(e)}")
        return {
            "success": False,
            "should_be_serialized": quantity == 1,  # Fallback logic
            "reasoning": "Error in assessment process. Using fallback logic: single items are more likely to be serialized.",
            "confidence": 0.5,
            "error": str(e)
        }

def process_receipt_with_llm_studio(image_data, filename, auto_analyze=False, auto_link=False, api_endpoint=None):
    """
    Process a receipt image with LLM Studio to extract data and optionally analyze line items
    
    Args:
        image_data: Binary image data
        filename: Original filename
        auto_analyze: Whether to analyze line items and suggest objects
        auto_link: Whether to try linking line items to existing objects
        api_endpoint: Custom API endpoint (optional)
        
    Returns:
        dict: Contains processed receipt data and analysis results
    """
    try:
        # Check if file is a PDF based on filename
        is_pdf = filename.lower().endswith('.pdf')
        
        if is_pdf:
            # Currently, LLM Studio does not support native PDF processing
            # We should use a different method or convert to image first
            # For simplicity, we'll return an error for now
            logger.error("PDF processing not supported with LLM Studio backend")
            return {
                "success": False,
                "error": "PDF processing is not supported with LLM Studio integration. Please use OpenAI or Claude for PDFs."
            }
        
        # Extract basic receipt data
        receipt_result = extract_receipt_data_with_llm_studio(image_data, api_endpoint)
        
        if not receipt_result["success"]:
            return receipt_result
        
        receipt_data = receipt_result["data"]
        
        # Add the original filename
        receipt_data["filename"] = filename
        
        # Add processing metadata
        receipt_data["processing_info"] = {
            "processed_at": datetime.utcnow().isoformat(),
            "provider": "llm_studio",
            "model": "local"
        }
        
        # If auto-analyze is enabled, extract line items as well
        line_items = []
        if auto_analyze:
            line_items = extract_line_items_with_llm_studio(
                image_data, 
                receipt_data,
                auto_link=auto_link,
                api_endpoint=api_endpoint
            )
        
        # Build and return the complete result
        return {
            "success": True,
            "receipt_data": receipt_data,
            "line_items": line_items,
            "provider": "llm_studio",
            "model": "local"
        }
        
    except Exception as e:
        logger.error(f"Error in LLM Studio receipt processing: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }