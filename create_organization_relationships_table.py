#!/usr/bin/env python3
"""
Migration script to create the organization_relationships table.
This adds support for many-to-many relationships between organizations.

Run this script to update your database with the new table structure.
"""

import sys
import os

# Add the current directory to Python path so we can import from the app
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app, db
from models import OrganizationRelationship

def create_organization_relationships_table():
    """Create the organization_relationships table if it doesn't exist"""
    app = create_app()
    
    with app.app_context():
        try:
            print("Creating organization_relationships table...")
            
            # Create the table if it doesn't exist
            db.create_all()
            
            print("✓ organization_relationships table created successfully!")
            print("\nTable structure:")
            print("- from_organization_id: Organization that initiates the relationship")
            print("- to_organization_id: Organization that receives the relationship")
            print("- relationship_type: Type of relationship (parent, subsidiary, partner, etc.)")
            print("- relationship_label: Custom label for the relationship")
            print("- is_bidirectional: Whether the relationship works both ways")
            print("- strength: Relationship strength (1-10)")
            print("- relationship_metadata: Additional JSON data")
            print("- start_date/end_date: Relationship lifecycle")
            print("- is_active: Whether the relationship is currently active")
            
            # Verify the table was created
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            
            if 'organization_relationships' in tables:
                print("\n✓ Table verified in database")
                
                # Show available columns
                columns = inspector.get_columns('organization_relationships')
                print(f"\nColumns created ({len(columns)}):")
                for col in columns:
                    print(f"  - {col['name']}: {col['type']}")
                    
            else:
                print("\n✗ Table not found in database")
                return False
                
            return True
            
        except Exception as e:
            print(f"\n✗ Error creating table: {str(e)}")
            return False

def main():
    """Main migration function"""
    print("Organization Relationships Table Migration")
    print("=" * 50)
    print()
    
    success = create_organization_relationships_table()
    
    if success:
        print("\n" + "=" * 50)
        print("Migration completed successfully!")
        print("\nYou can now:")
        print("1. View organization relationships at /organization-relationships/<org_id>")
        print("2. Create relationships between organizations")
        print("3. View organization networks and connections")
        print("4. Manage complex business relationship hierarchies")
        print("\nNext steps:")
        print("- Restart your Flask application")
        print("- Visit any organization's edit page to see the 'Manage Relationships' button")
        print("- Start building your organization network!")
    else:
        print("\n" + "=" * 50)
        print("Migration failed. Please check the error messages above.")
        sys.exit(1)

if __name__ == '__main__':
    main() 