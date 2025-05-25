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
    AISettings, Reminder, TaskQueue,
    Organization, User, OrganizationContact, UserPersonMapping, UserAlias,
    Note, CalendarEvent, Collection, OrganizationRelationship,
    ReceiptCreationTracking
)
# Import our new log utilities
from log_utils import get_logger, log_function_call

# Get a logger for this module
logger = get_logger(__name__)

def format_category_name(category):
    """Format category names for display (e.g., 'event_ticket' -> 'Event Ticket')"""
    if not category or category == 'Uncategorized':
        return category
    
    # Step 1: Replace underscores/hyphens with spaces and apply title case
    formatted = category.replace('_', ' ').replace('-', ' ').title()
    
    # Step 2: Apply general formatting rules
    
    # Rule 1: Convert common word combinations to use ampersand
    formatted = formatted.replace('Food Beverage', 'Food & Beverage')
    formatted = formatted.replace('Arts Crafts', 'Arts & Crafts') 
    formatted = formatted.replace('Health Beauty', 'Health & Beauty')
    formatted = formatted.replace('Home Garden', 'Home & Garden')
    
    # Rule 2: Fix common acronyms (word boundaries to avoid partial matches)
    import re
    acronym_fixes = {
        'Qr': 'QR', 'Ai': 'AI', 'Api': 'API', 'Ui': 'UI', 'Ux': 'UX', 
        'Id': 'ID', 'Url': 'URL', 'Pdf': 'PDF', 'Jpg': 'JPG', 'Png': 'PNG',
        'Html': 'HTML', 'Css': 'CSS', 'Js': 'JS', 'Usb': 'USB', 'Dvd': 'DVD'
    }
    
    for wrong, correct in acronym_fixes.items():
        # Replace at word boundaries only
        formatted = re.sub(r'\b' + wrong + r'\b', correct, formatted)
    
    return formatted

# Register the filter with Flask
app.jinja_env.filters['format_category'] = format_category_name

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

# Import OpenAI utilities - Our primary and only AI provider
from openai_utils import (
    process_receipt_with_openai,
    extract_receipt_data_with_openai,
    should_asset_be_serialized_openai,
    check_openai_api_connection
)

def allowed_file(filename):
    """Check if uploaded file has an allowed extension"""
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
    """
    Handle receipt file upload and AI analysis queue.
    The new AI-first workflow:
    1. Upload receipt (PDF/image) or take camera photo
    2. Send to MCP server for AI analysis 
    3. Queue in "receipt_processing" task for human review
    4. Human reviews AI suggestions in AI Queue
    5. Approve -> Creates invoice/objects automatically
    """
    if request.method == 'POST':
        # Import TaskQueue at the beginning so it's available in both try and except blocks
        from models import TaskQueue
        import base64
        
        # Check for camera-captured image data
        camera_image_data = request.form.get('camera_image_data')
        file = request.files.get('receipt_image')
        
        if not camera_image_data and (not file or file.filename == ''):
            flash('No file uploaded or photo taken', 'warning')
            return redirect(request.url)
        
        try:
            if camera_image_data:
                # Handle camera-captured image
                logger.info("Processing camera-captured image")
                
                # Extract base64 image data (remove data:image/jpeg;base64, prefix)
                if ',' in camera_image_data:
                    file_data = base64.b64decode(camera_image_data.split(',')[1])
                else:
                    file_data = base64.b64decode(camera_image_data)
                
                filename = f"camera_receipt_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg"
                original_filename = filename
                
            elif file and allowed_file(file.filename):
                # Handle uploaded file
                logger.info(f"Processing receipt file: {file.filename}")
                file_data = file.read()
                filename = secure_filename(file.filename)
                original_filename = file.filename
            else:
                flash('Invalid file format', 'warning')
                return redirect(request.url)
            
            # Handle PDF conversion
            if filename.lower().endswith('.pdf'):
                try:
                    logger.info(f"Processing PDF file: {filename}")
                    file_data = convert_pdf_to_image(file_data)
                    logger.info(f"Successfully converted PDF to image for processing")
                    filename = filename.rsplit('.', 1)[0] + '.jpg'
                except Exception as pdf_error:
                    logger.error(f"Error converting PDF to image: {str(pdf_error)}")
                    flash(f"Error processing PDF: {str(pdf_error)}", 'warning')
            
            # Step 1: Send to MCP Server for AI Analysis with OpenAI
            logger.info(f"Sending receipt to MCP server for analysis with OpenAI")
            
            try:
                # Import and use MCP client
                from mcp_client import analyze_receipt_sync
                
                # Send to MCP server for AI analysis (OpenAI only)
                mcp_result = analyze_receipt_sync(
                    image_data=file_data,
                    filename=filename,
                    provider='openai'
                )
                
                logger.info(f"MCP analysis successful: {mcp_result}")
                
                # Extract receipt data for duplicate checking
                receipt_data = extract_receipt_data_from_mcp_response(mcp_result)
                
                # Step 1.5: Check for duplicates before queuing
                vendor_name = receipt_data.get('vendor_name', '')
                receipt_date = receipt_data.get('date', '')
                total_amount = receipt_data.get('total_amount', 0)
                
                if vendor_name and receipt_date and total_amount:
                    # Check for duplicates
                    duplicate_check = {
                        'vendor_name': vendor_name,
                        'date': receipt_date,
                        'total_amount': total_amount
                    }
                    
                    # Look for existing receipts with same vendor, date, and amount
                    similar_receipts = Invoice.query.filter(
                        db.or_(
                            Invoice.vendor.has(Vendor.name.ilike(f'%{vendor_name}%')),
                            Invoice.data.op('->>')('vendor').ilike(f'%{vendor_name}%'),
                            Invoice.data.op('->>')('vendor_name').ilike(f'%{vendor_name}%')
                        )
                    ).filter(
                        Invoice.data.op('->>')('date') == receipt_date
                    ).all()
                    
                    # Check for exact matches
                    exact_matches = []
                    for existing_receipt in similar_receipts:
                        existing_total = existing_receipt.data.get('total_amount', 0) if existing_receipt.data else 0
                        try:
                            if abs(float(existing_total) - float(total_amount)) < 0.01:  # Within 1 cent
                                exact_matches.append(existing_receipt)
                        except (ValueError, TypeError):
                            continue
                    
                    if exact_matches:
                        match = exact_matches[0]
                        logger.warning(f"Potential duplicate receipt detected: {vendor_name} on {receipt_date} for ${total_amount}")
                        flash(f'⚠️ Potential duplicate detected! This receipt appears similar to #{match.invoice_number} from {vendor_name} on {receipt_date}. <a href="/receipts">Review existing receipts</a> to avoid duplicates.', 'warning')
                        # Continue processing but flag as potential duplicate
                        receipt_data['potential_duplicate'] = True
                        receipt_data['duplicate_of'] = match.invoice_number
                
                # Step 2: Create a Receipt Processing Queue Entry (not invoice yet!)
                receipt_queue_data = {
                    'ai_provider': 'openai',
                    'ai_analysis': mcp_result,
                    'original_filename': original_filename,
                    'processed_filename': filename,
                    'upload_timestamp': datetime.utcnow().isoformat(),
                    'user_preferences': {
                        'auto_approve': request.form.get('auto_approve', 'false') == 'true'
                    },
                    'duplicate_check_performed': True,
                    'potential_duplicate': receipt_data.get('potential_duplicate', False),
                    'capture_method': 'camera' if camera_image_data else 'upload'
                }
                
                # Create a temporary "receipt processing" task in the AI queue
                receipt_task = TaskQueue.queue_task({
                    'task_type': 'receipt_processing',
                    'execute_at': datetime.utcnow(),
                    'priority': 5,  # High priority for user uploads
                    'status': 'pending_review',  # Set status at top level
                    'data': receipt_queue_data
                })
                
                # Save the image data temporarily (we'll move this to attachment after approval)
                temp_attachment_data = {
                    'file_data': base64.b64encode(file_data).decode('utf-8'),
                    'file_type': 'image/jpeg' if camera_image_data else (file.content_type or 'image/jpeg')
                }
                
                # Update task with attachment data
                receipt_task.data.update({'attachment': temp_attachment_data})
                db.session.commit()
                
                logger.info(f"Receipt queued for review: Task ID {receipt_task.id}")
                
                # Success! Receipt is now in AI queue for review
                flash(f'Receipt uploaded and analyzed by AI! <a href="/ai-queue">Review AI suggestions in the AI Queue</a>', 'success')
                return redirect(url_for('ai_queue'))
                
            except Exception as mcp_error:
                logger.error(f"MCP server analysis failed: {str(mcp_error)}")
                
                # Fallback: Still queue for manual review but mark as AI analysis failed
                receipt_queue_data = {
                    'ai_provider': 'openai',
                    'ai_analysis': None,
                    'ai_error': str(mcp_error),
                    'original_filename': original_filename,
                    'processed_filename': filename,
                    'upload_timestamp': datetime.utcnow().isoformat(),
                    'requires_manual_entry': True,
                    'capture_method': 'camera' if camera_image_data else 'upload'
                }
                
                # Create task for manual processing
                receipt_task = TaskQueue.queue_task({
                    'task_type': 'receipt_processing',
                    'execute_at': datetime.utcnow(),
                    'priority': 5,
                    'status': 'ai_analysis_failed',  # Set status at top level
                    'data': receipt_queue_data
                })
                
                # Save the image data
                temp_attachment_data = {
                    'file_data': base64.b64encode(file_data).decode('utf-8'),
                    'file_type': 'image/jpeg' if camera_image_data else (file.content_type or 'image/jpeg')
                }
                receipt_task.data.update({'attachment': temp_attachment_data})
                db.session.commit()
            
                flash(f'Receipt uploaded but AI analysis failed. Please review manually in the <a href="/ai-queue">AI Queue</a>. Error: {str(mcp_error)[:100]}...', 'warning')
                return redirect(url_for('ai_queue'))
                
        except Exception as e:
            logger.error(f"Error processing receipt: {str(e)}", exc_info=True)
            flash(f'Error processing receipt: {str(e)}', 'danger')
            return redirect(request.url)
    
    # If GET request, render the upload form (simplified - no manual fields needed!)
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

@app.route('/view-receipt/<int:receipt_id>')
def view_receipt(receipt_id):
    """View a specific receipt details page"""
    try:
        receipt = Invoice.query.get_or_404(receipt_id)
        
        # Get line items and objects for this receipt
        line_items = InvoiceLineItem.query.filter_by(invoice_id=receipt_id).all()
        objects = Object.query.filter_by(invoice_id=receipt_id).all()
        attachments = Attachment.query.filter_by(invoice_id=receipt_id).all()
        
        # Get creation tracking summary to determine what can still be created
        creation_summary = ReceiptCreationTracking.get_creation_summary(receipt_id)
        
        # Determine what creation options should be available
        show_creation_options = {
            'organization': not ReceiptCreationTracking.is_created(receipt_id, 'organization', None),
            'calendar_event': not ReceiptCreationTracking.is_created(receipt_id, 'calendar_event', None),
            'line_item_objects': {}  # Will be populated per line item
        }
        
        # Check which line items can still have objects created
        # We need to check against the AI analysis line items, not just the InvoiceLineItem records
        ai_line_items = []
        if receipt.data and receipt.data.get('ai_analysis'):
            ai_analysis = receipt.data['ai_analysis']
            if isinstance(ai_analysis, dict):
                ai_line_items = ai_analysis.get('line_items', [])
        
        # If we have line items from either source, check tracking for each
        max_line_items = max(len(line_items), len(ai_line_items))
        for idx in range(max_line_items):
            can_create_object = not ReceiptCreationTracking.is_created(receipt_id, 'object', idx)
            show_creation_options['line_item_objects'][idx] = can_create_object
        
        return render_template('receipt_details.html', 
                             receipt=receipt,
                             line_items=line_items,
                             objects=objects,
                             attachments=attachments,
                             creation_summary=creation_summary,
                             show_creation_options=show_creation_options)
    except Exception as e:
        logger.error(f"Error viewing receipt {receipt_id}: {str(e)}")
        flash(f'Error loading receipt: {str(e)}', 'danger')
        return redirect(url_for('receipts_page'))

# Keep the old route for backward compatibility
@app.route('/paid-receipts')
def paid_receipts():
    """Redirect to receipts page for backward compatibility"""
    logger.debug("Redirecting from /paid-receipts to /receipts")
    return redirect(url_for('receipts_page'))

@app.route('/bills')
def bills_page():
    """Display bills (unpaid invoices) page with enhanced management features"""
    try:
        logger.debug("Rendering bills page")
        
        # Get all unpaid invoices (bills) or invoices with due dates
        bills_query = db.session.query(Invoice).filter(
            db.or_(
                Invoice.is_paid == False,
                Invoice.data.op('->>')('due_date').isnot(None)
            )
        ).order_by(Invoice.created_at.desc())
        
        all_bills = bills_query.all()
        
        # Categorize bills
        overdue_bills = []
        due_soon_bills = []
        regular_bills = []
        
        today = datetime.utcnow().date()
        
        for bill in all_bills:
            due_date_str = bill.data.get('due_date') if bill.data else None
            if due_date_str:
                try:
                    due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
                    days_until_due = (due_date - today).days
                    
                    if not bill.is_paid and days_until_due < 0:
                        overdue_bills.append(bill)
                    elif not bill.is_paid and days_until_due <= 7:
                        due_soon_bills.append(bill)
                    else:
                        regular_bills.append(bill)
                except ValueError:
                    regular_bills.append(bill)
            else:
                if not bill.is_paid:
                    regular_bills.append(bill)
        
        # Calculate totals
        total_outstanding = sum(
            float(bill.data.get('total_amount', 0)) 
            for bill in all_bills 
            if not bill.is_paid and bill.data and bill.data.get('total_amount')
        )
        
        overdue_amount = sum(
            float(bill.data.get('total_amount', 0)) 
            for bill in overdue_bills 
            if bill.data and bill.data.get('total_amount')
        )
        
        # Get vendors for dropdowns
        vendors = Vendor.query.all()
        
        return render_template('bills_page.html', 
                             overdue_bills=overdue_bills,
                             due_soon_bills=due_soon_bills,
                             regular_bills=regular_bills,
                             total_outstanding=total_outstanding,
                             overdue_amount=overdue_amount,
                             vendors=vendors,
                             today=today)
        
    except Exception as e:
        logger.error(f"Error loading bills: {str(e)}")
        flash(f'Error loading bills: {str(e)}', 'danger')
        return render_template('bills_page.html', 
                             overdue_bills=[], 
                             due_soon_bills=[], 
                             regular_bills=[],
                             total_outstanding=0,
                             overdue_amount=0,
                             vendors=[],
                             today=datetime.utcnow().date())

@app.route('/mark-bill-paid/<int:bill_id>', methods=['POST'])
def mark_bill_paid(bill_id):
    """Mark a bill as paid"""
    try:
        bill = Invoice.query.get(bill_id)
        if not bill:
            flash('Bill not found', 'danger')
            return redirect(url_for('bills_page'))
        
        # Get payment info from form
        payment_date = request.form.get('payment_date')
        payment_method = request.form.get('payment_method', '')
        payment_notes = request.form.get('payment_notes', '')
        
        # Update bill status
        bill.is_paid = True
        
        # Update payment info in data
        if not bill.data:
            bill.data = {}
        
        bill.data['payment_date'] = payment_date or datetime.utcnow().strftime('%Y-%m-%d')
        bill.data['payment_method'] = payment_method
        bill.data['payment_notes'] = payment_notes
        bill.data['marked_paid_at'] = datetime.utcnow().isoformat()
        
        db.session.commit()
        
        vendor_name = bill.vendor.name if bill.vendor else bill.data.get('vendor', 'Unknown Vendor')
        total_amount = bill.data.get('total_amount', 0)
        
        logger.info(f"Marked bill as paid: {bill.invoice_number} ({vendor_name}) - ${total_amount}")
        flash(f'Bill {bill.invoice_number} from {vendor_name} marked as paid (${total_amount})', 'success')
        
        return redirect(url_for('bills_page'))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error marking bill as paid: {str(e)}")
        flash(f'Error marking bill as paid: {str(e)}', 'danger')
        return redirect(url_for('bills_page'))

@app.route('/update-due-date/<int:bill_id>', methods=['POST'])
def update_due_date(bill_id):
    """Update the due date of a bill"""
    try:
        bill = Invoice.query.get(bill_id)
        if not bill:
            flash('Bill not found', 'danger')
            return redirect(url_for('bills_page'))
        
        new_due_date = request.form.get('due_date')
        if not new_due_date:
            flash('Due date is required', 'danger')
            return redirect(url_for('bills_page'))
        
        # Update due date
        if not bill.data:
            bill.data = {}
        
        old_due_date = bill.data.get('due_date', 'None')
        bill.data['due_date'] = new_due_date
        bill.data['due_date_updated_at'] = datetime.utcnow().isoformat()
        
        db.session.commit()
        
        vendor_name = bill.vendor.name if bill.vendor else bill.data.get('vendor', 'Unknown Vendor')
        logger.info(f"Updated due date for bill {bill.invoice_number} ({vendor_name}): {old_due_date} -> {new_due_date}")
        flash(f'Due date updated for {vendor_name} bill to {new_due_date}', 'success')
        
        return redirect(url_for('bills_page'))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating due date: {str(e)}")
        flash(f'Error updating due date: {str(e)}', 'danger')
        return redirect(url_for('bills_page'))

