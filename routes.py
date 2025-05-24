import os
import json
import base64
import logging
from datetime import datetime, timedelta
from openai import OpenAI
from flask import render_template, request, redirect, url_for, flash, jsonify, session, Response
from werkzeug.utils import secure_filename

# Initialize OpenAI client
openai = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
from app import app, db
from models import (
    Invoice, InvoiceLineItem, Attachment, Object, Vendor, 
    PersonPetAssociation, AIEvaluationQueue, ObjectAttachment, Category,
    AISettings, Reminder, TaskQueue
)
# Import our new log utilities
from log_utils import get_logger, log_function_call

# Get a logger for this module
logger = get_logger(__name__)

import ai_service
from ocr_utils import (
    extract_receipt_data, 
    extract_receipt_data_from_binary,
    process_receipt_with_ai,
    extract_line_items_with_object_suggestions,
    extract_vendor_from_image, 
    lookup_asset_details, 
    categorize_line_items,
    analyze_asset_image,
    should_asset_be_serialized,
    convert_pdf_to_image # Import the PDF conversion function
)

# Import Claude utilities for enhanced image analysis
from claude_utils import (
    analyze_asset_image_claude,
    lookup_asset_details_claude,
    should_asset_be_serialized_claude,
    process_receipt_with_claude, # Keep this if used elsewhere, otherwise remove
    check_claude_api_connection,
    extract_receipt_data_with_claude # This now handles line items too
)

# Import OpenAI utilities
from openai_utils import (
    process_receipt_with_openai, # Keep this if used elsewhere, otherwise remove
    extract_receipt_data_with_openai, # This now handles line items too
    should_asset_be_serialized_openai,
    check_openai_api_connection
)

# Import LLM Studio utilities for local model integration
from llm_studio_utils import (
    check_llm_studio_connection,
    process_receipt_with_llm_studio,
    extract_receipt_data_with_llm_studio,
    extract_line_items_with_llm_studio,
    analyze_asset_image_llm_studio,
    should_asset_be_serialized_llm_studio
)

# Configure which AI model to use (determined from settings)
USE_CLAUDE = True

# Initialize the Settings table if this is the first run
with app.app_context():
    try:
        AISettings.initialize_defaults()
        logger.info("AI Settings initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing AI settings: {str(e)}")

@app.route('/')
def index():
    """Home page route"""
    logger.debug("Rendering index page")
    return render_template('index.html')

