"""OCR utilities for receipt processing using OpenAI."""
import os
import base64
import logging
import json
import io
import tempfile
from datetime import datetime
from PIL import Image
from openai import OpenAI

# For PDF handling
import PyPDF2
try:
    import pdf2image
except ImportError:
    logger.warning("pdf2image not available, will use fallback PDF conversion")

# Configure logging
logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def convert_pdf_to_image(pdf_data):
    """
    Convert ALL pages of a PDF to a single concatenated image.
    This ensures multi-page documents (like email receipts) are fully analyzed.
    
    Args:
        pdf_data: Binary PDF data
        
    Returns:
        bytes: JPEG image data of all pages concatenated vertically
    """
    try:
        # Try with pdf2image first (better quality)
        if 'pdf2image' in globals():
            # Create a temporary file to store the PDF data
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_pdf:
                temp_pdf_path = temp_pdf.name
                temp_pdf.write(pdf_data)
            
            logger.info(f"Saved PDF to temporary file: {temp_pdf_path}")
            
            try:
                # Convert ALL pages of the PDF to images
                logger.info("Converting all pages of PDF to images for comprehensive analysis")
                images = pdf2image.convert_from_path(
                    temp_pdf_path, 
                    dpi=300  # Higher DPI for better quality
                )
                
                # Check if we got any images
                if not images or len(images) == 0:
                    raise ValueError("Could not convert PDF to image - no images returned")
                
                logger.info(f"Successfully converted {len(images)} pages from PDF")
                
                # If only one page, use it directly
                if len(images) == 1:
                    first_page = images[0]
                    
                    # Resize single page if it exceeds Claude's 8000 pixel limit
                    max_dimension = 8000
                    if first_page.width > max_dimension or first_page.height > max_dimension:
                        # Calculate scale factor to fit within limits
                        scale_factor = min(max_dimension / first_page.width, max_dimension / first_page.height)
                        new_width = int(first_page.width * scale_factor)
                        new_height = int(first_page.height * scale_factor)
                        
                        logger.info(f"Resizing single page from {first_page.width}x{first_page.height} to {new_width}x{new_height} for Claude compatibility")
                        first_page = first_page.resize((new_width, new_height), Image.Resampling.LANCZOS)
                else:
                    # Concatenate all pages vertically into one long image
                    logger.info(f"Concatenating {len(images)} pages into single image for analysis")
                    
                    # Calculate total height and max width
                    total_height = sum(img.height for img in images)
                    max_width = max(img.width for img in images)
                    
                    # Create new image with combined dimensions
                    combined_image = Image.new('RGB', (max_width, total_height), (255, 255, 255))
                    
                    # Paste each page
                    y_offset = 0
                    for img in images:
                        # Center each page if it's narrower than max_width
                        x_offset = (max_width - img.width) // 2 if img.width < max_width else 0
                        combined_image.paste(img, (x_offset, y_offset))
                        y_offset += img.height
                        
                        # Add a small gap between pages for clarity
                        if y_offset < total_height:  # Not the last page
                            # Draw a light gray line to separate pages
                            for x in range(max_width):
                                for gap_y in range(min(10, total_height - y_offset)):
                                    combined_image.putpixel((x, y_offset + gap_y), (240, 240, 240))
                            y_offset += min(10, total_height - y_offset)
                    
                    first_page = combined_image
                    logger.info(f"Created combined image: {max_width}x{total_height} pixels")
                
                # OpenAI can handle larger images, so no resizing needed
                logger.info(f"Using original image size: {first_page.width}x{first_page.height} pixels for OpenAI processing")
                
                # Save the image to a buffer in JPEG format
                buffer = io.BytesIO()
                first_page.save(buffer, format='JPEG', quality=95)  # High quality JPEG
                buffer.seek(0)
                
                # Get the image data
                image_data = buffer.getvalue()
                
                # Clean up the temporary file
                os.unlink(temp_pdf_path)
                
                logger.info(f"Successfully converted PDF ({len(images)} pages) to JPEG image using pdf2image")
                return image_data
                
            except Exception as e:
                # Clean up the temporary file
                os.unlink(temp_pdf_path)
                logger.error(f"Error converting PDF with pdf2image: {str(e)}")
                # Fall through to the fallback method
        
        # Fallback method with PyPDF2 and PIL
        logger.info("Falling back to PyPDF2 for PDF conversion")
        pdf_file = io.BytesIO(pdf_data)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        
        if len(pdf_reader.pages) == 0:
            raise ValueError("PDF has no pages")
        
        # Create a larger blank white image as a fallback for multi-page documents
        width, height = 2000, 2800 * max(1, len(pdf_reader.pages))  # Scale height by page count
        image = Image.new('RGB', (width, height), (255, 255, 255))
        
        # Add some text indicating this is a multi-page document
        if len(pdf_reader.pages) > 1:
            try:
                from PIL import ImageDraw, ImageFont
                draw = ImageDraw.Draw(image)
                # Try to use a default font
                try:
                    font = ImageFont.load_default()
                except:
                    font = None
                
                text = f"Multi-page PDF ({len(pdf_reader.pages)} pages) - Fallback conversion"
                if font:
                    draw.text((50, 50), text, fill=(100, 100, 100), font=font)
                else:
                    # Simple text without font
                    draw.text((50, 50), text, fill=(100, 100, 100))
                    
                logger.info(f"Created fallback image for {len(pdf_reader.pages)}-page PDF")
            except:
                pass  # If text drawing fails, just use blank image
        
        # Save the image to a buffer in JPEG format
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=90)
        buffer.seek(0)
        
        logger.info(f"Converted {len(pdf_reader.pages)}-page PDF to blank image with PyPDF2 fallback")
        return buffer.getvalue()
        
    except Exception as e:
        logger.error(f"All PDF conversion methods failed: {str(e)}")
        # Return a minimal blank image as a last resort
        img = Image.new('RGB', (800, 1200), (255, 255, 255))
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG')
        buffer.seek(0)
        return buffer.getvalue()

