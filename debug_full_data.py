#!/usr/bin/env python3

import json
from app import app, db
from models import TaskQueue

def debug_full_data():
    with app.app_context():
        print("=== FULL AI ANALYSIS DEBUG ===")
        
        # Get the latest receipt processing task
        task = TaskQueue.query.filter_by(
            task_type='receipt_processing'
        ).order_by(TaskQueue.created_at.desc()).first()
        
        if not task or not task.data or not task.data.get('ai_analysis'):
            print("No AI analysis data found")
            return
            
        ai_analysis = task.data['ai_analysis']
        if 'content' in ai_analysis and 'response' in ai_analysis['content']:
            response_str = ai_analysis['content']['response']
            
            # Clean up JSON markdown blocks
            if response_str.startswith('```json'):
                response_str = response_str.replace('```json\n', '').replace('\n```', '')
            elif response_str.startswith('```'):
                response_str = response_str.replace('```\n', '').replace('\n```', '')
            
            receipt_data = json.loads(response_str)
            
            print('=== BASIC INFO ===')
            print(f"Vendor: {receipt_data.get('vendor_name', 'N/A')}")
            print(f"Date: {receipt_data.get('date', 'N/A')}")
            print(f"Total: ${receipt_data.get('total_amount', 0)}")
            print(f"Description: {receipt_data.get('description', 'N/A')}")
            print()
            
            print('=== LINE ITEMS ===')
            line_items = receipt_data.get('line_items', [])
            print(f"Found {len(line_items)} line items:")
            for i, item in enumerate(line_items):
                print(f"\nItem {i+1}: {item.get('description', 'N/A')}")
                print(f"  Create Object: {item.get('create_object', False)}")
                print(f"  Object Type: {item.get('object_type', 'N/A')}")
                print(f"  Category: {item.get('category', 'N/A')}")
                print(f"  Unit Price: ${item.get('unit_price', 0)}")
                print(f"  Confidence: {item.get('confidence', 'N/A')}")
                
                # Check for object suggestions
                obj_suggestion = item.get('object_suggestion', {})
                if obj_suggestion:
                    print(f"  Object Suggestion: {obj_suggestion}")
                
                # Check for expiration info (events)
                exp_info = item.get('expiration_info', {})
                if exp_info:
                    print(f"  Expiration Info: {exp_info}")
            
            print('\n=== EVENT DETAILS ===')
            event_details = receipt_data.get('event_details', {})
            if event_details:
                for key, value in event_details.items():
                    print(f"  {key}: {value}")
            else:
                print("  No event details found")
            
            print('\n=== PEOPLE FOUND ===')
            people = receipt_data.get('people_found', [])
            if people:
                for person in people:
                    print(f"  Person: {person.get('person_name', 'N/A')}")
                    print(f"    Role: {person.get('role', 'N/A')}")
                    print(f"    Relationship: {person.get('relationship_to_purchase', 'N/A')}")
                    print(f"    Confidence: {person.get('confidence', 'N/A')}")
                    contact_info = person.get('contact_info', {})
                    if contact_info:
                        print(f"    Contact: {contact_info}")
                    print()
            else:
                print("  No people found")
            
            print('\n=== VENDOR DETAILS ===')
            vendor_details = receipt_data.get('vendor_details', {})
            if vendor_details:
                for key, value in vendor_details.items():
                    print(f"  {key}: {value}")
            else:
                print("  No vendor details found")
            
            print('\n=== DIGITAL ASSETS ===')
            digital_assets = receipt_data.get('digital_assets', {})
            if digital_assets:
                for key, value in digital_assets.items():
                    print(f"  {key}: {value}")
            else:
                print("  No digital assets found")

if __name__ == '__main__':
    debug_full_data() 