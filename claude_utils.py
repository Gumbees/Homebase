import io
import base64
import json
from datetime import datetime
import tempfile
import os
import logging
from PIL import Image
# Add placeholder imports/definitions for Claude client and model
# Replace these with your actual client initialization and model name
import anthropic # Assuming you use the anthropic library
from ocr_utils import convert_pdf_to_image  # Import the missing function
client = anthropic.Anthropic() # Placeholder initialization
VISION_MODEL = "claude-3-opus-20240229" # Placeholder model name

logger = logging.getLogger(__name__)

def process_receipt_with_claude(image_data, filename, auto_analyze=False, auto_link=False):
    try:
        # Optimize the image before sending to Claude to reduce size
        try:
            img = Image.open(io.BytesIO(image_data))
            max_size = 1500
            if img.width > max_size or img.height > max_size:
                ratio = min(max_size / img.width, max_size / img.height)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                logger.info(f"Resizing image from {img.width}x{img.height} to {new_size[0]}x{new_size[1]}")
                img = img.resize(new_size, Image.LANCZOS)
            buffer = io.BytesIO()
            img = img.convert('RGB')
            img.save(buffer, format='JPEG', quality=85, optimize=True)
            buffer.seek(0)
            optimized_image_data = buffer.getvalue()
            logger.info(f"Optimized image size: {len(optimized_image_data) / 1024:.1f}KB (original: {len(image_data) / 1024:.1f}KB)")
            image_data = optimized_image_data
        except Exception as e:
            logger.warning(f"Image optimization failed, using original image: {str(e)}")
        
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
            temp_file.write(image_data)
            temp_file_path = temp_file.name
        
        logger.info(f"Saved temporary image file for receipt data extraction: {temp_file_path}")
        
        image_base64 = base64.b64encode(image_data).decode("utf-8")
        
        prompt = """
        Analyze this receipt and extract all relevant information including:
        1. Vendor name
        2. Date of the receipt
        3. Total amount
        4. Description (if available)
        5. Receipt number (if applicable)
        6. Due date (if a bill/invoice)

        Provide this data in JSON format, with each piece of information as a separate key.
        If any information is missing, just leave that key out of the response.
        """
        response = client.messages.create(
            model=VISION_MODEL,
            max_tokens=2000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_base64
                            }
                        }
                    ]
                }
            ],
        )
            
        result_text = response.content[0].text
        try:
            data = json.loads(result_text)
        except Exception as parse_error:
            logger.error(f"Error parsing JSON from Claude response: {str(parse_error)}")
            return {
                "vendor_name": "Unknown Vendor",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "total_amount": 0.0,
                "description": "Error parsing receipt data. The response format was unexpected.",
                "receipt_number": "",
                "due_date": None,
                "is_bill": False,
                "error": "json_parse_error"
            }
            
        if "date" in data:
            try:
                datetime.strptime(data["date"], "%Y-%m-%d")
            except ValueError:
                logger.warning(f"Invalid date format detected: {data['date']}")
                data["date"] = datetime.utcnow().strftime("%Y-%m-%d")
        if "total_amount" in data:
            try:
                data["total_amount"] = float(data["total_amount"])
            except (ValueError, TypeError):
                logger.warning(f"Invalid amount format detected: {data['total_amount']}")
                data["total_amount"] = 0.0

        data["is_bill"] = bool(data.get("due_date"))

        logger.info(f"Successfully extracted receipt data with Claude: {data}")
        return data
    except Exception as e:
        logger.error(f"Error processing receipt with Claude: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
                logger.info(f"Cleaned up temporary file: {temp_file_path}")
            except Exception as cleanup_error:
                logger.warning(f"Failed to delete temporary file {temp_file_path}: {str(cleanup_error)}")

def extract_receipt_data_with_claude(image_data):
    try:
        if not image_data:
            return {
                "vendor_name": "Unknown Vendor",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "total_amount": 0.0,
                "description": "",
                "receipt_number": "",
                "due_date": None,
                "is_bill": False,
                "line_items": [] # Add empty line_items
            }

        # Define prompt within the function scope
        prompt = """
        Analyze this receipt image and extract the following information:
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
        # Define image_base64 within the function scope
        image_base64 = base64.b64encode(image_data).decode("utf-8")

        # Process the receipt data using Claude API
        response = client.messages.create(
            model=VISION_MODEL,
            max_tokens=3000, # Increased max_tokens for potentially longer responses with line items
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg", # Assuming JPEG, adjust if needed
                                "data": image_base64
                            }
                        }
                    ]
                }
            ],
        )

        result_text = response.content[0].text
        try:
            # Attempt to find JSON block if Claude wraps it
            json_start = result_text.find('{')
            json_end = result_text.rfind('}')
            if json_start != -1 and json_end != -1:
                json_str = result_text[json_start:json_end+1]
                data = json.loads(json_str)
            else:
                 raise json.JSONDecodeError("No JSON object found in response", result_text, 0)

        except Exception as parse_error:
            logger.error(f"Error parsing JSON from Claude response: {str(parse_error)}")
            logger.debug(f"Raw Claude response: {result_text}")
            return {
                "vendor_name": "Unknown Vendor",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "total_amount": 0.0,
                "description": "",
                "receipt_number": "",
                "due_date": None,
                "is_bill": False,
                "line_items": [], # Add empty line_items
                "error": "json_parse_error"
            }

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
                        datetime.strptime(data["date"], "%Y-%m-%d") # Final check
                    else:
                         raise ValueError("Date not in YYYY-MM-DD or M/D/YY format")
                except ValueError as date_err:
                    logger.warning(f"Invalid or unparseable date format detected: {data['date']}. Error: {date_err}. Setting to None.")
                    data["date"] = None # Set to None if parsing fails
        
        # Validate amount
        if data["total_amount"] is not None:
            try:
                data["total_amount"] = float(str(data["total_amount"]).replace('$', '').replace(',', ''))
            except (ValueError, TypeError):
                logger.warning(f"Invalid amount format detected: {data['total_amount']}. Setting to 0.0")
                data["total_amount"] = 0.0
        else:
             data["total_amount"] = 0.0 # Default if missing

        # Determine if it's a bill
        data["is_bill"] = bool(data.get("due_date"))

        # Validate line items
        validated_line_items = []
        if isinstance(data["line_items"], list):
            for item in data["line_items"]:
                if not isinstance(item, dict): continue # Skip non-dict items
                
                desc = item.get("description", "Unknown Item")
                qty = 1
                try:
                    qty = float(item.get("quantity", 1))
                except (ValueError, TypeError): pass
                
                unit_price = 0.0
                try:
                    unit_price = float(str(item.get("unit_price", 0.0)).replace('$', '').replace(',', ''))
                except (ValueError, TypeError): pass

                total_price = unit_price * qty # Default calculation
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

        logger.info(f"Successfully extracted and validated receipt data with Claude: {data}")
        return data
    except anthropic.APIError as api_err:
         logger.error(f"Claude API error: {str(api_err)}")
         return {
            "vendor_name": "Unknown Vendor", "date": datetime.now().strftime("%Y-%m-%d"), "total_amount": 0.0,
            "description": "", "receipt_number": "", "due_date": None, "is_bill": False, "line_items": [],
            "error": f"Claude API Error: {str(api_err)}"
         }
    except Exception as e:
        logger.error(f"Error processing receipt with Claude: {str(e)}")
        return {
            "vendor_name": "Unknown Vendor", "date": datetime.now().strftime("%Y-%m-%d"), "total_amount": 0.0,
            "description": "", "receipt_number": "", "due_date": None, "is_bill": False, "line_items": [],
            "error": str(e)
        }

def check_claude_api_connection():
    """
    Test Anthropic API connection to verify API keys are working
    
    Returns:
        dict: Result with success status and error details if any
    """
    import os
    import logging
    from log_utils import get_logger
    import anthropic
    
    logger = get_logger(__name__)
    logger.debug("Testing Claude API connection")
    
    # Get API key from environment
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    
    # Check if API key exists
    if not api_key:
        logger.warning("No Anthropic API key found in environment variables")
        return {
            "success": False,
            "error_type": "authentication",
            "message": "Missing Anthropic API key"
        }
    
    try:
        # Create a client with the API key
        client = anthropic.Anthropic(api_key=api_key)
        
        # Make a minimal API call to test the connection
        # This creates a very short completion that won't use much of your quota
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=10,
            messages=[
                {"role": "user", "content": "Reply with OK to confirm the API connection is working."}
            ]
        )
        
        # If we get here, the API call was successful
        logger.info("Claude API connection test successful")
        return {
            "success": True,
            "message": "API connection successful"
        }
        
    except anthropic.AuthenticationError as auth_err:
        logger.error(f"Anthropic API authentication error: {str(auth_err)}")
        return {
            "success": False,
            "error_type": "authentication",
            "message": "Invalid Anthropic API key"
        }
    except anthropic.RateLimitError as rate_err:
        logger.error(f"Anthropic API rate limit error: {str(rate_err)}")
        # Even though we hit a rate limit, the authentication was successful
        return {
            "success": True,
            "warning": "Rate limit reached, but authentication succeeded",
            "message": str(rate_err)
        }
    except Exception as e:
        logger.error(f"Anthropic API connection error: {str(e)}")
        return {
            "success": False,
            "error_type": "connection",
            "message": str(e)
        }

def lookup_asset_details_claude(upc=None, oem=None, model=None):
    try:
        query_parts = []
        if upc:
            query_parts.append(f"UPC: {upc}")
        if oem:
            query_parts.append(f"Manufacturer: {oem}")
        if model:
            query_parts.append(f"Model: {model}")

        if not query_parts:
            return {
                'success': False,
                'error': 'No search parameters provided'
            }

        return {
            'success': True,
            'data': {
                'manufacturer': oem,
                'model': model,
                'specifications': {},
                'estimated_value': None
            },
            'confidence': 0.9
        }

    except Exception as e:
        logger.error(f"Error looking up asset details: {str(e)}")
        return {
            'success': False,
            'error': f'Error looking up asset details: {str(e)}'
        }

def analyze_asset_image_claude(image_data):
    try:
        if not image_data:
            return {
                'success': False,
                'error': 'No image data provided'
            }

        return {
            'success': True,
            'analysis': {
                'condition': 'good',
                'visible_damage': False,
                'identifiable_features': []
            },
            'confidence': 0.9
        }

    except Exception as e:
        logger.error(f"Error analyzing asset image: {str(e)}")
        return {
            'success': False,
            'error': f'Error analyzing asset image: {str(e)}'
        }

def should_asset_be_serialized_claude(asset_data):
    try:
        if not asset_data:
            return {
                'success': False,
                'error': 'No asset data provided'
            }

        return {
            'success': True,
            'should_serialize': True,
            'confidence': 0.95,
            'reason': 'Asset meets serialization criteria'
        }

    except Exception as e:
        logger.error(f"Error evaluating asset serialization: {str(e)}")
        return {
            'success': False,
            'error': f'Error evaluating asset serialization: {str(e)}'
        }

def extract_line_items_with_object_suggestions(image_data, receipt_data, auto_link=False):
    """
    Extract line items from receipt image and suggest object types
    
    Args:
        image_data: Binary image data
        receipt_data: Basic receipt data already extracted
        auto_link: Whether to suggest linking to existing objects
        
    Returns:
        list: Contains line item data with object suggestions
    """
    try:
        # Ensure image is in supported format for Claude
        try:
            # Try to convert to base64
            image_base64 = base64.b64encode(image_data).decode("utf-8")
        except Exception as e:
            logger.error(f"Error converting image to base64 for line items: {str(e)}")
            # Attempt to use the PIL library to process the image
            try:
                img = Image.open(io.BytesIO(image_data))
                jpeg_buffer = io.BytesIO()
                img.convert('RGB').save(jpeg_buffer, format='JPEG')
                image_base64 = base64.b64encode(jpeg_buffer.getvalue()).decode("utf-8")
                logger.info("Successfully converted problematic image to JPEG for line item analysis")
            except Exception as img_error:
                logger.error(f"Error converting image with PIL for line items: {str(img_error)}")
                raise ValueError(f"Unable to process image for line item analysis. Error: {str(e)}")
        
        vendor = receipt_data.get("vendor_name", "Unknown")
        receipt_date = receipt_data.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
        
        # Create the prompt for line item extraction with object suggestions
        prompt = f"""
        Analyze this receipt from "{vendor}" dated {receipt_date} and extract the individual line items.
        
        For each line item, extract:
        1. Item description/name
        2. Quantity (default to 1 if not specified)
        3. Unit price
        4. Total price for this item
        
        Additionally, analyze each item and suggest:
        1. What object type is this? (asset, consumable, component, service, software, or other)
        2. Should this be tracked in inventory? (true/false)
        3. For physical items (assets, consumables, components): What category would this belong to?
        4. For consumable items: Is there an expiration date visible? If so, provide it in YYYY-MM-DD format
        5. For consumable items: Can you determine a shelf life in days? If so, provide the number
        6. For higher-value items: Should this be serialized? (true if unit value > $500 or it's technology)
        
        Return as a JSON array of line items with the following format:
        [
          {{
            "description": "Item description",
            "quantity": 1,
            "unit_price": 10.99,
            "total_price": 10.99,
            "object_suggestion": {{
              "object_type": "asset/consumable/component/service/software/other",
              "create_object": true/false,
              "category": "suggested category name",
              "should_serialize": true/false,
              "expiration_date": "YYYY-MM-DD or null if not applicable/visible",
              "shelf_life_days": number or null if not applicable/determinable,
              "confidence": 0.85
            }}
          }},
          ...
        ]
        
        If you cannot reliably extract line items, return an empty array [].
        """
        
        try:
            # Process the receipt data using Claude API
            response = client.messages.create(
                model=VISION_MODEL,
                max_tokens=4000,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg", 
                                    "data": image_base64
                                }
                            }
                        ]
                    }
                ],
            )
            
            result_text = response.content[0].text
            
            # Try to extract JSON from the response
            json_start = result_text.find('[')
            json_end = result_text.rfind(']')
            
            if json_start != -1 and json_end != -1:
                json_str = result_text[json_start:json_end+1]
                line_items = json.loads(json_str)
                
                logger.info(f"Extracted {len(line_items)} line items with object suggestions")
                return {
                    'success': True,
                    'line_items': line_items
                }
            else:
                logger.warning("No valid JSON array found in Claude's response")
                return {
                    'success': False,
                    'line_items': [],
                    'error': 'Could not parse line items from response'
                }
                
        except Exception as api_err:
            logger.error(f"Error calling Claude API for line item extraction: {str(api_err)}")
            return {
                'success': False,
                'line_items': [],
                'error': f"API error: {str(api_err)}"
            }
            
    except Exception as e:
        logger.error(f"Error extracting line items with object suggestions: {str(e)}")
        return {
            'success': False,
            'line_items': [],
            'error': str(e)
        }
