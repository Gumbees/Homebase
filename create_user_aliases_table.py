#!/usr/bin/env python3
"""
Database migration script to create the user_aliases table.
This enables dynamic linking of person objects to users via name aliases.

Run this script to add the new table to your database:
python create_user_aliases_table.py
"""

import os
import sys
from datetime import datetime

# Add the parent directory to Python path so we can import from the app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app import create_app, db
    from models import UserAlias
    print("✓ Successfully imported app and models")
except ImportError as e:
    print(f"✗ Error importing app: {e}")
    print("Make sure you're running this script from the Homebase directory")
    sys.exit(1)

def create_user_aliases_table():
    """Create the user_aliases table if it doesn't exist"""
    
    app = create_app()
    
    with app.app_context():
        try:
            # Check if table already exists
            inspector = db.inspect(db.engine)
            existing_tables = inspector.get_table_names()
            
            if 'user_aliases' in existing_tables:
                print("ℹ️  Table 'user_aliases' already exists, skipping creation")
                return True
            
            print("🔄 Creating user_aliases table...")
            
            # Create the table
            db.create_all()
            
            # Verify table was created
            inspector = db.inspect(db.engine)
            updated_tables = inspector.get_table_names()
            
            if 'user_aliases' in updated_tables:
                print("✅ Successfully created user_aliases table!")
                
                # Show table structure
                columns = inspector.get_columns('user_aliases')
                print("\nTable structure:")
                for column in columns:
                    print(f"  - {column['name']} ({column['type']})")
                
                return True
            else:
                print("❌ Failed to create user_aliases table")
                return False
                
        except Exception as e:
            print(f"❌ Error creating table: {e}")
            return False

def verify_user_alias_functionality():
    """Test basic UserAlias functionality"""
    
    app = create_app()
    
    with app.app_context():
        try:
            print("\n🧪 Testing UserAlias functionality...")
            
            # Test query (should not crash)
            alias_count = UserAlias.query.count()
            print(f"✓ Current alias count: {alias_count}")
            
            # Test the fuzzy matching function
            matches = UserAlias.find_matching_users("Test Name", confidence_threshold=0.7)
            print(f"✓ Fuzzy matching function works (found {len(matches)} matches)")
            
            print("✅ UserAlias functionality verified!")
            return True
            
        except Exception as e:
            print(f"❌ Error testing functionality: {e}")
            return False

if __name__ == "__main__":
    print("🚀 User Aliases Table Migration")
    print("=" * 40)
    
    # Create table
    if create_user_aliases_table():
        # Test functionality
        if verify_user_alias_functionality():
            print("\n🎉 Migration completed successfully!")
            print("\nNext steps:")
            print("1. Visit /users to see the new Users page")
            print("2. Use 'Promote to User' on person objects")
            print("3. Add aliases to users for dynamic linking")
        else:
            print("\n⚠️  Table created but functionality test failed")
    else:
        print("\n💥 Migration failed!")
        sys.exit(1) 