@app.route('/receipt-upload', methods=['GET', 'POST'])
def receipt_upload():
    """Handle receipt upload and processing"""
    if request.method == 'POST':
        # Debug request information
        logger.debug(f"POST request to receipt-upload with form data keys: {list(request.form.keys())}")
        logger.debug(f"Files in request: {list(request.files.keys())}")
        
        # Check if a file was uploaded
        if 'receipt_image' not in request.files:
            logger.error("File input 'receipt_image' not found in request.files")
            flash('No file part - Please ensure you selected a file', 'danger')
            return redirect(request.url)
        
        file = request.files['receipt_image']
        
        # Check if the user submitted an empty form
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)
        
        # Process the file if it exists
        if file:
            try:
                # Get form data and AI processing options
                # Always set auto_analyze to true to ensure line items are processed
                auto_analyze = True
                auto_link = request.form.get('auto_link', 'false').lower() == 'true'
                
                # Read the file data
                file_data = file.read()
                file.seek(0)  # Reset file pointer
                
                # Secure the filename to prevent security issues
                filename = secure_filename(file.filename)
                logger.info(f"Processing receipt file: {filename}, auto_analyze={auto_analyze}")
                
                # Check if file is a PDF and convert to image if needed
                if filename.lower().endswith('.pdf'):
                    logger.info(f"Processing PDF file: {filename}")
                    try:
                        # Import PDF conversion function
                        from ocr_utils import convert_pdf_to_image
                        
                        # Convert PDF to image for AI processing
                        file_data = convert_pdf_to_image(file_data)
                        logger.info(f"Successfully converted PDF to image for processing")
                        
                        # Update filename to reflect the conversion
                        filename = filename.rsplit('.', 1)[0] + '.jpg'
                    except Exception as pdf_error:
                        logger.error(f"Error converting PDF to image: {str(pdf_error)}")
                        flash(f"Error processing PDF: {str(pdf_error)}", 'warning')
                
                # Process with AI for enhanced receipt data and line item extraction
                logger.info(f"Processing receipt with AI (auto_analyze={auto_analyze}, auto_link={auto_link})")
                
                # Check if user specified which model to use
                selected_model = request.form.get('ai_model', 'claude') # Default to claude
                
                # Determine which AI model to use based on selection
                use_claude = (selected_model != 'openai') # Use Claude unless 'openai' is explicitly selected
                
                # Use our wrapper function that handles model selection
                logger.info(f"Processing receipt with {'Claude' if use_claude else 'OpenAI'}")
                result = process_receipt_with_ai(file_data, filename, auto_analyze, auto_link, use_claude=use_claude)
                
                if not result.get('success', False):
                    logger.error(f"Error in AI processing: {result.get('error')}")
                    flash(f"Error processing receipt with AI: {result.get('error')}", 'danger')
                    return redirect(request.url)
                
                receipt_data = result.get('receipt_data', {})
                line_items = receipt_data.get('line_items', [])
                
                # Extract basic receipt info
                vendor_name = receipt_data.get('vendor_name', '')
                date_str = receipt_data.get('date', '')
                total_amount = receipt_data.get('total_amount', 0)
                description = receipt_data.get('description', '')
                receipt_number = receipt_data.get('receipt_number', '')
                due_date = receipt_data.get('due_date')
                is_bill = receipt_data.get('is_bill', False)
                
                # If AI processing failed or wasn't used, fall back to manual form data
                if not vendor_name or not date_str or not total_amount:
                    vendor_name = request.form.get('vendor_name', '')
                    date_str = request.form.get('date', '')
                    total_amount = request.form.get('total_amount', '')
                    description = request.form.get('description', '')
                    receipt_number = request.form.get('receipt_number', '')
                    due_date = request.form.get('due_date', '')
                    is_bill = bool(due_date)
                    # Keep line_items from AI processing if available
                
                # Validate required fields
                if not vendor_name or not date_str or not total_amount:
                    logger.warning("Missing required fields for receipt processing")
                    flash('Vendor name, date, and total amount are required', 'danger')
                    return redirect(request.url)
                
                # Parse the date
                try:
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                except ValueError:
                    logger.error(f"Invalid date format: {date_str}")
                    flash('Invalid date format', 'danger')
                    return redirect(request.url)
                
                # Create a new invoice with JSON data
                invoice_data = {
                    'vendor': vendor_name,
                    'date': date_str,
                    'total_amount': float(total_amount),
                    'description': description,
                    'receipt_number': receipt_number,
                    'due_date': due_date,
                    'status': 'processed',
                    'is_bill': is_bill
                }
                
                # Check if vendor exists, if not create a new one or leave vendor_id as null
                vendor_id = None
                vendor = Vendor.query.filter_by(name=vendor_name).first()
                if vendor:
                    vendor_id = vendor.id
                    logger.info(f"Linked receipt to existing vendor: {vendor_name} (ID: {vendor_id})")
                
                # Create the invoice
                invoice = Invoice(
                    invoice_number=Invoice.generate_invoice_number(),
                    vendor_id=vendor_id,
                    is_paid=True,  # Mark as paid since it's a receipt
                    data=invoice_data
                )
                db.session.add(invoice)
                db.session.flush()  # Flush to get the invoice ID
                
                # Create a line item for the invoice (basic line item for the total amount)
                # This is only used if no line items were detected by AI
                if not line_items:
                    line_item_data = {
                        'description': description or 'General purchase',
                        'amount': float(total_amount),
                        'quantity': 1,
                    }
                    line_item = InvoiceLineItem(
                        invoice_id=invoice.id,
                        data=line_item_data
                    )
                    db.session.add(line_item)
                else:
                    # Create line items from AI-detected items
                    for idx, item_data in enumerate(line_items):
                        # Check if this line item should create an object
                        create_object = request.form.get(f'line_items[{idx}][create_object]') == 'true'
                        
                        # Get line item data
                        item_description = request.form.get(f'line_items[{idx}][description]') or item_data.get('description', '')
                        item_quantity = float(request.form.get(f'line_items[{idx}][quantity]') or item_data.get('quantity', 1))
                        item_unit_price = float(request.form.get(f'line_items[{idx}][unit_price]') or item_data.get('unit_price', 0))
                        item_total_price = float(request.form.get(f'line_items[{idx}][total_price]') or item_data.get('total_price', 0))
                        
                        # Save the line item
                        line_item_data = {
                            'description': item_description,
                            'quantity': item_quantity,
                            'unit_price': item_unit_price,
                            'total_price': item_total_price,
                        }
                        
                        line_item = InvoiceLineItem(
                            invoice_id=invoice.id,
                            data=line_item_data
                        )
                        db.session.add(line_item)
                        
                        # Create object if requested
                        if create_object:
                            # Get object type and category from form
                            object_type = request.form.get(f'line_items[{idx}][object_type]', 'consumable')
                            category = request.form.get(f'line_items[{idx}][category]', '')
                            
                            # Create object data dictionary
                            object_data = {
                                'name': item_description,
                                'acquisition_date': date_str,
                                'acquisition_cost': item_total_price,
                                'vendor': vendor_name,
                                'description': item_description,
                                'category': category,
                                'quantity': item_quantity if object_type == 'consumable' else 1,
                                'needs_approval': (object_type == 'asset'),  # Only assets need approval
                                'approved': (object_type != 'asset')  # Non-assets are auto-approved
                            }
                            
                            # Add asset-specific data if available
                            if object_type == 'asset':
                                object_data.update({
                                    'upc': request.form.get('upc_code', ''),
                                    'serial_number': request.form.get('serial_number', ''),
                                    'model': request.form.get('model', ''),
                                    'manufacturer': request.form.get('oem', vendor_name),
                                })
                            
                            # Check if we should link to existing object (only for assets)
                            linked_to_existing = False
                            if auto_link and object_type == 'asset':
                                # Try to find an existing asset with the same name, manufacturer, and model
                                existing_assets = Object.query.filter_by(object_type='asset').all()
                                for existing in existing_assets:
                                    if (existing.data.get('name', '').lower() == item_description.lower() and 
                                        existing.data.get('manufacturer', '').lower() == object_data.get('manufacturer', '').lower()):
                                        # Found a match - just link the invoice ID but don't create a new object
                                        logger.info(f"Linked line item '{item_description}' to existing asset ID {existing.id}")
                                        linked_to_existing = True
                                        break
                            
                            # Create new object if not linked to existing
                            if not linked_to_existing:
                                new_object = Object(
                                    invoice_id=invoice.id,
                                    object_type=object_type,
                                    data=object_data
                                )
                                db.session.add(new_object)
                
                # Create an attachment for the receipt
                attachment = Attachment(
                    invoice_id=invoice.id,
                    filename=filename,
                    file_data=file_data,  # Use the saved file data
                    file_type=file.content_type
                )
                db.session.add(attachment)
                
                # Commit the changes to the database
                db.session.commit()
                
                logger.info(f"Receipt processed successfully: Invoice #{invoice.invoice_number} created")
                flash(f'Receipt processed successfully! Invoice #{invoice.invoice_number} created.', 'success')
                return redirect(url_for('receipts_page'))
                
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error processing receipt: {str(e)}", exc_info=True)
                flash(f'Error processing receipt: {str(e)}', 'danger')
                return redirect(request.url)
    
    # If GET request, render the upload form
    logger.debug("Rendering receipt upload form")
    return render_template('receipt_form.html')