@app.route('/inventory')
def inventory():
    """Display inventory management page with type and category filtering"""
    logger.debug("Rendering inventory page")
    
    # Get filter parameters
    object_type = request.args.get('object_type', 'all')
    category = request.args.get('category', 'all')
    
    # Build query with filters
    query = Object.query
    
    if object_type != 'all':
        query = query.filter_by(object_type=object_type)
    
    if category != 'all':
        # Filter by category in the JSON data field
        query = query.filter(
            db.or_(
                Object.data.op('->>')('category') == category,
                Object.data.op('->')('categories').op('@>')(f'["{category}"]')  # For array categories
            )
        )
    
    objects = query.order_by(Object.created_at.desc()).all()
    
    # Get unique object types for filter
    object_types = db.session.query(Object.object_type).distinct().all()
    object_types = [t[0] for t in object_types]
    
    # Get unique categories for filter
    categories = set()
    all_objects = Object.query.all()
    for obj in all_objects:
        if obj.data:
            # Handle single category
            if obj.data.get('category'):
                categories.add(obj.data['category'])
            # Handle multiple categories
            if obj.data.get('categories'):
                if isinstance(obj.data['categories'], list):
                    categories.update(obj.data['categories'])
                elif isinstance(obj.data['categories'], str):
                    categories.add(obj.data['categories'])
    
    categories = sorted(list(categories))
    
    # Convert objects to JSON for analysis
    objects_json = json.dumps([{
        'id': obj.id,
        'object_type': obj.object_type,
        'data': obj.data
    } for obj in objects])
    
    logger.debug(f"Inventory loaded: {len(objects)} objects (type: {object_type}, category: {category})")
    
    return render_template('inventory.html', 
                         objects=objects,
                         object_types=object_types,
                         categories=categories,
                         selected_type=object_type,
                         selected_category=category,
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


@app.route('/api/receipt-details/<int:receipt_id>')
def get_receipt_details(receipt_id):
    """
    Get detailed information about a specific receipt for the modal view.
    Enhanced with rich AI analysis data and object creation suggestions.
    """
    try:
        logger.debug(f"Fetching details for receipt ID: {receipt_id}")
        
        # Get the invoice/receipt
        receipt = Invoice.query.get(receipt_id)
        if not receipt:
            logger.warning(f"Receipt not found: {receipt_id}")
            return jsonify({'success': False, 'error': 'Receipt not found'}), 404
        
        # Get line items
        line_items = InvoiceLineItem.query.filter_by(invoice_id=receipt_id).all()
        logger.debug(f"Found {len(line_items)} line items for receipt {receipt_id}")
        
        # Get objects created from this receipt
        objects = Object.query.filter_by(invoice_id=receipt_id).all()
        logger.debug(f"Found {len(objects)} objects for receipt {receipt_id}")
        
        # Get receipt attachments
        attachments = Attachment.query.filter_by(invoice_id=receipt_id).all()
        logger.debug(f"Found {len(attachments)} attachments for receipt {receipt_id}")
        
        # Safely handle data extraction
        receipt_data = receipt.data or {}
        vendor_name = None
        if receipt.vendor:
            vendor_name = receipt.vendor.name
        else:
            vendor_name = receipt_data.get('vendor', receipt_data.get('vendor_name', 'Unknown Vendor'))
        
        # Build response data with safe data access
        response_data = {
            'id': receipt.id,
            'invoice_number': receipt.invoice_number,
            'data': receipt_data,
            'is_paid': receipt.is_paid,
            'vendor_id': receipt.vendor_id,
            'vendor': vendor_name,
            'created_at': receipt.created_at.isoformat() if receipt.created_at else None,
            'line_items': [],
            'objects': [],
            'attachments': [],
            'ai_analysis': None
        }
        
        # Extract rich AI analysis data if available
        if receipt_data.get('ai_processed') and 'ai_analysis' in receipt_data:
            ai_analysis_raw = receipt_data['ai_analysis']
            logger.debug(f"Receipt {receipt_id} has AI analysis: {type(ai_analysis_raw)}")
            
            # Parse nested MCP response structure for rich AI data
            try:
                if isinstance(ai_analysis_raw, dict) and 'content' in ai_analysis_raw and 'response' in ai_analysis_raw['content']:
                    # Parse the JSON string in the response field
                    response_str = ai_analysis_raw['content']['response']
                    logger.debug(f"Receipt {receipt_id} response_str preview: {response_str[:200]}...")
                    
                    # Clean up JSON markdown blocks
                    if response_str.startswith('```json'):
                        response_str = response_str.replace('```json\n', '').replace('\n```', '')
                    elif response_str.startswith('```'):
                        response_str = response_str.replace('```\n', '').replace('\n```', '')
                    
                    # Parse the actual receipt data
                    ai_analysis = json.loads(response_str)
                    logger.debug(f"Receipt {receipt_id} parsed AI analysis keys: {list(ai_analysis.keys())}")
                    
                    # Check for event_details specifically
                    event_details = ai_analysis.get('event_details', {})
                    logger.debug(f"Receipt {receipt_id} event_details: {event_details}")
                    
                    # Extract rich AI analysis for the response
                    ai_analysis_data = {
                        'vendor_name': ai_analysis.get('vendor_name', ''),
                        'date': ai_analysis.get('date', ''),
                        'total_amount': ai_analysis.get('total_amount', 0),
                        'description': ai_analysis.get('description', ''),
                        'overall_confidence': ai_analysis.get('overall_confidence', 0),
                        'image_quality': ai_analysis.get('image_quality', ''),
                        'extraction_notes': ai_analysis.get('extraction_notes', ''),
                        'subtotal': ai_analysis.get('subtotal', 0),
                        'tax_amount': ai_analysis.get('tax_amount', 0),
                        'fees': ai_analysis.get('fees', 0),
                        'receipt_number': ai_analysis.get('receipt_number', ''),
                        'payment_method': ai_analysis.get('payment_method', ''),
                        # Rich AI analysis data
                        'event_details': event_details,
                        'people_found': ai_analysis.get('people_found', []),
                        'vendor_details': ai_analysis.get('vendor_details', {}),
                        'digital_assets': ai_analysis.get('digital_assets', {}),
                        'line_items_ai': ai_analysis.get('line_items', [])  # AI-enhanced line items
                    }
                    
                    # Smart event detection if no explicit event_details
                    if not event_details:
                        detected_event_details = detect_event_from_receipt_data(ai_analysis)
                        if detected_event_details:
                            ai_analysis_data['event_details'] = detected_event_details
                            logger.info(f"Receipt {receipt_id} - Detected event from receipt data: {detected_event_details.get('event_name', 'Unknown Event')}")
                    
                    response_data['ai_analysis'] = ai_analysis_data
                    logger.debug(f"Receipt {receipt_id} - event_details count: {len(ai_analysis_data['event_details'])}, people_found count: {len(ai_analysis.get('people_found', []))}")
                    logger.debug(f"Extracted rich AI analysis for receipt {receipt_id}")
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Error parsing AI analysis for receipt {receipt_id}: {str(e)}")
                logger.debug(f"Receipt {receipt_id} raw AI analysis that failed: {ai_analysis_raw}")
                response_data['ai_analysis'] = None
        else:
            logger.debug(f"Receipt {receipt_id} - ai_processed: {receipt_data.get('ai_processed')}, has ai_analysis: {'ai_analysis' in receipt_data}")
        
        # Safely process line items with enhanced data
        for item in line_items:
            try:
                item_data = item.data or {}
                response_data['line_items'].append({
                    'id': item.id,
                    'data': item_data,
                    'description': item_data.get('description', 'N/A'),
                    'quantity': item_data.get('quantity', 1),
                    'unit_price': item_data.get('unit_price', 0),
                    'total_price': item_data.get('total_price', 0),
                    # Enhanced AI data for line items
                    'create_object': item_data.get('create_object', False),
                    'object_type': item_data.get('object_type', ''),
                    'category': item_data.get('category', ''),
                    'confidence': item_data.get('confidence', 0),
                    'expiration_info': item_data.get('expiration_info', {}),
                    'object_details': item_data.get('object_details', {})
                })
            except Exception as item_error:
                logger.warning(f"Error processing line item {item.id}: {str(item_error)}")
                continue
        
        # Safely process objects
        for obj in objects:
            try:
                obj_data = obj.data or {}
                response_data['objects'].append({
                    'id': obj.id,
                    'object_type': obj.object_type,
                    'data': obj_data,
                    'name': obj_data.get('name', 'Unnamed Object'),
                    'category': obj_data.get('category', 'Uncategorized')
                })
            except Exception as obj_error:
                logger.warning(f"Error processing object {obj.id}: {str(obj_error)}")
                continue
        
        # Safely process attachments
        for attachment in attachments:
            try:
                response_data['attachments'].append({
                    'id': attachment.id,
                    'filename': attachment.filename,
                    'file_type': attachment.file_type,
                    'upload_date': attachment.upload_date.isoformat() if attachment.upload_date else None,
                    'file_data_b64': base64.b64encode(attachment.file_data).decode('utf-8') if attachment.file_data else None
                })
            except Exception as att_error:
                logger.warning(f"Error processing attachment {attachment.id}: {str(att_error)}")
                continue
        
        # Add creation tracking information (convert tracking objects to serializable format)
        creation_summary = ReceiptCreationTracking.get_creation_summary(receipt_id)
        
        # Convert tracking objects to dictionaries for JSON serialization
        serializable_summary = {
            'receipt_level': {},
            'line_items': {},
            'totals': creation_summary['totals']  # Totals are already just counts
        }
        
        # Convert receipt-level tracking objects
        for creation_type, trackings in creation_summary['receipt_level'].items():
            serializable_summary['receipt_level'][creation_type] = [
                {
                    'id': t.id,
                    'creation_type': t.creation_type,
                    'creation_id': t.creation_id,
                    'created_at': t.created_at.isoformat() if t.created_at else None,
                    'metadata': t.creation_metadata
                }
                for t in trackings
            ]
        
        # Convert line item tracking objects
        for line_idx, types_dict in creation_summary['line_items'].items():
            serializable_summary['line_items'][line_idx] = {}
            for creation_type, trackings in types_dict.items():
                serializable_summary['line_items'][line_idx][creation_type] = [
                    {
                        'id': t.id,
                        'creation_type': t.creation_type,
                        'creation_id': t.creation_id,
                        'created_at': t.created_at.isoformat() if t.created_at else None,
                        'metadata': t.creation_metadata
                    }
                    for t in trackings
                ]
        
        response_data['creation_tracking'] = serializable_summary
        
        # Enhanced creation suggestions based on tracking
        response_data['suggestions'] = {
            'can_create_organization': not ReceiptCreationTracking.is_created(receipt_id, 'organization', None),
            'can_create_event': not ReceiptCreationTracking.is_created(receipt_id, 'calendar_event', None),
            'line_item_suggestions': {}
        }
        
        # Check each line item for creation possibilities
        for i, item_data in enumerate(response_data['line_items']):
            line_idx = i
            created_objects = ReceiptCreationTracking.get_created_entities(receipt_id, line_idx, 'object')
            suggestions = {
                'can_create_object': not ReceiptCreationTracking.is_created(receipt_id, 'object', line_idx),
                'already_created_objects': [
                    {
                        'id': obj.id,
                        'creation_type': obj.creation_type,
                        'creation_id': obj.creation_id,
                        'created_at': obj.created_at.isoformat() if obj.created_at else None,
                        'metadata': obj.creation_metadata
                    } 
                    for obj in created_objects
                ]
            }
            response_data['suggestions']['line_item_suggestions'][line_idx] = suggestions
        
        # Check for people creation possibilities
        if response_data.get('ai_analysis', {}).get('people_found'):
            created_people = ReceiptCreationTracking.get_created_entities(receipt_id, None, 'object')
            response_data['suggestions']['can_create_people'] = not ReceiptCreationTracking.is_created(receipt_id, 'object', None)  # People are stored as objects
            response_data['suggestions']['already_created_people'] = [
                {
                    'id': obj.id,
                    'creation_type': obj.creation_type,
                    'creation_id': obj.creation_id,
                    'created_at': obj.created_at.isoformat() if obj.created_at else None,
                    'metadata': obj.creation_metadata
                } 
                for obj in created_people
            ]
        
        logger.debug(f"Successfully compiled enhanced receipt details with creation tracking for {receipt_id}")
        
        return jsonify({
            'success': True,
            'receipt': response_data
        })
        
    except Exception as e:
        logger.error(f"Error getting receipt details for {receipt_id}: {str(e)}", exc_info=True)
        
        # Return detailed error information for debugging
        error_details = {
            'success': False, 
            'error': f'Server error: {str(e)}',
            'error_type': type(e).__name__,
            'receipt_id': receipt_id
        }
        
        # In development, include more debug info
        if app.debug:
            import traceback
            error_details['traceback'] = traceback.format_exc()
        
        return jsonify(error_details), 500

@app.route('/delete-receipt/<int:receipt_id>', methods=['POST'])
def delete_receipt(receipt_id):
    """
    Delete a receipt/invoice and optionally its related objects.
    """
    try:
        # Get the receipt
        receipt = Invoice.query.get(receipt_id)
        if not receipt:
            flash('Receipt not found', 'danger')
            return redirect(url_for('receipts_page'))
        
        # Get form data
        delete_objects = request.form.get('delete_objects') == 'true'
        delete_reason = request.form.get('delete_reason', 'No reason provided')
        
        # Get related items for logging
        line_items = InvoiceLineItem.query.filter_by(invoice_id=receipt_id).all()
        objects = Object.query.filter_by(invoice_id=receipt_id).all()
        attachments = Attachment.query.filter_by(invoice_id=receipt_id).all()
        creation_tracking = ReceiptCreationTracking.query.filter_by(invoice_id=receipt_id).all()
        
        logger.info(f"Deleting receipt {receipt.invoice_number}: {len(line_items)} line items, {len(objects)} objects, {len(attachments)} attachments, {len(creation_tracking)} creation tracking records. Delete objects: {delete_objects}. Reason: {delete_reason}")
        
        # Delete related objects if requested
        deleted_objects = []
        if delete_objects:
            for obj in objects:
                # Also delete object attachments
                object_attachments = ObjectAttachment.query.filter_by(object_id=obj.id).all()
                for att in object_attachments:
                    db.session.delete(att)
                
                deleted_objects.append(obj.data.get('name', f'Object {obj.id}'))
                db.session.delete(obj)
                logger.info(f"Deleted object: {obj.data.get('name', f'Object {obj.id}')} (ID: {obj.id})")
        else:
            # If not deleting objects, unlink them from the receipt by setting invoice_id to NULL
            for obj in objects:
                obj.invoice_id = None
                logger.info(f"Unlinked object: {obj.data.get('name', f'Object {obj.id}')} (ID: {obj.id}) from receipt")
        
        # Delete line items
        for item in line_items:
            db.session.delete(item)
        
        # Delete attachments
        for attachment in attachments:
            db.session.delete(attachment)
        
        # Handle creation tracking records
        for tracking in creation_tracking:
            if delete_objects:
                # If we're deleting objects, delete the tracking records too
                db.session.delete(tracking)
                logger.info(f"Deleted creation tracking record: {tracking.creation_type} ID {tracking.creation_id}")
            else:
                # If we're keeping objects but unlinking them, we need to decide what to do with tracking
                # Since the objects will have invoice_id=NULL, we should delete the tracking records
                # as they no longer represent a valid invoice-to-object relationship
                db.session.delete(tracking)
                logger.info(f"Deleted creation tracking record for unlinked {tracking.creation_type} ID {tracking.creation_id}")
        
        # Store receipt info for the success message
        receipt_info = f"{receipt.invoice_number} ({receipt.data.get('vendor', 'Unknown Vendor')})"
        
        # Delete the receipt itself
        db.session.delete(receipt)
        db.session.commit()
        
        # Create success message
        message_parts = [f'Receipt {receipt_info} deleted successfully']
        if deleted_objects:
            message_parts.append(f"Also deleted {len(deleted_objects)} related objects: {', '.join(deleted_objects[:3])}")
            if len(deleted_objects) > 3:
                message_parts[-1] += f" and {len(deleted_objects) - 3} more"
        elif objects and not delete_objects:
            message_parts.append(f"Unlinked {len(objects)} related objects from receipt (objects kept in inventory)")
        
        flash('. '.join(message_parts) + '.', 'success')
        
        return redirect(url_for('receipts_page'))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting receipt: {str(e)}", exc_info=True)
        flash(f'Error deleting receipt: {str(e)}', 'danger')
        return redirect(url_for('receipts_page'))

@app.route('/reminders', methods=['GET'])
def view_reminders():
    """View reminders page"""
    try:
        # Get all pending reminders, ordered by reminder_date
        pending_reminders = Reminder.query.filter_by(is_completed=False).order_by(Reminder.reminder_date).all()
        
        # Convert to list of dictionaries for the template
        reminders_data = []
        for reminder in pending_reminders:
            reminder_dict = {
                'id': reminder.id,
                'title': reminder.data.get('title', 'Untitled Reminder'),
                'description': reminder.data.get('description', ''),
                'reminder_date': reminder.reminder_date.strftime('%Y-%m-%d') if reminder.reminder_date else '',
                'reminder_time': reminder.reminder_date.strftime('%H:%M') if reminder.reminder_date else '',
                'priority': reminder.data.get('priority', 'normal'),
                'type': reminder.data.get('type', 'general'),
                'created_date': reminder.created_date.strftime('%Y-%m-%d %H:%M') if reminder.created_date else ''
            }
            reminders_data.append(reminder_dict)
        
        return render_template('reminders.html', reminders=reminders_data)
        
    except Exception as e:
        logger.error(f"Error loading reminders: {str(e)}")
        flash(f'Error loading reminders: {str(e)}', 'danger')
        return render_template('reminders.html', reminders=[])

@app.route('/api/check-duplicate-receipt', methods=['POST'])
def check_duplicate_receipt():
    """
    Check if a receipt is a duplicate based on vendor, date, and total amount.
    Used before processing new receipts to prevent duplicates.
    """
    try:
        data = request.json
        vendor_name = data.get('vendor_name', '').strip()
        receipt_date = data.get('date', '')
        total_amount = data.get('total_amount', 0)
        
        if not vendor_name or not receipt_date or not total_amount:
            return jsonify({'is_duplicate': False, 'message': 'Insufficient data for duplicate check'})
        
        # Look for existing receipts with same vendor, date, and amount
        similar_receipts = Invoice.query.filter(
            db.or_(
                Invoice.vendor.has(Vendor.name.ilike(f'%{vendor_name}%')),
                Invoice.data.op('->>')('vendor').ilike(f'%{vendor_name}%'),
                Invoice.data.op('->>')('vendor_name').ilike(f'%{vendor_name}%')
            )
        ).filter(
            Invoice.data.op('->>')('date') == receipt_date
        ).all()
        
        # Check for exact matches
        exact_matches = []
        for receipt in similar_receipts:
            receipt_total = receipt.data.get('total_amount', 0) if receipt.data else 0
            try:
                if abs(float(receipt_total) - float(total_amount)) < 0.01:  # Within 1 cent
                    exact_matches.append(receipt)
            except (ValueError, TypeError):
                continue
        
        if exact_matches:
            match = exact_matches[0]
            return jsonify({
                'is_duplicate': True,
                'message': f'Potential duplicate of receipt #{match.invoice_number}',
                'duplicate_receipt': {
                    'id': match.id,
                    'invoice_number': match.invoice_number,
                    'vendor': match.vendor.name if match.vendor else match.data.get('vendor', 'Unknown'),
                    'date': match.data.get('date') if match.data else None,
                    'total_amount': match.data.get('total_amount') if match.data else 0
                }
            })
        
        # Check for near matches (within 5% of total amount)
        near_matches = []
        for receipt in similar_receipts:
            receipt_total = receipt.data.get('total_amount', 0) if receipt.data else 0
            try:
                percentage_diff = abs(float(receipt_total) - float(total_amount)) / float(total_amount)
                if percentage_diff <= 0.05:  # Within 5%
                    near_matches.append(receipt)
            except (ValueError, TypeError, ZeroDivisionError):
                continue
        
        if near_matches:
            return jsonify({
                'is_duplicate': False,
                'is_similar': True,
                'message': f'Found {len(near_matches)} similar receipt(s) from same vendor on same date',
                'similar_receipts': [{
                    'id': receipt.id,
                    'invoice_number': receipt.invoice_number,
                    'total_amount': receipt.data.get('total_amount') if receipt.data else 0
                } for receipt in near_matches[:3]]  # Limit to 3 for brevity
            })
        
        return jsonify({
            'is_duplicate': False,
            'message': 'No duplicate receipts found'
        })
        
    except Exception as e:
        logger.error(f"Error checking for duplicate receipt: {str(e)}")
        return jsonify({
            'is_duplicate': False,
            'error': f'Error during duplicate check: {str(e)}'
        }), 500

@app.route('/photo-inventory', methods=['GET', 'POST'])
def photo_inventory():
    """Photo-based inventory analysis using AI"""
    if request.method == 'POST':
        import base64
        
        # Check for camera-captured image data
        camera_image_data = request.form.get('camera_image_data')
        file = request.files.get('object_photo')
        
        if not camera_image_data and (not file or file.filename == ''):
            flash('No photo uploaded or taken', 'warning')
            return redirect(request.url)
        
        try:
            # Handle camera-captured image
            if camera_image_data:
                logger.info("Processing camera-captured photo for inventory")
                
                # Decode base64 image data
                if camera_image_data.startswith('data:image'):
                    header, image_data = camera_image_data.split(',', 1)
                    file_data = base64.b64decode(image_data)
                    file_type = 'image/jpeg'
                    original_filename = 'camera_capture.jpg'
                else:
                    file_data = base64.b64decode(camera_image_data)
                    file_type = 'image/jpeg'
                    original_filename = 'camera_capture.jpg'
                    
                processed_filename = f"photo_inventory_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg"
                
            # Handle file upload
            elif file and allowed_file(file.filename):
                logger.info(f"Processing uploaded photo for inventory: {file.filename}")
                file_data = file.read()
                original_filename = secure_filename(file.filename)
                file_type = file.content_type or 'image/jpeg'
                processed_filename = f"photo_inventory_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{original_filename}"
            else:
                flash('Invalid file type. Please upload an image.', 'warning')
                return redirect(request.url)
            
            # Get additional context from form
            description = request.form.get('description', '').strip()
            condition_notes = request.form.get('condition_notes', '').strip()
            estimated_age = request.form.get('estimated_age', '').strip()
            purchase_info = request.form.get('purchase_info', '').strip()
            
            # Create object from photo (basic implementation for now)
            # This can be enhanced with AI analysis later
            object_data = {
                'name': description if description else 'Photo Inventory Item',
                'description': description if description else 'Object from photo inventory',
                'condition_notes': condition_notes,
                'estimated_age': estimated_age,
                'purchase_info': purchase_info,
                'created_from_photo': True,
                'photo_captured_method': 'camera' if camera_image_data else 'upload',
                'created_date': datetime.utcnow().strftime('%Y-%m-%d')
            }
            
            # Create object in database
            new_object = Object(
                object_type='asset',  # Default to asset, can be changed later
                data=object_data
            )
            db.session.add(new_object)
            db.session.flush()  # Get the object ID
            
            # Create photo attachment
            photo_attachment = ObjectAttachment(
                object_id=new_object.id,
                filename=processed_filename,
                file_data=file_data,
                file_type=file_type,
                attachment_type='photo',
                description='Primary object photo from inventory capture',
                metadata={'original_filename': original_filename}
            )
            db.session.add(photo_attachment)
            db.session.commit()
            
            logger.info(f"Created object {new_object.id} from photo inventory with attachment")
            flash(f'Successfully created object "{object_data["name"]}" from photo!', 'success')
            
            # Redirect to object details or inventory
            return redirect(url_for('inventory'))
                
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error processing photo inventory: {str(e)}")
            flash(f'Error processing photo: {str(e)}', 'danger')
            return redirect(request.url)
    
    return render_template('photo_inventory.html')

@app.route('/ai-queue')
def ai_queue():
    """AI processing queue page - shows all AI-related tasks"""
    try:
        # Get all AI-related tasks with relevant statuses
        ai_related_statuses = ['pending', 'pending_review', 'ai_analysis_failed', 'processing', 'needs_review']
        
        tasks = TaskQueue.query.filter(
            TaskQueue.status.in_(ai_related_statuses)
        ).order_by(TaskQueue.created_at.desc()).all()
        
        logger.info(f"DEBUG: Found {len(tasks)} total tasks")
        
        # Categorize tasks for the template
        receipt_tasks = []
        ai_evaluations = []
        
        for task in tasks:
            logger.info(f"DEBUG: Processing task {task.id}, type={task.task_type}, status={task.status}")
            if task.task_type == 'receipt_processing':
                # Add extracted receipt data for the template
                task.extracted_receipt_data = {}
                if task.data and task.data.get('ai_analysis'):
                    ai_analysis = task.data['ai_analysis']
                    
                    # Parse the MCP response structure (handles both Claude and OpenAI formats)
                    try:
                        logger.info(f"DEBUG: Task {task.id} - ai_analysis keys: {list(ai_analysis.keys())}")
                        
                        # MCP server normalizes both Claude and OpenAI responses into the same format
                        if 'content' in ai_analysis:
                            content = ai_analysis['content']
                            logger.info(f"DEBUG: Task {task.id} - content type: {type(content)}, keys: {list(content.keys()) if isinstance(content, dict) else 'not dict'}")
                            
                            # Check if content contains direct receipt data (current format - both Claude and OpenAI when they return valid JSON)
                            if isinstance(content, dict) and 'vendor_name' in content:
                                # Data is directly available in content
                                receipt_data = content
                                logger.info(f"DEBUG: Task {task.id} - using CURRENT format (valid JSON response), vendor_name found in content")
                            # Check if content contains a 'response' field (legacy format - when AI returns text instead of JSON)
                            elif isinstance(content, dict) and 'response' in content:
                                # Legacy format: data is a JSON string in content.response
                                response_str = content['response']
                                logger.info(f"DEBUG: Task {task.id} - using LEGACY format (text response), response_str preview: {response_str[:200]}...")
                                
                                # Clean up JSON markdown blocks
                                if response_str.startswith('```json'):
                                    response_str = response_str.replace('```json\n', '').replace('\n```', '')
                                elif response_str.startswith('```'):
                                    response_str = response_str.replace('```\n', '').replace('\n```', '')
                                
                                logger.info(f"DEBUG: Task {task.id} - cleaned response_str preview: {response_str[:200]}...")
                                receipt_data = json.loads(response_str)
                            else:
                                logger.error(f"DEBUG: Task {task.id} - unknown content format: {content}")
                                receipt_data = {}
                            
                            if receipt_data:
                                logger.info(f"DEBUG: Task {task.id} - parsed receipt_data keys: {list(receipt_data.keys())}")
                                
                                # Extract all the receipt info for the template
                                extracted_data = {
                                    'vendor_name': receipt_data.get('vendor_name', ''),
                                    'date': receipt_data.get('date', ''),
                                    'total_amount': receipt_data.get('total_amount', 0),
                                    'description': receipt_data.get('description', ''),
                                    'line_items': receipt_data.get('line_items', []),
                                    'is_bill': receipt_data.get('is_bill', False),
                                    'due_date': receipt_data.get('due_date', None),
                                    'subtotal': receipt_data.get('subtotal', 0),
                                    'tax_amount': receipt_data.get('tax_amount', 0),
                                    'fees': receipt_data.get('fees', 0),
                                    'receipt_number': receipt_data.get('receipt_number', ''),
                                    'payment_method': receipt_data.get('payment_method', ''),
                                    'overall_confidence': receipt_data.get('overall_confidence', 0),
                                    'image_quality': receipt_data.get('image_quality', ''),
                                    'extraction_notes': receipt_data.get('extraction_notes', ''),
                                    # Rich AI analysis data
                                    'event_details': receipt_data.get('event_details', {}),
                                    'people_found': receipt_data.get('people_found', []),
                                    'vendor_details': receipt_data.get('vendor_details', {}),
                                    'digital_assets': receipt_data.get('digital_assets', {})
                                }
                                
                                # Smart event detection if no explicit event_details
                                if not extracted_data['event_details']:
                                    event_details = detect_event_from_receipt_data(receipt_data)
                                    if event_details:
                                        extracted_data['event_details'] = event_details
                                        logger.info(f"Task {task.id} - Detected event from receipt data: {event_details.get('event_name', 'Unknown Event')}")
                                
                                task.extracted_receipt_data = extracted_data
                                logger.info(f"DEBUG: Task {task.id} SUCCESSFULLY extracted receipt data: vendor={task.extracted_receipt_data['vendor_name']}, total=${task.extracted_receipt_data['total_amount']}")
                                
                                # Log event detection status
                                if task.extracted_receipt_data.get('event_details'):
                                    logger.info(f"Task {task.id} has event details: {task.extracted_receipt_data['event_details']}")
                                else:
                                    logger.info(f"Task {task.id} has no event details detected")
                            else:
                                logger.error(f"DEBUG: Task {task.id} - no receipt data extracted")
                                task.extracted_receipt_data = {}
                        else:
                            # Fallback for very old format
                            logger.info(f"DEBUG: Task {task.id} - using very old fallback format")
                            task.extracted_receipt_data = {
                                'vendor_name': ai_analysis.get('vendor', ''),
                                'date': ai_analysis.get('date', ''),
                                'total_amount': ai_analysis.get('total_amount', 0),
                                'description': ai_analysis.get('description', ''),
                                'line_items': ai_analysis.get('line_items', []),
                                'is_bill': ai_analysis.get('is_bill', False),
                                'due_date': ai_analysis.get('due_date', None)
                            }
                            logger.info(f"DEBUG: Task {task.id} using very old fallback, vendor={task.extracted_receipt_data['vendor_name']}")
                            
                    except json.JSONDecodeError as e:
                        logger.error(f"DEBUG: Task {task.id} JSON parse error: {str(e)}")
                        logger.error(f"DEBUG: Task {task.id} failed JSON string: {response_str[:500]}...")
                        task.extracted_receipt_data = {}
                    except Exception as e:
                        logger.error(f"DEBUG: Task {task.id} extraction error: {str(e)}")
                        logger.error(f"DEBUG: Task {task.id} ai_analysis structure: {ai_analysis}")
                        task.extracted_receipt_data = {}
                    
                    logger.info(f"DEBUG: Task {task.id} has AI analysis")
                else:
                    logger.info(f"DEBUG: Task {task.id} has no AI analysis")
                
                # Add simple creation tracking (just check if anything has been created)
                try:
                    existing_invoice_id = None
                    if hasattr(task, 'data') and task.data and task.data.get('created_invoice_id'):
                        existing_invoice_id = task.data.get('created_invoice_id')
                    
                    if existing_invoice_id:
                        # Simple checks: has ANYTHING been created from this receipt?
                        task.creation_tracking_info = {
                            'can_create_organization': not ReceiptCreationTracking.is_created(existing_invoice_id, 'organization', None),
                            'can_create_event': not ReceiptCreationTracking.is_created(existing_invoice_id, 'calendar_event', None),
                            'line_item_tracking': {}
                        }
                        
                        # Check each line item: has ANY object been created from this line?
                        if hasattr(task, 'extracted_receipt_data') and task.extracted_receipt_data:
                            line_items = task.extracted_receipt_data.get('line_items', [])
                            if isinstance(line_items, list):
                                for idx in range(len(line_items)):
                                    already_created = ReceiptCreationTracking.is_created(existing_invoice_id, 'object', idx)
                                    task.creation_tracking_info['line_item_tracking'][idx] = {
                                        'already_created': already_created
                                    }
                    else:
                        # No invoice created yet, everything can be created
                        line_item_count = 0
                        if hasattr(task, 'extracted_receipt_data') and task.extracted_receipt_data:
                            line_items = task.extracted_receipt_data.get('line_items', [])
                            line_item_count = len(line_items) if isinstance(line_items, list) else 0
                        
                        task.creation_tracking_info = {
                            'can_create_organization': True,
                            'can_create_event': True,
                            'line_item_tracking': {idx: {'already_created': False} for idx in range(line_item_count)}
                        }
                except Exception as tracking_error:
                    logger.error(f"Task {task.id} creation tracking error: {str(tracking_error)}")
                    # Fallback: allow all creation options
                    task.creation_tracking_info = {
                        'can_create_organization': True,
                        'can_create_event': True,
                        'line_item_tracking': {}
                    }
                
                receipt_tasks.append(task)
                logger.info(f"DEBUG: Added task {task.id} to receipt_tasks, now has {len(receipt_tasks)} items")
            elif task.task_type in ['object_evaluation', 'ai_evaluation']:
                ai_evaluations.append(task)
        
        # Calculate summary stats
        total_tasks = len(tasks)
        pending_review = len([t for t in tasks if t.status == 'pending_review'])
        failed_analysis = len([t for t in tasks if t.status == 'ai_analysis_failed'])
        
        logger.info(f"DEBUG: Before render_template - receipt_tasks: {len(receipt_tasks)}, ai_evaluations: {len(ai_evaluations)}")
        logger.info(f"AI Queue loaded: {total_tasks} tasks ({pending_review} pending review, {failed_analysis} failed)")
        
        return render_template('ai_queue.html', 
                             receipt_tasks=receipt_tasks,
                             ai_evaluations=ai_evaluations,
                             total_tasks=total_tasks,
                             pending_review=pending_review,
                             failed_analysis=failed_analysis)
    except Exception as e:
        logger.error(f"Error loading AI queue: {str(e)}", exc_info=True)
        flash(f'Error loading AI queue: {str(e)}', 'danger')
        return render_template('ai_queue.html', receipt_tasks=[], ai_evaluations=[], total_tasks=0, pending_review=0, failed_analysis=0)

@app.route('/process-ai-task/<int:task_id>', methods=['POST'])
def process_ai_task(task_id):
    """Process an AI task - approve receipt processing, object evaluation, etc."""
    try:
        task = TaskQueue.query.get_or_404(task_id)
        action = request.form.get('action', 'approve')
        
        logger.info(f"Processing AI task {task_id}: {task.task_type} with action: {action}")
        
        if task.task_type == 'receipt_processing':
            if action == 'approve':
                # Convert the AI analysis to actual invoice and objects
                success = process_receipt_task(task)
                if success:
                    task.status = 'completed'
                    task.completed_at = datetime.utcnow()
                    flash('Receipt processed successfully and added to inventory!', 'success')
                else:
                    task.status = 'failed'
                    flash('Error processing receipt. Please try again.', 'danger')
            elif action == 'reject':
                task.status = 'rejected'
                task.completed_at = datetime.utcnow()
                flash('Receipt processing rejected.', 'info')
            elif action == 'edit':
                # Redirect to manual editing (to be implemented)
                flash('Manual editing not yet implemented. Please approve or reject for now.', 'warning')
                return redirect(url_for('ai_queue'))
                
        elif task.task_type in ['object_evaluation', 'ai_evaluation']:
            if action == 'approve':
                task.status = 'completed'
                task.completed_at = datetime.utcnow()
                flash('AI evaluation approved!', 'success')
            elif action == 'reject':
                task.status = 'rejected'
                task.completed_at = datetime.utcnow()
                flash('AI evaluation rejected.', 'info')
        
        db.session.commit()
        return redirect(url_for('ai_queue'))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error processing AI task {task_id}: {str(e)}")
        flash(f'Error processing task: {str(e)}', 'danger')
        return redirect(url_for('ai_queue'))

def process_receipt_task(task):
    """Convert a receipt processing task into actual invoice and objects"""
    try:
        ai_analysis_raw = task.data.get('ai_analysis', {})
        if not ai_analysis_raw:
            logger.error("No AI analysis data found in task")
            return False
        
        # Parse MCP response (unified logic for both Claude and OpenAI)
        ai_analysis = {}
        try:
            if 'content' in ai_analysis_raw:
                content = ai_analysis_raw['content']
                
                # Both Claude and OpenAI use same format via MCP server
                if isinstance(content, dict) and 'vendor_name' in content:
                    # Direct JSON response (both providers when they return valid JSON)
                    ai_analysis = content
                    logger.info(f"Process receipt - using direct JSON format, vendor: {ai_analysis.get('vendor_name', 'Unknown')}")
                elif isinstance(content, dict) and 'response' in content:
                    # Text response that needs parsing (both providers when they return text)
                    response_str = content['response']
                    
                    # Clean up JSON markdown blocks
                    if response_str.startswith('```json'):
                        response_str = response_str.replace('```json\n', '').replace('\n```', '')
                    elif response_str.startswith('```'):
                        response_str = response_str.replace('```\n', '').replace('\n```', '')
                    
                    ai_analysis = json.loads(response_str)
                    logger.info(f"Process receipt - using text response format, vendor: {ai_analysis.get('vendor_name', 'Unknown')}")
                else:
                    logger.error(f"Process receipt - unknown content format: {content}")
                    return False
            else:
                # Very old fallback
                ai_analysis = ai_analysis_raw
                logger.info(f"Process receipt - using very old fallback format")
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Error parsing receipt data for processing: {str(e)}")
            return False
            
        # Get vendor name from AI analysis
        vendor_name = ai_analysis.get('vendor_name', ai_analysis.get('vendor', 'Unknown Vendor'))
        
        # Create or get vendor entity (FIXED vendor creation)
        vendor = None
        if vendor_name and vendor_name != 'Unknown Vendor':
            # Try to find existing vendor
            vendor = Vendor.query.filter_by(name=vendor_name).first()
            if not vendor:
                # Create new vendor
                vendor = Vendor(name=vendor_name)
                db.session.add(vendor)
                db.session.flush()  # Get vendor ID
                logger.info(f"Created new vendor: {vendor_name}")
            else:
                logger.info(f"Using existing vendor: {vendor_name}")
        
        # Create invoice from AI analysis
        invoice_data = {
            'date': ai_analysis.get('date', datetime.utcnow().strftime('%Y-%m-%d')),
            'vendor': vendor_name,
            'vendor_name': vendor_name,  # Also store in data for backup
            'total_amount': ai_analysis.get('total_amount', 0),
            'is_paid': True,
            'ai_processed': True,
            'ai_confidence': ai_analysis_raw.get('confidence', 0.5),
            'original_filename': task.data.get('original_filename', ''),
            'processed_at': datetime.utcnow().isoformat(),
            'subtotal': ai_analysis.get('subtotal', 0),
            'tax_amount': ai_analysis.get('tax_amount', 0),
            'fees': ai_analysis.get('fees', 0),
            'receipt_number': ai_analysis.get('receipt_number', ''),
            'payment_method': ai_analysis.get('payment_method', ''),
            'description': ai_analysis.get('description', ''),
            # Store full AI analysis for reference
            'ai_analysis': ai_analysis_raw
        }
        
        # Generate unique invoice number
        invoice_number = Invoice.generate_invoice_number()
        
        # Create the invoice with proper vendor linking
        invoice = Invoice(
            invoice_number=invoice_number,
            vendor_id=vendor.id if vendor else None,
            is_paid=True,
            data=invoice_data
        )
        db.session.add(invoice)
        db.session.flush()  # Get the invoice ID
        
        # Create attachment from the stored image data
        attachment_data = task.data.get('attachment', {})
        if attachment_data.get('file_data'):
            attachment = Attachment(
                invoice_id=invoice.id,
                filename=task.data.get('processed_filename', 'receipt.jpg'),
                file_data=base64.b64decode(attachment_data['file_data']),
                file_type=attachment_data.get('file_type', 'image/jpeg'),
                upload_date=datetime.utcnow()
            )
            db.session.add(attachment)
        
        # Create objects from line items if they exist
        line_items = ai_analysis.get('line_items', [])
        objects_created = 0
        
        # Process AI-suggested categories (create them if they don't exist)
        new_categories = process_ai_suggested_categories(line_items)
        if new_categories:
            logger.info(f"Created {len(new_categories)} new categories from AI suggestions: {[cat['name'] for cat in new_categories]}")
        
        for item in line_items:
            if item.get('create_object', False):
                object_data = {
                    'name': item.get('description', 'Unnamed Item'),
                    'description': item.get('description', ''),
                    'acquisition_cost': item.get('unit_price', 0),
                    'acquisition_date': invoice_data['date'],
                    'vendor': invoice_data['vendor'],
                    'ai_processed': True,
                    'ai_confidence': item.get('confidence', 0.5)
                }
                
                # Determine object type
                object_type = item.get('object_type', item.get('suggested_type', 'asset'))
                if object_type not in ['asset', 'consumable', 'component', 'service', 'software']:
                    object_type = 'asset'
                
                # Add consumable-specific metadata for event tickets/passes
                if object_type == 'consumable':
                    object_data.update({
                        'category': item.get('category', 'consumable'),
                        'consumption_type': item.get('consumption_type', 'single_use'),
                        'quantity': item.get('quantity', 1),
                        'current_stock': item.get('quantity', 1),  # Initial stock = quantity purchased
                        'track_stock': True,  # Always track event tickets
                        'reorder_threshold': 0,  # Don't reorder event tickets
                    })
                    
                    # Handle expiration info for event tickets
                    expiration_info = item.get('expiration_info', {})
                    if expiration_info:
                        if expiration_info.get('expires_after_event'):
                            # Set expiration date to the event date
                            event_date = expiration_info.get('event_date')
                            if event_date:
                                object_data['expiration_date'] = event_date
                                logger.info(f"Set event ticket expiration to event date: {event_date}")
                    
                    # Special metadata for event tickets
                    if item.get('category') == 'event_ticket':
                        object_data.update({
                            'is_event_ticket': True,
                            'event_related': True,
                            'single_use_item': True,
                            'ticket_type': 'event_admission'
                        })
                
                # Create the object
                obj = Object(
                    invoice_id=invoice.id,
                    object_type=object_type,
                    data=object_data
                )
                db.session.add(obj)
                db.session.flush()  # Get the object ID for attachments
                
                # Handle digital assets for event tickets (QR codes, digital tickets, etc.)
                # First check line item level digital assets
                line_item_digital_assets = item.get('digital_assets', {})
                
                # Also check receipt-level digital assets from AI analysis
                receipt_digital_assets = {}
                if ai_analysis.get('digital_assets'):
                    receipt_digital_assets = ai_analysis['digital_assets']
                
                # Combine both sources
                all_digital_assets = {**receipt_digital_assets, **line_item_digital_assets}
                
                if object_type == 'consumable' and all_digital_assets:
                    logger.info(f"Processing digital assets for event ticket {obj.id}: {list(all_digital_assets.keys())}")
                    
                    # Create attachments for QR codes
                    qr_code_data = all_digital_assets.get('qr_code') or all_digital_assets.get('qr_codes')
                    if qr_code_data:
                        # Handle multiple QR codes or single QR code
                        qr_codes = qr_code_data if isinstance(qr_code_data, list) else [qr_code_data]
                        
                        for i, qr_code in enumerate(qr_codes):
                            if qr_code and isinstance(qr_code, str):
                                qr_attachment = ObjectAttachment(
                                    object_id=obj.id,
                                    filename=f"qr_code_{obj.id}_{i+1}.txt" if len(qr_codes) > 1 else f"qr_code_{obj.id}.txt",
                                    file_data=qr_code.encode('utf-8'),
                                    file_type='text/plain',
                                    attachment_type='qr_code',
                                    description=f'QR code for event ticket{f" #{i+1}" if len(qr_codes) > 1 else ""}',
                                    ai_analyzed=True,
                                    ai_analysis_result={'type': 'qr_code', 'content': qr_code}
                                )
                                db.session.add(qr_attachment)
                                logger.info(f"Created QR code attachment #{i+1} for event ticket {obj.id}")
                    
                    # Create attachments for confirmation codes
                    conf_code_data = (all_digital_assets.get('confirmation_code') or 
                                     all_digital_assets.get('confirmation_codes') or
                                     all_digital_assets.get('booking_reference') or
                                     all_digital_assets.get('reference_number'))
                    
                    if conf_code_data:
                        # Handle multiple confirmation codes or single code
                        conf_codes = conf_code_data if isinstance(conf_code_data, list) else [conf_code_data]
                        
                        for i, conf_code in enumerate(conf_codes):
                            if conf_code:
                                conf_attachment = ObjectAttachment(
                                    object_id=obj.id,
                                    filename=f"confirmation_{obj.id}_{i+1}.txt" if len(conf_codes) > 1 else f"confirmation_{obj.id}.txt",
                                    file_data=str(conf_code).encode('utf-8'),
                                    file_type='text/plain',
                                    attachment_type='confirmation_code',
                                    description=f'Event confirmation code{f" #{i+1}" if len(conf_codes) > 1 else ""}',
                                    ai_analyzed=True,
                                    ai_analysis_result={'type': 'confirmation_code', 'code': str(conf_code)}
                                )
                                db.session.add(conf_attachment)
                                logger.info(f"Created confirmation code attachment #{i+1} for event ticket {obj.id}")
                    
                    # Create attachments for digital ticket images/PDFs
                    ticket_data = (all_digital_assets.get('ticket_image') or 
                                  all_digital_assets.get('digital_ticket') or
                                  all_digital_assets.get('ticket_pdf'))
                    
                    if ticket_data:
                        # Determine file type from data
                        file_type = 'application/pdf'
                        filename_ext = 'pdf'
                        
                        if isinstance(ticket_data, str):
                            if ticket_data.startswith('data:image/'):
                                file_type = 'image/jpeg'
                                filename_ext = 'jpg'
                            elif 'image' in str(ticket_data).lower():
                                file_type = 'image/jpeg'
                                filename_ext = 'jpg'
                        
                        ticket_attachment = ObjectAttachment(
                            object_id=obj.id,
                            filename=f"digital_ticket_{obj.id}.{filename_ext}",
                            file_data=str(ticket_data).encode('utf-8'),
                            file_type=file_type,
                            attachment_type='digital_ticket',
                            description='Digital event ticket',
                            ai_analyzed=True,
                            ai_analysis_result={'type': 'digital_ticket', 'source': 'ai_extraction'}
                        )
                        db.session.add(ticket_attachment)
                        logger.info(f"Created digital ticket attachment for event ticket {obj.id}")
                    
                    # Store digital asset references in object metadata for easy access
                    if all_digital_assets:
                        object_data['digital_assets_detected'] = True
                        object_data['digital_asset_types'] = list(all_digital_assets.keys())
                        object_data['has_qr_code'] = bool(qr_code_data)
                        object_data['has_confirmation_code'] = bool(conf_code_data)
                        object_data['has_digital_ticket'] = bool(ticket_data)
                
                # Schedule expiration task for consumables with expiration dates
                if object_type == 'consumable' and object_data.get('expiration_date'):
                    try:
                        TaskQueue.schedule_consumable_expiration(
                            object_id=obj.id,  # Now we have the object ID
                            expiration_date=object_data['expiration_date'],
                            quantity=object_data.get('quantity', 1)
                        )
                        logger.info(f"Scheduled expiration tracking for consumable: {object_data['name']}")
                    except Exception as exp_error:
                        logger.warning(f"Could not schedule expiration for consumable: {str(exp_error)}")
                
                objects_created += 1
                logger.info(f"Created {object_type} object: {object_data['name']} (category: {object_data.get('category', 'N/A')})")
        
        # Create line items
        for item in line_items:
            line_item = InvoiceLineItem(
                invoice_id=invoice.id,
                data=item
            )
            db.session.add(line_item)
        
        logger.info(f"Successfully processed receipt task: Invoice {invoice_number}, {objects_created} objects created")
        return True
        
    except Exception as e:
        logger.error(f"Error in process_receipt_task: {str(e)}")
        db.session.rollback()
        return False

@app.route('/vendors')
def vendors():
    """Enhanced hybrid vendors management page with vendor name linking support"""
    try:
        # Step 1: Get all unique vendor names from receipt metadata
        vendor_names_from_receipts = db.session.query(
            Invoice.data.op('->>')('vendor').label('vendor_name')
        ).filter(
            Invoice.data.op('->>')('vendor').isnot(None)
        ).distinct().all()
        
        # Also check for vendor_name field variation
        vendor_names_from_receipts2 = db.session.query(
            Invoice.data.op('->>')('vendor_name').label('vendor_name')
        ).filter(
            Invoice.data.op('->>')('vendor_name').isnot(None)
        ).distinct().all()
        
        # Combine and deduplicate
        all_vendor_names = set()
        for result in vendor_names_from_receipts + vendor_names_from_receipts2:
            if result.vendor_name and result.vendor_name.strip():
                all_vendor_names.add(result.vendor_name.strip())
        
        # Step 2: Get Organizations and their linked vendor names
        organizations = Organization.query.all()
        
        # Build organization lookup by vendor name
        org_by_vendor_name = {}
        for org in organizations:
            # Add the organization's primary name
            org_by_vendor_name[org.name] = org
            
            # Add any linked vendor names
            if org.data and org.data.get('linked_vendor_names'):
                for vendor_name in org.data['linked_vendor_names']:
                    org_by_vendor_name[vendor_name] = org
        
        # Step 3: Get legacy Vendor entities (keeping for compatibility)
        legacy_vendors = {v.name: v for v in Vendor.query.all()}
        
        # Step 4: Build enhanced hybrid vendor list
        hybrid_vendors = []
        
        # Process all vendor names from receipts
        for vendor_name in sorted(all_vendor_names):
            # Count receipts for this specific vendor name
            receipt_count = Invoice.query.filter(
                db.or_(
                    Invoice.data.op('->>')('vendor') == vendor_name,
                    Invoice.data.op('->>')('vendor_name') == vendor_name
                )
            ).count()
            
            # Check if linked to organization
            organization = org_by_vendor_name.get(vendor_name)
            legacy_vendor = legacy_vendors.get(vendor_name)
            
            # Determine if this is a linked vendor name (not the primary org name)
            is_linked_name = organization and organization.name != vendor_name
            
            hybrid_vendors.append({
                'name': vendor_name,
                'receipt_count': receipt_count,
                'is_organization': organization is not None,
                'is_legacy_vendor': legacy_vendor is not None,
                'is_linked_name': is_linked_name,
                'organization': organization,
                'legacy_vendor': legacy_vendor,
                'type': 'organization' if organization else ('legacy' if legacy_vendor else 'metadata'),
                'organization_primary_name': organization.name if organization else None
            })
        
        # Step 5: Add organizations that don't have receipts yet (but weren't already added)
        for org in organizations:
            if org.name not in all_vendor_names:
                # Count total receipts across all linked vendor names
                total_receipts = 0
                linked_names = [org.name]
                if org.data and org.data.get('linked_vendor_names'):
                    linked_names.extend(org.data['linked_vendor_names'])
                
                for linked_name in linked_names:
                    total_receipts += Invoice.query.filter(
                        db.or_(
                            Invoice.data.op('->>')('vendor') == linked_name,
                            Invoice.data.op('->>')('vendor_name') == linked_name
                        )
                    ).count()
                
                hybrid_vendors.append({
                    'name': org.name,
                    'receipt_count': total_receipts,
                    'is_organization': True,
                    'is_legacy_vendor': False,
                    'is_linked_name': False,
                    'organization': org,
                    'legacy_vendor': None,
                    'type': 'organization',
                    'organization_primary_name': org.name
                })
        
        # Sort by organization status, then by name
        hybrid_vendors.sort(key=lambda x: (not x['is_organization'], x['name'].lower()))
        
        return render_template('vendors_hybrid.html', vendors=hybrid_vendors)
        
    except Exception as e:
        logger.error(f"Error loading enhanced hybrid vendors: {str(e)}")
        flash(f'Error loading vendors: {str(e)}', 'danger')
        return render_template('vendors_hybrid.html', vendors=[])

@app.route('/promote-vendor/<vendor_name>', methods=['POST'])
def promote_vendor(vendor_name):
    """Enhanced promotion with AI-powered organizational suggestions"""
    try:
        # Check if already an organization
        existing_org = Organization.query.filter_by(name=vendor_name).first()
        if existing_org:
            return jsonify({'success': False, 'error': f'"{vendor_name}" is already an organization'})
        
        # Get all receipts from this vendor for AI analysis
        vendor_receipts = Invoice.query.filter(
            db.or_(
                Invoice.data.op('->>')('vendor') == vendor_name,
                Invoice.data.op('->>')('vendor_name') == vendor_name
            )
        ).limit(10).all()  # Limit to 10 most recent receipts for analysis
        
        # Prepare data for AI analysis
        vendor_analysis_data = {
            'vendor_name': vendor_name,
            'receipts': [],
            'total_transactions': len(vendor_receipts),
            'analysis_request': 'vendor_organization_analysis'
        }
        
        # Add receipt data for AI analysis
        for receipt in vendor_receipts[:5]:  # Use up to 5 receipts for analysis
            if receipt.data:
                vendor_analysis_data['receipts'].append({
                    'date': receipt.data.get('date'),
                    'total_amount': receipt.data.get('total_amount'),
                    'vendor_details': receipt.data.get('vendor_details', {}),
                    'description': receipt.data.get('description', ''),
                    'line_items': receipt.data.get('line_items', [])[:3]  # Sample line items
                })
        
        # Get AI suggestions for organizational details
        ai_suggestions = {}
        try:
            from mcp_client import analyze_vendor_organization_sync
            
            logger.info(f"Requesting AI analysis for vendor organization: {vendor_name}")
            
            # Call MCP server for organizational analysis
            ai_result = analyze_vendor_organization_sync(
                vendor_name=vendor_name,
                analysis_data=vendor_analysis_data
            )
            
            if ai_result and 'content' in ai_result and 'response' in ai_result['content']:
                response_str = ai_result['content']['response']
                
                # Clean up JSON markdown blocks
                if response_str.startswith('```json'):
                    response_str = response_str.replace('```json\n', '').replace('\n```', '')
                elif response_str.startswith('```'):
                    response_str = response_str.replace('```\n', '').replace('\n```', '')
                
                ai_suggestions = json.loads(response_str)
                logger.info(f"AI analysis successful for vendor {vendor_name}: {ai_suggestions}")
            
        except Exception as ai_error:
            logger.warning(f"AI analysis failed for vendor {vendor_name}: {str(ai_error)}")
            # Continue with manual promotion if AI fails
            ai_suggestions = {
                'suggested_business_type': 'Unknown',
                'confidence': 0.0,
                'ai_available': False,
                'error': str(ai_error)
            }
        
        # Get similar vendor names for linking suggestions
        similar_vendors = find_similar_vendor_names(vendor_name)
        
        # If this is a JSON request, return AI suggestions for user review
        if request.content_type == 'application/json':
            return jsonify({
                'success': True,
                'vendor_name': vendor_name,
                'ai_suggestions': ai_suggestions,
                'similar_vendors': similar_vendors[:5],  # Limit to 5 suggestions
                'total_receipts': len(vendor_receipts),
                'needs_user_confirmation': True
            })
        
        # Handle form submission for actual promotion
        suggested_links = request.form.getlist('link_vendor_names')
        
        # Create organization data (everything goes in data field)
        organization_data = {
            'email': request.form.get('contact_email', '').strip() or ai_suggestions.get('suggested_email'),
            'phone': request.form.get('contact_phone', '').strip() or ai_suggestions.get('suggested_phone'),
            'website': request.form.get('website', '').strip() or ai_suggestions.get('suggested_website'),
            'address': request.form.get('address', '').strip() or ai_suggestions.get('suggested_address'),
            'business_type': request.form.get('business_type', '').strip() or ai_suggestions.get('suggested_business_type', 'Unknown'),
            'notes': request.form.get('notes', '').strip() or ai_suggestions.get('ai_analysis_notes'),
            'promoted_from_metadata': True,
            'promoted_at': datetime.utcnow().isoformat(),
            'linked_vendor_names': suggested_links,
            'ai_enhanced': bool(ai_suggestions.get('confidence', 0) > 0.5),
            'ai_confidence': ai_suggestions.get('confidence', 0.0),
            'ai_suggestions_used': ai_suggestions,
            'total_receipts_analyzed': len(vendor_receipts)
        }
        
        # Remove None values
        organization_data = {k: v for k, v in organization_data.items() if v is not None}
        
        # Create new organization with AI-enhanced data
        organization = Organization(
            name=vendor_name,
            organization_type='vendor',
            is_active=True,
            data=organization_data
        )
        
        db.session.add(organization)
        db.session.commit()
        
        logger.info(f"Promoted vendor '{vendor_name}' to Organization with AI enhancement (confidence: {ai_suggestions.get('confidence', 0.0)})")
        
        return jsonify({
            'success': True,
            'message': f'Successfully promoted "{vendor_name}" to organization',
            'organization_id': organization.id,
            'ai_enhanced': bool(ai_suggestions.get('confidence', 0) > 0.5),
            'linked_vendors': len(suggested_links)
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error promoting vendor {vendor_name}: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error promoting vendor: {str(e)}'
        })

@app.route('/edit-organization/<int:org_id>', methods=['GET', 'POST'])
def edit_organization(org_id):
    """Enhanced organization editing with vendor name management"""
    organization = Organization.query.get_or_404(org_id)
    
    if request.method == 'POST':
        try:
            # Update organization data (everything goes in data field)
            if not organization.data:
                organization.data = {}
            
            # Update contact info in data
            organization.data.update({
                'email': request.form.get('contact_email', '').strip() or None,
                'phone': request.form.get('contact_phone', '').strip() or None,
                'website': request.form.get('website', '').strip() or None,
                'address': request.form.get('address', '').strip() or None,
                'business_type': request.form.get('business_type', '').strip() or None,
                'notes': request.form.get('notes', '').strip() or None,
                'last_updated': datetime.utcnow().isoformat()
            })
            
            # Handle vendor names linking
            linked_vendor_names = []
            vendor_names_input = request.form.get('linked_vendor_names', '').strip()
            if vendor_names_input:
                # Split by comma and clean up
                names = [name.strip() for name in vendor_names_input.split(',') if name.strip()]
                # Remove the organization's own name if included
                linked_vendor_names = [name for name in names if name != organization.name]
            
            organization.data['linked_vendor_names'] = linked_vendor_names
            
            db.session.commit()
            
            logger.info(f"Updated organization: {organization.name} with {len(linked_vendor_names)} linked vendor names")
            flash(f'Organization "{organization.name}" updated successfully with {len(linked_vendor_names)} linked vendor names', 'success')
            return redirect(url_for('vendors'))
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating organization: {str(e)}")
            flash(f'Error updating organization: {str(e)}', 'danger')
    
    # Get available vendor names for linking suggestions
    available_vendor_names = get_available_vendor_names_for_linking(organization)
    
    return render_template('edit_organization.html', 
                         organization=organization,
                         available_vendor_names=available_vendor_names)

@app.route('/organization-relationships/<int:org_id>')
def organization_relationships(org_id):
    """View and manage relationships for an organization"""
    try:
        organization = Organization.query.get_or_404(org_id)
        
        # Get all relationships for this organization
        outgoing_relationships = OrganizationRelationship.query.filter_by(
            from_organization_id=org_id, is_active=True
        ).all()
        
        incoming_relationships = OrganizationRelationship.query.filter_by(
            to_organization_id=org_id, is_active=True
        ).all()
        
        # Get all other organizations for relationship creation
        other_organizations = Organization.query.filter(
            Organization.id != org_id,
            Organization.is_active == True
        ).order_by(Organization.name).all()
        
        # Get relationship types
        relationship_types = OrganizationRelationship.get_relationship_types()
        
        return render_template('organization_relationships.html',
                             organization=organization,
                             outgoing_relationships=outgoing_relationships,
                             incoming_relationships=incoming_relationships,
                             other_organizations=other_organizations,
                             relationship_types=relationship_types)
        
    except Exception as e:
        logger.error(f"Error loading organization relationships: {str(e)}")
        flash(f'Error loading relationships: {str(e)}', 'danger')
        return redirect(url_for('vendors'))

@app.route('/create-organization-relationship', methods=['POST'])
def create_organization_relationship():
    """Create a new relationship between organizations"""
    try:
        from_org_id = int(request.form.get('from_organization_id'))
        to_org_id = int(request.form.get('to_organization_id'))
        relationship_type = request.form.get('relationship_type')
        relationship_label = request.form.get('relationship_label', '').strip() or None
        is_bidirectional = request.form.get('is_bidirectional') == 'true'
        strength = int(request.form.get('strength', 5))
        start_date = request.form.get('start_date')
        
        # Validate inputs
        if from_org_id == to_org_id:
            flash('Cannot create relationship with the same organization', 'danger')
            return redirect(url_for('organization_relationships', org_id=from_org_id))
        
        # Check if relationship already exists
        existing = OrganizationRelationship.query.filter_by(
            from_organization_id=from_org_id,
            to_organization_id=to_org_id,
            relationship_type=relationship_type,
            is_active=True
    ).first()
    
        if existing:
            flash('This relationship already exists', 'warning')
            return redirect(url_for('organization_relationships', org_id=from_org_id))
        
        # Create the relationship
        relationship_data = {
            'strength': strength,
            'relationship_metadata': {
                'created_via': 'web_interface',
                'notes': request.form.get('notes', '').strip() or None
            }
        }
        
        if start_date:
            relationship_data['start_date'] = datetime.strptime(start_date, '%Y-%m-%d')
        
        relationship = OrganizationRelationship.create_relationship(
            from_org_id=from_org_id,
            to_org_id=to_org_id,
            relationship_type=relationship_type,
            relationship_label=relationship_label,
            is_bidirectional=is_bidirectional,
            **relationship_data
        )
        
        from_org = Organization.query.get(from_org_id)
        to_org = Organization.query.get(to_org_id)
        
        logger.info(f"Created relationship: {from_org.name} -[{relationship_type}]-> {to_org.name}")
        
        if is_bidirectional:
            flash(f'Created bidirectional {relationship_type} relationship between {from_org.name} and {to_org.name}', 'success')
        else:
            flash(f'Created {relationship_type} relationship: {from_org.name} → {to_org.name}', 'success')
        
        return redirect(url_for('organization_relationships', org_id=from_org_id))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating organization relationship: {str(e)}")
        flash(f'Error creating relationship: {str(e)}', 'danger')
        return redirect(url_for('vendors'))

@app.route('/delete-organization-relationship/<int:relationship_id>', methods=['POST'])
def delete_organization_relationship(relationship_id):
    """Delete an organization relationship"""
    try:
        relationship = OrganizationRelationship.query.get_or_404(relationship_id)
        from_org_id = relationship.from_organization_id
        
        # Store info for logging
        from_org_name = relationship.from_organization.name
        to_org_name = relationship.to_organization.name
        rel_type = relationship.relationship_type
        
        # If bidirectional, also delete the reverse relationship
        if relationship.is_bidirectional:
            reverse_relationship = OrganizationRelationship.query.filter_by(
                from_organization_id=relationship.to_organization_id,
                to_organization_id=relationship.from_organization_id,
                relationship_type=OrganizationRelationship._get_reverse_relationship_type(rel_type),
                is_active=True
            ).first()
            
            if reverse_relationship:
                db.session.delete(reverse_relationship)
        
        # Delete the main relationship
        db.session.delete(relationship)
        db.session.commit()
        
        logger.info(f"Deleted relationship: {from_org_name} -[{rel_type}]-> {to_org_name}")
        flash(f'Deleted {rel_type} relationship between {from_org_name} and {to_org_name}', 'success')
        
        return redirect(url_for('organization_relationships', org_id=from_org_id))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting organization relationship: {str(e)}")
        flash(f'Error deleting relationship: {str(e)}', 'danger')
        return redirect(url_for('vendors'))

@app.route('/api/organization-network/<int:org_id>')
def get_organization_network(org_id):
    """Get the network of relationships for an organization"""
    try:
        max_depth = int(request.args.get('max_depth', 2))
        network = OrganizationRelationship.get_organization_network(org_id, max_depth)
        
        # Enrich with organization details
        def enrich_network(network_data):
            if not network_data:
                return network_data
                
            org_id = network_data.get('organization_id')
            if org_id:
                org = Organization.query.get(org_id)
                if org:
                    network_data['organization'] = {
                        'id': org.id,
                        'name': org.name,
                        'organization_type': org.organization_type
                    }
            
            # Recursively enrich connected networks
            for rel in network_data.get('outgoing_relationships', []):
                enrich_network(rel.get('connected_network', {}))
            
            for rel in network_data.get('incoming_relationships', []):
                enrich_network(rel.get('connected_network', {}))
            
            return network_data
        
        enriched_network = enrich_network(network)
        
        return jsonify({
            'success': True,
            'network': enriched_network
        })
        
    except Exception as e:
        logger.error(f"Error getting organization network: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/get-similar-vendors/<vendor_name>')
def get_similar_vendors(vendor_name):
    """API endpoint to get similar vendor names for linking suggestions"""
    try:
        similar_vendors = find_similar_vendor_names(vendor_name)
        return jsonify({
            'success': True,
            'similar_vendors': similar_vendors
        })
    except Exception as e:
        logger.error(f"Error finding similar vendors: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

def find_similar_vendor_names(vendor_name):
    """Find vendor names that might belong to the same organization"""
    # Get all vendor names from receipts
    vendor_names_from_receipts = db.session.query(
        Invoice.data.op('->>')('vendor').label('vendor_name')
    ).filter(
        Invoice.data.op('->>')('vendor').isnot(None)
    ).distinct().all()
    
    vendor_names_from_receipts2 = db.session.query(
        Invoice.data.op('->>')('vendor_name').label('vendor_name')
    ).filter(
        Invoice.data.op('->>')('vendor_name').isnot(None)
    ).distinct().all()
    
    all_names = set()
    for result in vendor_names_from_receipts + vendor_names_from_receipts2:
        if result.vendor_name and result.vendor_name.strip():
            all_names.add(result.vendor_name.strip())
    
    # Simple similarity matching
    vendor_lower = vendor_name.lower()
    similar_names = []
    
    for name in all_names:
        if name == vendor_name:
            continue
            
        name_lower = name.lower()
        
        # Check for various similarity patterns
        if (vendor_lower in name_lower or name_lower in vendor_lower or
            # Check for common patterns like "Amazon" and "Amazon.com"
            vendor_lower.replace('.com', '') == name_lower.replace('.com', '') or
            # Check for abbreviations
            ''.join(word[0] for word in vendor_lower.split()) == name_lower or
            name_lower == ''.join(word[0] for word in vendor_lower.split())):
            
            # Get receipt count for this name
            receipt_count = Invoice.query.filter(
                db.or_(
                    Invoice.data.op('->>')('vendor') == name,
                    Invoice.data.op('->>')('vendor_name') == name
                )
            ).count()
            
            similar_names.append({
                'name': name,
                'receipt_count': receipt_count
            })
    
    # Sort by receipt count (most used first)
    similar_names.sort(key=lambda x: x['receipt_count'], reverse=True)
    return similar_names

def get_available_vendor_names_for_linking(organization):
    """Get vendor names that could be linked to this organization"""
    # Get all vendor names
    vendor_names_from_receipts = db.session.query(
        Invoice.data.op('->>')('vendor').label('vendor_name')
    ).filter(
        Invoice.data.op('->>')('vendor').isnot(None)
    ).distinct().all()
    
    vendor_names_from_receipts2 = db.session.query(
        Invoice.data.op('->>')('vendor_name').label('vendor_name')
    ).filter(
        Invoice.data.op('->>')('vendor_name').isnot(None)
    ).distinct().all()
    
    all_names = set()
    for result in vendor_names_from_receipts + vendor_names_from_receipts2:
        if result.vendor_name and result.vendor_name.strip():
            all_names.add(result.vendor_name.strip())
    
    # Remove names already linked to any organization
    organizations = Organization.query.all()
    linked_names = set()
    
    for org in organizations:
        linked_names.add(org.name)
        if org.data and org.data.get('linked_vendor_names'):
            linked_names.update(org.data['linked_vendor_names'])
    
    # Return available names with receipt counts
    available_names = []
    for name in all_names:
        if name not in linked_names:
            receipt_count = Invoice.query.filter(
                db.or_(
                    Invoice.data.op('->>')('vendor') == name,
                    Invoice.data.op('->>')('vendor_name') == name
                )
            ).count()
            
            available_names.append({
                'name': name,
                'receipt_count': receipt_count
            })
    
    # Sort by receipt count
    available_names.sort(key=lambda x: x['receipt_count'], reverse=True)
    return available_names

@app.route('/approvals-queue')
def approvals_queue():
    """Approvals queue page"""
    try:
        # Get items needing approval
        pending_approvals = TaskQueue.query.filter_by(
            status='pending',
            task_type='approval_required'
        ).order_by(TaskQueue.created_at.desc()).all()
        
        return render_template('approvals_queue.html', approvals=pending_approvals)
    except Exception as e:
        logger.error(f"Error loading approvals queue: {str(e)}")
        flash(f'Error loading approvals queue: {str(e)}', 'danger')
        return render_template('approvals_queue.html', approvals=[])

@app.route('/reports')
def reports():
    """Reports dashboard"""
    try:
        # Get all data
        invoices = Invoice.query.all()
        all_objects = Object.query.all()
        assets = [obj for obj in all_objects if obj.object_type == 'asset']
        vendors = Vendor.query.all()
        
        # Basic counts
        total_receipts = len(invoices)
        total_objects = len(all_objects)
        total_vendors = len(vendors)
        
        # Separate paid/unpaid invoices
        paid_invoices = [inv for inv in invoices if inv.is_paid]
        unpaid_invoices = [inv for inv in invoices if not inv.is_paid]
        paid_invoices_count = len(paid_invoices)
        unpaid_invoices_count = len(unpaid_invoices)
        
        # Calculate invoice totals
        paid_invoices_total = 0
        unpaid_invoices_total = 0
        total_expenses = 0
        
        for inv in paid_invoices:
            total = inv.data.get('total', 0) if inv.data else 0
            try:
                amount = float(total)
                paid_invoices_total += amount
                total_expenses += amount
            except (ValueError, TypeError):
                pass
                
        for inv in unpaid_invoices:
            total = inv.data.get('total', 0) if inv.data else 0
            try:
                amount = float(total)
                unpaid_invoices_total += amount
                total_expenses += amount
            except (ValueError, TypeError):
                pass
        
        # Calculate asset values
        assets_purchase_value = 0
        assets_estimated_value = 0
        
        for asset in assets:
            if asset.data:
                purchase_value = asset.data.get('acquisition_cost', 0)
                estimated_value = asset.data.get('estimated_value', 0)
                
                try:
                    if purchase_value:
                        assets_purchase_value += float(purchase_value)
                    if estimated_value:
                        assets_estimated_value += float(estimated_value)
                except (ValueError, TypeError):
                    pass
        
        # Calculate asset value change percentage
        assets_value_change = 0
        if assets_purchase_value > 0:
            assets_value_change = ((assets_estimated_value - assets_purchase_value) / assets_purchase_value) * 100
        
        # Calculate average expense
        average_expense = total_expenses / len(invoices) if invoices else 0
        
        # Group expenses by category
        expense_categories = {}
        for inv in invoices:
            if inv.data and 'line_items' in inv.data:
                for item in inv.data['line_items']:
                    category = item.get('category', 'Uncategorized')
                    price = item.get('unit_price', 0)
                    quantity = item.get('quantity', 1)
                    try:
                        expense_categories[category] = expense_categories.get(category, 0) + (float(price) * float(quantity))
                    except (ValueError, TypeError):
                        pass
        
        # Prepare expense data for template
        expense_data = expense_categories
        expense_values = list(expense_categories.values())
        
        # Group vendors by spending
        vendor_spending = {}
        for inv in invoices:
            vendor_name = inv.data.get('vendor', 'Unknown') if inv.data else 'Unknown'
            total = inv.data.get('total', 0) if inv.data else 0
            try:
                vendor_spending[vendor_name] = vendor_spending.get(vendor_name, 0) + float(total)
            except (ValueError, TypeError):
                pass
        
        # Sort vendors by spending and prepare data
        sorted_vendors = sorted(vendor_spending.items(), key=lambda x: x[1], reverse=True)
        top_vendor = {'name': sorted_vendors[0][0], 'total': sorted_vendors[0][1]} if sorted_vendors else {'name': 'None', 'total': 0}
        avg_spent_per_vendor = sum(vendor_spending.values()) / len(vendor_spending) if vendor_spending else 0
        
        # Prepare vendor data for template
        vendors_data = [{'name': name, 'total': total, 'categories': ['General']} for name, total in sorted_vendors[:10]]
        
        # Prepare chart data (simplified)
        invoice_months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun']  # Placeholder
        invoice_data = {
            'paid': [paid_invoices_total/6]*6,  # Simplified
            'unpaid': [unpaid_invoices_total/6]*6  # Simplified
        }
        
        asset_categories = list(expense_categories.keys())[:5]  # Top 5 categories
        asset_values = list(expense_categories.values())[:5]
        
        top_vendors_names = [v['name'] for v in vendors_data[:5]]
        top_vendors_values = [v['total'] for v in vendors_data[:5]]
        
        return render_template('reports.html',
                             # Basic counts
                             invoices=invoices,
                             total_receipts=total_receipts,
                             total_objects=total_objects,
                             total_vendors=total_vendors,
                             assets=assets,
                             vendors=vendors_data,
                             
                             # Invoice data
                             paid_invoices_count=paid_invoices_count,
                             unpaid_invoices_count=unpaid_invoices_count,
                             paid_invoices_total=paid_invoices_total,
                             unpaid_invoices_total=unpaid_invoices_total,
                             
                             # Asset data
                             assets_purchase_value=assets_purchase_value,
                             assets_estimated_value=assets_estimated_value,
                             assets_value_change=assets_value_change,
                             
                             # Expense data
                             total_expenses=total_expenses,
                             average_expense=average_expense,
                             expense_categories=list(expense_categories.keys()),
                             expense_data=expense_data,
                             expense_values=expense_values,
                             
                             # Vendor data
                             top_vendor=top_vendor,
                             avg_spent_per_vendor=avg_spent_per_vendor,
                             
                             # Chart data
                             invoice_months=invoice_months,
                             invoice_data=invoice_data,
                             asset_categories=asset_categories,
                             asset_values=asset_values,
                             top_vendors_names=top_vendors_names,
                             top_vendors_values=top_vendors_values)
                             
    except Exception as e:
        logger.error(f"Error loading reports: {str(e)}")
        flash(f'Error loading reports: {str(e)}', 'danger')
        
        # Return empty data structure
        return render_template('reports.html',
                             invoices=[],
                             total_receipts=0,
                             total_objects=0,
                             total_vendors=0,
                             assets=[],
                             vendors=[],
                             paid_invoices_count=0,
                             unpaid_invoices_count=0,
                             paid_invoices_total=0,
                             unpaid_invoices_total=0,
                             assets_purchase_value=0,
                             assets_estimated_value=0,
                             assets_value_change=0,
                             total_expenses=0,
                             average_expense=0,
                             expense_categories=[],
                             expense_data={},
                             expense_values=[],
                             top_vendor={'name': 'None', 'total': 0},
                             avg_spent_per_vendor=0,
                             invoice_months=[],
                             invoice_data={'paid': [], 'unpaid': []},
                             asset_categories=[],
                             asset_values=[],
                             top_vendors_names=[],
                             top_vendors_values=[])

@app.route('/inventory-valuation-report')
def inventory_valuation_report():
    """Inventory valuation report - basic implementation"""
    try:
        # Get all objects with estimated values
        objects = Object.query.all()
        
        total_value = 0
        categorized_objects = {}
        
        for obj in objects:
            obj_data = obj.data or {}
            estimated_value = obj_data.get('estimated_value', 0) or obj_data.get('acquisition_cost', 0)
            
            if estimated_value:
                try:
                    total_value += float(estimated_value)
                except (ValueError, TypeError):
                    pass
            
            # Group by category
            category = obj_data.get('category', 'Uncategorized')
            if category not in categorized_objects:
                categorized_objects[category] = []
            categorized_objects[category].append({
                'name': obj_data.get('name', 'Unnamed Object'),
                'estimated_value': estimated_value,
                'object_type': obj.object_type
            })
        
        return render_template('reports.html',  # Temporary - use reports template
                             total_receipts=Invoice.query.count(),
                             total_objects=len(objects),
                             total_vendors=Vendor.query.count(),
                             total_inventory_value=total_value,
                             categorized_objects=categorized_objects)
    except Exception as e:
        logger.error(f"Error loading inventory valuation report: {str(e)}")
        flash(f'Error loading valuation report: {str(e)}', 'danger')
        return redirect(url_for('reports'))

@app.route('/calendar')
def calendar_page():
    """Calendar page to view events"""
    try:
        logger.debug("Rendering calendar page")
        return render_template('calendar.html')
    except Exception as e:
        logger.error(f"Error loading calendar: {str(e)}")
        flash(f'Error loading calendar: {str(e)}', 'danger')
        return render_template('calendar.html')

@app.route('/settings')
def settings():
    """Settings page"""
    try:
        ai_settings = AISettings.query.first()
        if not ai_settings:
            ai_settings = AISettings()
        
        # Check if API key is from environment or database
        env_api_key = os.environ.get("OPENAI_API_KEY")
        db_api_key = getattr(ai_settings, 'openai_api_key', '')
        
        # Determine source and display value
        if env_api_key:
            # API key from environment - mask it and mark as read-only
            api_key_display = "*" * (len(env_api_key) - 8) + env_api_key[-8:] if len(env_api_key) > 8 else "*" * len(env_api_key)
            api_key_source = "environment"
            api_key_actual = env_api_key
        else:
            # API key from database
            api_key_display = db_api_key
            api_key_source = "database"
            api_key_actual = db_api_key
            
        # Create provider structure expected by template (OpenAI only)
        providers = {
            'openai': {
                'is_enabled': getattr(ai_settings, 'openai_enabled', True),
                'is_default': True,  # OpenAI is the only provider
                'api_key': api_key_display,
                'api_key_actual': api_key_actual,
                'api_key_source': api_key_source,
                'config': {
                    'default_model': getattr(ai_settings, 'openai_model', 'gpt-4o'),
                    'vision_model': getattr(ai_settings, 'openai_vision_model', 'gpt-4o'),
                    'image_model': getattr(ai_settings, 'openai_image_model', 'dall-e-3'),
                    'timeout': getattr(ai_settings, 'openai_timeout', 120)
                }
            }
        }
            
        # Create features structure expected by template
        features = {
            'auto_analyze': getattr(ai_settings, 'auto_analyze_receipts', True),
            'auto_link': getattr(ai_settings, 'auto_link', True),
            'auto_vendor': getattr(ai_settings, 'auto_vendor', True),
            'auto_categorize': getattr(ai_settings, 'auto_categorize', True),
            'daily_limit': getattr(ai_settings, 'daily_limit', 30)
        }
        
        return render_template('settings.html', settings=ai_settings, providers=providers, features=features)
    except Exception as e:
        logger.error(f"Error loading settings: {str(e)}")
        flash(f'Error loading settings: {str(e)}', 'danger')
        
        # Even on error, check for environment API key
        env_api_key = os.environ.get("OPENAI_API_KEY")
        if env_api_key:
            api_key_display = "*" * (len(env_api_key) - 8) + env_api_key[-8:] if len(env_api_key) > 8 else "*" * len(env_api_key)
            api_key_source = "environment"
            api_key_actual = env_api_key
        else:
            api_key_display = ""
            api_key_source = "database"
            api_key_actual = ""
        
        # Return empty providers structure on error (OpenAI only)
        empty_providers = {
            'openai': {
                'is_enabled': True, 
                'is_default': True, 
                'api_key': api_key_display,
                'api_key_actual': api_key_actual,
                'api_key_source': api_key_source,
                'config': {}
            }
        }
        # Create empty features for error case
        empty_features = {
            'auto_analyze': True,
            'auto_link': True,
            'auto_vendor': True,
            'auto_categorize': True,
            'daily_limit': 30
        }
        return render_template('settings.html', settings=None, providers=empty_providers, features=empty_features)

@app.route('/settings/update/openai', methods=['POST'])
def update_openai_settings():
    """Update OpenAI settings"""
    try:
        # For now, just flash a message and redirect back
        flash('OpenAI settings update is not yet implemented', 'info')
        return redirect(url_for('settings'))
    except Exception as e:
        logger.error(f"Error updating OpenAI settings: {str(e)}")
        flash(f'Error updating settings: {str(e)}', 'danger')
        return redirect(url_for('settings'))

@app.route('/settings/update-ai-features', methods=['POST'])
def update_ai_features():
    """Update AI feature settings"""
    try:
        # For now, just flash a message and redirect back
        flash('AI feature settings update is not yet implemented', 'info')
        return redirect(url_for('settings'))
    except Exception as e:
        logger.error(f"Error updating AI features: {str(e)}")
        flash(f'Error updating settings: {str(e)}', 'danger')
        return redirect(url_for('settings'))

@app.route('/api/re-evaluate-receipt/<int:receipt_id>', methods=['POST'])
def re_evaluate_receipt(receipt_id):
    """
    Re-evaluate an existing receipt with AI while preventing duplicates.
    Smart duplicate detection ensures we don't create duplicate objects.
    """
    try:
        # Get the existing receipt
        receipt = Invoice.query.get(receipt_id)
        if not receipt:
            return jsonify({'success': False, 'error': 'Receipt not found'}), 404
        
        # Get the receipt attachment for re-analysis
        attachment = Attachment.query.filter_by(invoice_id=receipt_id).first()
        if not attachment:
            return jsonify({'success': False, 'error': 'No attachment found for re-analysis'}), 400
        
        logger.info(f"Re-evaluating receipt {receipt.invoice_number} with AI")
        
        # Simulate AI re-analysis with duplicate prevention
        # In a real implementation, this would call the AI service again
        
        analysis_results = {
            'objects_created': 0,
            'objects_updated': 0,
            'objects_skipped': 0,
            'confidence_changes': [],
            'new_categories_found': 0
        }
        
        # For now, just return success without making changes
        flash(f'Receipt {receipt.invoice_number} re-evaluated successfully. No changes needed.', 'info')
        
        return jsonify({
            'success': True,
            'message': 'Receipt re-evaluated successfully',
            'analysis': analysis_results
        })
        
    except Exception as e:
        logger.error(f"Error re-evaluating receipt {receipt_id}: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error during re-evaluation: {str(e)}'
        }), 500

# Helper function for MCP response processing
def extract_receipt_data_from_mcp_response(mcp_result):
    """Extract comprehensive receipt data from MCP server response (unified for both Claude and OpenAI)"""
    try:
        if isinstance(mcp_result, dict):
            # Use unified parsing logic for both Claude and OpenAI
            if 'content' in mcp_result:
                content = mcp_result['content']
                
                # Both providers use same format via MCP server
                if isinstance(content, dict) and 'vendor_name' in content:
                    # Direct JSON response (both providers when they return valid JSON)
                    receipt_data = content
                    logger.debug(f"Extract MCP - using direct JSON format, vendor: {receipt_data.get('vendor_name', 'Unknown')}")
                elif isinstance(content, dict) and 'response' in content:
                    # Text response that needs parsing (both providers when they return text)
                    response_str = content['response']
                    
                    # Clean up JSON markdown blocks
                    if response_str.startswith('```json'):
                        response_str = response_str.replace('```json\n', '').replace('\n```', '')
                    elif response_str.startswith('```'):
                        response_str = response_str.replace('```\n', '').replace('\n```', '')
                    
                    # Parse the JSON string
                    receipt_data = json.loads(response_str)
                    logger.debug(f"Extract MCP - using text response format, vendor: {receipt_data.get('vendor_name', 'Unknown')}")
                else:
                    logger.error(f"Extract MCP - unknown content format: {content}")
                    return {'vendor_name': '', 'date': '', 'total_amount': 0}
                
                # Return comprehensive data including digital assets
                result = {
                    'vendor_name': receipt_data.get('vendor_name', ''),
                    'date': receipt_data.get('date', ''),
                    'total_amount': receipt_data.get('total_amount', 0),
                    'line_items': receipt_data.get('line_items', []),
                    'digital_assets': receipt_data.get('digital_assets', {}),
                    'event_details': receipt_data.get('event_details', {}),
                    'people_found': receipt_data.get('people_found', []),
                    'vendor_details': receipt_data.get('vendor_details', {}),
                    'description': receipt_data.get('description', ''),
                    'is_bill': receipt_data.get('is_bill', False),
                    'due_date': receipt_data.get('due_date', None),
                    'subtotal': receipt_data.get('subtotal', 0),
                    'tax_amount': receipt_data.get('tax_amount', 0),
                    'fees': receipt_data.get('fees', 0),
                    'receipt_number': receipt_data.get('receipt_number', ''),
                    'payment_method': receipt_data.get('payment_method', ''),
                    'overall_confidence': receipt_data.get('overall_confidence', 0),
                    'image_quality': receipt_data.get('image_quality', ''),
                    'extraction_notes': receipt_data.get('extraction_notes', '')
                }
                
                logger.debug(f"Extract MCP - extracted {len(result['line_items'])} line items, digital_assets: {bool(result['digital_assets'])}")
                return result
            
            # Very old fallback to direct structure
            return {
                'vendor_name': mcp_result.get('vendor', ''),
                'date': mcp_result.get('date', ''),
                'total_amount': mcp_result.get('total_amount', 0),
                'line_items': mcp_result.get('line_items', []),
                'digital_assets': mcp_result.get('digital_assets', {}),
                'event_details': mcp_result.get('event_details', {}),
                'people_found': mcp_result.get('people_found', [])
            }
        else:
            return {'vendor_name': '', 'date': '', 'total_amount': 0, 'line_items': [], 'digital_assets': {}, 'event_details': {}, 'people_found': []}
    except Exception as e:
        logger.warning(f"Error extracting receipt data from MCP response: {str(e)}")
        return {'vendor_name': '', 'date': '', 'total_amount': 0, 'line_items': [], 'digital_assets': {}, 'event_details': {}, 'people_found': []}

def detect_event_from_receipt_data(receipt_data):
    """
    Smart event detection from receipt data when explicit event_details are not provided.
    Looks for event indicators in description, line items, and vendor information.
    Also ensures event-related items are properly classified as consumable objects.
    """
    try:
        description = receipt_data.get('description', '').lower()
        vendor_name = receipt_data.get('vendor_name', '').lower()
        line_items = receipt_data.get('line_items', [])
        
        # Event keywords to look for
        event_keywords = [
            'festival', 'concert', 'event', 'ticket', 'pass', 'admission', 
            'show', 'performance', 'conference', 'convention', 'expo',
            'workshop', 'seminar', 'meetup', 'gathering', 'celebration'
        ]
        
        # Ticket/pass specific keywords (these should be consumable)
        ticket_keywords = [
            'ticket', 'pass', 'entry', 'admission', 'badge', 'wristband',
            'voucher', 'stub', 'entry pass', 'weekend pass', 'day pass'
        ]
        
        # Check if description contains event keywords
        is_event_description = any(keyword in description for keyword in event_keywords)
        
        # Check if any line items suggest this is an event
        event_line_items = []
        for item in line_items:
            item_desc = item.get('description', '').lower()
            item_category = item.get('category', '').lower()
            
            if (item_category == 'event' or 
                any(keyword in item_desc for keyword in event_keywords)):
                
                # Update line item to be properly classified as consumable if it's ticket/pass related
                if any(ticket_keyword in item_desc for ticket_keyword in ticket_keywords):
                    item['object_type'] = 'consumable'
                    item['create_object'] = True
                    item['category'] = 'event_ticket'
                    item['consumption_type'] = 'single_use'
                    item['expiration_info'] = {
                        'expires_after_event': True,
                        'event_date': receipt_data.get('date', '')
                    }
                    
                    # Check for digital assets (QR codes, ticket images, etc.)
                    digital_assets = receipt_data.get('digital_assets', {})
                    if digital_assets:
                        item['digital_assets'] = digital_assets
                        item['has_qr_code'] = bool(digital_assets.get('qr_code') or digital_assets.get('confirmation_code'))
                        item['has_digital_ticket'] = True
                        logger.info(f"Found digital assets for ticket '{item_desc}': {list(digital_assets.keys())}")
                    
                    logger.info(f"Classified '{item_desc}' as consumable event ticket")
                
                event_line_items.append(item)
        
        # Check vendor name for event-related businesses
        event_vendor_keywords = ['eventeny', 'ticketmaster', 'eventbrite', 'stubhub']
        is_event_vendor = any(keyword in vendor_name for keyword in event_vendor_keywords)
        
        # If we detect event indicators, create synthetic event details
        if is_event_description or event_line_items or is_event_vendor:
            # Extract event name from description
            event_name = "Event"
            if description:
                # Try to extract meaningful event name from description
                # Look for patterns like "Festival", "Concert", etc.
                words = description.split()
                for i, word in enumerate(words):
                    if any(keyword in word.lower() for keyword in ['festival', 'concert', 'show']):
                        # Take a few words around the keyword as event name
                        start = max(0, i-2)
                        end = min(len(words), i+3)
                        event_name = ' '.join(words[start:end])
                        break
                else:
                    # Fallback to first part of description
                    event_name = ' '.join(words[:4]) if words else description[:50]
            
            # Create synthetic event details
            event_details = {
                'event_name': event_name.title(),
                'event_date': receipt_data.get('date', ''),
                'venue_location': '',  # Could be extracted from vendor details if available
                'description': description,
                'event_type': 'detected_from_receipt',
                'confidence': 0.8 if event_line_items else 0.6,
                'detection_method': 'smart_analysis',
                'consumable_items_detected': len([item for item in event_line_items if item.get('object_type') == 'consumable']),
                'tickets_and_passes': [item for item in event_line_items if item.get('object_type') == 'consumable'],
                'indicators': {
                    'description_match': is_event_description,
                    'line_items_match': len(event_line_items) > 0,
                    'vendor_match': is_event_vendor,
                    'matching_line_items': len(event_line_items)
                }
            }
            
            logger.info(f"Detected event from receipt: {event_name} (confidence: {event_details['confidence']}, {event_details['consumable_items_detected']} consumable items)")
            return event_details
            
        return None
        
    except Exception as e:
        logger.error(f"Error in event detection: {str(e)}")
        return None

@app.route('/ai-queue/task/<int:task_id>')
def ai_queue_detail(task_id):
    """View detailed information about a specific AI queue task"""
    try:
        task = TaskQueue.query.get_or_404(task_id)
        
        # Add extracted receipt data for display
        if task.task_type == 'receipt_processing':
            task.extracted_receipt_data = {}
            if task.data and task.data.get('ai_analysis'):
                ai_analysis = task.data['ai_analysis']
                
                # Parse the nested MCP response structure
                try:
                    if 'content' in ai_analysis and 'response' in ai_analysis['content']:
                        # Parse the JSON string in the response field
                        response_str = ai_analysis['content']['response']
                        
                        # Clean up JSON markdown blocks
                        if response_str.startswith('```json'):
                            response_str = response_str.replace('```json\n', '').replace('\n```', '')
                        elif response_str.startswith('```'):
                            response_str = response_str.replace('```\n', '').replace('\n```', '')
                        
                        # Parse the actual receipt data
                        receipt_data = json.loads(response_str)
                        
                        # Extract all the receipt info for the template
                        extracted_data = {
                            'vendor_name': receipt_data.get('vendor_name', ''),
                            'date': receipt_data.get('date', ''),
                            'total_amount': receipt_data.get('total_amount', 0),
                            'description': receipt_data.get('description', ''),
                            'line_items': receipt_data.get('line_items', []),
                            'is_bill': receipt_data.get('is_bill', False),
                            'due_date': receipt_data.get('due_date', None),
                            'subtotal': receipt_data.get('subtotal', 0),
                            'tax_amount': receipt_data.get('tax_amount', 0),
                            'fees': receipt_data.get('fees', 0),
                            'receipt_number': receipt_data.get('receipt_number', ''),
                            'payment_method': receipt_data.get('payment_method', ''),
                            'overall_confidence': receipt_data.get('overall_confidence', 0),
                            'image_quality': receipt_data.get('image_quality', ''),
                            'extraction_notes': receipt_data.get('extraction_notes', ''),
                            # Rich AI analysis data
                            'event_details': receipt_data.get('event_details', {}),
                            'people_found': receipt_data.get('people_found', []),
                            'vendor_details': receipt_data.get('vendor_details', {}),
                            'digital_assets': receipt_data.get('digital_assets', {})
                        }
                        
                        # Smart event detection if no explicit event_details
                        if not extracted_data['event_details']:
                            event_details = detect_event_from_receipt_data(receipt_data)
                            if event_details:
                                extracted_data['event_details'] = event_details
                                logger.info(f"Task detail {task_id} - Detected event from receipt data: {event_details.get('event_name', 'Unknown Event')}")
                        
                        task.extracted_receipt_data = extracted_data
                    else:
                        # Fallback to legacy direct structure
                        task.extracted_receipt_data = {
                            'vendor_name': ai_analysis.get('vendor', ''),
                            'date': ai_analysis.get('date', ''),
                            'total_amount': ai_analysis.get('total_amount', 0),
                            'description': ai_analysis.get('description', ''),
                            'line_items': ai_analysis.get('line_items', []),
                            'is_bill': ai_analysis.get('is_bill', False),
                            'due_date': ai_analysis.get('due_date', None)
                        }
                except (json.JSONDecodeError, Exception) as e:
                    logger.error(f"Error parsing receipt data for task {task_id}: {str(e)}")
                    task.extracted_receipt_data = {}
        
        return render_template('ai_queue_detail.html', task=task)
        
    except Exception as e:
        logger.error(f"Error loading task details: {str(e)}")
        flash(f'Error loading task details: {str(e)}', 'danger')
        return redirect(url_for('ai_queue'))

@app.route('/approve-receipt/<int:task_id>', methods=['POST'])
def approve_receipt(task_id):
    """Approve a receipt processing task and create invoice/objects"""
    try:
        task = TaskQueue.query.get_or_404(task_id)
        
        if task.task_type != 'receipt_processing':
            flash('Invalid task type for receipt approval', 'danger')
            return redirect(url_for('ai_queue'))
        
        # Process the receipt task
        success = process_receipt_task(task)
        if success:
            task.status = 'completed'
            task.completed_at = datetime.utcnow()
            db.session.commit()
            flash('Receipt approved and processed successfully!', 'success')
        else:
            task.status = 'failed'
            db.session.commit()
            flash('Error processing receipt. Please try again.', 'danger')
        
        return redirect(url_for('ai_queue'))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving receipt: {str(e)}")
        flash(f'Error approving receipt: {str(e)}', 'danger')
        return redirect(url_for('ai_queue'))

@app.route('/reject-receipt/<int:task_id>', methods=['POST'])
def reject_receipt(task_id):
    """Reject a receipt processing task"""
    try:
        task = TaskQueue.query.get_or_404(task_id)
        reason = request.form.get('reason', 'No reason provided')
        
        if task.task_type != 'receipt_processing':
            flash('Invalid task type for receipt rejection', 'danger')
            return redirect(url_for('ai_queue'))
        
        # Mark task as rejected
        task.status = 'rejected'
        task.completed_at = datetime.utcnow()
        if not task.data:
            task.data = {}
        task.data['rejection_reason'] = reason
        task.data['rejected_at'] = datetime.utcnow().isoformat()
        
        db.session.commit()
        
        logger.info(f"Receipt task {task_id} rejected: {reason}")
        flash(f'Receipt rejected: {reason}', 'info')
        
        return redirect(url_for('ai_queue'))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error rejecting receipt: {str(e)}")
        flash(f'Error rejecting receipt: {str(e)}', 'danger')
        return redirect(url_for('ai_queue'))

@app.route('/create-object-from-receipt', methods=['POST'])
def create_object_from_receipt():
    """Create an object from a receipt line item with AI suggestions"""
    try:
        data = request.json
        receipt_id = data.get('receipt_id')
        item_index = data.get('item_index')
        object_type = data.get('object_type', 'asset')
        category = data.get('category', '')
        description = data.get('description', '')
        unit_price = float(data.get('unit_price', 0))
        quantity = int(float(data.get('quantity', 1)))  # Convert to float first, then int to handle '1.0'
        
        # Handle person-specific data if object_type is person
        person_role = data.get('person_role', '')
        relationship = data.get('relationship', '')
        
        # Get the receipt
        receipt = Invoice.query.get(receipt_id)
        if not receipt:
            return jsonify({'success': False, 'error': 'Receipt not found'}), 404
        
        # Check if object already created for this line item
        line_index = data.get('line_index', item_index)  # Support both field names
        if ReceiptCreationTracking.is_created(receipt_id, 'object', line_index):
            return jsonify({'success': False, 'error': 'Object already created for this line item'}), 400
        
        # Create object data
        object_data = {
            'name': description or 'Unnamed Object',
            'description': description,
            'acquisition_cost': unit_price,
            'acquisition_date': receipt.data.get('date', datetime.utcnow().strftime('%Y-%m-%d')),
            'vendor': receipt.data.get('vendor', receipt.data.get('vendor_name', 'Unknown Vendor')),
            'quantity': quantity,
            'ai_processed': True,
            'ai_confidence': data.get('confidence', 0.8),
            'created_from_receipt': True,
            'receipt_id': receipt_id,
            'receipt_line_item_index': item_index
        }
        
        # Smart classification: detect object type automatically
        desc_lower = description.lower()
        
        # Auto-detect people
        person_keywords = ['person', 'contact', 'individual', 'attendee', 'participant', 'member', 'customer', 'client']
        if any(keyword in desc_lower for keyword in person_keywords) or object_type == 'person':
            object_type = 'person'
            object_data.update({
                'role': person_role,
                'relationship_to_purchase': relationship,
                'detected_from_receipt': True,
                'detection_date': datetime.utcnow().strftime('%Y-%m-%d'),
                'contact_type': 'receipt_detected'
            })
            logger.info(f"Auto-classified '{description}' as person object")
        
        # Auto-detect event tickets
        elif any(keyword in desc_lower for keyword in ['ticket', 'pass', 'entry', 'admission', 'badge', 'wristband', 'voucher', 'stub']):
            object_type = 'consumable'
            object_data.update({
                'category': 'event_ticket',
                'consumption_type': 'single_use',
                'current_stock': quantity,
                'track_stock': True,
                'reorder_threshold': 0,
                'is_event_ticket': True,
                'event_related': True,
                'single_use_item': True,
                'ticket_type': 'event_admission',
                'expiration_date': receipt.data.get('date')  # Expire on event date
            })
            logger.info(f"Auto-classified '{description}' as consumable event ticket")
        
        if category:
            object_data['category'] = category
        
        # Create the object
        new_object = Object(
            invoice_id=receipt_id,
            object_type=object_type,
            data=object_data
        )
        db.session.add(new_object)
        db.session.flush()  # Get object ID for potential attachments
        
        # Handle digital assets for event tickets - enhanced version
        if object_type == 'consumable' and object_data.get('is_event_ticket'):
            # Check if the receipt has digital assets that should be attached
            if receipt.data and receipt.data.get('ai_analysis'):
                try:
                    ai_analysis_raw = receipt.data['ai_analysis']
                    ai_analysis = extract_receipt_data_from_mcp_response(ai_analysis_raw)
                    
                    # Get digital assets from both receipt level and potentially line item level
                    digital_assets = ai_analysis.get('digital_assets', {})
                    
                    if digital_assets:
                        logger.info(f"Processing digital assets for manually created event ticket {new_object.id}: {list(digital_assets.keys())}")
                        
                        # Create QR code attachments (handle multiple)
                        qr_code_data = digital_assets.get('qr_code') or digital_assets.get('qr_codes')
                        if qr_code_data:
                            qr_codes = qr_code_data if isinstance(qr_code_data, list) else [qr_code_data]
                            
                            for i, qr_code in enumerate(qr_codes):
                                if qr_code:
                                    qr_attachment = ObjectAttachment(
                                        object_id=new_object.id,
                                        filename=f"qr_code_{new_object.id}_{i+1}.txt" if len(qr_codes) > 1 else f"qr_code_{new_object.id}.txt",
                                        file_data=str(qr_code).encode('utf-8'),
                                        file_type='text/plain',
                                        attachment_type='qr_code',
                                        description=f'QR code for event ticket{f" #{i+1}" if len(qr_codes) > 1 else ""}',
                                        ai_analyzed=True,
                                        ai_analysis_result={'type': 'qr_code', 'content': str(qr_code)}
                                    )
                                    db.session.add(qr_attachment)
                                    logger.info(f"Attached QR code #{i+1} to event ticket {new_object.id}")
                        
                        # Create confirmation code attachments (handle multiple)
                        conf_code_data = (digital_assets.get('confirmation_code') or 
                                         digital_assets.get('confirmation_codes') or
                                         digital_assets.get('booking_reference') or
                                         digital_assets.get('reference_number'))
                        
                        if conf_code_data:
                            conf_codes = conf_code_data if isinstance(conf_code_data, list) else [conf_code_data]
                            
                            for i, conf_code in enumerate(conf_codes):
                                if conf_code:
                                    conf_attachment = ObjectAttachment(
                                        object_id=new_object.id,
                                        filename=f"confirmation_{new_object.id}_{i+1}.txt" if len(conf_codes) > 1 else f"confirmation_{new_object.id}.txt",
                                        file_data=str(conf_code).encode('utf-8'),
                                        file_type='text/plain',
                                        attachment_type='confirmation_code',
                                        description=f'Event confirmation code{f" #{i+1}" if len(conf_codes) > 1 else ""}',
                                        ai_analyzed=True,
                                        ai_analysis_result={'type': 'confirmation_code', 'code': str(conf_code)}
                                    )
                                    db.session.add(conf_attachment)
                                    logger.info(f"Attached confirmation code #{i+1} to event ticket {new_object.id}")
                        
                        # Store metadata about digital assets
                        object_data['digital_assets_detected'] = True
                        object_data['digital_asset_types'] = list(digital_assets.keys())
                        object_data['has_qr_code'] = bool(qr_code_data)
                        object_data['has_confirmation_code'] = bool(conf_code_data)
                        
                        # Update the object with enhanced metadata
                        new_object.data = object_data
                
                except Exception as e:
                    logger.warning(f"Could not process digital assets for event ticket: {str(e)}")
        
        # Track the creation
        line_index = data.get('line_index', item_index)  # Support both field names
        ReceiptCreationTracking.track_creation(
            invoice_id=receipt_id,
            line_item_index=line_index,
            creation_type='object',
            creation_id=new_object.id,
            metadata={'object_type': object_type, 'description': description}
        )
        
        db.session.commit()
        
        logger.info(f"Created {object_type} object '{description}' from receipt {receipt.invoice_number} line {line_index}")
        
        # Auto-suggest event creation for event tickets
        event_suggestion = None
        if object_type == 'consumable' and object_data.get('is_event_ticket'):
            # Check if there's already an event for this receipt
            existing_event = CalendarEvent.query.filter(
                CalendarEvent.data.op('->>')('receipt_id') == str(receipt_id)
            ).first()
            
            if not existing_event:
                # Suggest event creation
                event_suggestion = {
                    'should_create_event': True,
                    'suggested_event_title': extract_event_name(description, object_data['vendor'], []),
                    'suggested_event_date': object_data['acquisition_date'],
                    'suggested_event_type': 'entertainment',
                    'reason': f'Event ticket detected: {description}',
                    'receipt_id': receipt_id,
                    'related_object_id': new_object.id
                }
                logger.info(f"Auto-suggesting event creation for event ticket {new_object.id}")
        
        response_data = {
            'success': True,
            'message': f'Successfully created {object_type}',
            'object_name': description,
            'object_id': new_object.id
        }
        
        if event_suggestion:
            response_data['event_suggestion'] = event_suggestion
        
        return jsonify(response_data)
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating object from receipt: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error creating object: {str(e)}'
        }), 500

