#!/usr/bin/env python3
"""
Database migration script to add receipt creation tracking table.
This table tracks what objects, people, events, and organizations have been created from receipts.
"""

import os
import sys
from app import app, db
from models import ReceiptCreationTracking

def create_receipt_tracking_table():
    """Create the receipt creation tracking table"""
    with app.app_context():
        try:
            # Create the table
            db.create_all()
            
            print("✅ Receipt creation tracking table created successfully!")
            
            # Verify the table exists
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            
            if 'receipt_creation_tracking' in tables:
                print("✅ Table 'receipt_creation_tracking' verified in database")
                
                # Show table structure
                columns = inspector.get_columns('receipt_creation_tracking')
                print("\n📋 Table structure:")
                for col in columns:
                    print(f"   {col['name']}: {col['type']}")
                
                # Show indexes
                indexes = inspector.get_indexes('receipt_creation_tracking')
                if indexes:
                    print("\n📊 Indexes:")
                    for idx in indexes:
                        print(f"   {idx['name']}: {idx['column_names']}")
                        
                # Show foreign keys
                foreign_keys = inspector.get_foreign_keys('receipt_creation_tracking')
                if foreign_keys:
                    print("\n🔗 Foreign keys:")
                    for fk in foreign_keys:
                        print(f"   {fk['name']}: {fk['constrained_columns']} -> {fk['referred_table']}.{fk['referred_columns']}")
                        
            else:
                print("❌ Table 'receipt_creation_tracking' not found in database")
                return False
                
            return True
            
        except Exception as e:
            print(f"❌ Error creating receipt tracking table: {str(e)}")
            db.session.rollback()
            return False

def main():
    """Main migration function"""
    print("🔄 Creating receipt creation tracking table...")
    
    if create_receipt_tracking_table():
        print("\n✅ Migration completed successfully!")
        print("\nThis table will track:")
        print("  • Objects created from receipts (by line item)")
        print("  • People created from receipts")
        print("  • Events created from receipts")
        print("  • Organizations promoted from receipts")
        print("  • Prevention of duplicate creation")
        print("  • Granular tracking at line item level")
    else:
        print("\n❌ Migration failed!")
        sys.exit(1)

if __name__ == "__main__":
    main() 