@app.route('/add_object', methods=['GET', 'POST'])
@app.route('/edit_object/<object_id>', methods=['GET', 'POST'])
def add_object(object_id=None):
    today = datetime.now().strftime('%Y-%m-%d')
    edit_mode = object_id is not None
    
    # For edit mode, fetch the existing object
    object_data = None
    if edit_mode:
        try:
            object_data = db.get_object_by_id(object_id)
            if not object_data:
                flash('Object not found!', 'danger')
                return redirect(url_for('inventory'))
        except Exception as e:
            flash(f'Error retrieving object: {str(e)}', 'danger')
            return redirect(url_for('inventory'))
    
    if request.method == 'POST':
        try:
            # Basic object data
            object_type = request.form.get('object_type')
            name = request.form.get('name')
            description = request.form.get('description')
            categories = request.form.getlist('categories')
            
            # Create base object data dictionary
            data = {
                'name': name,
                'description': description,
                'categories': categories
            }
            
            # Process different fields based on object type
            if object_type in ['asset', 'component', 'consumable', 'service', 'software']:
                # Handle common value-related fields
                acquisition_date = request.form.get('acquisition_date')
                acquisition_cost = request.form.get('acquisition_cost')
                
                if acquisition_date:
                    data['acquisition_date'] = acquisition_date
                
                if acquisition_cost and acquisition_cost.strip():
                    data['acquisition_cost'] = float(acquisition_cost)
            
            if object_type in ['asset', 'component']:
                # Handle asset and component specific fields
                estimated_value = request.form.get('estimated_value')
                useful_life_years = request.form.get('useful_life_years')
                
                if estimated_value and estimated_value.strip():
                    data['estimated_value'] = float(estimated_value)
                
                if useful_life_years and useful_life_years.strip():
                    data['useful_life_years'] = int(useful_life_years)
                
                # Process specifications JSON
                specifications = request.form.get('specifications')
                if specifications:
                    data['specifications'] = json.loads(specifications)
            
            if object_type in ['asset', 'component', 'consumable']:
                # Handle physical item fields
                manufacturer = request.form.get('manufacturer')
                model = request.form.get('model')
                upc = request.form.get('upc')
                quantity = request.form.get('quantity', '1')
                
                if manufacturer:
                    data['manufacturer'] = manufacturer
                
                if model:
                    data['model'] = model
                    
                if upc:
                    data['upc'] = upc
                    
                if quantity and quantity.strip():
                    data['quantity'] = int(quantity)
            
            if object_type == 'asset':
                # Asset-specific fields
                serial_number = request.form.get('serial_number')
                
                if serial_number:
                    data['serial_number'] = serial_number
            
            if object_type == 'component':
                # Component-specific fields
                parent_id = request.form.get('parent_id')
                
                if parent_id:
                    data['parent_id'] = parent_id
            
            if object_type == 'consumable':
                # Consumable-specific fields
                stock_level = request.form.get('stock_level', '0')
                expiration_date = request.form.get('expiration_date')
                shelf_life = request.form.get('shelf_life', '0')
                track_stock = request.form.get('track_stock') == 'true'
                reorder_threshold = request.form.get('reorder_threshold', '0')
                
                if stock_level and stock_level.strip():
                    data['current_stock'] = int(stock_level)
                
                if expiration_date:
                    data['expiration_date'] = expiration_date
                
                if shelf_life and shelf_life.strip():
                    data['shelf_life'] = int(shelf_life)
                
                data['track_stock'] = track_stock
                
                if reorder_threshold and reorder_threshold.strip():
                    data['reorder_threshold'] = int(reorder_threshold)
            
            if object_type in ['service', 'software']:
                # Service and software specific fields
                subscription_renewal = request.form.get('subscription_renewal')
                
                if subscription_renewal:
                    data['subscription_renewal'] = subscription_renewal
            
            if object_type == 'person':
                # Person-specific fields
                contact_email = request.form.get('contact_email')
                contact_phone = request.form.get('contact_phone')
                address = request.form.get('address')
                
                if contact_email:
                    data['contact_email'] = contact_email
                    
                if contact_phone:
                    data['contact_phone'] = contact_phone
                    
                if address:
                    data['address'] = address
            
            if object_type == 'pet':
                # Pet-specific fields
                breed = request.form.get('breed')
                birth_date = request.form.get('birth_date')
                
                if breed:
                    data['breed'] = breed
                    
                if birth_date:
                    data['birth_date'] = birth_date
            
            # Set create_invoice flag
            create_invoice = request.form.get('create_invoice') == 'true'
            
            # Adding or updating?
            if edit_mode:
                # Update existing object
                db.update_object(object_id, object_type, data)
                
                # Handle consumable expiration scheduling for updates
                if object_type == 'consumable':
                    # Get the updated object to ensure we have the latest data
                    updated_obj = Object.query.get(object_id)
                    if updated_obj:
                        # If expiration date is provided, schedule it
                        if data.get('expiration_date'):
                            # Remove any existing scheduled expirations for this consumable
                            TaskQueue.query.filter_by(
                                task_type='consumable_expiration',
                                object_id=object_id,
                                status='pending'
                            ).delete()
                            db.session.commit()
                            
                            # Schedule the new expiration
                            TaskQueue.schedule_consumable_expiration(
                                object_id=object_id,
                                expiration_date=data['expiration_date'],
                                quantity=data.get('quantity', 1)
                            )
                            logger.info(f"Scheduled expiration task for updated consumable {object_id} on {data['expiration_date']}")
                
                flash(f'{object_type.capitalize()} updated successfully!', 'success')
            else:
                # Create new object
                new_object_id = db.create_object(object_type, data)
                
                # Create invoice record if requested
                if create_invoice and object_type in ['asset', 'component', 'consumable', 'service', 'software'] and 'acquisition_cost' in data:
                    invoice_data = {
                        'date': data.get('acquisition_date', datetime.now().strftime('%Y-%m-%d')),
                        'vendor': 'Manual Entry',
                        'total_amount': data['acquisition_cost'],
                        'is_paid': True,
                        'is_asset': object_type != 'service'
                    }
                    
                    invoice_id = db.create_invoice(invoice_data, None)
                    
                    # Link object to invoice
                    db.link_object_to_invoice(new_object_id, invoice_id)
                
                # Handle consumables with expiration dates or shelf life
                if object_type == 'consumable':
                    obj = Object.query.get(new_object_id)
                    expiration_date = data.get('expiration_date')
                    shelf_life = data.get('shelf_life')
                    
                    # Calculate expiration date if not explicitly provided but shelf life is
                    if shelf_life and not expiration_date:
                        today_date = datetime.now().date()
                        expiry_date = today_date + timedelta(days=int(shelf_life))
                        expiration_date = expiry_date.strftime('%Y-%m-%d')
                        # Update the object with the calculated expiration date
                        data['expiration_date'] = expiration_date
                        db.update_object(new_object_id, 'consumable', {'expiration_date': expiration_date})
                    
                    # Schedule expiration task
                    if expiration_date:
                        TaskQueue.schedule_consumable_expiration(
                            object_id=new_object_id,
                            expiration_date=expiration_date,
                            quantity=data.get('quantity', 1)
                        )
                        logger.info(f"Scheduled expiration task for new consumable {new_object_id} on {expiration_date}")
                    
                    # Schedule stock check if tracking stock
                    if data.get('track_stock'):
                        # Schedule an immediate stock check to add to shopping list if needed
                        TaskQueue.queue_task({
                            'task_type': 'stock_check',
                            'execute_at': datetime.now(),
                            'priority': 3,  # Medium priority
                            'data': {
                                'target_object_id': new_object_id  # Specific object to check
                            }
                        })
                        logger.info(f"Scheduled stock check for new consumable {new_object_id}")
                
                flash(f'{object_type.capitalize()} added successfully!', 'success')
            
            return redirect(url_for('inventory'))
            
        except Exception as e:
            flash(f'Error saving object: {str(e)}', 'danger')
    
    # For GET requests, prepare the form
    try:
        # Get all parent objects (assets) for component selection
        parent_objects = []
        if object_id is None or object_data['object_type'] == 'component':
            parent_objects = db.get_objects_by_type('asset')
            
        # If edit mode, convert object data from JSON
        if edit_mode:
            # The object data is already fetched above
            pass
            
        return render_template('object_form.html', 
                              object_type=request.args.get('object_type', 'asset') if not edit_mode else object_data['object_type'],
                              edit_mode=edit_mode,
                              object=object_data,
                              parent_objects=parent_objects,
                              today=today)
    
    except Exception as e:
        flash(f'Error preparing form: {str(e)}', 'danger')
        return redirect(url_for('inventory'))