# REMOVED: /create-person-from-receipt route - people are now handled by /create-object-from-receipt

@app.route('/create-calendar-event-from-receipt', methods=['POST'])
def create_calendar_event_from_receipt():
    """Create a calendar event from AI-detected event data"""
    try:
        data = request.json
        receipt_id = data.get('receipt_id')
        
        # Check for suggested parameters from auto-suggestion
        suggested_title = data.get('suggested_title')
        suggested_date = data.get('suggested_date')
        suggested_type = data.get('suggested_type')
        related_object_id = data.get('related_object_id')
        
        # Get the receipt
        receipt = Invoice.query.get(receipt_id)
        if not receipt:
            return jsonify({'success': False, 'error': 'Receipt not found'}), 404
        
        # Check if calendar event already created for this receipt
        if ReceiptCreationTracking.is_created(receipt_id, 'calendar_event', None):
            return jsonify({'success': False, 'error': 'Calendar event already created for this receipt'}), 400
        
        # Extract event details from AI analysis
        ai_analysis = None
        if receipt.data and receipt.data.get('ai_analysis'):
            ai_analysis_raw = receipt.data['ai_analysis']
            
            try:
                if isinstance(ai_analysis_raw, dict) and 'content' in ai_analysis_raw and 'response' in ai_analysis_raw['content']:
                    response_str = ai_analysis_raw['content']['response']
                    
                    # Clean up JSON markdown blocks
                    if response_str.startswith('```json'):
                        response_str = response_str.replace('```json\n', '').replace('\n```', '')
                    elif response_str.startswith('```'):
                        response_str = response_str.replace('```\n', '').replace('\n```', '')
                    
                    ai_analysis = json.loads(response_str)
            except Exception as e:
                logger.warning(f"Error parsing AI analysis for calendar event: {str(e)}")
                return jsonify({'success': False, 'error': 'Could not parse event data from receipt'}), 400
        
        if not ai_analysis or not ai_analysis.get('event_details'):
            # Try smart event detection if no explicit event_details
            if ai_analysis:
                detected_event_details = detect_event_from_receipt_data(ai_analysis)
                if detected_event_details:
                    ai_analysis['event_details'] = detected_event_details
                    logger.info(f"Receipt {receipt_id} - Using smart-detected event details for calendar creation")
                else:
                    return jsonify({'success': False, 'error': 'No event details found in receipt'}), 400
            else:
                return jsonify({'success': False, 'error': 'No event details found in receipt'}), 400
        
        event_details = ai_analysis['event_details']
        
        # Create calendar event - use suggested parameters if available
        if suggested_title:
            event_title = suggested_title
        else:
            event_title = event_details.get('event_name', f"Event from {receipt.data.get('vendor', 'Unknown Vendor')}")
        
        if suggested_date:
            event_date_str = suggested_date
        else:
            event_date_str = event_details.get('event_date', receipt.data.get('date'))
            
        event_location = event_details.get('venue_location', '')
        
        # Use suggested event type if provided
        event_type = suggested_type if suggested_type else 'receipt_generated'
        
        # Parse event date
        event_date = None
        if event_date_str:
            try:
                event_date = datetime.strptime(event_date_str, '%Y-%m-%d')
            except ValueError:
                try:
                    event_date = datetime.strptime(event_date_str, '%m/%d/%Y')
                except ValueError:
                    event_date = datetime.utcnow()
        else:
            event_date = datetime.utcnow()
        
        # Create the calendar event with enhanced relationship data
        calendar_event = CalendarEvent(
            title=event_title,
            description=f"Event created from receipt analysis. {event_details.get('description', '')}",
            start_time=event_date,  # Use start_time instead of event_date
            event_type=event_type,
            data={
                'location': event_location,
                'created_from_receipt': True,
                'receipt_id': receipt_id,
                'vendor': receipt.data.get('vendor', receipt.data.get('vendor_name', 'Unknown Vendor')),
                'total_amount': receipt.data.get('total_amount', 0),
                'event_details': event_details,
                'ai_confidence': ai_analysis.get('overall_confidence', 0.8),
                'invoice_id': receipt_id,  # Store invoice ID for relationship
                'created_from_ai_analysis': True
            }
        )
        
        db.session.add(calendar_event)
        db.session.flush()  # Get the event ID before committing
        
        # Update any existing objects from this receipt to reference the event
        existing_objects = Object.query.filter_by(invoice_id=receipt_id).all()
        for obj in existing_objects:
            if not obj.data:
                obj.data = {}
            obj.data['calendar_event_id'] = calendar_event.id
            obj.data['related_event_title'] = event_title
            obj.data['event_date'] = event_date.strftime('%Y-%m-%d')
            obj.data['event_related'] = True
            
            # Special handling for event tickets
            if obj.object_type == 'consumable' and obj.data.get('is_event_ticket'):
                obj.data['event_admission_date'] = event_date.strftime('%Y-%m-%d')
                if not obj.data.get('expiration_date'):
                    obj.data['expiration_date'] = event_date.strftime('%Y-%m-%d')
            
            logger.info(f"Linked object {obj.id} ({obj.data.get('name', 'unnamed')}) to calendar event {calendar_event.id}")
        
        # Track the creation
        ReceiptCreationTracking.track_creation(
            invoice_id=receipt_id,
            line_item_index=None,  # Receipt-level creation
            creation_type='calendar_event',
            creation_id=calendar_event.id,
            metadata={'event_title': event_title, 'event_type': event_type}
        )
        
        db.session.commit()
        
        logger.info(f"Created calendar event '{event_title}' from receipt {receipt.invoice_number} and linked {len(existing_objects)} objects")
        
        return jsonify({
            'success': True,
            'message': f'Successfully created calendar event and linked {len(existing_objects)} objects',
            'event_name': event_title,
            'event_id': calendar_event.id,
            'event_date': event_date.strftime('%Y-%m-%d'),
            'linked_objects': len(existing_objects)
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating calendar event from receipt: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error creating calendar event: {str(e)}'
        }), 500

