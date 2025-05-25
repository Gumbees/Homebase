#!/usr/bin/env python3

import json
from app import app, db
from models import TaskQueue

def debug_task_data():
    with app.app_context():
        print("=== LATEST TASK DATA DEBUG ===")
        
        # Get the latest receipt processing task
        latest_task = TaskQueue.query.filter_by(
            task_type='receipt_processing'
        ).order_by(TaskQueue.created_at.desc()).first()
        
        if not latest_task:
            print("No receipt processing tasks found")
            return
            
        print(f"Task ID: {latest_task.id}")
        print(f"Status: {latest_task.status}")
        print(f"Created: {latest_task.created_at}")
        
        if latest_task.data:
            print("\n=== TASK DATA ===")
            
            # Check key fields
            ai_analysis = latest_task.data.get('ai_analysis')
            ai_error = latest_task.data.get('ai_error')
            ai_provider = latest_task.data.get('ai_provider')
            
            print(f"AI Provider: {ai_provider}")
            print(f"AI Error: {ai_error}")
            print(f"Has AI Analysis: {ai_analysis is not None}")
            
            if ai_analysis:
                print(f"AI Analysis type: {type(ai_analysis)}")
                print(f"AI Analysis keys: {list(ai_analysis.keys()) if isinstance(ai_analysis, dict) else 'Not a dict'}")
                
                if isinstance(ai_analysis, dict):
                    vendor = ai_analysis.get('vendor', 'MISSING')
                    date = ai_analysis.get('date', 'MISSING') 
                    total = ai_analysis.get('total_amount', 'MISSING')
                    print(f"  Vendor: {vendor}")
                    print(f"  Date: {date}")
                    print(f"  Total: {total}")
            else:
                print("AI Analysis is None/empty")
            
            print("\n=== FULL TASK DATA (first 1000 chars) ===")
            data_str = json.dumps(latest_task.data, indent=2)
            print(data_str[:1000])
            if len(data_str) > 1000:
                print("... (truncated)")
        else:
            print("Task has no data")

if __name__ == '__main__':
    debug_task_data() 