@app.route('/receipts')
def receipts_page():
    """Display paid receipts page"""
    logger.debug("Rendering receipts page")
    
    # Query for paid receipts using date from data JSON column
    receipts = Invoice.query.filter_by(is_paid=True)\
        .order_by(Invoice.data['date'].desc())\
        .all()
    return render_template('receipts_page.html', receipts=receipts)

# Keep the old route for backward compatibility
@app.route('/paid-receipts')
def paid_receipts():
    """Redirect to receipts page for backward compatibility"""
    logger.debug("Redirecting from /paid-receipts to /receipts")
    return redirect(url_for('receipts_page'))

@app.route('/bills')
def bills_page():
    """Display bills (unpaid invoices) page"""
    logger.debug("Rendering bills page")
    
    # Query for unpaid invoices
    bills = Invoice.query.filter_by(is_paid=False)\
        .order_by(Invoice.data['date'].desc())\
        .all()
    # Get vendors for the link vendor modal
    vendors = Vendor.query.all()
    # Get today's date for overdue checking
    today = datetime.now().date()
    return render_template('bills_page.html', bills=bills, vendors=vendors, today=today)

@app.route('/inventory')
def inventory():
    """Display inventory management page"""
    logger.debug("Rendering inventory page")
    
    # Query all objects, optionally filtered by type
    object_type = request.args.get('object_type', 'all')
    if object_type != 'all':
        objects = Object.query.filter_by(object_type=object_type).order_by(Object.created_at.desc()).all()
    else:
        objects = Object.query.order_by(Object.created_at.desc()).all()
    
    # Get unique object types for filter
    object_types = db.session.query(Object.object_type).distinct().all()
    object_types = [t[0] for t in object_types]
    
    # Convert objects to JSON for analysis
    objects_json = json.dumps([{
        'id': obj.id,
        'object_type': obj.object_type,
        'data': obj.data
    } for obj in objects])
    
    return render_template('inventory.html', 
                         objects=objects,
                         object_types=object_types,
                         selected_type=object_type,
                         objects_json=objects_json)