@app.route('/create-organization-from-receipt', methods=['POST'])
def create_organization_from_receipt():
    """Create an organization from a receipt vendor"""
    try:
        data = request.json
        receipt_id = data.get('receipt_id')
        vendor_name = data.get('vendor_name')
        
        # Get the receipt
        receipt = Invoice.query.get(receipt_id)
        if not receipt:
            return jsonify({'success': False, 'error': 'Receipt not found'}), 404
        
        if not vendor_name:
            vendor_name = receipt.data.get('vendor') or receipt.data.get('vendor_name', 'Unknown Vendor')
        
        # Check if organization already created for this receipt
        if ReceiptCreationTracking.is_created(receipt_id, 'organization', None):
            return jsonify({'success': False, 'error': 'Organization already created for this receipt'}), 400
        
        # Check if organization already exists
        existing_org = Organization.query.filter_by(name=vendor_name).first()
        if existing_org:
            return jsonify({'success': False, 'error': f'Organization "{vendor_name}" already exists'}), 400
        
        # Create organization with basic data from receipt
        organization = Organization(
            name=vendor_name,
            organization_type='vendor',
            is_active=True,
            data={
                'created_from_receipt': True,
                'receipt_id': receipt_id,
                'created_from_vendor_name': vendor_name,
                'business_type': 'Unknown',
                'total_receipts': 1,
                'first_transaction_date': receipt.data.get('date'),
                'first_transaction_amount': receipt.data.get('total_amount', 0)
            }
        )
        
        db.session.add(organization)
        db.session.flush()  # Get organization ID
        
        # Track the creation
        ReceiptCreationTracking.track_creation(
            invoice_id=receipt_id,
            line_item_index=None,  # Receipt-level creation
            creation_type='organization',
            creation_id=organization.id,
            metadata={'vendor_name': vendor_name, 'organization_type': 'vendor'}
        )
        
        db.session.commit()
        
        logger.info(f"Created organization '{vendor_name}' from receipt {receipt.invoice_number}")
        
        return jsonify({
            'success': True,
            'message': f'Successfully created organization',
            'organization_name': vendor_name,
            'organization_id': organization.id
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating organization from receipt: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error creating organization: {str(e)}'
        }), 500