def process_receipt_with_ai(image_data, filename, auto_analyze=False, auto_link=False, use_claude=None):
    """
    Process a receipt image with AI to extract data and optionally analyze line items.
    Now uses OpenAI exclusively for better image processing capabilities.
    
    Args:
        image_data: Binary image data
        filename: Original filename
        auto_analyze: Whether to analyze line items and suggest objects
        auto_link: Whether to try linking line items to existing objects
        use_claude: Deprecated parameter - OpenAI is now used exclusively
        
    Returns:
        dict: Contains processed receipt data and analysis results
    """
    # Import OpenAI functions
    from openai_utils import process_receipt_with_openai
    
    logger.info(f"Processing receipt '{filename}' using OpenAI")
    
    # Always use OpenAI now
    return process_receipt_with_openai(image_data, filename, auto_analyze, auto_link)

def extract_receipt_data_from_binary(image_data):
    """
    Extract data from receipt image binary data using OpenAI Vision API
    
    Args:
        image_data: Binary image data
        
    Returns:
        dict: Contains extracted receipt data (vendor, date, amount, description)
    """
    try:
        # Ensure image is in supported format for OpenAI
        try:
            # Try to convert to base64
            base64_image = base64.b64encode(image_data).decode("utf-8")
        except Exception as e:
            logger.error(f"Error converting image to base64: {str(e)}")
            # Attempt to use the PIL library to process the image
            try:
                img = Image.open(io.BytesIO(image_data))
                jpeg_buffer = io.BytesIO()
                img.convert('RGB').save(jpeg_buffer, format='JPEG')
                base64_image = base64.b64encode(jpeg_buffer.getvalue()).decode("utf-8")
                logger.info("Successfully converted problematic image to JPEG")
            except Exception as img_error:
                logger.error(f"Error converting image with PIL: {str(img_error)}")
                raise ValueError(f"Unable to process image. Please ensure it's a valid image file. Error: {str(e)}")
        
        # Create the prompt for receipt data extraction
        prompt = """
        Please analyze this receipt image and extract the following information:
        1. Vendor/Store name
        2. Date of purchase (in YYYY-MM-DD format)
        3. Total amount (just the number, without currency symbol)
        4. List of items purchased or a brief description
        5. Receipt/invoice number (if present)
        6. Due date (if this is an unpaid invoice/bill, in YYYY-MM-DD format)
        
        Return the information in JSON format with these keys:
        {
          "vendor_name": "Store name",
          "date": "YYYY-MM-DD",
          "total_amount": 123.45,
          "description": "Brief description or list of items",
          "receipt_number": "Receipt number if visible",
          "due_date": "YYYY-MM-DD if this is an unpaid bill, otherwise null"
        }
        """
        
        try:
            # The newest OpenAI model is "gpt-4o" which was released May 13, 2024.
            response = client.chat.completions.create(
                model="gpt-4o",  # Current model with vision capabilities
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                            },
                        ],
                    }
                ],
                max_tokens=500,
                response_format={"type": "json_object"},
            )
            
            # Parse the response
            result = response.choices[0].message.content
            data = json.loads(result)
            
        except Exception as vision_error:
            # Log the error
            logger.warning(f"Error with vision model: {str(vision_error)}")
            
            # If it's a quota or rate error, use fallback
            if "429" in str(vision_error) or "exceeded your current quota" in str(vision_error):
                logger.info("API quota exceeded. Using fallback...")
                return handle_quota_exceeded(image_data)
            else:
                # For other errors, re-raise
                raise vision_error
        
        # Validate date format if present
        if "date" in data:
            try:
                # Try to parse the date to ensure it's valid
                datetime.strptime(data["date"], "%Y-%m-%d")
            except ValueError:
                # If the date is not in the correct format, try to fix it
                logger.warning(f"Invalid date format detected: {data['date']}")
                data["date"] = datetime.utcnow().strftime("%Y-%m-%d")
        
        # Validate amount if present
        if "total_amount" in data:
            try:
                # Ensure total_amount is a float
                data["total_amount"] = float(data["total_amount"])
            except (ValueError, TypeError):
                logger.warning(f"Invalid amount format detected: {data['total_amount']}")
                data["total_amount"] = 0.0
        
        # Determine if this is a bill (unpaid invoice) based on due date
        data["is_bill"] = bool(data.get("due_date"))
        
        logger.info(f"Successfully extracted receipt data: {data}")
        return data
        
    except Exception as e:
        logger.error(f"Error in receipt data extraction: {str(e)}")
        return {
            "vendor_name": None,
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "total_amount": 0.0,
            "description": None,
            "receipt_number": None,
            "due_date": None,
            "is_bill": False,
            "error": str(e)
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
        # Ensure image is in supported format for OpenAI
        try:
            # Try to convert to base64
            base64_image = base64.b64encode(image_data).decode("utf-8")
        except Exception as e:
            logger.error(f"Error converting image to base64 for line items: {str(e)}")
            # Attempt to use the PIL library to process the image
            try:
                img = Image.open(io.BytesIO(image_data))
                jpeg_buffer = io.BytesIO()
                img.convert('RGB').save(jpeg_buffer, format='JPEG')
                base64_image = base64.b64encode(jpeg_buffer.getvalue()).decode("utf-8")
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
            # The newest OpenAI model is "gpt-4o" which was released May 13, 2024.
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                            },
                        ],
                    }
                ],
                max_tokens=1000,
                response_format={"type": "json_object"},
            )
            
            # Parse the response
            result = json.loads(response.choices[0].message.content)
            
            # If result isn't already a list, check if there's a property that contains the array
            if not isinstance(result, list):
                for key in result:
                    if isinstance(result[key], list):
                        result = result[key]
                        break
            
            # If we still don't have a list, return an empty list
            if not isinstance(result, list):
                logger.warning("Line item extraction did not return a valid array")
                return []
            
            # TODO: If auto_link is enabled, check for similar objects in the database
            # and add suggested linking information
            
            logger.info(f"Successfully extracted {len(result)} line items with object suggestions")
            return result
            
        except Exception as api_error:
            logger.error(f"Error extracting line items: {str(api_error)}")
            return []
    
    except Exception as e:
        logger.error(f"Error processing line items: {str(e)}")
        return []