@app.route('/api/consumable/schedule-expiration', methods=['POST'])
def schedule_consumable_expiration():
    """
    Schedule a task to handle consumable expiration.
    This API endpoint expects:
    - object_id: ID of the consumable object
    - expiration_date: When the consumable expires (YYYY-MM-DD)
    - quantity: Quantity that will expire (default: 1)
    """
    try:
        data = request.json
        object_id = data.get('object_id')
        expiration_date = data.get('expiration_date')
        quantity = data.get('quantity', 1)
        
        if not object_id or not expiration_date:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
            
        # Check if the object exists and is a consumable
        obj = Object.query.get(object_id)
        if not obj:
            return jsonify({'success': False, 'error': f'Object with ID {object_id} not found'}), 404
        if obj.object_type != 'consumable':
            return jsonify({'success': False, 'error': 'Object is not a consumable'}), 400
            
        # Schedule the expiration task
        task = TaskQueue.schedule_consumable_expiration(
            object_id=object_id, 
            expiration_date=expiration_date,
            quantity=quantity
        )
        
        return jsonify({
            'success': True, 
            'message': f'Expiration scheduled for {expiration_date}',
            'task_id': task.id
        })
        
    except Exception as e:
        app.logger.error(f"Error scheduling consumable expiration: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/shopping-list', methods=['GET'])
def get_shopping_list():
    """
    Get the current shopping list reminder.
    Returns the open shopping list reminder or creates a new one if none exists.
    """
    try:
        # Get open shopping list
        shopping_list = Reminder.query.filter_by(
            reminder_type='shopping_list',
            status='open'
        ).first()
        
        if not shopping_list:
            # Create a new shopping list if one doesn't exist
            shopping_list = Reminder(
                title="Shopping List - Inventory Restock",
                description="Items that need to be reordered based on inventory thresholds",
                reminder_type='shopping_list',
                status='open',
                due_date=datetime.utcnow() + timedelta(days=7),
                items=[]
            )
            db.session.add(shopping_list)
            db.session.commit()
        
        return jsonify({
            'success': True,
            'shopping_list': {
                'id': shopping_list.id,
                'title': shopping_list.title,
                'description': shopping_list.description,
                'due_date': shopping_list.due_date.isoformat() if shopping_list.due_date else None,
                'status': shopping_list.status,
                'items': shopping_list.items or []
            }
        })
        
    except Exception as e:
        app.logger.error(f"Error retrieving shopping list: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/shopping-list/item', methods=['POST'])
def update_shopping_list_item():
    """
    Update an item in the shopping list.
    Marks an item as purchased or modifies its quantity.
    """
    try:
        data = request.json
        reminder_id = data.get('reminder_id')
        object_id = data.get('object_id')
        purchased = data.get('purchased')
        quantity = data.get('quantity')
        
        if not reminder_id or not object_id:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
            
        # Get the reminder
        reminder = Reminder.query.get(reminder_id)
        if not reminder:
            return jsonify({'success': False, 'error': f'Reminder with ID {reminder_id} not found'}), 404
            
        # Update the specific item in the items array
        items = reminder.items or []
        item_found = False
        
        for i, item in enumerate(items):
            if item.get('object_id') == object_id:
                # Update the item
                if purchased is not None:
                    items[i]['purchased'] = purchased
                if quantity is not None:
                    items[i]['suggested_quantity'] = quantity
                item_found = True
                break
                
        if not item_found:
            return jsonify({'success': False, 'error': f'Item with object ID {object_id} not found in reminder'}), 404
            
        # Save changes
        reminder.items = items
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Shopping list item updated',
            'items': items
        })
        
    except Exception as e:
        app.logger.error(f"Error updating shopping list item: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/reminders/mark-complete', methods=['POST'])
def mark_reminder_complete():
    """
    Mark a reminder as complete.
    """
    try:
        data = request.json
        reminder_id = data.get('reminder_id')
        
        if not reminder_id:
            return jsonify({'success': False, 'error': 'Missing reminder ID'}), 400
            
        # Get the reminder
        reminder = Reminder.query.get(reminder_id)
        if not reminder:
            return jsonify({'success': False, 'error': f'Reminder with ID {reminder_id} not found'}), 404
            
        # Mark as complete
        reminder.mark_complete()
        
        return jsonify({
            'success': True,
            'message': f'Reminder "{reminder.title}" marked as complete'
        })
        
    except Exception as e:
        app.logger.error(f"Error marking reminder as complete: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/reminders', methods=['GET'])
def view_reminders():
    """
    Display the reminders page.
    """
    # Get all open reminders
    reminders = Reminder.get_open_reminders()
    
    # Get the shopping list specifically
    shopping_list = Reminder.query.filter_by(
        reminder_type='shopping_list',
        status='open'
    ).first()
    
    return render_template(
        'reminders.html', 
        reminders=reminders,
        shopping_list=shopping_list
    )