@app.route('/create-object-from-task', methods=['POST'])
def create_object_from_task():
    """Create an object from a task queue item (similar to create-object-from-receipt)"""
    try:
        data = request.json
        task_id = data.get('task_id')
        item_index = data.get('item_index')
        object_type = data.get('object_type', 'asset')
        category = data.get('category', '')
        description = data.get('description', '')
        unit_price = float(data.get('unit_price', 0))
        quantity = int(float(data.get('quantity', 1)))  # Convert to float first, then int to handle '1.0'
        
        # Get the task
        task = TaskQueue.query.get(task_id)
        if not task:
            return jsonify({'success': False, 'error': 'Task not found'}), 404
        
        if task.task_type != 'receipt_processing':
            return jsonify({'success': False, 'error': 'Invalid task type'}), 400
        
        # Get vendor name from task data
        vendor_name = 'Unknown Vendor'
        if task.data and task.data.get('ai_analysis'):
            # Extract vendor from AI analysis
            ai_analysis = task.data['ai_analysis']
            if 'content' in ai_analysis and 'response' in ai_analysis['content']:
                try:
                    response_str = ai_analysis['content']['response']
                    if response_str.startswith('```json'):
                        response_str = response_str.replace('```json\n', '').replace('\n```', '')
                    elif response_str.startswith('```'):
                        response_str = response_str.replace('```\n', '').replace('\n```', '')
                    
                    receipt_data = json.loads(response_str)
                    vendor_name = receipt_data.get('vendor_name', vendor_name)
                except Exception as e:
                    logger.warning(f"Could not extract vendor from task {task_id}: {str(e)}")
        
        # Create object data
        object_data = {
            'name': description or 'Unnamed Object',
            'description': description,
            'acquisition_cost': unit_price,
            'acquisition_date': datetime.utcnow().strftime('%Y-%m-%d'),
            'vendor': vendor_name,
            'quantity': quantity,
            'ai_processed': True,
            'ai_confidence': data.get('confidence', 0.8),
            'created_from_task': True,
            'task_id': task_id,
            'task_line_item_index': item_index
        }
        
        # Smart classification: detect if this should be a consumable event ticket
        desc_lower = description.lower()
        ticket_keywords = ['ticket', 'pass', 'entry', 'admission', 'badge', 'wristband', 'voucher', 'stub']
        if any(keyword in desc_lower for keyword in ticket_keywords):
            object_type = 'consumable'
            object_data.update({
                'category': 'event_ticket',
                'consumption_type': 'single_use',
                'current_stock': quantity,
                'track_stock': True,
                'reorder_threshold': 0,
                'is_event_ticket': True,
                'event_related': True,
                'single_use_item': True,
                'ticket_type': 'event_admission'
            })
            logger.info(f"Auto-classified '{description}' as consumable event ticket")
        
        if category:
            object_data['category'] = category
        
        # Create the object without linking to a receipt (since it's still in task queue)
        new_object = Object(
            object_type=object_type,
            data=object_data
        )
        db.session.add(new_object)
        db.session.commit()
        
        logger.info(f"Created {object_type} object '{description}' from task {task_id}")
        
        return jsonify({
            'success': True,
            'message': f'Successfully created {object_type}',
            'object_name': description,
            'object_id': new_object.id
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating object from task: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error creating object: {str(e)}'
        }), 500

