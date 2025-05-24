"""OpenAI API utilities for enhanced image recognition and analysis."""
import base64
import io
import json
import logging
import os
import tempfile
from datetime import datetime

import openai
from PIL import Image

# Configure logging
logger = logging.getLogger(__name__)

# Initialize OpenAI client
openai_api_key = os.environ.get('OPENAI_API_KEY')
openai_client = openai.OpenAI(api_key=openai_api_key)

# The newest OpenAI model is "gpt-4o" which was released May 13, 2024.
# do not change this unless explicitly requested by the user
DEFAULT_MODEL = "gpt-4o"
DEFAULT_VISION_MODEL = "gpt-4o"

# Default retry configuration
MAX_RETRIES = 2
RETRY_DELAY = 2  # seconds

def check_openai_api_connection():
    """
    Test OpenAI API connection to verify API keys are working
    
    Returns:
        dict: Result with success status and error details if any
    """
    import os
    import logging
    from log_utils import get_logger
    from openai import OpenAI, OpenAIError, AuthenticationError, RateLimitError
    
    logger = get_logger(__name__)
    logger.debug("Testing OpenAI API connection")
    
    # Get API key from environment
    api_key = os.environ.get("OPENAI_API_KEY")
    
    # Check if API key exists
    if not api_key:
        logger.warning("No OpenAI API key found in environment variables")
        return {
            "success": False,
            "error_type": "authentication",
            "message": "Missing OpenAI API key"
        }
    
    try:
        # Create a client with the API key
        client = OpenAI(api_key=api_key)
        
        # Make a minimal API call to test the connection
        # This creates a very short completion that won't use much of your quota
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            max_tokens=10,
            messages=[
                {"role": "user", "content": "Reply with OK to confirm the API connection is working."}
            ]
        )
        
        # If we get here, the API call was successful
        logger.info("OpenAI API connection test successful")
        return {
            "success": True,
            "message": "API connection successful"
        }
        
    except AuthenticationError as auth_err:
        logger.error(f"OpenAI API authentication error: {str(auth_err)}")
        return {
            "success": False,
            "error_type": "authentication",
            "message": "Invalid OpenAI API key"
        }
    except RateLimitError as rate_err:
        logger.error(f"OpenAI API rate limit error: {str(rate_err)}")
        # Even though we hit a rate limit, the authentication was successful
        return {
            "success": True,
            "warning": "Rate limit reached, but authentication succeeded",
            "message": str(rate_err)
        }
    except Exception as e:
        logger.error(f"OpenAI API connection error: {str(e)}")
        return {
            "success": False,
            "error_type": "connection",
            "message": str(e)
        }

