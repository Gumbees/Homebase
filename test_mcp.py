#!/usr/bin/env python3

import os
from app import app, db
from models import TaskQueue
from datetime import datetime

def test_task_creation():
    with app.app_context():
        print("Testing task creation with different statuses...")
        
        # Test 1: Create a task with pending_review status directly
        test_task = TaskQueue.queue_task({
            'task_type': 'test_task',
            'execute_at': datetime.utcnow(),
            'priority': 5,
            'status': 'pending_review',
            'data': {'test': 'data'}
        })
        
        print(f"Created test task ID: {test_task.id}")
        print(f"Task status: '{test_task.status}'")
        
        # Test 2: Query it back
        retrieved_task = TaskQueue.query.get(test_task.id)
        print(f"Retrieved task status: '{retrieved_task.status}'")
        
        # Test 3: Check MCP server connection
        print(f"MCP_SERVER_URL: {os.environ.get('MCP_SERVER_URL', 'Not set')}")
        
        # Test 4: Try to import MCP client
        try:
            from mcp_client import analyze_receipt_sync
            print("MCP client import: SUCCESS")
        except Exception as e:
            print(f"MCP client import: FAILED - {e}")

if __name__ == '__main__':
    test_task_creation() 