#!/usr/bin/env python3

from app import app, db
from models import TaskQueue
from datetime import datetime, timedelta
import json

def debug_tasks():
    with app.app_context():
        tasks = TaskQueue.query.all()
        print(f'Total tasks in database: {len(tasks)}')
        print('All tasks:')
        for task in tasks:
            print(f'  ID: {task.id}, Type: {task.task_type}, Status: "{task.status}", Created: {task.created_at}')
        
        print('\nTasks with pending_review status:')
        pending_review_tasks = TaskQueue.query.filter_by(status='pending_review').all()
        print(f'Count: {len(pending_review_tasks)}')
        for task in pending_review_tasks:
            print(f'  ID: {task.id}, Type: {task.task_type}, Status: "{task.status}"')

# Look for recent tasks
recent_tasks = TaskQueue.query.filter(
    TaskQueue.created_at > datetime.utcnow() - timedelta(hours=2)
).order_by(TaskQueue.created_at.desc()).limit(5).all()

print(f'Found {len(recent_tasks)} recent tasks:')
for task in recent_tasks:
    print(f'Task {task.id}: type={task.task_type}, status={task.status}, created={task.created_at}')
    if task.data and task.data.get('ai_analysis'):
        ai_analysis = task.data['ai_analysis']
        if 'content' in ai_analysis and 'response' in ai_analysis['content']:
            response_str = ai_analysis['content']['response']
            if response_str.startswith('```json'):
                response_str = response_str.replace('```json\n', '').replace('\n```', '')
            try:
                receipt_data = json.loads(response_str)
                print(f'  -> vendor: {receipt_data.get("vendor_name", "NOT_FOUND")}')
                print(f'  -> total: {receipt_data.get("total_amount", "NOT_FOUND")}')
                print(f'  -> date: {receipt_data.get("date", "NOT_FOUND")}')
            except Exception as e:
                print(f'  -> Parse error: {e}')
        else:
            print(f'  -> No nested content structure')
    else:
        print(f'  -> No AI analysis data')

if __name__ == '__main__':
    debug_tasks() 