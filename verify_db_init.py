#!/usr/bin/env python3
"""
Database initialization verification script.
This script verifies that all tables are created correctly on a fresh database.
"""

import os
import sys
from app import app, db
from models import *  # Import all models
from sqlalchemy import inspect

def verify_database_initialization():
    """Verify that all database tables are created correctly"""
    with app.app_context():
        try:
            print("🔄 Verifying database initialization...")
            
            # Create all tables
            db.create_all()
            print("✅ db.create_all() executed successfully")
            
            # Initialize default settings
            AISettings.initialize_defaults()
            print("✅ AI Settings initialized")
            
            # Get database inspector
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            
            # Define expected tables
            expected_tables = {
                'vendors',
                'invoices', 
                'invoice_line_items',
                'attachments',
                'objects',
                'object_categories',
                'object_attachments',
                'categories',
                'person_pet_associations',
                'ai_evaluation_queue',
                'ai_settings',
                'task_queue',
                'reminders',
                'organizations',
                'organization_relationships',
                'organization_contacts',
                'users',
                'user_person_mapping',
                'notes',
                'calendar_events',
                'collection_objects',
                'collections',
                'receipt_creation_tracking'  # Our new table
            }
            
            print(f"\n📋 Database contains {len(tables)} tables:")
            for table in sorted(tables):
                status = "✅" if table in expected_tables else "❓"
                print(f"   {status} {table}")
            
            # Check for missing tables
            missing_tables = expected_tables - set(tables)
            if missing_tables:
                print(f"\n❌ Missing expected tables:")
                for table in sorted(missing_tables):
                    print(f"   - {table}")
                return False
            
            # Verify our new table structure
            print(f"\n🔍 Verifying receipt_creation_tracking table structure:")
            if 'receipt_creation_tracking' in tables:
                columns = inspector.get_columns('receipt_creation_tracking')
                expected_columns = {
                    'id', 'invoice_id', 'line_item_index', 'creation_type', 
                    'creation_id', 'created_at', 'created_by_task_id', 'creation_metadata'
                }
                
                actual_columns = {col['name'] for col in columns}
                print(f"   Expected columns: {sorted(expected_columns)}")
                print(f"   Actual columns:   {sorted(actual_columns)}")
                
                if expected_columns <= actual_columns:
                    print("   ✅ All expected columns present")
                else:
                    missing_cols = expected_columns - actual_columns
                    print(f"   ❌ Missing columns: {missing_cols}")
                    return False
                
                # Check for the correct column name (creation_metadata, not metadata)
                if 'creation_metadata' in actual_columns:
                    print("   ✅ Column 'creation_metadata' found (correct name)")
                else:
                    print("   ❌ Column 'creation_metadata' not found")
                    return False
                
                # Show foreign keys
                foreign_keys = inspector.get_foreign_keys('receipt_creation_tracking')
                print(f"   Foreign keys: {len(foreign_keys)} found")
                for fk in foreign_keys:
                    print(f"     - {fk['name']}: {fk['constrained_columns']} -> {fk['referred_table']}.{fk['referred_columns']}")
            
            print(f"\n✅ Database initialization verification completed successfully!")
            print(f"   Total tables: {len(tables)}")
            print(f"   Expected tables: {len(expected_tables)}")
            print(f"   All required tables present: {'Yes' if not missing_tables else 'No'}")
            
            return True
            
        except Exception as e:
            print(f"❌ Error during database verification: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

def test_receipt_creation_tracking():
    """Test the ReceiptCreationTracking model methods"""
    with app.app_context():
        try:
            print("\n🧪 Testing ReceiptCreationTracking model...")
            
            # Test the track_creation method (without committing)
            print("   Testing track_creation method...")
            tracking = ReceiptCreationTracking.track_creation(
                invoice_id=999,  # Non-existent ID for testing
                creation_type='object',
                creation_id=888,
                line_item_index=0,
                metadata={'test': True}
            )
            
            # Verify the object was created correctly
            assert tracking.invoice_id == 999
            assert tracking.creation_type == 'object'
            assert tracking.creation_id == 888
            assert tracking.line_item_index == 0
            assert tracking.creation_metadata == {'test': True}
            print("   ✅ track_creation method works correctly")
            
            # Test the is_created method
            print("   Testing is_created method...")
            # This should return False since we haven't committed
            result = ReceiptCreationTracking.is_created(999, 'object', 0)
            assert result == False
            print("   ✅ is_created method works correctly")
            
            # Don't commit - this is just a test
            db.session.rollback()
            
            print("   ✅ ReceiptCreationTracking model tests passed")
            return True
            
        except Exception as e:
            print(f"   ❌ Error testing ReceiptCreationTracking: {str(e)}")
            db.session.rollback()
            return False

def main():
    """Main verification function"""
    print("🏠 Homebase Database Initialization Verification")
    print("=" * 50)
    
    success = True
    
    # Verify database initialization
    if not verify_database_initialization():
        success = False
    
    # Test our new model
    if not test_receipt_creation_tracking():
        success = False
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 All verification tests passed!")
        print("   The database is properly initialized and ready for use.")
    else:
        print("💥 Some verification tests failed!")
        print("   Please check the errors above and fix any issues.")
        sys.exit(1)

if __name__ == "__main__":
    main() 