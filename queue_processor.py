import os
import json
import logging
import argparse
import time
import traceback
from datetime import datetime, timedelta
from sqlalchemy.exc import SQLAlchemyError
from app import app, db
from models import Object, TaskQueue, Reminder

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='logs/queue_processor.log',
    filemode='a'
)
logger = logging.getLogger('queue_processor')

def process_tasks():
    """
    Main function to process all pending tasks in the queue.
    """
    logger.info("Starting task queue processor")
    
    with app.app_context():
        # Get all pending tasks that are ready to be executed
        tasks = TaskQueue.get_pending_tasks()
        
        if not tasks:
            logger.info("No pending tasks found")
            return
        
        logger.info(f"Found {len(tasks)} pending tasks to process")
        
        for task in tasks:
            try:
                # Mark task as processing
                task.status = 'processing'
                task.last_attempt = datetime.utcnow()
                task.attempts += 1
                db.session.commit()
                
                logger.info(f"Processing task {task.id} of type {task.task_type}")
                
                # Process task based on type
                result = None
                if task.task_type == 'consumable_expiration':
                    result = process_consumable_expiration(task)
                elif task.task_type == 'stock_check':
                    result = process_stock_check(task)
                else:
                    logger.warning(f"Unknown task type: {task.task_type}")
                    task.status = 'failed'
                    task.error_message = f"Unknown task type: {task.task_type}"
                    db.session.commit()
                    continue
                
                # Mark task as completed
                task.status = 'completed'
                task.completed_at = datetime.utcnow()
                task.result = result
                db.session.commit()
                logger.info(f"Task {task.id} completed successfully")
                
            except Exception as e:
                logger.error(f"Error processing task {task.id}: {str(e)}")
                logger.error(traceback.format_exc())
                
                # Mark task as failed
                task.status = 'failed'
                task.error_message = str(e)
                db.session.commit()

def process_consumable_expiration(task):
    """
    Process a consumable expiration task.
    Reduces the quantity of a consumable when it expires.
    
    Args:
        task: TaskQueue object with task_type='consumable_expiration'
        
    Returns:
        dict: Result information
    """
    logger.info(f"Processing consumable expiration for object {task.object_id}")
    
    # Get the consumable object
    obj = Object.query.get(task.object_id)
    if not obj:
        return {'error': f"Object with ID {task.object_id} not found"}
    
    if obj.object_type != 'consumable':
        return {'error': f"Object {task.object_id} is not a consumable"}
        
    # Get the expiring quantity from task data
    expiring_quantity = task.data.get('quantity', 1)
    
    # Get current quantity
    current_quantity = obj.data.get('quantity', 0)
    
    # Calculate new quantity
    new_quantity = max(0, current_quantity - expiring_quantity)
    
    # Update the object
    obj.data['quantity'] = new_quantity
    
    # If this consumable is stock tracked and quantity is now 0 or below threshold, 
    # add it to the shopping list
    track_stock = obj.data.get('track_stock', False)
    reorder_threshold = obj.data.get('reorder_threshold', 0)
    
    if track_stock and new_quantity <= reorder_threshold:
        # Add to shopping list
        add_to_shopping_list(obj)
    
    # If not stock tracked and quantity is 0, mark for deletion
    if not track_stock and new_quantity <= 0:
        obj.data['marked_for_deletion'] = True
        
    # Save changes
    db.session.commit()
    
    # Return result info
    return {
        'object_id': obj.id,
        'name': obj.data.get('name', 'Unknown Consumable'),
        'previous_quantity': current_quantity,
        'expired_quantity': expiring_quantity,
        'new_quantity': new_quantity,
        'track_stock': track_stock,
        'added_to_shopping_list': track_stock and new_quantity <= reorder_threshold
    }