def extract_receipt_data(image_file):
    """
    Extract data from receipt image using OpenAI Vision API (legacy function)
    
    Args:
        image_file: File object from request.files
        
    Returns:
        dict: Contains extracted receipt data (vendor, date, amount, description)
    """
    try:
        # Read the image file
        image_data = image_file.read()
        
        # Ensure image is in a supported format
        try:
            # Try to open the image to verify it's valid
            img = Image.open(io.BytesIO(image_data))
            
            # Convert to JPEG to ensure compatibility
            jpeg_buffer = io.BytesIO()
            img.convert('RGB').save(jpeg_buffer, format='JPEG')
            
            # Get the converted image data
            jpeg_data = jpeg_buffer.getvalue()
            
            # Convert to base64
            base64_image = base64.b64encode(jpeg_data).decode("utf-8")
            logger.info("Successfully converted image to JPEG format for OCR processing")
        except Exception as img_error:
            logger.error(f"Error handling image format: {str(img_error)}")
            # Just try with the original format as fallback
            base64_image = base64.b64encode(image_data).decode("utf-8")
        
        # Reset the file pointer to the beginning for future operations
        image_file.seek(0)
        
        # Create the prompt for receipt data extraction
        prompt = """
        Please analyze this receipt image and extract the following information:
        1. Vendor/Store name
        2. Date of purchase (in YYYY-MM-DD format)
        3. Total amount (just the number, without currency symbol)
        4. List of items purchased or a brief description
        
        Return the information in JSON format with these keys:
        {
          "vendor": "Store name",
          "date": "YYYY-MM-DD",
          "total_amount": 123.45,
          "description": "Brief description or list of items"
        }
        """

        try:
            # Use the current model for vision capabilities (gpt-4o)
            try:
                # The newest OpenAI model is "gpt-4o" which was released May 13, 2024.
                response = client.chat.completions.create(
                    model="gpt-4o",  # Current model with vision capabilities
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                                },
                            ],
                        }
                    ],
                    max_tokens=500,
                    response_format={"type": "json_object"},
                )
                
                # Parse the response
                result = response.choices[0].message.content
                data = json.loads(result)
                
            except Exception as vision_error:
                # Log the error
                logger.warning(f"Error with vision model: {str(vision_error)}")
                
                # If it's a quota or rate error, use fallback
                if "429" in str(vision_error) or "exceeded your current quota" in str(vision_error):
                    logger.info("API quota exceeded. Using fallback...")
                    return handle_quota_exceeded(image_file)
                else:
                    # For other errors, re-raise
                    raise vision_error
            
        except Exception as api_error:
            # Log the API error
            logger.error(f"OpenAI API error: {str(api_error)}")
            
            # Use fallback for any API errors
            logger.warning("API error, using basic fallback.")
            return handle_quota_exceeded(image_file)
        
        # Validate date format if present
        if "date" in data:
            try:
                # Try to parse the date to ensure it's valid
                datetime.strptime(data["date"], "%Y-%m-%d")
            except ValueError:
                # If the date is not in the correct format, try to fix it
                logger.warning(f"Invalid date format detected: {data['date']}")
                data["date"] = None
        
        # Validate amount if present
        if "total_amount" in data:
            try:
                # Ensure total_amount is a float
                data["total_amount"] = float(data["total_amount"])
            except (ValueError, TypeError):
                logger.warning(f"Invalid amount format detected: {data['total_amount']}")
                data["total_amount"] = None
        
        logger.info(f"Successfully extracted receipt data: {data}")
        return data
        
    except Exception as e:
        logger.error(f"Error in OCR processing: {str(e)}")
        return {
            "vendor": None,
            "date": None,
            "total_amount": None,
            "description": None,
            "error": str(e)
        }