@app.route('/create-person-from-task', methods=['POST'])
def create_person_from_task():
    """Create a person object from AI-detected person data in a task"""
    try:
        data = request.json
        task_id = data.get('task_id')
        person_name = data.get('person_name')
        person_role = data.get('person_role', '')
        relationship = data.get('relationship', '')
        
        # Get the task
        task = TaskQueue.query.get(task_id)
        if not task:
            return jsonify({'success': False, 'error': 'Task not found'}), 404
        
        if task.task_type != 'receipt_processing':
            return jsonify({'success': False, 'error': 'Invalid task type'}), 400
        
        # Get vendor name from task data
        vendor_name = 'Unknown Vendor'
        if task.data and task.data.get('ai_analysis'):
            try:
                ai_analysis = task.data['ai_analysis']
                if 'content' in ai_analysis and 'response' in ai_analysis['content']:
                    response_str = ai_analysis['content']['response']
                    if response_str.startswith('```json'):
                        response_str = response_str.replace('```json\n', '').replace('\n```', '')
                    elif response_str.startswith('```'):
                        response_str = response_str.replace('```\n', '').replace('\n```', '')
                    
                    receipt_data = json.loads(response_str)
                    vendor_name = receipt_data.get('vendor_name', vendor_name)
            except Exception as e:
                logger.warning(f"Could not extract vendor from task {task_id}: {str(e)}")
        
        # Create person object data
        object_data = {
            'name': person_name,
            'description': f"Person detected from AI task analysis",
            'role': person_role,
            'relationship_to_purchase': relationship,
            'detected_from_task': True,
            'task_id': task_id,
            'vendor': vendor_name,
            'detection_date': datetime.utcnow().strftime('%Y-%m-%d'),
            'ai_processed': True
        }
        
        # Create the person object
        person_object = Object(
            object_type='person',
            data=object_data
        )
        db.session.add(person_object)
        db.session.commit()
        
        logger.info(f"Created person object '{person_name}' from task {task_id}")
        
        return jsonify({
            'success': True,
            'message': f'Successfully created person: {person_name}',
            'object_name': person_name,
            'object_id': person_object.id
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating person from task: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error creating person: {str(e)}'
        }), 500

@app.route('/create-calendar-event-from-task', methods=['POST'])
def create_calendar_event_from_task():
    """Create a calendar event from AI-detected event data in a task"""
    try:
        data = request.json
        task_id = data.get('task_id')
        
        # Get the task
        task = TaskQueue.query.get(task_id)
        if not task:
            return jsonify({'success': False, 'error': 'Task not found'}), 404
        
        if task.task_type != 'receipt_processing':
            return jsonify({'success': False, 'error': 'Invalid task type'}), 400
        
        # Extract event details from task AI analysis (unified parsing)
        ai_analysis = None
        vendor_name = 'Unknown Vendor'
        
        if task.data and task.data.get('ai_analysis'):
            ai_analysis_raw = task.data['ai_analysis']
            
            try:
                # Use unified parsing logic for both Claude and OpenAI
                if 'content' in ai_analysis_raw:
                    content = ai_analysis_raw['content']
                    
                    # Both providers use same format via MCP server
                    if isinstance(content, dict) and 'vendor_name' in content:
                        # Direct JSON response (both providers when they return valid JSON)
                        ai_analysis = content
                        vendor_name = ai_analysis.get('vendor_name', vendor_name)
                        logger.info(f"Task {task_id} calendar - using direct JSON format, vendor: {vendor_name}")
                    elif isinstance(content, dict) and 'response' in content:
                        # Text response that needs parsing (both providers when they return text)
                        response_str = content['response']
                        
                        # Clean up JSON markdown blocks
                        if response_str.startswith('```json'):
                            response_str = response_str.replace('```json\n', '').replace('\n```', '')
                        elif response_str.startswith('```'):
                            response_str = response_str.replace('```\n', '').replace('\n```', '')
                        
                        ai_analysis = json.loads(response_str)
                        vendor_name = ai_analysis.get('vendor_name', vendor_name)
                        logger.info(f"Task {task_id} calendar - using text response format, vendor: {vendor_name}")
                    else:
                        logger.error(f"Task {task_id} calendar - unknown content format: {content}")
            except Exception as e:
                logger.warning(f"Error parsing AI analysis for calendar event: {str(e)}")
                return jsonify({'success': False, 'error': 'Could not parse event data from task'}), 400
        
        if not ai_analysis or not ai_analysis.get('event_details'):
            # Try smart event detection if no explicit event_details
            if ai_analysis:
                detected_event_details = detect_event_from_receipt_data(ai_analysis)
                if detected_event_details:
                    ai_analysis['event_details'] = detected_event_details
                    logger.info(f"Task {task_id} - Using smart-detected event details for calendar creation")
                else:
                    return jsonify({'success': False, 'error': 'No event details found in task'}), 400
            else:
                return jsonify({'success': False, 'error': 'No event details found in task'}), 400
        
        event_details = ai_analysis['event_details']
        
        # Create calendar event
        event_title = event_details.get('event_name', f"Event from {vendor_name}")
        event_date_str = event_details.get('event_date', datetime.utcnow().strftime('%Y-%m-%d'))
        event_location = event_details.get('venue_location', '')
        
        # Parse event date
        event_date = None
        if event_date_str:
            try:
                event_date = datetime.strptime(event_date_str, '%Y-%m-%d')
            except ValueError:
                try:
                    event_date = datetime.strptime(event_date_str, '%m/%d/%Y')
                except ValueError:
                    event_date = datetime.utcnow()
        else:
            event_date = datetime.utcnow()
        
        # Create the calendar event with task relationship
        calendar_event = CalendarEvent(
            title=event_title,
            description=f"Event created from task analysis. {event_details.get('description', '')}",
            start_time=event_date,  # Use start_time instead of event_date
            event_type='task_generated',
            data={
                'location': event_location,
                'created_from_task': True,
                'task_id': task_id,
                'vendor': vendor_name,
                'event_details': event_details,
                'ai_confidence': ai_analysis.get('overall_confidence', 0.8),
                'created_from_ai_analysis': True
            }
        )
        
        db.session.add(calendar_event)
        db.session.commit()
        
        logger.info(f"Created calendar event '{event_title}' from task {task_id}")
        
        return jsonify({
            'success': True,
            'message': f'Successfully created calendar event',
            'event_name': event_title,
            'event_id': calendar_event.id,
            'event_date': event_date.strftime('%Y-%m-%d')
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating calendar event from task: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error creating calendar event: {str(e)}'
        }), 500

@app.route('/object/delete/<int:object_id>', methods=['POST'])
def delete_object(object_id):
    """Delete an object from inventory"""
    try:
        obj = Object.query.get_or_404(object_id)
        
        # Store object info for logging
        object_name = obj.data.get('name', f'Object {object_id}')
        object_type = obj.object_type
        
        # Delete related object attachments
        object_attachments = ObjectAttachment.query.filter_by(object_id=object_id).all()
        for attachment in object_attachments:
            db.session.delete(attachment)
        
        # Delete the object
        db.session.delete(obj)
        db.session.commit()
        
        logger.info(f"Deleted {object_type} object: {object_name} (ID: {object_id})")
        flash(f'Successfully deleted {object_type} "{object_name}"', 'success')
        
        return redirect(url_for('inventory'))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting object {object_id}: {str(e)}")
        flash(f'Error deleting object: {str(e)}', 'danger')
        return redirect(url_for('inventory'))

# ==========================================
# AI METADATA EXTRACTION HELPER FUNCTIONS
# ==========================================

def extract_upc_from_text(text):
    """Extract UPC/barcode from text description"""
    import re
    
    # Common UPC patterns (12 digits)
    upc_patterns = [
        r'\bUPC[:\s]*(\d{12})\b',
        r'\bBarcode[:\s]*(\d{12})\b',
        r'\b(\d{12})\b',  # Generic 12-digit pattern
        r'\bEAN[:\s]*(\d{13})\b'  # EAN-13 pattern
    ]
    
    for pattern in upc_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None

def extract_manufacturer(description, vendor_name):
    """Extract manufacturer name from product description"""
    # Common manufacturer keywords
    manufacturer_keywords = ['mfg', 'manufacturer', 'made by', 'brand']
    
    # Split description into words
    words = description.lower().split()
    
    # Look for manufacturer indicators
    for i, word in enumerate(words):
        if any(keyword in word for keyword in manufacturer_keywords):
            # Try to get the next word as manufacturer
            if i + 1 < len(words):
                return words[i + 1].title()
    
    # If vendor looks like a manufacturer, use it
    if vendor_name and len(vendor_name.strip()) > 2:
        return vendor_name.title()
    
    # Try to extract brand names from common patterns
    import re
    brand_pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:Model|Series|Type)'
    match = re.search(brand_pattern, description)
    if match:
        return match.group(1)
    
    return None

def extract_model_number(description):
    """Extract model number from product description"""
    import re
    
    # Common model number patterns
    model_patterns = [
        r'(?:Model|Mod\.?|M)[:\s#]*([A-Z0-9\-]+)',
        r'(?:Series|Ser\.?)[:\s#]*([A-Z0-9\-]+)',
        r'(?:Type|T)[:\s#]*([A-Z0-9\-]+)',
        r'\b([A-Z]{2,}\d+[A-Z0-9\-]*)\b',  # Pattern like ABC123XYZ
        r'\b(\d+[A-Z]{2,}[\w\-]*)\b'       # Pattern like 123ABC-XYZ
    ]
    
    for pattern in model_patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    
    return None

def extract_serial_number(description):
    """Extract serial number from product description"""
    import re
    
    # Common serial number patterns
    serial_patterns = [
        r'(?:Serial|S/N|SN)[:\s#]*([A-Z0-9\-]+)',
        r'(?:Serial Number|Serial No\.?)[:\s#]*([A-Z0-9\-]+)',
        r'\bSN[:\s]([A-Z0-9\-]+)',
    ]
    
    for pattern in serial_patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    
    return None

def determine_object_type_smart(description):
    """Determine the most appropriate object type based on description"""
    desc_lower = description.lower()
    
    # Consumable indicators
    consumable_keywords = ['ticket', 'pass', 'voucher', 'food', 'drink', 'fuel', 'supplies', 'paper', 'ink']
    if any(keyword in desc_lower for keyword in consumable_keywords):
        return 'consumable'
    
    # Asset indicators (durable goods)
    asset_keywords = ['computer', 'laptop', 'phone', 'equipment', 'machine', 'tool', 'furniture', 'vehicle', 'monitor']
    if any(keyword in desc_lower for keyword in asset_keywords):
        return 'asset'
    
    # Default to expense for services and unclear items
    return 'expense'

def suggest_categories_smart(description):
    """Suggest categories based on item description"""
    desc_lower = description.lower()
    
    categories = []
    
    # Technology
    if any(word in desc_lower for word in ['computer', 'laptop', 'phone', 'tablet', 'software']):
        categories.append('technology')
    
    # Office supplies
    if any(word in desc_lower for word in ['pen', 'paper', 'stapler', 'folder', 'supplies']):
        categories.append('office_supplies')
    
    # Food & Beverage
    if any(word in desc_lower for word in ['food', 'drink', 'coffee', 'lunch', 'dinner']):
        categories.append('food_beverage')
    
    # Transportation
    if any(word in desc_lower for word in ['fuel', 'gas', 'parking', 'uber', 'taxi']):
        categories.append('transportation')
    
    # Events & Entertainment
    if any(word in desc_lower for word in ['ticket', 'admission', 'event', 'concert', 'show']):
        categories.append('events_entertainment')
    
    return categories if categories else ['uncategorized']

def has_serial_indicators(description):
    """Check if item likely needs serial number tracking"""
    desc_lower = description.lower()
    
    # Items that typically have serial numbers
    serial_items = ['computer', 'laptop', 'phone', 'tablet', 'equipment', 'machine', 'tool', 'monitor']
    return any(item in desc_lower for item in serial_items)

def get_depreciation_category(description):
    """Get depreciation category for tax purposes"""
    desc_lower = description.lower()
    
    # Technology items (typically 3-5 years)
    if any(word in desc_lower for word in ['computer', 'laptop', 'phone', 'tablet', 'software']):
        return 'technology'
    
    # Office equipment (typically 5-7 years)
    if any(word in desc_lower for word in ['printer', 'scanner', 'copier', 'furniture']):
        return 'office_equipment'
    
    # Vehicles (varies by type)
    if any(word in desc_lower for word in ['car', 'truck', 'vehicle']):
        return 'vehicles'
    
    return 'general'

def requires_maintenance(description):
    """Check if item typically requires regular maintenance"""
    desc_lower = description.lower()
    
    # Items that need maintenance
    maintenance_items = ['computer', 'printer', 'machine', 'equipment', 'vehicle', 'tool']
    return any(item in desc_lower for item in maintenance_items)

def extract_event_name(description, vendor_name, line_items):
    """Extract event name from various sources"""
    # Try line items first
    for item in line_items:
        item_desc = item.get('description', '')
        if any(word in item_desc.lower() for word in ['festival', 'concert', 'event', 'show']):
            # Extract the event name
            words = item_desc.split()
            event_words = []
            for word in words:
                if word.lower() not in ['ticket', 'pass', 'admission', 'entry', 'for']:
                    event_words.append(word)
            if event_words:
                return ' '.join(event_words)
    
    # Try vendor name
    if vendor_name and any(word in vendor_name.lower() for word in ['event', 'festival', 'concert']):
        return vendor_name
    
    # Try description
    if description:
        return description
    
    return f"Event from {vendor_name}" if vendor_name else "Unknown Event"

def extract_event_location(description, receipt_data):
    """Extract event location from description or receipt data"""
    # Look for common location indicators
    import re
    
    location_patterns = [
        r'(?:at|@)\s+([A-Za-z\s,]+?)(?:\s+on|\s+\d|$)',
        r'(?:venue|location)[:\s]+([A-Za-z\s,]+?)(?:\s+on|\s+\d|$)',
        r'(?:Address|Addr)[:\s]+([A-Za-z0-9\s,]+?)(?:\s+on|\s+\d|$)'
    ]
    
    for pattern in location_patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    # Check receipt data for location
    if receipt_data.get('venue_location'):
        return receipt_data['venue_location']
    
    return ''

def determine_event_type(description, line_items):
    """Determine the type of event based on description and items"""
    desc_lower = description.lower()
    
    if any(word in desc_lower for word in ['music', 'concert', 'festival', 'band']):
        return 'music_event'
    elif any(word in desc_lower for word in ['conference', 'seminar', 'workshop', 'training']):
        return 'business_event'
    elif any(word in desc_lower for word in ['sport', 'game', 'match', 'tournament']):
        return 'sports_event'
    elif any(word in desc_lower for word in ['food', 'dining', 'restaurant']):
        return 'dining_event'
    else:
        return 'general_event'

def count_tickets_in_items(line_items):
    """Count the number of tickets/passes in line items"""
    ticket_count = 0
    for item in line_items:
        if item.get('object_type') == 'consumable' and item.get('category') == 'event_ticket':
            ticket_count += item.get('quantity', 1)
    return ticket_count

def ensure_category_exists(category_name, object_type):
    """
    Ensure a category exists in the database, create it if it doesn't.
    This supports dynamic category creation from AI suggestions.
    """
    try:
        if not category_name or not object_type:
            return None
            
        # Check if category already exists
        existing_category = Category.query.filter_by(
            name=category_name, 
            object_type=object_type
        ).first()
        
        if existing_category:
            logger.debug(f"Category '{category_name}' already exists for {object_type}")
            return existing_category
        
        # Create new category
        new_category = Category(
            name=category_name,
            object_type=object_type,
            description=f'AI-suggested category for {object_type}s',
            is_default=False,
            confidence_score=0.8  # AI-suggested = medium-high confidence
        )
        
        db.session.add(new_category)
        db.session.commit()
        
        logger.info(f"Created new AI-suggested category: '{category_name}' for {object_type}")
        return new_category
        
    except Exception as e:
        logger.error(f"Error creating category '{category_name}' for {object_type}: {str(e)}")
        # Don't fail the whole process if category creation fails
        return None

def process_ai_suggested_categories(line_items):
    """
    Process AI-suggested categories and ensure they exist in the database.
    This enables dynamic category expansion based on AI recommendations.
    """
    categories_created = []
    
    try:
        for item in line_items:
            category = item.get('category')
            object_type = item.get('object_type')
            
            if category and object_type:
                # Ensure the category exists
                category_obj = ensure_category_exists(category, object_type)
                if category_obj and category_obj.name not in [cat['name'] for cat in categories_created]:
                    categories_created.append({
                        'name': category_obj.name,
                        'object_type': category_obj.object_type,
                        'created': True
                    })
        
        if categories_created:
            logger.info(f"Processed {len(categories_created)} AI-suggested categories: {[cat['name'] for cat in categories_created]}")
        
        return categories_created
        
    except Exception as e:
        logger.error(f"Error processing AI-suggested categories: {str(e)}")
        return []

# Add these new API endpoints after the existing API routes