def process_receipt_with_openai(image_data, filename, auto_analyze=False, auto_link=False):
    """
    Process a receipt image with OpenAI to extract data and optionally analyze line items
    
    Args:
        image_data: Binary image data
        filename: Original filename
        auto_analyze: Whether to analyze line items and suggest objects
        auto_link: Whether to try linking line items to existing objects
        
    Returns:
        dict: Contains processed receipt data and analysis results
    """
    try:
        # Check if file is a PDF based on filename
        is_pdf = filename.lower().endswith('.pdf')
        
        # Process accordingly
        try:
            if is_pdf:
                logger.info(f"Processing PDF receipt: {filename}")
                try:
                    # Use the correct module for PDF conversion
                    from ocr_utils import convert_pdf_to_image
                    jpeg_data = convert_pdf_to_image(image_data)
                    logger.info(f"Successfully converted PDF to image for OpenAI API")
                except Exception as pdf_error:
                    logger.error(f"Error converting PDF to image: {str(pdf_error)}")
                    return {
                        "success": False,
                        "error": f"Unable to process PDF. Please ensure the PDF contains a valid receipt image. Error: {str(pdf_error)}"
                    }
            else:
                # Convert image to supported format (JPEG)
                image = Image.open(io.BytesIO(image_data))
                
                # Create a byte buffer to save the image in JPEG format
                jpeg_buffer = io.BytesIO()
                image.convert('RGB').save(jpeg_buffer, format='JPEG')
                
                # Get the converted image data
                jpeg_data = jpeg_buffer.getvalue()
                
                logger.info(f"Successfully converted image to JPEG for OpenAI API")
        except Exception as img_error:
            logger.error(f"Error converting receipt file format: {str(img_error)}")
            return {
                "success": False,
                "error": f"Unable to process file format. Please upload a valid image file (JPEG, PNG) or PDF. Error: {str(img_error)}"
            }
        
        # Extract basic receipt data first with retry logic
        attempt = 0
        last_error = None
        max_attempts = MAX_RETRIES + 1  # Include the first attempt
        
        while attempt < max_attempts:
            try:
                logger.info(f"Extracting receipt data with OpenAI (attempt {attempt+1}/{max_attempts})")
                receipt_data = extract_receipt_data_with_openai(jpeg_data)
                
                # Check if the API call had an error
                if receipt_data.get("error"):
                    error_type = receipt_data.get("error_type", "unknown")
                    error_details = receipt_data.get("error_details", "Unknown error")
                    
                    # For connection or rate limit errors, retry
                    if error_type in ["api_connection", "rate_limit"]:
                        logger.warning(f"API error during extraction (attempt {attempt+1}): {error_type} - {error_details}")
                        last_error = error_details
                        attempt += 1
                        
                        # Sleep before retrying
                        if attempt < max_attempts:
                            import time
                            time.sleep(RETRY_DELAY * attempt)  # Progressive backoff
                            continue
                        else:
                            # All attempts failed
                            logger.error(f"Failed to extract receipt data after {max_attempts} attempts")
                            return {
                                "success": False,
                                "error": f"Failed to connect to OpenAI API after multiple attempts. The service may be temporarily unavailable. Last error: {last_error}"
                            }
                    else:
                        # Other errors should not be retried
                        logger.error(f"Non-retriable error in receipt extraction: {error_type}")
                        break
                
                # Success - proceed with line item extraction if requested
                break
                
            except Exception as api_error:
                logger.warning(f"Error in API call (attempt {attempt+1}): {str(api_error)}")
                last_error = str(api_error)
                attempt += 1
                
                # Retry on network/API errors
                if attempt < max_attempts:
                    import time
                    time.sleep(RETRY_DELAY * attempt)
                else:
                    logger.error(f"Failed to process receipt after {max_attempts} attempts")
                    return {
                        "success": False,
                        "error": f"Failed to process receipt after multiple attempts. Last error: {last_error}"
                    }
        
        # If auto-analyze is enabled, analyze line items and create object suggestions
        if auto_analyze:
            try:
                logger.info("Analyzing line items...")
                # Line item analysis logic can be added here if needed
            except Exception as line_error:
                # Don't fail the whole receipt if line items fail
                logger.error(f"Error processing line items: {str(line_error)}")
                receipt_data["line_items"] = []
                receipt_data["line_item_error"] = str(line_error)
        
        # Add metadata
        receipt_data["source_filename"] = filename
        receipt_data["processed_at"] = datetime.now().isoformat()
        receipt_data["ai_model"] = "openai"
        
        return {
            "success": True,
            "receipt_data": receipt_data,
            "filename": filename
        }
        
    except Exception as e:
        logger.error(f"Error processing receipt with OpenAI: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

def extract_receipt_data_with_openai(image_data):
    """
    Extract data from receipt image binary data using OpenAI Vision API
    
    Args:
        image_data: Binary image data
        
    Returns:
        dict: Contains extracted receipt data (vendor, date, amount, description)
    """
    try:
        # Convert to base64
        image_base64 = base64.b64encode(image_data).decode("utf-8")
        
        # Create the prompt for receipt data extraction
        prompt = """
        Please analyze this receipt image and extract the following information:
        1. Vendor/Store name
        2. Date of purchase (in YYYY-MM-DD format)
        3. Total amount (just the number, without currency symbol)
        4. Receipt/invoice number (if present)
        5. Due date (if this is an unpaid invoice/bill, in YYYY-MM-DD format)
        6. A list of individual line items, each with:
           - description: Full item name/description
           - quantity: Quantity purchased (default to 1 if not specified)
           - unit_price: Price per single item
           - total_price: Total price for the line item (quantity * unit_price)

        Return the information in JSON format with these exact keys:
        {
          "vendor_name": "Store name",
          "date": "YYYY-MM-DD",
          "total_amount": 123.45,
          "receipt_number": "Receipt number if visible",
          "due_date": "YYYY-MM-DD if this is an unpaid bill, otherwise null",
          "line_items": [
            {
              "description": "Item 1 full name/description",
              "quantity": 1,
              "unit_price": 10.99,
              "total_price": 10.99
            },
            {
              "description": "Item 2 full name/description",
              "quantity": 2,
              "unit_price": 5.49,
              "total_price": 10.98
            }
          ]
        }
        If any top-level field (like receipt_number or due_date) is not found, omit the key or set it to null.
        If no line items are found, return an empty list for "line_items".
        Ensure all prices are numbers, not strings.
        """

        # Call OpenAI API with the image
        response = openai_client.chat.completions.create(
            model=DEFAULT_VISION_MODEL,
            messages=[
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
            response_format={"type": "json_object"},
            max_tokens=3000  # Increased max_tokens
        )

        # Extract the message content
        result_text = response.choices[0].message.content

        # Parse the JSON data
        data = json.loads(result_text)

        # ... existing error handling ...

        # --- Data Validation and Normalization ---
        # Ensure required keys exist, provide defaults if missing
        data["vendor_name"] = data.get("vendor_name")
        data["date"] = data.get("date")
        data["total_amount"] = data.get("total_amount")
        data["receipt_number"] = data.get("receipt_number")
        data["due_date"] = data.get("due_date")
        data["line_items"] = data.get("line_items", [])

        # Validate date format
        if data["date"]:
            try:
                # Try parsing YYYY-MM-DD first
                datetime.strptime(data["date"], "%Y-%m-%d")
            except ValueError:
                try:
                    # Try parsing M/D/YY or MM/DD/YY
                    parts = data["date"].split('/')
                    if len(parts) == 3:
                        month = parts[0].zfill(2)
                        day = parts[1].zfill(2)
                        year_part = parts[2]
                        if len(year_part) == 2:
                             year = f"20{year_part}" if int(year_part) < 70 else f"19{year_part}"
                        elif len(year_part) == 4:
                             year = year_part
                        else:
                             raise ValueError("Invalid year format")
                        data["date"] = f"{year}-{month}-{day}"
                        datetime.strptime(data["date"], "%Y-%m-%d")  # Final check
                    else:
                         raise ValueError("Date not in YYYY-MM-DD or M/D/YY format")
                except ValueError as date_err:
                    logger.warning(f"Invalid or unparseable date format detected: {data['date']}. Error: {date_err}. Setting to None.")
                    data["date"] = None  # Set to None if parsing fails
        
        # Validate amount
        if data["total_amount"] is not None:
            try:
                data["total_amount"] = float(str(data["total_amount"]).replace('$', '').replace(',', ''))
            except (ValueError, TypeError):
                logger.warning(f"Invalid amount format detected: {data['total_amount']}. Setting to 0.0")
                data["total_amount"] = 0.0
        else:
             data["total_amount"] = 0.0  # Default if missing

        # Determine if it's a bill
        data["is_bill"] = bool(data.get("due_date"))

        # Validate line items
        validated_line_items = []
        if isinstance(data["line_items"], list):
            for item in data["line_items"]:
                if not isinstance(item, dict): continue  # Skip non-dict items
                
                desc = item.get("description", "Unknown Item")
                qty = 1
                try:
                    qty = float(item.get("quantity", 1))
                except (ValueError, TypeError): pass
                
                unit_price = 0.0
                try:
                    unit_price = float(str(item.get("unit_price", 0.0)).replace('$', '').replace(',', ''))
                except (ValueError, TypeError): pass

                total_price = unit_price * qty  # Default calculation
                try:
                    # Use provided total if valid, otherwise use calculated
                    provided_total = item.get("total_price")
                    if provided_total is not None:
                         total_price = float(str(provided_total).replace('$', '').replace(',', ''))
                except (ValueError, TypeError): pass

                validated_line_items.append({
                    "description": desc,
                    "quantity": qty,
                    "unit_price": unit_price,
                    "total_price": total_price
                })
        data["line_items"] = validated_line_items
        # --- End Validation ---

        logger.info(f"Successfully extracted and validated receipt data with OpenAI: {data}")
        return data

    except Exception as e:
        logger.error(f"Error in receipt data extraction with OpenAI: {str(e)}")
        return {
            "vendor_name": None,
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "total_amount": 0.0,
            "description": None,
            "receipt_number": None,
            "due_date": None,
            "is_bill": False,
            "line_items": [],
            "error": str(e)
        }

def should_asset_be_serialized_openai(item_name, quantity, price=None, category=None, description=None):
    """
    Use OpenAI to determine if an asset should be serialized.
    
    Args:
        item_name: Name or title of the asset
        quantity: Quantity purchased
        price: Price of the item (optional)
        category: Category of the item (optional)
        description: Additional description of the item (optional)
        
    Returns:
        dict: Expert assessment of whether asset should be serialized
    """
    try:
        # Prepare the context
        prompt = f"""
        As an asset management expert, determine if this item should be serialized (tracked individually with unique serial numbers) 
        based on its characteristics:
        
        Item name: {item_name}
        Quantity: {quantity}
        """
        
        if price is not None:
            prompt += f"Price: ${price}\n"
            
        if category:
            prompt += f"Category: {category}\n"
            
        if description:
            prompt += f"Description: {description}\n"
            
        prompt += """
        Provide an expert assessment on whether this item should be tracked with individual serial numbers. 
        Items that typically need serial numbers include:
        - High-value equipment (computers, phones, TVs, etc.)
        - Items that need warranty tracking
        - Equipment subject to regulatory compliance
        - Items that may need service records
        - Unique or irreplaceable items
        
        Return your analysis as a JSON object with the following structure:
        {
            "should_serialize": true/false,
            "confidence": 0.0-1.0 (your confidence score),
            "reasoning": "Brief explanation of your decision"
        }
        """
        
        # Call OpenAI API for analysis
        response = openai_client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "You are an expert asset management advisor specialized in inventory tracking systems."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            max_tokens=500
        )
        
        # Extract the response text
        result_text = response.choices[0].message.content
        
        # Parse the JSON result
        result = json.loads(result_text)
        
        # Add metadata
        result["item_name"] = item_name
        result["quantity"] = quantity
        result["ai_model"] = "openai"
        
        logger.info(f"OpenAI serialization assessment for '{item_name}': {result['should_serialize']} (confidence: {result['confidence']})")
        return result
        
    except Exception as e:
        logger.error(f"Error in serialization assessment with OpenAI: {str(e)}")
        # Return a default response with error info
        return {
            "should_serialize": True if quantity == 1 else False,  # Default logic
            "confidence": 0.5,  # Low confidence due to error
            "reasoning": f"Error during assessment: {str(e)}. Defaulting to standard logic (serialize if quantity is 1).",
            "item_name": item_name,
            "quantity": quantity,
            "ai_model": "openai",
            "error": str(e)
        }

def categorize_item(description, object_type, amount=None, vendor=None):
    """
    Use OpenAI to suggest appropriate categories for an item based on its description and object type.
    
    Args:
        description: Description of the item
        object_type: Type of object (asset, consumable, component, service, software)
        amount: Amount/price of the item (optional)
        vendor: Vendor name (optional)
        
    Returns:
        dict: Contains suggested categories with confidence scores
    """
    try:
        # Prepare context information based on object type
        categories_by_type = {
            "asset": [
                "Electronics", "Furniture", "Appliances", "Vehicles", "Equipment", "Tools",
                "Infrastructure", "Art", "Office Equipment"
            ],
            "consumable": [
                "Office Supplies", "Cleaning Supplies", "Food", "Drinks", "Medical Supplies",
                "Packaging", "Paper Products", "Kitchen Supplies", "Parts"
            ],
            "component": [
                "Computer Components", "Mechanical Parts", "Electrical Components", 
                "Structural Components", "Electronic Modules", "Hardware"
            ],
            "service": [
                "Subscription", "Maintenance", "Consulting", "Utilities", "Internet",
                "Cloud Services", "Professional Services", "Communication"
            ],
            "software": [
                "Operating Systems", "Applications", "Development Tools", "Security", 
                "Productivity", "Creative", "Enterprise", "Games", "Utilities"
            ]
        }
        
        # Get sample categories for this object type
        sample_categories = categories_by_type.get(object_type.lower(), ["General"])
        sample_categories_text = ", ".join(sample_categories)
        
        # Build the prompt
        prompt = f"""
        Analyze this item and suggest appropriate categories for it as a {object_type}:
        
        Item Information:
        - Description: {description}
        {f"- Price: ${amount}" if amount else ""}
        {f"- Vendor: {vendor}" if vendor else ""}
        - Object Type: {object_type}
        
        Example categories for {object_type}s: {sample_categories_text}
        
        Please suggest up to 3 categories that would best fit this item, ordered by relevance.
        If none of the example categories fit, suggest new appropriate categories.
        For each category, include:
        1. Category name (be concise, 1-3 words)
        2. Brief description
        3. Suggested icon (FontAwesome icon name, e.g., fa-laptop)
        4. Confidence score (0.0-1.0)
        
        Return your suggestions as a JSON array with this structure:
        [
            {{
                "name": "Category Name",
                "description": "Brief category description",
                "icon": "fa-icon-name",
                "confidence": 0.95
            }},
            ...
        ]
        
        Only suggest categories that make logical sense for this {object_type}.
        """
        
        # Call OpenAI API
        response = openai_client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": f"You are an expert in inventory categorization, particularly for {object_type}s."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,  # Lower temperature for more consistent results
            response_format={"type": "json_object"}
        )
        
        # Parse the response
        result_text = response.choices[0].message.content
        result = json.loads(result_text)
        
        # Ensure we have the right format (array of categories)
        categories = []
        if isinstance(result, dict) and "categories" in result:
            # Some models might wrap results in a categories field
            categories = result["categories"]
        elif isinstance(result, list):
            # Direct list of categories
            categories = result
        else:
            # Try to find any array in the result
            for key, value in result.items():
                if isinstance(value, list) and len(value) > 0:
                    categories = value
                    break
        
        # Log the categories
        logger.info(f"Suggested categories for '{description}' ({object_type}): {[c.get('name') for c in categories]}")
        
        return {
            "success": True,
            "categories": categories,
            "object_type": object_type
        }
        
    except Exception as e:
        logger.error(f"Error suggesting categories: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "object_type": object_type
        }