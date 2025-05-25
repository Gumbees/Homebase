#!/usr/bin/env python3

from app import app, db
from models import TaskQueue

def debug_ai_queue():
    with app.app_context():
        print("=== AI QUEUE DEBUG ===")
        
        # Get all AI-related tasks with relevant statuses
        ai_related_statuses = ['pending', 'pending_review', 'ai_analysis_failed', 'processing', 'needs_review']
        
        tasks = TaskQueue.query.filter(
            TaskQueue.status.in_(ai_related_statuses)
        ).order_by(TaskQueue.created_at.desc()).all()
        
        print(f"Total tasks found: {len(tasks)}")
        
        # Categorize tasks for the template
        receipt_tasks = []
        ai_evaluations = []
        
        for task in tasks:
            print(f"  Task {task.id}: type='{task.task_type}', status='{task.status}'")
            if task.task_type == 'receipt_processing':
                # Add extracted receipt data for the template
                task.extracted_receipt_data = {}
                if task.data and task.data.get('ai_analysis'):
                    ai_analysis = task.data['ai_analysis']
                    task.extracted_receipt_data = {
                        'vendor_name': ai_analysis.get('vendor', ''),
                        'date': ai_analysis.get('date', ''),
                        'total_amount': ai_analysis.get('total_amount', 0),
                    }
                    print(f"    Has AI analysis: vendor={task.extracted_receipt_data['vendor_name']}")
                else:
                    print(f"    No AI analysis - task.data keys: {list(task.data.keys()) if task.data else 'None'}")
                receipt_tasks.append(task)
            elif task.task_type in ['object_evaluation', 'ai_evaluation']:
                ai_evaluations.append(task)
        
        print(f"\nCategorized:")
        print(f"  receipt_tasks: {len(receipt_tasks)}")
        print(f"  ai_evaluations: {len(ai_evaluations)}")
        
        # Calculate summary stats
        pending_review = len([t for t in tasks if t.status == 'pending_review'])
        failed_analysis = len([t for t in tasks if t.status == 'ai_analysis_failed'])
        
        print(f"\nSummary stats:")
        print(f"  pending_review: {pending_review}")
        print(f"  failed_analysis: {failed_analysis}")
        
        # Check template data
        template_data = {
            'receipt_tasks': receipt_tasks,
            'ai_evaluations': ai_evaluations,
            'total_tasks': len(tasks),
            'pending_review': pending_review,
            'failed_analysis': failed_analysis
        }
        
        print(f"\nTemplate will receive:")
        for key, value in template_data.items():
            if isinstance(value, list):
                print(f"  {key}: list with {len(value)} items")
            else:
                print(f"  {key}: {value}")

if __name__ == '__main__':
    debug_ai_queue() 