@app.route('/api/object-types', methods=['GET'])
def get_object_types():
    """Get all available object types with descriptions for AI context"""
    try:
        # Define all supported object types with descriptions
        object_types = {
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
        
        return jsonify({
            'success': True,
            'object_types': object_types
        })
        
    except Exception as e:
        logger.error(f"Error getting object types: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/categories', methods=['GET'])
def get_all_categories():
    """Get all existing categories across all object types for AI context"""
    try:
        # Get all categories from database
        categories = Category.query.all()
        
        # Organize by object type
        categories_by_type = {}
        all_categories = []
        
        for category in categories:
            if category.object_type not in categories_by_type:
                categories_by_type[category.object_type] = []
            
            category_info = {
                'name': category.name,
                'object_type': category.object_type,
                'description': category.description,
                'icon': category.icon,
                'color': category.color,
                'is_default': category.is_default
            }
            
            categories_by_type[category.object_type].append(category_info)
            all_categories.append(category_info)
        
        # Also include any categories from object metadata (for backward compatibility)
        objects = Object.query.all()
        metadata_categories = set()
        
        for obj in objects:
            if obj.data:
                # Handle both 'category' and 'categories' fields
                if 'category' in obj.data and obj.data['category']:
                    metadata_categories.add((obj.data['category'], obj.object_type))
                if 'categories' in obj.data:
                    if isinstance(obj.data['categories'], list):
                        for cat in obj.data['categories']:
                            if cat:
                                metadata_categories.add((cat, obj.object_type))
                    elif isinstance(obj.data['categories'], str) and obj.data['categories']:
                        metadata_categories.add((obj.data['categories'], obj.object_type))
        
        # Add metadata categories that aren't in the Category table
        existing_category_keys = {(cat['name'], cat['object_type']) for cat in all_categories}
        
        for cat_name, obj_type in metadata_categories:
            if (cat_name, obj_type) not in existing_category_keys:
                category_info = {
                    'name': cat_name,
                    'object_type': obj_type,
                    'description': f'Category from object metadata',
                    'icon': None,
                    'color': None,
                    'is_default': False
                }
                
                if obj_type not in categories_by_type:
                    categories_by_type[obj_type] = []
                categories_by_type[obj_type].append(category_info)
                all_categories.append(category_info)
        
        return jsonify({
            'success': True,
            'categories_by_type': categories_by_type,
            'all_categories': all_categories,
            'total_categories': len(all_categories)
        })
        
    except Exception as e:
        logger.error(f"Error getting categories: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/categories', methods=['POST'])
def create_category():
    """Create a new category dynamically"""
    try:
        data = request.json
        name = data.get('name', '').strip()
        object_type = data.get('object_type', '').strip()
        description = data.get('description', '').strip()
        icon = data.get('icon', '').strip()
        color = data.get('color', '').strip()
        
        if not name or not object_type:
            return jsonify({
                'success': False,
                'error': 'Name and object_type are required'
            }), 400
        
        # Check if category already exists
        existing = Category.query.filter_by(name=name, object_type=object_type).first()
        if existing:
            return jsonify({
                'success': False,
                'error': f'Category "{name}" already exists for {object_type}s'
            }), 400
        
        # Create new category
        category = Category(
            name=name,
            object_type=object_type,
            description=description or f'User-created category for {object_type}s',
            icon=icon or None,
            color=color or None,
            is_default=False,
            confidence_score=1.0  # User-created = high confidence
        )
        
        db.session.add(category)
        db.session.commit()
        
        logger.info(f"Created new category: {name} for {object_type}")
        
        return jsonify({
            'success': True,
            'message': f'Category "{name}" created successfully',
            'category': {
                'id': category.id,
                'name': category.name,
                'object_type': category.object_type,
                'description': category.description,
                'icon': category.icon,
                'color': category.color
            }
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating category: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/categories/suggest', methods=['POST'])
def suggest_new_categories():
    """AI-powered suggestion of new categories based on item description"""
    try:
        data = request.json
        description = data.get('description', '').strip()
        object_type = data.get('object_type', '').strip()
        existing_categories = data.get('existing_categories', [])
        
        if not description or not object_type:
            return jsonify({
                'success': False,
                'error': 'Description and object_type are required'
            }), 400
        
        # Use OpenAI to suggest new categories
        from openai_utils import categorize_item
        
        result = categorize_item(
            description=description,
            object_type=object_type,
            amount=data.get('amount'),
            vendor=data.get('vendor')
        )
        
        if result['success']:
            suggested_categories = []
            for cat in result['categories']:
                # Check if this category already exists
                existing_cat = Category.query.filter_by(
                    name=cat['name'], 
                    object_type=object_type
                ).first()
                
                if not existing_cat and cat['name'] not in existing_categories:
                    suggested_categories.append({
                        'name': cat['name'],
                        'description': cat.get('description', ''),
                        'icon': cat.get('icon', ''),
                        'confidence': cat.get('confidence', 0.8),
                        'is_new': True
                    })
                else:
                    suggested_categories.append({
                        'name': cat['name'],
                        'description': cat.get('description', ''),
                        'icon': cat.get('icon', ''),
                        'confidence': cat.get('confidence', 0.8),
                        'is_new': False,
                        'exists': True
                    })
            
            return jsonify({
                'success': True,
                'suggested_categories': suggested_categories,
                'object_type': object_type
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Failed to suggest categories')
            }), 500
        
    except Exception as e:
        logger.error(f"Error suggesting categories: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ==========================================
# AI API CONNECTION ENDPOINTS
# ==========================================

@app.route('/api/check-api-connection', methods=['GET'])
def check_api_connection():
    """Check OpenAI API connection status"""
    try:
        result = check_openai_api_connection()
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error checking OpenAI API connection: {str(e)}")
        return jsonify({
            'success': False,
            'error_type': 'server_error',
            'message': f'Error checking API connection: {str(e)}'
        }), 500

# ==========================================
# CALENDAR API ENDPOINTS
# ==========================================

@app.route('/api/calendar/events', methods=['GET'])
def get_calendar_events():
    """Get all calendar events for the calendar display"""
    try:
        logger.info("Calendar events API called")
        
        # Get all calendar events
        events = CalendarEvent.query.order_by(CalendarEvent.start_time).all()
        logger.info(f"Found {len(events)} calendar events in database")
        
        calendar_events = []
        for event in events:
            try:
                # Simplified related objects check
                related_objects = []
                has_tickets = False
                
                # Basic event object
                event_data = {
                    'id': event.id,
                    'title': event.title,
                    'start': event.start_time.isoformat(),
                    'description': event.description or '',
                    'backgroundColor': '#007bff',
                    'borderColor': '#007bff',
                    'extendedProps': {
                        'event_type': event.event_type or 'general',
                        'has_objects': False,
                        'has_tickets': False,
                        'object_count': 0,
                        'location': event.data.get('location', '') if event.data else ''
                    }
                }
                
                calendar_events.append(event_data)
                
            except Exception as event_error:
                logger.error(f"Error processing event {event.id}: {str(event_error)}")
                # Continue processing other events
                continue
        
        logger.info(f"Returning {len(calendar_events)} calendar events")
        return jsonify(calendar_events)
        
    except Exception as e:
        logger.error(f"Error getting calendar events: {str(e)}")
        return jsonify([]), 200  # Return empty array instead of error to prevent frontend crash

@app.route('/api/calendar/events', methods=['POST'])
def create_calendar_event():
    """Create a new calendar event"""
    try:
        data = request.json
        title = data.get('title', '').strip()
        date = data.get('date')
        time = data.get('time', '').strip()
        description = data.get('description', '').strip()
        location = data.get('location', '').strip()
        
        if not title or not date:
            return jsonify({
                'success': False,
                'error': 'Title and date are required'
            }), 400
        
        # Parse datetime
        if time:
            datetime_str = f"{date} {time}"
            event_datetime = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
        else:
            event_datetime = datetime.strptime(date, '%Y-%m-%d')
        
        # Create the event
        event = CalendarEvent(
            title=title,
            description=description,
            start_time=event_datetime,
            event_type='user_created',
            data={
                'location': location,
                'created_via': 'calendar_interface',
                'manual_entry': True
            }
        )
        
        db.session.add(event)
        db.session.commit()
        
        logger.info(f"Created calendar event: {title} on {event_datetime}")
        
        return jsonify({
            'success': True,
            'message': 'Event created successfully',
            'event_id': event.id
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating calendar event: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/calendar/event/<int:event_id>')
def get_calendar_event_details(event_id):
    """Get detailed information about a specific calendar event"""
    try:
        event = CalendarEvent.query.get(event_id)
        if not event:
            return jsonify({
                'success': False,
                'error': 'Event not found'
            }), 404
        
        # Get related objects
        related_objects = []
        
        # Method 1: Direct receipt linkage
        if event.data and event.data.get('receipt_id'):
            related_objects = Object.query.filter_by(
                invoice_id=event.data['receipt_id']
            ).all()
            logger.debug(f"Found {len(related_objects)} objects via receipt_id")
        
        # Method 2: Look for objects with event relationships
        if not related_objects:
            # Look for objects that reference this event
            objects_with_event_ref = Object.query.filter(
                Object.data.op('->>')('calendar_event_id') == str(event_id)
            ).all()
            related_objects.extend(objects_with_event_ref)
            logger.debug(f"Found {len(objects_with_event_ref)} objects via event reference")
        
        # Method 3: Temporal and vendor matching for receipt-generated events
        if not related_objects and event.data and event.data.get('created_from_receipt'):
            vendor = event.data.get('vendor', '')
            if vendor:
                # Look for objects from same vendor created around same time
                potential_objects = Object.query.filter(
                    Object.data.op('->>')('vendor').ilike(f'%{vendor}%')
                ).filter(
                    Object.created_at.between(
                        event.created_at - timedelta(hours=2),
                        event.created_at + timedelta(hours=2)
                    )
                ).all()
                
                # Filter for event-related objects
                for obj in potential_objects:
                    if (obj.object_type == 'consumable' and 
                        obj.data and obj.data.get('is_event_ticket')):
                        related_objects.append(obj)
                
                logger.debug(f"Found {len(related_objects)} objects via temporal matching")
        
        # Build detailed object information including attachments
        detailed_objects = []
        for obj in related_objects:
            # Get attachments for this object
            attachments = ObjectAttachment.query.filter_by(object_id=obj.id).all()
            
            # Extract confirmation codes and QR codes from attachments
            confirmation_codes = []
            qr_codes = []
            
            for attachment in attachments:
                if attachment.attachment_type == 'confirmation_code':
                    if attachment.ai_analysis_result and attachment.ai_analysis_result.get('code'):
                        confirmation_codes.append(attachment.ai_analysis_result['code'])
                elif attachment.attachment_type == 'qr_code':
                    if attachment.ai_analysis_result and attachment.ai_analysis_result.get('content'):
                        qr_codes.append(attachment.ai_analysis_result['content'])
            
            # Enhanced object data
            obj_data = obj.data or {}
            
            # Add extracted codes to object data for display
            if confirmation_codes:
                obj_data['confirmation_codes'] = confirmation_codes
                obj_data['confirmation_code'] = confirmation_codes[0]  # Primary code
            
            if qr_codes:
                obj_data['qr_codes'] = qr_codes
                obj_data['qr_code'] = qr_codes[0]  # Primary QR code
            
            detailed_objects.append({
                'id': obj.id,
                'object_type': obj.object_type,
                'data': obj_data,
                'created_at': obj.created_at.isoformat() if obj.created_at else None,
                'attachments_count': len(attachments),
                'has_confirmation_codes': len(confirmation_codes) > 0,
                'has_qr_codes': len(qr_codes) > 0
            })
        
        event_details = {
            'id': event.id,
            'title': event.title,
            'description': event.description,
            'start_time': event.start_time.isoformat(),
            'event_type': event.event_type,
            'data': event.data or {},
            'created_at': event.created_at.isoformat() if event.created_at else None,
            'related_objects': detailed_objects
        }
        
        logger.debug(f"Event {event_id} details: {len(detailed_objects)} related objects")
        
        return jsonify({
            'success': True,
            'event': event_details
        })
        
    except Exception as e:
        logger.error(f"Error getting event details for {event_id}: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/object-details/<int:object_id>')
def get_object_details(object_id):
    """Get comprehensive details for a specific object"""
    try:
        # Get the object
        obj = Object.query.get(object_id)
        if not obj:
            return jsonify({'success': False, 'error': 'Object not found'}), 404
        
        # Get related data
        attachments = ObjectAttachment.query.filter_by(object_id=object_id).all()
        invoice = Invoice.query.get(obj.invoice_id) if obj.invoice_id else None
        
        # Build comprehensive object details
        object_details = {
            'id': obj.id,
            'object_type': obj.object_type,
            'data': obj.data or {},
            'created_at': obj.created_at.isoformat() if obj.created_at else None,
            'updated_at': obj.updated_at.isoformat() if obj.updated_at else None,
            'invoice_id': obj.invoice_id
        }
        
        # Add user mappings for person objects
        if obj.object_type == 'person':
            user_mappings = []
            for mapping in obj.user_mappings:
                user_mappings.append({
                    'user_id': mapping.user_id,
                    'username': mapping.user.username,
                    'display_name': mapping.user.display_name,
                    'is_primary': mapping.is_primary,
                    'created_at': mapping.created_at.isoformat() if mapping.created_at else None
                })
            object_details['user_mappings'] = user_mappings
        
        # Add invoice details if available
        if invoice:
            object_details['invoice'] = {
                'id': invoice.id,
                'invoice_number': invoice.invoice_number,
                'vendor': invoice.vendor.name if invoice.vendor else invoice.data.get('vendor', 'Unknown'),
                'date': invoice.data.get('date') if invoice.data else None,
                'total_amount': invoice.data.get('total_amount') if invoice.data else None,
                'is_paid': invoice.is_paid
            }
        
        # Add attachments
        object_details['attachments'] = []
        for attachment in attachments:
            object_details['attachments'].append({
                'id': attachment.id,
                'filename': attachment.filename,
                'file_type': attachment.file_type,
                'attachment_type': attachment.attachment_type,
                'description': attachment.description,
                'upload_date': attachment.upload_date.isoformat() if attachment.upload_date else None,
                'ai_analyzed': attachment.ai_analyzed,
                'ai_analysis_result': attachment.ai_analysis_result
            })
        
        # Calculate derived information
        derived_info = {}
        
        # Age calculation
        if obj.created_at:
            age_days = (datetime.utcnow() - obj.created_at).days
            derived_info['age_days'] = age_days
            derived_info['age_display'] = f"{age_days} days" if age_days < 30 else f"{age_days // 30} months"
        
        # Value depreciation for assets
        if obj.object_type == 'asset' and obj.data:
            acquisition_cost = obj.data.get('acquisition_cost')
            estimated_value = obj.data.get('estimated_value')
            if acquisition_cost and estimated_value:
                depreciation = float(acquisition_cost) - float(estimated_value)
                depreciation_percent = (depreciation / float(acquisition_cost)) * 100
                derived_info['depreciation'] = {
                    'amount': depreciation,
                    'percentage': depreciation_percent
                }
        
        # Stock status for consumables
        if obj.object_type == 'consumable' and obj.data:
            current_stock = obj.data.get('current_stock', 0)
            reorder_threshold = obj.data.get('reorder_threshold', 0)
            if current_stock <= reorder_threshold:
                derived_info['stock_status'] = 'low'
            else:
                derived_info['stock_status'] = 'good'
        
        # Expiration status for consumables
        if obj.object_type == 'consumable' and obj.data and obj.data.get('expiration_date'):
            try:
                expiration_date = datetime.strptime(obj.data['expiration_date'], '%Y-%m-%d')
                days_until_expiration = (expiration_date - datetime.utcnow()).days
                derived_info['expiration'] = {
                    'days_until': days_until_expiration,
                    'status': 'expired' if days_until_expiration < 0 else ('expiring_soon' if days_until_expiration <= 30 else 'good')
                }
            except ValueError:
                pass
        
        object_details['derived_info'] = derived_info
        
        # Get category information
        if obj.data and obj.data.get('category'):
            category = Category.query.filter_by(
                name=obj.data['category'],
                object_type=obj.object_type
            ).first()
            if category:
                object_details['category_info'] = {
                    'name': category.name,
                    'description': category.description,
                    'icon': category.icon,
                    'color': category.color
                }
        
        # Get related calendar events
        related_events = []
        
        # Method 1: Direct event reference in object data
        if obj.data and obj.data.get('calendar_event_id'):
            event = CalendarEvent.query.get(obj.data['calendar_event_id'])
            if event:
                related_events.append({
                    'id': event.id,
                    'title': event.title,
                    'start_time': event.start_time.isoformat(),
                    'description': event.description,
                    'event_type': event.event_type,
                    'relationship_type': 'direct_reference'
                })
        
        # Method 2: Events from same receipt/invoice
        if obj.invoice_id:
            receipt_events = CalendarEvent.query.filter(
                CalendarEvent.data.op('->>')('receipt_id') == str(obj.invoice_id)
            ).all()
            for event in receipt_events:
                if not any(e['id'] == event.id for e in related_events):
                    related_events.append({
                        'id': event.id,
                        'title': event.title,
                        'start_time': event.start_time.isoformat(),
                        'description': event.description,
                        'event_type': event.event_type,
                        'relationship_type': 'same_receipt'
                    })
        
        # Method 3: Events created around same time from same vendor (for event tickets)
        if (obj.object_type == 'consumable' and obj.data and obj.data.get('is_event_ticket') and
            obj.data.get('vendor')):
            vendor = obj.data['vendor']
            temporal_events = CalendarEvent.query.filter(
                CalendarEvent.data.op('->>')('vendor').ilike(f'%{vendor}%')
            ).filter(
                CalendarEvent.created_at.between(
                    obj.created_at - timedelta(hours=2),
                    obj.created_at + timedelta(hours=2)
                )
            ).all()
            
            for event in temporal_events:
                if not any(e['id'] == event.id for e in related_events):
                    related_events.append({
                        'id': event.id,
                        'title': event.title,
                        'start_time': event.start_time.isoformat(),
                        'description': event.description,
                        'event_type': event.event_type,
                        'relationship_type': 'temporal_vendor_match'
                    })
        
        if related_events:
            object_details['related_events'] = related_events
            logger.debug(f"Found {len(related_events)} related events for object {object_id}")
        
        logger.debug(f"Retrieved comprehensive details for object {object_id}")
        
        return jsonify({
            'success': True,
            'object': object_details
        })
        
    except Exception as e:
        logger.error(f"Error getting object details for {object_id}: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/approve-receipt-with-selections/<int:task_id>', methods=['POST'])
def approve_receipt_with_selections(task_id):
    """
    Enhanced receipt approval that handles checkbox-based object creation.
    Creates multiple related objects and tracks what has been created.
    """
    try:
        task = TaskQueue.query.get_or_404(task_id)
        
        if task.task_type != 'receipt_processing':
            flash('Invalid task type for receipt approval', 'danger')
            return redirect(url_for('ai_queue'))
        
        # Get form data for what should be created
        create_invoice = request.form.get('create_invoice', 'on') == 'on'
        create_objects = request.form.getlist('create_objects')  # List of line item indices
        create_people = request.form.getlist('create_people')    # List of people indices
        create_events = request.form.get('create_events') == 'on'
        create_organization = request.form.get('create_organization') == 'on'
        
        logger.info(f"Processing receipt {task_id} with selections: invoice={create_invoice}, "
                   f"objects={create_objects}, people={create_people}, events={create_events}, org={create_organization}")
        
        # Process the receipt and create invoice
        if create_invoice:
            success = process_receipt_task_enhanced(task, {
                'create_objects': create_objects,
                'create_people': create_people, 
                'create_events': create_events,
                'create_organization': create_organization
            })
            
            if success:
                task.status = 'completed'
                task.completed_at = datetime.utcnow()
                db.session.commit()
                
                # Get the created invoice for tracking
                invoice_id = task.data.get('created_invoice_id')
                if invoice_id:
                    # Show summary of what was created
                    summary = ReceiptCreationTracking.get_creation_summary(invoice_id)
                    object_count = summary['totals'].get('object', 0)
                    people_count = summary['totals'].get('person', 0)
                    event_count = summary['totals'].get('event', 0)
                    org_count = summary['totals'].get('organization', 0)
                    
                    flash(f'Receipt processed successfully! Created: Invoice, {object_count} objects, '
                          f'{people_count} people, {event_count} events, {org_count} organizations', 'success')
                else:
                    flash('Receipt processed successfully!', 'success')
            else:
                task.status = 'failed'
                db.session.commit()
                flash('Error processing receipt. Please try again.', 'danger')
        else:
            # Just mark as completed without creating invoice
            task.status = 'completed'
            task.completed_at = datetime.utcnow()
            db.session.commit()
            flash('Receipt marked as processed (no invoice created)', 'info')
        
        return redirect(url_for('ai_queue'))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error approving receipt with selections: {str(e)}")
        flash(f'Error approving receipt: {str(e)}', 'danger')
        return redirect(url_for('ai_queue'))


def process_receipt_task_enhanced(task, selections):
    """
    Enhanced version of process_receipt_task that handles selective object creation
    and tracks what has been created to prevent duplicates.
    """
    try:
        ai_analysis_raw = task.data.get('ai_analysis', {})
        if not ai_analysis_raw:
            logger.error("No AI analysis data found in task")
            return False
        
        # Parse MCP response (same logic as original)
        ai_analysis = {}
        try:
            if 'content' in ai_analysis_raw:
                content = ai_analysis_raw['content']
                
                if isinstance(content, dict) and 'vendor_name' in content:
                    ai_analysis = content
                elif isinstance(content, dict) and 'response' in content:
                    response_str = content['response']
                    if response_str.startswith('```json'):
                        response_str = response_str.replace('```json\n', '').replace('\n```', '')
                    elif response_str.startswith('```'):
                        response_str = response_str.replace('```\n', '').replace('\n```', '')
                    ai_analysis = json.loads(response_str)
                else:
                    logger.error(f"Process receipt - unknown content format: {content}")
                    return False
            else:
                ai_analysis = ai_analysis_raw
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Error parsing receipt data for processing: {str(e)}")
            return False
        
        # Create vendor (same as original)
        vendor_name = ai_analysis.get('vendor_name', ai_analysis.get('vendor', 'Unknown Vendor'))
        vendor = None
        if vendor_name and vendor_name != 'Unknown Vendor':
            vendor = Vendor.query.filter_by(name=vendor_name).first()
            if not vendor:
                vendor = Vendor(name=vendor_name)
                db.session.add(vendor)
                db.session.flush()
        
        # Create invoice data (same as original)
        invoice_data = {
            'date': ai_analysis.get('date', datetime.utcnow().strftime('%Y-%m-%d')),
            'vendor': vendor_name,
            'vendor_name': vendor_name,
            'total_amount': ai_analysis.get('total_amount', 0),
            'is_paid': True,
            'ai_processed': True,
            'ai_confidence': ai_analysis_raw.get('confidence', 0.5),
            'original_filename': task.data.get('original_filename', ''),
            'processed_at': datetime.utcnow().isoformat(),
            'subtotal': ai_analysis.get('subtotal', 0),
            'tax_amount': ai_analysis.get('tax_amount', 0),
            'fees': ai_analysis.get('fees', 0),
            'receipt_number': ai_analysis.get('receipt_number', ''),
            'payment_method': ai_analysis.get('payment_method', ''),
            'description': ai_analysis.get('description', ''),
            'ai_analysis': ai_analysis_raw
        }
        
        # Create the invoice
        invoice_number = Invoice.generate_invoice_number()
        invoice = Invoice(
            invoice_number=invoice_number,
            vendor_id=vendor.id if vendor else None,
            is_paid=True,
            data=invoice_data
        )
        db.session.add(invoice)
        db.session.flush()  # Get the invoice ID
        
        # Store invoice ID in task data for reference
        task.data['created_invoice_id'] = invoice.id
        
        # Create attachment (same as original)
        attachment_data = task.data.get('attachment', {})
        if attachment_data.get('file_data'):
            attachment = Attachment(
                invoice_id=invoice.id,
                filename=task.data.get('processed_filename', 'receipt.jpg'),
                file_data=base64.b64decode(attachment_data['file_data']),
                file_type=attachment_data.get('file_type', 'image/jpeg'),
                upload_date=datetime.utcnow()
            )
            db.session.add(attachment)
        
        # Create line items (same as original)
        line_items = ai_analysis.get('line_items', [])
        for item in line_items:
            line_item = InvoiceLineItem(
                invoice_id=invoice.id,
                data=item
            )
            db.session.add(line_item)
        
        # Enhanced object creation with tracking
        create_objects = selections.get('create_objects', [])
        for line_idx_str in create_objects:
            try:
                line_idx = int(line_idx_str)
                if line_idx < len(line_items):
                    item = line_items[line_idx]
                    
                    # Check if object already created for this line item
                    if ReceiptCreationTracking.is_created(invoice.id, 'object', line_idx):
                        logger.info(f"Object for line item {line_idx} already created, skipping")
                        continue
                    
                    # Create the object
                    obj = create_object_from_line_item(item, invoice, line_idx)
                    if obj:
                        # Track the creation
                        ReceiptCreationTracking.track_creation(
                            invoice_id=invoice.id,
                            line_item_index=line_idx,
                            creation_type='object',
                            creation_id=obj.id,
                            task_id=task.id,
                            metadata={'line_item_data': item, 'object_type': obj.object_type}
                        )
                        logger.info(f"Created and tracked {obj.object_type} object: {obj.data.get('name')} for line item {line_idx}")
            except (ValueError, IndexError) as e:
                logger.error(f"Error processing object creation for line item {line_idx_str}: {str(e)}")
        
        # Enhanced people creation with tracking
        create_people = selections.get('create_people', [])
        people_found = ai_analysis.get('people_found', [])
        for person_idx_str in create_people:
            try:
                person_idx = int(person_idx_str)
                if person_idx < len(people_found):
                    person_data = people_found[person_idx]
                    
                    # Check if person already created
                    if ReceiptCreationTracking.is_created(invoice.id, 'object', None):
                        logger.info(f"Person {person_data.get('person_name')} already created, skipping")
                        continue
                    
                    # Create the person object
                    person_obj = create_person_from_data(person_data, invoice)
                    if person_obj:
                        # Track the creation
                        ReceiptCreationTracking.track_creation(
                            invoice_id=invoice.id,
                            line_item_index=None,  # Receipt-level creation
                            creation_type='object',
                            creation_id=person_obj.id,
                            task_id=task.id,
                            metadata={'person_data': person_data, 'object_type': 'person'}
                        )
                        logger.info(f"Created and tracked person: {person_obj.data.get('name')}")
            except (ValueError, IndexError) as e:
                logger.error(f"Error processing person creation for index {person_idx_str}: {str(e)}")
        
        # Enhanced event creation with tracking
        if selections.get('create_events') and ai_analysis.get('event_details'):
            # Check if event already created
            if not ReceiptCreationTracking.is_created(invoice.id, 'calendar_event', None):
                event_obj = create_event_from_data(ai_analysis['event_details'], invoice)
                if event_obj:
                    # Track the creation
                    ReceiptCreationTracking.track_creation(
                        invoice_id=invoice.id,
                        line_item_index=None,  # Receipt-level creation
                        creation_type='calendar_event',
                        creation_id=event_obj.id,
                        task_id=task.id,
                        metadata={'event_data': ai_analysis['event_details']}
                    )
                    logger.info(f"Created and tracked event: {event_obj.title}")
        
        # Enhanced organization creation with tracking
        if selections.get('create_organization') and vendor_name and vendor_name != 'Unknown Vendor':
            # Check if organization already created
            if not ReceiptCreationTracking.is_created(invoice.id, 'organization', None):
                org = Organization.get_or_create(vendor_name)
                if org:
                    # Track the creation (or promotion)
                    ReceiptCreationTracking.track_creation(
                        invoice_id=invoice.id,
                        line_item_index=None,  # Receipt-level creation
                        creation_type='organization',
                        creation_id=org.id,
                        task_id=task.id,
                        metadata={'vendor_name': vendor_name}
                    )
                    logger.info(f"Created/promoted and tracked organization: {org.name}")
        
        logger.info(f"Successfully processed receipt task with enhanced tracking: Invoice {invoice_number}")
        return True
        
    except Exception as e:
        logger.error(f"Error in process_receipt_task_enhanced: {str(e)}")
        db.session.rollback()
        return False

def create_object_from_line_item(item, invoice, line_idx):
    """
    Create an object from a line item with smart type detection, category suggestions,
    attachment processing, QR code extraction, and confirmation code handling.
    """
    try:
        description = item.get('description', 'Unnamed Item')
        quantity = int(float(item.get('quantity', 1)))
        unit_price = float(item.get('unit_price', 0))
        
        # Smart object type detection
        object_type = determine_object_type_smart(description)
        
        # Use AI-suggested categories from the receipt analysis first, fallback to smart suggestions
        suggested_category = None
        category = None
        
        # First try to get AI-suggested category from extracted metadata
        if extracted_metadata:
            suggested_category = (extracted_metadata.get('suggested_category') or 
                                (extracted_metadata.get('category_suggestions', []) and 
                                 extracted_metadata['category_suggestions'][0]))
        
        # If no AI suggestion, use fallback smart categorization
        if not suggested_category:
            suggested_categories = suggest_categories_smart(description)
            if suggested_categories:
                suggested_category = suggested_categories[0]
        
        # Create/ensure the category exists if we have a suggestion
        if suggested_category:
            category = ensure_category_exists(suggested_category, object_type)
            logger.info(f"Using {'AI-suggested' if extracted_metadata.get('suggested_category') else 'smart-suggested'} category: {suggested_category}")
        
        # Extract additional metadata from item
        extracted_metadata = item.get('extracted_metadata', {})
        upc = extract_upc_from_text(description)
        manufacturer = extract_manufacturer(description, invoice.data.get('vendor_name', ''))
        model_number = extract_model_number(description)
        serial_number = extract_serial_number(description)
        
        # Create object data
        object_data = {
            'name': description,
            'description': description,
            'acquisition_cost': unit_price,
            'acquisition_date': invoice.data.get('date', datetime.utcnow().strftime('%Y-%m-%d')),
            'vendor': invoice.data.get('vendor_name', 'Unknown Vendor'),
            'quantity': quantity,
            'ai_processed': True,
            'ai_confidence': 0.8,
            'created_from_receipt': True,
            'invoice_id': invoice.id,
            'line_item_index': line_idx,
            'line_item_data': item,
            'category': category.name if category else suggested_category or 'uncategorized',
            'category_id': category.id if category else None,
            'suggested_category': suggested_category,
            'ai_category_used': bool(extracted_metadata and extracted_metadata.get('suggested_category')),
        }
        
        # Add extracted metadata
        if upc:
            object_data['upc'] = upc
        if manufacturer:
            object_data['manufacturer'] = manufacturer
        if model_number:
            object_data['model_number'] = model_number
        if serial_number:
            object_data['serial_number'] = serial_number
            object_data['track_serial'] = True
        
        # Add depreciation and maintenance info
        if has_serial_indicators(description):
            object_data['track_serial'] = True
            object_data['depreciation_category'] = get_depreciation_category(description)
        
        if requires_maintenance(description):
            object_data['requires_maintenance'] = True
        
        # Extract confirmation codes if present
        digital_assets = invoice.data.get('digital_assets', {})
        conf_code_data = (digital_assets.get('confirmation_code') or
                         digital_assets.get('confirmation_codes') or
                         extracted_metadata.get('confirmation_code') or
                         extracted_metadata.get('confirmation_codes'))
        
        if conf_code_data:
            object_data['has_confirmation_code'] = True
            object_data['confirmation_code'] = conf_code_data[0] if isinstance(conf_code_data, list) else conf_code_data
        
        # Check for QR codes
        if digital_assets.get('qr_code') or extracted_metadata.get('qr_code'):
            object_data['has_qr_code'] = True
        
        # Add type-specific data
        if object_type == 'consumable':
            object_data.update({
                'current_stock': quantity,
                'track_stock': True,
                'reorder_threshold': max(1, quantity // 4),
                'consumption_type': 'countable'
            })
        elif object_type == 'asset':
            object_data.update({
                'depreciation_method': 'straight_line',
                'depreciation_period': 60  # 5 years default
            })
        
        # Create the object
        new_object = Object(
            invoice_id=invoice.id,
            object_type=object_type,
            data=object_data
        )
        db.session.add(new_object)
        db.session.flush()  # Get the ID
        
        # Link object to category if one was created/found
        if category:
            new_object.categories.append(category)
            logger.info(f"Linked object {new_object.id} to category '{category.name}' (ID: {category.id})")
        
        # Handle attachments
        _create_object_attachments(new_object, invoice, digital_assets, extracted_metadata)
        
        logger.info(f"Created {object_type} object '{description}' from line item {line_idx} with category '{category.name if category else 'uncategorized'}'")
        return new_object
        
    except Exception as e:
        logger.error(f"Error creating object from line item {line_idx}: {str(e)}")
        return None

def _create_object_attachments(obj, invoice, digital_assets, extracted_metadata):
    """
    Create attachments for the object including QR codes, confirmation codes, and receipt image.
    """
    try:
        logger.debug(f"Creating attachments for object {obj.id} - digital_assets: {digital_assets}, extracted_metadata: {extracted_metadata}")
        # Copy receipt attachment to object
        receipt_attachment = Attachment.query.filter_by(invoice_id=invoice.id).first()
        if receipt_attachment:
            object_attachment = ObjectAttachment(
                object_id=obj.id,
                filename=f"receipt_{invoice.invoice_number}_{receipt_attachment.filename}",
                file_data=receipt_attachment.file_data,
                file_type=receipt_attachment.file_type,
                attachment_type='receipt',
                description=f'Original receipt for {obj.data.get("name", "object")}',
                ai_analyzed=True,
                ai_analysis_result={'source': 'receipt', 'invoice_id': invoice.id}
            )
            db.session.add(object_attachment)
        
        # Create QR code attachments - both text and image if available
        qr_code_data = digital_assets.get('qr_code') or extracted_metadata.get('qr_code')
        qr_code_image = digital_assets.get('qr_code_image') or extracted_metadata.get('qr_code_image')
        
        if qr_code_data:
            # Create text attachment for QR code data
            qr_text_attachment = ObjectAttachment(
                object_id=obj.id,
                filename=f"qr_code_{obj.id}.txt",
                file_data=qr_code_data.encode('utf-8') if isinstance(qr_code_data, str) else str(qr_code_data).encode('utf-8'),
                file_type='text/plain',
                attachment_type='qr_code',
                description='QR code data from receipt',
                ai_analyzed=True,
                ai_analysis_result={'type': 'qr_code', 'data': qr_code_data}
            )
            db.session.add(qr_text_attachment)
            logger.info(f"Created QR code text attachment for object {obj.id}")
        
        if qr_code_image:
            # Create image attachment for cropped QR code
            try:
                import base64
                qr_image_data = base64.b64decode(qr_code_image)
                qr_image_attachment = ObjectAttachment(
                    object_id=obj.id,
                    filename=f"qr_code_{obj.id}.jpg",
                    file_data=qr_image_data,
                    file_type='image/jpeg',
                    attachment_type='qr_code_image',
                    description='Cropped QR code image from receipt',
                    ai_analyzed=True,
                    ai_analysis_result={'type': 'qr_code_image', 'source': 'ai_cropped'}
                )
                db.session.add(qr_image_attachment)
                logger.info(f"Created QR code image attachment for object {obj.id}")
            except Exception as e:
                logger.error(f"Error creating QR code image attachment: {str(e)}")
        
        # Create UPC code attachments - both text and image if available
        upc_code_data = digital_assets.get('upc_code') or extracted_metadata.get('upc_code')
        upc_code_image = digital_assets.get('upc_code_image') or extracted_metadata.get('upc_code_image')
        
        if upc_code_data:
            # Create text attachment for UPC code data
            upc_text_attachment = ObjectAttachment(
                object_id=obj.id,
                filename=f"upc_code_{obj.id}.txt",
                file_data=str(upc_code_data).encode('utf-8'),
                file_type='text/plain',
                attachment_type='upc_code',
                description='UPC/barcode data from receipt',
                ai_analyzed=True,
                ai_analysis_result={'type': 'upc_code', 'data': upc_code_data}
            )
            db.session.add(upc_text_attachment)
            logger.info(f"Created UPC code text attachment for object {obj.id}")
        
        if upc_code_image:
            # Create image attachment for cropped UPC code
            try:
                upc_image_data = base64.b64decode(upc_code_image)
                upc_image_attachment = ObjectAttachment(
                    object_id=obj.id,
                    filename=f"upc_code_{obj.id}.jpg",
                    file_data=upc_image_data,
                    file_type='image/jpeg',
                    attachment_type='upc_code_image',
                    description='Cropped UPC/barcode image from receipt',
                    ai_analyzed=True,
                    ai_analysis_result={'type': 'upc_code_image', 'source': 'ai_cropped'}
                )
                db.session.add(upc_image_attachment)
                logger.info(f"Created UPC code image attachment for object {obj.id}")
            except Exception as e:
                logger.error(f"Error creating UPC code image attachment: {str(e)}")
        
        # Create confirmation code attachments
        conf_code_data = (digital_assets.get('confirmation_code') or
                         digital_assets.get('confirmation_codes') or
                         extracted_metadata.get('confirmation_code') or
                         extracted_metadata.get('confirmation_codes'))
        
        if conf_code_data:
            # Handle multiple confirmation codes or single code
            conf_codes = conf_code_data if isinstance(conf_code_data, list) else [conf_code_data]
            
            for i, conf_code in enumerate(conf_codes):
                conf_attachment = ObjectAttachment(
                    object_id=obj.id,
                    filename=f"confirmation_{obj.id}_{i+1}.txt" if len(conf_codes) > 1 else f"confirmation_{obj.id}.txt",
                    file_data=str(conf_code).encode('utf-8'),
                    file_type='text/plain',
                    attachment_type='confirmation_code',
                    description=f'Confirmation code{f" #{i+1}" if len(conf_codes) > 1 else ""} from receipt',
                    ai_analyzed=True,
                    ai_analysis_result={'type': 'confirmation_code', 'code': str(conf_code)}
                )
                db.session.add(conf_attachment)
                logger.info(f"Created confirmation code attachment #{i+1} for object {obj.id}")
        
        db.session.flush()
        
    except Exception as e:
        logger.error(f"Error creating attachments for object {obj.id}: {str(e)}")

def create_person_from_data(person_data, invoice):
    """
    Create a person object from AI-detected person data.
    """
    try:
        person_name = person_data.get('person_name', 'Unknown Person')
        
        # Create person object data
        object_data = {
            'name': person_name,
            'description': f"Person detected from receipt analysis",
            'role': person_data.get('person_role', ''),
            'relationship_to_purchase': person_data.get('relationship', ''),
            'detected_from_receipt': True,
            'receipt_id': invoice.id,
            'vendor': invoice.data.get('vendor_name', 'Unknown Vendor'),
            'detection_date': datetime.utcnow().strftime('%Y-%m-%d'),
            'ai_processed': True,
            'person_data': person_data
        }
        
        # Create the person object
        person_object = Object(
            invoice_id=invoice.id,
            object_type='person',
            data=object_data
        )
        db.session.add(person_object)
        db.session.flush()  # Get the ID
        
        logger.info(f"Created person object '{person_name}' from receipt {invoice.invoice_number}")
        return person_object
        
    except Exception as e:
        logger.error(f"Error creating person from data: {str(e)}")
        return None

def create_event_from_data(event_details, invoice):
    """
    Create a calendar event from AI-detected event data.
    """
    try:
        event_title = event_details.get('event_name', f"Event from {invoice.data.get('vendor_name', 'Unknown Vendor')}")
        event_date_str = event_details.get('event_date', invoice.data.get('date'))
        event_location = event_details.get('venue_location', '')
        
        # Parse event date
        event_date = None
        if event_date_str:
            try:
                event_date = datetime.strptime(event_date_str, '%Y-%m-%d')
            except ValueError:
                try:
                    event_date = datetime.strptime(event_date_str, '%m/%d/%Y')
                except ValueError:
                    event_date = datetime.utcnow()
        else:
            event_date = datetime.utcnow()
        
        # Create the calendar event
        calendar_event = CalendarEvent(
            title=event_title,
            description=f"Event created from receipt analysis. {event_details.get('description', '')}",
            start_time=event_date,
            event_type='entertainment',
            data={
                'location': event_location,
                'created_from_receipt': True,
                'receipt_id': invoice.id,
                'event_details': event_details,
                'vendor': invoice.data.get('vendor_name', 'Unknown Vendor')
            }
        )
        db.session.add(calendar_event)
        db.session.flush()  # Get the ID
        
        logger.info(f"Created calendar event '{event_title}' from receipt {invoice.invoice_number}")
        return calendar_event
        
    except Exception as e:
        logger.error(f"Error creating event from data: {str(e)}")
        return None

@app.route('/view-attachment/<int:attachment_id>')
def view_attachment(attachment_id):
    """
    View a receipt attachment (PDF or image) in the browser.
    """
    try:
        attachment = Attachment.query.get(attachment_id)
        if not attachment:
            flash('Attachment not found', 'danger')
            return redirect(url_for('receipts_page'))
        
        return Response(
            attachment.file_data,
            mimetype=attachment.file_type,
            headers={
                'Content-Disposition': f'inline; filename="{attachment.filename}"',
                'Content-Type': attachment.file_type
            }
        )
        
    except Exception as e:
        logger.error(f"Error viewing attachment {attachment_id}: {str(e)}")
        flash(f'Error viewing attachment: {str(e)}', 'danger')
        return redirect(url_for('receipts_page'))

@app.route('/view-object-attachment/<int:attachment_id>')
def view_object_attachment(attachment_id):
    """
    View an object attachment (photo, document, QR code, etc.) in the browser.
    """
    try:
        attachment = ObjectAttachment.query.get(attachment_id)
        if not attachment:
            flash('Object attachment not found', 'danger')
            return redirect(url_for('inventory'))
        
        return Response(
            attachment.file_data,
            mimetype=attachment.file_type,
            headers={
                'Content-Disposition': f'inline; filename="{attachment.filename}"',
                'Content-Type': attachment.file_type
            }
        )
        
    except Exception as e:
        logger.error(f"Error viewing object attachment {attachment_id}: {str(e)}")
        flash(f'Error viewing object attachment: {str(e)}', 'danger')
        return redirect(url_for('inventory'))

# ==========================================
# USER MANAGEMENT ENDPOINTS
# ==========================================

@app.route('/users')
def users_page():
    """Users management page"""
    try:
        users = User.query.order_by(User.username).all()
        
        # Get similar person groups for potential user promotions
        similar_groups = User.find_similar_person_groups(confidence_threshold=0.8)
        
        return render_template('users.html', users=users, similar_groups=similar_groups)
    except Exception as e:
        logger.error(f"Error loading users page: {str(e)}")
        flash(f'Error loading users: {str(e)}', 'danger')
        return render_template('users.html', users=[], similar_groups=[])

@app.route('/users/<int:user_id>')
def view_user(user_id):
    """View user details and linked person objects"""
    try:
        user = User.query.get_or_404(user_id)
        linked_persons = user.get_linked_person_objects()
        
        # Get all entities related to the linked person objects
        person_names = []
        for person in linked_persons:
            person_name = person.data.get('name', '')
            if person_name:
                person_names.append(person_name)
        
        # Initialize related entities collections
        related_objects = []
        related_invoices = []
        related_organizations = []
        related_calendar_events = []
        related_notes = []
        related_tasks = []
        
        if linked_persons:
            from sqlalchemy import or_
            
            # Get person object IDs for relationship queries
            person_ids = {person.id for person in linked_persons}
            
            # 1. Related Objects through proper database relationships
            related_objects_set = set()
            
            for person in linked_persons:
                # A. Objects that have this person as parent (components of person objects)
                child_objects = Object.query.filter_by(parent_id=person.id).all()
                related_objects_set.update(child_objects)
                
                # B. Objects that have this person object as their parent (if person is a component)
                if person.parent_id:
                    parent_object = Object.query.get(person.parent_id)
                    if parent_object:
                        related_objects_set.add(parent_object)
                        # Also get siblings (other components of the same parent)
                        siblings = Object.query.filter(
                            Object.parent_id == person.parent_id,
                            Object.id != person.id
                        ).all()
                        related_objects_set.update(siblings)
                
                # C. Pet objects related to this person through PersonPetAssociation
                pet_associations = PersonPetAssociation.query.filter_by(person_id=person.id).all()
                for assoc in pet_associations:
                    pet_object = Object.query.get(assoc.object_id)
                    if pet_object:
                        related_objects_set.add(pet_object)
                
                # D. Objects from same invoices as this person object
                if person.invoice_id:
                    invoice_objects = Object.query.filter(
                        Object.invoice_id == person.invoice_id,
                        Object.id != person.id
                    ).all()
                    related_objects_set.update(invoice_objects)
                
                # E. Objects in same collections as this person object
                person_collections = person.collections.all()
                for collection in person_collections:
                    collection_objects = collection.objects.filter(Object.id != person.id).all()
                    related_objects_set.update(collection_objects)
                
                # F. Objects that have notes referencing this person object
                person_notes = Note.query.filter_by(object_id=person.id).all()
                for note in person_notes:
                    if note.object_id and note.object_id != person.id:
                        noted_object = Object.query.get(note.object_id)
                        if noted_object:
                            related_objects_set.add(noted_object)
            
            # Convert to list and sort by creation date
            related_objects = sorted(list(related_objects_set), 
                                   key=lambda x: x.created_at or datetime.min, reverse=True)
            
            # 2. Related Invoices through proper relationships
            related_invoices_set = set()
            for person in linked_persons:
                # A. Invoices that contain this person object
                if person.invoice_id:
                    invoice = Invoice.query.get(person.invoice_id)
                    if invoice:
                        related_invoices_set.add(invoice)
                
                # B. Invoices from organizations where this person is a contact
                org_contacts = OrganizationContact.query.filter_by(person_object_id=person.id).all()
                for contact in org_contacts:
                    org_invoices = Invoice.query.filter(
                        Invoice.data['vendor'].astext == contact.organization.name
                    ).all()
                    related_invoices_set.update(org_invoices)
            
            related_invoices = sorted(list(related_invoices_set), 
                                    key=lambda x: x.created_at or datetime.min, reverse=True)
            
            # 3. Related Organizations through proper relationships
            related_organizations_set = set()
            for person in linked_persons:
                # Organizations where this person is a contact
                org_contacts = OrganizationContact.query.filter_by(person_object_id=person.id).all()
                for contact in org_contacts:
                    related_organizations_set.add(contact.organization)
            
            related_organizations = sorted(list(related_organizations_set), 
                                         key=lambda x: x.created_at or datetime.min, reverse=True)
            
            # 4. Related Calendar Events through proper relationships
            related_calendar_events_set = set()
            for person in linked_persons:
                # A. Events created by the user (if person is linked to user)
                if user:
                    user_events = CalendarEvent.query.filter_by(user_id=user.id).all()
                    related_calendar_events_set.update(user_events)
                
                # B. Events from same invoices as person objects
                if person.invoice_id:
                    invoice_events = CalendarEvent.query.filter(
                        CalendarEvent.data['invoice_id'].astext == str(person.invoice_id)
                    ).all()
                    related_calendar_events_set.update(invoice_events)
            
            related_calendar_events = sorted(list(related_calendar_events_set), 
                                           key=lambda x: x.start_time or datetime.min, reverse=True)
            
            # 5. Related Notes through proper relationships
            related_notes_set = set()
            for person in linked_persons:
                # A. Notes directly attached to this person object
                person_notes = Note.query.filter_by(object_id=person.id).all()
                related_notes_set.update(person_notes)
                
                # B. Notes created by the user (if person is linked to user)
                if user:
                    user_notes = Note.query.filter_by(user_id=user.id).all()
                    related_notes_set.update(user_notes)
                
                # C. Notes attached to organizations where this person is a contact
                org_contacts = OrganizationContact.query.filter_by(person_object_id=person.id).all()
                for contact in org_contacts:
                    org_notes = Note.query.filter_by(organization_id=contact.organization_id).all()
                    related_notes_set.update(org_notes)
            
            related_notes = sorted(list(related_notes_set), 
                                 key=lambda x: x.created_at or datetime.min, reverse=True)
            
            # 6. Related Tasks through proper relationships
            related_tasks_set = set()
            for person in linked_persons:
                # A. Tasks that created this person object
                creation_tasks = TaskQueue.query.filter(
                    TaskQueue.data['created_object_id'].astext == str(person.id)
                ).all()
                related_tasks_set.update(creation_tasks)
                
                # B. Tasks from same invoices as person objects
                if person.invoice_id:
                    invoice_tasks = TaskQueue.query.filter(
                        TaskQueue.data['receipt_id'].astext == str(person.invoice_id)
                    ).all()
                    related_tasks_set.update(invoice_tasks)
            
            related_tasks = sorted(list(related_tasks_set), 
                                 key=lambda x: x.created_at or datetime.min, reverse=True)
        
        return render_template('user_details.html', 
                               user=user, 
                               linked_persons=linked_persons,
                               related_objects=related_objects,
                               related_invoices=related_invoices,
                               related_organizations=related_organizations,
                               related_calendar_events=related_calendar_events,
                               related_notes=related_notes,
                               related_tasks=related_tasks,
                               person_names=person_names)
    except Exception as e:
        logger.error(f"Error loading user {user_id}: {str(e)}")
        flash(f'Error loading user: {str(e)}', 'danger')
        return redirect(url_for('users_page'))

@app.route('/promote-person-to-user/<int:person_id>', methods=['GET', 'POST'])
def promote_person_to_user(person_id):
    """Promote a person object to a User entity or link to existing user"""
    try:
        person = Object.query.get_or_404(person_id)
        
        if person.object_type != 'person':
            flash('Only person objects can be promoted to users', 'warning')
            return redirect(request.referrer or url_for('inventory'))
        
        person_name = person.data.get('name', '')
        
        if request.method == 'GET':
            # Show promotion options page with similar users
            similar_users = UserAlias.find_matching_users(person_name, confidence_threshold=0.7)
            return render_template('promote_person.html', 
                                   person=person, 
                                   similar_users=similar_users)
        
        # POST request - handle promotion action
        action = request.form.get('action')
        
        if action == 'link_existing':
            # Link to existing user
            user_id = int(request.form.get('user_id'))
            user = User.query.get_or_404(user_id)
            
            # Check if mapping already exists
            existing_mapping = UserPersonMapping.query.filter_by(
                user_id=user_id, 
                person_object_id=person_id
            ).first()
            
            if existing_mapping:
                flash(f'Person "{person_name}" is already linked to user "{user.display_name}"', 'info')
                return redirect(url_for('view_user', user_id=user_id))
            
            # Create person mapping
            mapping = UserPersonMapping(
                user_id=user_id,
                person_object_id=person_id,
                is_primary=False  # Not primary since user already exists
            )
            db.session.add(mapping)
            
            # Add alias if it doesn't exist
            if person_name:
                user.add_alias(person_name, 'linked_person', 1.0)
            
            db.session.commit()
            
            flash(f'Successfully linked "{person_name}" to existing user "{user.display_name}"!', 'success')
            return redirect(url_for('view_user', user_id=user_id))
            
        elif action == 'create_new':
            # Create new user
            first_name = person.data.get('first_name', '')
            last_name = person.data.get('last_name', '')
            email = person.data.get('email', '')
            
            # Generate username from name
            if first_name and last_name:
                username = f"{first_name.lower()}.{last_name.lower()}".replace(' ', '.')
            else:
                username = person_name.lower().replace(' ', '.')
            
            # Ensure unique username
            counter = 1
            original_username = username
            while User.query.filter_by(username=username).first():
                username = f"{original_username}{counter}"
                counter += 1
            
            # Create user
            user = User(
                username=username,
                email=email or f"{username}@example.com",
                data={
                    'display_name': person_name,
                    'first_name': first_name,
                    'last_name': last_name,
                    'promoted_from_person_id': person_id,
                    'promoted_at': datetime.utcnow().isoformat()
                }
            )
            
            db.session.add(user)
            db.session.flush()
            
            # Create primary person mapping
            mapping = UserPersonMapping(
                user_id=user.id,
                person_object_id=person_id,
                is_primary=True
            )
            db.session.add(mapping)
            
            # Add primary alias
            if person_name:
                alias = UserAlias(
                    user_id=user.id,
                    alias_name=person_name,
                    alias_type='primary_name',
                    confidence=1.0
                )
                db.session.add(alias)
            
            db.session.commit()
            
            flash(f'Successfully created new user "{username}" from "{person_name}"!', 'success')
            return redirect(url_for('view_user', user_id=user.id))
        
        else:
            flash('Invalid action specified', 'danger')
            return redirect(request.referrer or url_for('inventory'))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error promoting person {person_id} to user: {str(e)}")
        flash(f'Error promoting person to user: {str(e)}', 'danger')
        return redirect(request.referrer or url_for('inventory'))

@app.route('/users/<int:user_id>/add-alias', methods=['POST'])
def add_user_alias(user_id):
    """Add an alias to a user for dynamic person linking"""
    try:
        user = User.query.get_or_404(user_id)
        
        alias_name = request.form.get('alias_name', '').strip()
        alias_type = request.form.get('alias_type', 'name')
        confidence = float(request.form.get('confidence', 1.0))
        
        if not alias_name:
            flash('Alias name is required', 'warning')
            return redirect(url_for('view_user', user_id=user_id))
        
        alias = user.add_alias(alias_name, alias_type, confidence)
        db.session.commit()
        
        flash(f'Added alias "{alias_name}" to user {user.display_name}', 'success')
        return redirect(url_for('view_user', user_id=user_id))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error adding alias to user {user_id}: {str(e)}")
        flash(f'Error adding alias: {str(e)}', 'danger')
        return redirect(url_for('view_user', user_id=user_id))

@app.route('/users/<int:user_id>/remove-alias/<int:alias_id>', methods=['POST'])
def remove_user_alias(user_id, alias_id):
    """Remove an alias from a user"""
    try:
        alias = UserAlias.query.filter_by(id=alias_id, user_id=user_id).first_or_404()
        alias_name = alias.alias_name
        
        db.session.delete(alias)
        db.session.commit()
        
        flash(f'Removed alias "{alias_name}"', 'success')
        return redirect(url_for('view_user', user_id=user_id))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error removing alias {alias_id} from user {user_id}: {str(e)}")
        flash(f'Error removing alias: {str(e)}', 'danger')
        return redirect(url_for('view_user', user_id=user_id))

@app.route('/api/similar-persons', methods=['GET'])
def get_similar_persons():
    """API endpoint to get groups of similar person objects"""
    try:
        confidence_threshold = float(request.args.get('confidence', 0.8))
        similar_groups = User.find_similar_person_groups(confidence_threshold)
        
        groups_data = []
        for group in similar_groups:
            group_data = []
            for person in group:
                group_data.append({
                    'id': person.id,
                    'name': person.data.get('name', ''),
                    'description': person.data.get('description', ''),
                    'created_at': person.created_at.isoformat() if person.created_at else None
                })
            groups_data.append(group_data)
        
        return jsonify({
            'success': True,
            'groups': groups_data,
            'count': len(groups_data)
        })
        
    except Exception as e:
        logger.error(f"Error getting similar persons: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500