def process_stock_check(task):
    """
    Process a stock check task.
    Checks inventory levels for all tracked consumables and components.
    
    Args:
        task: TaskQueue object with task_type='stock_check'
        
    Returns:
        dict: Result information
    """
    logger.info("Processing stock check task")
    
    # Get all consumables and components that are stock tracked
    consumables = Object.query.filter_by(object_type='consumable').all()
    components = Object.query.filter_by(object_type='component').all()
    
    low_stock_items = []
    
    # Check consumables
    for item in consumables:
        if item.data.get('track_stock', False):
            quantity = item.data.get('quantity', 0)
            threshold = item.data.get('reorder_threshold', 0)
            
            if quantity <= threshold:
                low_stock_items.append(item)
                logger.info(f"Consumable {item.id} ({item.data.get('name')}) is below threshold: {quantity}/{threshold}")
    
    # Check components
    for item in components:
        if item.data.get('track_stock', False):
            quantity = item.data.get('quantity', 0)
            threshold = item.data.get('reorder_threshold', 0)
            
            if quantity <= threshold:
                low_stock_items.append(item)
                logger.info(f"Component {item.id} ({item.data.get('name')}) is below threshold: {quantity}/{threshold}")
    
    # Add all low stock items to shopping list
    for item in low_stock_items:
        add_to_shopping_list(item)
    
    # Schedule next stock check (weekly)
    next_check = datetime.utcnow() + timedelta(days=7)
    TaskQueue.queue_task({
        'task_type': 'stock_check',
        'execute_at': next_check,
        'priority': 2,  # Medium-low priority
        'data': {}
    })
    
    return {
        'items_checked': len(consumables) + len(components),
        'low_stock_items': len(low_stock_items),
        'next_check': next_check.isoformat()
    }

def add_to_shopping_list(obj):
    """
    Add an item to the shopping list reminder.
    
    Args:
        obj: Object model instance to add to the shopping list
        
    Returns:
        bool: Success status
    """
    try:
        # Get the current shopping list or create a new one
        shopping_list = Reminder.query.filter_by(
            reminder_type='shopping_list',
            status='open'
        ).first()
        
        if not shopping_list:
            # Create a new shopping list
            shopping_list = Reminder(
                title="Shopping List - Inventory Restock",
                description="Items that need to be reordered based on inventory thresholds",
                reminder_type='shopping_list',
                status='open',
                due_date=datetime.utcnow() + timedelta(days=7),
                items=[]
            )
            db.session.add(shopping_list)
            db.session.flush()  # Get the ID without committing
            
        # Get current items
        items = shopping_list.items or []
        
        # Check if the item is already in the list
        for item in items:
            if item.get('object_id') == obj.id:
                logger.info(f"Item {obj.id} ({obj.data.get('name')}) already in shopping list")
                return True
        
        # Add the item
        suggested_quantity = max(1, obj.data.get('reorder_threshold', 1))
        
        items.append({
            'object_id': obj.id,
            'name': obj.data.get('name', 'Unknown Item'),
            'object_type': obj.object_type,
            'current_quantity': obj.data.get('quantity', 0),
            'suggested_quantity': suggested_quantity,
            'purchased': False,
            'added_at': datetime.utcnow().isoformat()
        })
        
        # Update the shopping list
        shopping_list.items = items
        db.session.commit()
        
        logger.info(f"Added {obj.data.get('name')} to shopping list")
        return True
        
    except Exception as e:
        logger.error(f"Error adding item to shopping list: {str(e)}")
        db.session.rollback()
        return False

def run_queue_processor_loop():
    """
    Run the queue processor in a continuous loop.
    Processes tasks every minute.
    """
    while True:
        try:
            process_tasks()
        except Exception as e:
            logger.error(f"Error in queue processor loop: {str(e)}")
        
        # Sleep for a minute
        time.sleep(60)

if __name__ == "__main__":
    # If run as a script, start the continuous processor loop
    logger.info("Starting queue processor in continuous loop mode")
    run_queue_processor_loop()