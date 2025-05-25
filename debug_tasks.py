#!/usr/bin/env python3

from app import app, db
from models import TaskQueue

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

if __name__ == '__main__':
    debug_tasks() 