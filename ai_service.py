"""
AI Re-evaluation Service for regular object re-evaluation.
This service runs in the background to process the AI evaluation queue.
"""
import logging
from datetime import datetime, timedelta
from app import db
from models import Object, AIEvaluationQueue
# Import our log utilities
from log_utils import get_logger, log_function_call

# Get a logger for this module using our utilities
logger = get_logger(__name__)

# Maximum number of evaluations to process per day
DAILY_LIMIT = 30

def schedule_evaluations():
    """
    Find objects due for re-evaluation and add them to the queue.
    This function should be called daily by a scheduler.
    """
    logger.info("Finding objects due for re-evaluation...")
    
    try:
        # Find objects that are due for evaluation
        due_objects = AIEvaluationQueue.find_objects_due_for_evaluation()
        
        if not due_objects:
            logger.info("No objects are due for re-evaluation.")
            return 0
        
        logger.info(f"Found {len(due_objects)} objects due for re-evaluation.")
        
        # Schedule them for evaluation
        scheduled_count = AIEvaluationQueue.schedule_evaluations()
        
        logger.info(f"Scheduled {scheduled_count} objects for re-evaluation.")
        return scheduled_count
    
    except Exception as e:
        logger.error(f"Error scheduling evaluations: {str(e)}", exc_info=True)
        return 0

def process_evaluation_queue(date=None, limit=DAILY_LIMIT):
    """
    Process pending evaluations in the queue for a specific date.
    If no date is provided, defaults to today.
    
    Args:
        date: Date to process evaluations for
        limit: Maximum number of evaluations to process
        
    Returns:
        int: Number of evaluations processed
    """
    log_function_call(logger, "process_evaluation_queue", args=(date, limit))
    logger.info(f"Processing evaluation queue for {date or 'today'}...")
    
    try:
        # Get the queue for the specified date
        queue_items = AIEvaluationQueue.get_daily_queue(date, limit)
        
        if not queue_items:
            logger.info("No evaluations in queue.")
            return 0
        
        logger.info(f"Found {len(queue_items)} evaluations to process.")
        
        processed_count = 0
        for queue_item in queue_items:
            # Mark as processing
            queue_item.status = 'processing'
            queue_item.last_attempt = datetime.utcnow()
            queue_item.attempts += 1
            db.session.commit()
            
            try:
                # Get the object
                obj = Object.query.get(queue_item.object_id)
                
                if not obj:
                    logger.warning(f"Object {queue_item.object_id} not found, skipping.")
                    queue_item.status = 'failed'
                    queue_item.error_message = "Object not found"
                    db.session.commit()
                    continue
                
                # Re-evaluate the object based on its type
                logger.debug(f"Re-evaluating object {obj.id} of type {obj.object_type}")
                result = re_evaluate_object(obj)
                
                # Update the queue item
                queue_item.status = 'completed'
                queue_item.completed_at = datetime.utcnow()
                queue_item.result = result
                
                # Record the evaluation in the object
                confidence = result.get('confidence')
                obj.record_evaluation(result, confidence)
                
                db.session.commit()
                processed_count += 1
                
                logger.info(f"Successfully re-evaluated object {obj.id} ({obj.data.get('name', 'unnamed')}).")
                
            except Exception as e:
                logger.error(f"Error processing queue item {queue_item.id}: {str(e)}", exc_info=True)
                queue_item.status = 'failed'
                queue_item.error_message = str(e)
                db.session.commit()
        
        logger.info(f"Processed {processed_count} evaluations.")
        return processed_count
        
    except Exception as e:
        logger.error(f"Error processing evaluation queue: {str(e)}", exc_info=True)
        return 0

def re_evaluate_object(obj):
    """
    Re-evaluate an object using the appropriate AI function based on its type.
    
    Args:
        obj: Object instance to re-evaluate
        
    Returns:
        dict: Result of the evaluation
    """
    log_function_call(logger, "re_evaluate_object", args=(f"Object ID: {obj.id}",))
    
    if obj.is_asset or obj.is_component or obj.is_consumable:
        # For physical objects, use Claude to lookup details
        if 'upc' in obj.data or 'manufacturer' in obj.data or 'model' in obj.data:
            upc = obj.data.get('upc')
            manufacturer = obj.data.get('manufacturer')
            model = obj.data.get('model')
            
            logger.info(f"Looking up details for {obj.object_type} - UPC: {upc}, Manufacturer: {manufacturer}, Model: {model}")
            
            # Import here to avoid circular imports
            from claude_utils import lookup_asset_details_claude
            
            result = lookup_asset_details_claude(upc=upc, oem=manufacturer, model=model)
            
            if result['success']:
                # Check if we should update the data
                confidence = result.get('confidence', 0)
                logger.debug(f"AI lookup returned with confidence: {confidence}")
                
                # If confidence is high enough (>=0.9), automatically update the data
                if confidence >= 0.9:
                    # Update fields 
                    data = obj.data.copy()
                    
                    # Only update these fields if they exist in the result
                    for field in ['manufacturer', 'model', 'category', 'estimated_value', 
                                 'specifications', 'description']:
                        if field in result and result[field]:
                            data[field] = result[field]
                    
                    obj.data = data
                    logger.info(f"Auto-updated object {obj.id} data due to high confidence ({confidence})")
                
                return result
            
            logger.warning(f"Failed to lookup object details for {obj.id}")
            return {'success': False, 'error': 'Failed to lookup object details'}
    
    # For other object types, implement specialized evaluation logic
    # This is a placeholder
    logger.info(f"No specialized re-evaluation for object type {obj.object_type}")
    return {
        'success': True,
        'message': f'Re-evaluated {obj.object_type} object',
        'confidence': 1.0,
        'last_evaluated_at': datetime.utcnow().isoformat()
    }

def run_daily_evaluations():
    """
    Main function to run daily evaluations.
    This should be scheduled to run once a day.
    """
    logger.info("Starting daily AI re-evaluations...")
    
    # First, schedule any objects that are due
    scheduled = schedule_evaluations()
    logger.info(f"Scheduled {scheduled} objects for re-evaluation.")
    
    # Then process the queue for today
    processed = process_evaluation_queue()
    logger.info(f"Processed {processed} evaluations.")
    
    return scheduled, processed