def extract_vendor_from_image(image_data):
    """
    Extract vendor information from a receipt image using OpenAI Vision API
    
    Args:
        image_data: Binary image data
        
    Returns:
        dict: Contains extracted vendor information
    """
    try:
        # Convert to base64
        base64_image = base64.b64encode(image_data).decode("utf-8")
        
        # Create the prompt specifically for vendor extraction
        prompt = """
        Please analyze this receipt image and focus ONLY on identifying the vendor/merchant/store name.
        
        Return the information in this JSON format:
        {
          "vendor_name": "The exact store or vendor name as it appears on the receipt, with correct capitalization",
          "confidence": 0.95  # A confidence score between 0 and 1
        }
        
        If you cannot identify a vendor name, return:
        {
          "vendor_name": null,
          "confidence": 0
        }
        """

        try:
            # Use the current model for vision capabilities (gpt-4o)
            # The newest OpenAI model is "gpt-4o" which was released May 13, 2024.
            response = client.chat.completions.create(
                model="gpt-4o",  # Current model with vision capabilities
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                            },
                        ],
                    }
                ],
                max_tokens=300,
                response_format={"type": "json_object"},
            )
            
            # Parse the response
            result = response.choices[0].message.content
            vendor_data = json.loads(result)
            
            logger.info(f"Successfully extracted vendor data: {vendor_data}")
            return {
                "success": True,
                "vendor_name": vendor_data.get("vendor_name"),
                "confidence": vendor_data.get("confidence", 0)
            }
            
        except Exception as api_error:
            # Log the API error
            logger.error(f"OpenAI API error in vendor extraction: {str(api_error)}")
            
            # Return error information
            return {
                "success": False,
                "error": str(api_error)
            }
    
    except Exception as e:
        logger.error(f"Error in vendor extraction: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

def analyze_asset_image(image_data):
    """
    Analyze an image of an asset to extract details using OpenAI Vision API.
    
    Args:
        image_data: Binary image data
        
    Returns:
        dict: Contains extracted asset information
    """
    try:
        # Convert binary image to base64
        import base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        from openai import OpenAI
        import os
        
        # Initialize the OpenAI client
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        
        # Create the prompt for asset analysis
        prompt = """
        Analyze this image of a product or asset and extract as much information as possible, including:
        
        1. What is this product/asset?
        2. Brand or manufacturer
        3. Model name or number (if visible)
        4. Product category (electronics, furniture, equipment, etc.)
        5. Key features or specifications visible
        6. Approximate dimensions or size
        7. Condition (new, used, etc.) if you can tell
        8. Any visible serial numbers, UPC, or identifiers
        9. Material composition (metal, plastic, etc.)
        10. Estimated value range (in USD)
        
        Return the information as a structured JSON object with the following fields:
        {
            "name": "Product name",
            "manufacturer": "Brand name",
            "model": "Model number/name",
            "category": "Product category",
            "description": "Brief description",
            "specifications": {
                "dimensions": "Dimensions if visible",
                "material": "Material composition",
                "color": "Color description",
                "other_key_specs": "Any other visible specifications"
            },
            "identifiers": {
                "serial_number": "Serial number if visible",
                "upc": "UPC code if visible"
            },
            "condition": "Condition assessment",
            "estimated_value": estimated price (numeric, don't include currency symbol)
        }
        
        Focus on being accurate with visible information rather than making guesses for fields you cannot determine.
        """
        
        # The newest OpenAI model is "gpt-4o" which was released May 13, 2024.
        # do not change this unless explicitly requested by the user
        response = client.chat.completions.create(
            model="gpt-4o",
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
                            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                        }
                    ]
                }
            ],
            max_tokens=800,
            response_format={"type": "json_object"},
        )
        
        # Parse the response
        import json
        result = json.loads(response.choices[0].message.content)
        
        # Log the result (omitting long descriptions for brevity)
        logger.info(f"Successfully analyzed asset image: {result.get('name')}, {result.get('manufacturer')}, {result.get('model')}")
        
        return {
            "success": True,
            "data": result
        }
        
    except Exception as e:
        logger.error(f"Error in asset image analysis: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

def lookup_asset_details(upc=None, oem=None, model=None):
    """
    Lookup asset details using UPC, OEM, and/or model information with OpenAI.
    
    Args:
        upc: Universal Product Code (optional)
        oem: Original Equipment Manufacturer (optional)
        model: Model number or name (optional)
        
    Returns:
        dict: Contains asset details including specs, estimated value, etc.
    """
    try:
        # Build a prompt based on available information
        if upc:
            main_identifier = f"UPC code: {upc}"
        elif oem and model:
            main_identifier = f"OEM: {oem}, Model: {model}"
        elif model:
            main_identifier = f"Model: {model}"
        elif oem:
            main_identifier = f"OEM: {oem}"
        else:
            return {
                "success": False,
                "error": "Insufficient information provided. Please provide UPC, OEM, or model information."
            }
        
        prompt = f"""
        I need comprehensive information about an asset with the following identifier:
        {main_identifier}
        
        Please provide the following details in JSON format:
        1. Full product name
        2. Manufacturer name
        3. Model details
        4. Category (e.g., Laptop, Monitor, Printer, etc.)
        5. Specifications (key technical details)
        6. Estimated current value (in USD)
        7. Estimated useful life (in years)
        8. Typical warranty period
        
        Return the information in this JSON format:
        {{
            "product_name": "Full product name",
            "manufacturer": "Manufacturer name",
            "model": "Model identifier",
            "category": "Product category",
            "specifications": {{
                "key1": "value1",
                "key2": "value2",
                ...
            }},
            "estimated_value": 999.99,
            "useful_life_years": 3,
            "warranty_period": "1 year"
        }}
        
        If you cannot find reliable information, include a confidence rating (0-1) for each field.
        """
        
        try:
            # The newest OpenAI model is "gpt-4o" which was released May 13, 2024.
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an expert in technology and asset valuation."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            
            # Parse the response
            result = response.choices[0].message.content
            asset_data = json.loads(result)
            
            logger.info(f"Successfully retrieved asset data: {asset_data}")
            return {
                "success": True,
                "data": asset_data,
                "needs_approval": True  # All automatically generated asset details need approval
            }
            
        except Exception as api_error:
            # Log the API error
            logger.error(f"OpenAI API error in asset lookup: {str(api_error)}")
            
            # Return error information
            return {
                "success": False,
                "error": str(api_error)
            }
    
    except Exception as e:
        logger.error(f"Error in asset lookup: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

def categorize_expense(description, amount, vendor=None):
    """
    Categorize an expense line item using OpenAI.
    
    Args:
        description: Description of the expense
        amount: Amount of the expense
        vendor: Vendor name (optional)
        
    Returns:
        dict: Contains categorization details including category, subcategory, confidence
    """
    try:
        # Create the prompt
        prompt = f"""
        Categorize the following expense line item into the most appropriate business expense category.
        
        Expense Details:
        - Description: {description}
        - Amount: ${amount:.2f}
        {f"- Vendor: {vendor}" if vendor else ""}
        
        Please provide the following in JSON format:
        1. Main category (e.g., Office Supplies, Travel, Equipment, Software, etc.)
        2. Sub-category (more specific classification)
        3. Is this likely an asset or consumable? (Asset = durable item with useful life >1 year)
        4. Your confidence level in this categorization (0.0-1.0)
        
        Standard business expense categories:
        - Office Supplies (paper, toner, pens, etc.)
        - Technology (software, online services, domain names)
        - Hardware (computers, peripherals, components)
        - Furniture (chairs, desks, cabinets)
        - Professional Services (legal, accounting, consulting)
        - Marketing (advertising, promotional materials)
        - Travel (airfare, hotels, transportation)
        - Meals & Entertainment (business meals, client entertainment)
        - Utilities (electricity, internet, phone)
        - Rent (office space, coworking)
        - Insurance (business insurance, liability)
        - Education (courses, books, training)
        - Subscription Services (recurring SaaS, publications)
        - Shipping & Postage
        - Miscellaneous (other expenses)
        
        Return ONLY a JSON object with this format:
        {
            "category": "Main Category Name", 
            "subcategory": "Subcategory Name", 
            "is_asset": true/false,
            "confidence": 0.95
        }
        """
        
        try:
            # The newest OpenAI model is "gpt-4o" which was released May 13, 2024.
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an expert accountant specializing in business expense categorization."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                response_format={"type": "json_object"},
            )
            
            # Parse the response
            result = response.choices[0].message.content
            category_data = json.loads(result)
            
            logger.info(f"Successfully categorized expense: {category_data}")
            return {
                "success": True,
                **category_data
            }
            
        except Exception as api_error:
            # Log the API error
            logger.error(f"OpenAI API error in expense categorization: {str(api_error)}")
            
            # Return error information
            return {
                "success": False,
                "error": str(api_error)
            }
        
    except Exception as e:
        logger.error(f"Error in expense categorization: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

def should_asset_be_serialized(item_name, quantity, price=None, category=None, description=None, use_claude=None):
    """
    Check if a particular asset should be serialized based on its characteristics.
    Now uses OpenAI exclusively for consistent decision-making.
    
    Args:
        item_name: Name or title of the asset
        quantity: Quantity purchased
        price: Price of the item (optional)
        category: Category of the item (optional)
        description: Additional description of the item (optional)
        use_claude: Deprecated parameter - OpenAI is now used exclusively
        
    Returns:
        dict: Contains assessment of whether asset should be serialized and confidence
    """
    # Import OpenAI functions
    from openai_utils import should_asset_be_serialized_openai
    
    logger.info(f"Determining if asset '{item_name}' should be serialized using OpenAI")
    
    # Always use OpenAI now
    return should_asset_be_serialized_openai(item_name, quantity, price, category, description)


def categorize_line_items(line_items, vendor=None):
    """
    Categorize multiple line items from a receipt.
    
    Args:
        line_items: List of line items with description and amount
        vendor: Vendor name (optional)
        
    Returns:
        dict: Contains categorized line items with confidence scores
    """
    try:
        import os
        import openai
        import json
        from openai import OpenAI
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Initialize OpenAI client
        openai_api_key = os.environ.get("OPENAI_API_KEY")
        client = OpenAI(api_key=openai_api_key)
        
        if not openai_api_key:
            logger.error("OpenAI API key is missing")
            return {
                "success": False,
                "error": "OpenAI API key is missing"
            }
            
        # Format the prompt
        items_text = ""
        for i, item in enumerate(line_items):
            description = item.get('description', 'Unknown')
            amount = item.get('amount', 0)
            items_text += f"{i+1}. Description: {description}, Amount: ${amount:.2f}\n"
        
        vendor_info = f"Vendor: {vendor}\n" if vendor else ""
        
        prompt = f"""
        Analyze the following receipt line items and categorize each expense:
        
        {vendor_info}
        {items_text}
        
        For each line item, provide the following:
        1. Category (e.g., Office Supplies, IT Equipment, Food, Travel, etc.)
        2. Subcategory (more specific type)
        3. Whether it's an asset (true for durable goods like electronics, equipment, furniture)
        4. Confidence level (0.0 to 1.0)
        
        Format your response as a JSON object where keys are the line item numbers and 
        values are objects with category, subcategory, is_asset, and confidence fields.
        Example: {{"1": {{"category": "Office Supplies", "subcategory": "Stationery", "is_asset": false, "confidence": 0.95}}}}
        """
        
        # Call the OpenAI API
        response = client.chat.completions.create(
            model="gpt-4o",  # the newest OpenAI model is "gpt-4o" which was released May 13, 2024. Do not change this unless explicitly requested by the user.
            messages=[
                {"role": "system", "content": "You are a financial categorization assistant that specializes in analyzing receipt line items."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        
        # Parse the response
        result = response.choices[0].message.content
        categories_data = json.loads(result)
        
        logger.info(f"Successfully categorized {len(categories_data)} line items")
        
        return {
            "success": True,
            "categories": categories_data
        }
            
    except Exception as e:
        logger.error(f"Error in line item categorization: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }


def handle_quota_exceeded(image_data):
    """
    Fallback method when API quota is exceeded or rate limit is reached.
    Returns a default object with an informative error message.
    
    Args:
        image_data: Binary image data
        
    Returns:
        dict: Contains a default structure with an error message
    """
    # Get today's date as default
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Try to extract some basic image info for better user experience
    try:
        from PIL import Image
        import io
        
        # Convert binary data to image
        img = Image.open(io.BytesIO(image_data))
        
        # Get basic image info
        width, height = img.size
        format_type = img.format
        mode = img.mode
        
        # Create a more descriptive message
        error_msg = (
            f"API quota exceeded. Using fallback mode with limited functionality. "
            f"Your image ({format_type}, {width}x{height}) was received but cannot be processed with OCR. "
            f"Please enter receipt details manually."
        )
    except Exception:
        # If image analysis fails, use generic message
        error_msg = "OpenAI API quota exceeded. Please enter receipt details manually or try again later."
    
    return {
        "vendor_name": None,
        "date": today,
        "total_amount": None,
        "description": None,
        "receipt_number": None,
        "due_date": None,
        "is_bill": False,
        "quota_exceeded": True,
        "error": error_msg
    }