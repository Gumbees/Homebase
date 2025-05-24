#!/usr/bin/env python3
"""
Migration script to add object_categories junction table and update the
database schema to support multiple categories per object.
"""

import os
import sys
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import database-related modules
import sqlalchemy
from sqlalchemy.dialects.postgresql import JSONB

try:
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
except ImportError:
    logger.error("Could not import psycopg2. Please install it with: pip install psycopg2-binary")
    sys.exit(1)
    
def update_schema():
    """Update schema with multiple categories support"""
    # Get database connection details
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        logger.error("DATABASE_URL environment variable is not set")
        sys.exit(1)
    
    # Parse the connection string to get individual components
    conn_parts = db_url.split('/')
    db_name = conn_parts[-1].split('?')[0]
    conn_info = '/'.join(conn_parts[:-1]) + '/postgres'  # Connect to the postgres database first
    
    try:
        # Create a connection to the default postgres database
        logger.info("Connecting to PostgreSQL database...")
        conn = psycopg2.connect(conn_info)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        
        # Now connect to the actual database
        logger.info(f"Connecting to database: {db_name}")
        target_conn = psycopg2.connect(db_url)
        target_conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        
        # Create the object_categories table
        create_object_categories_table(target_conn)
        
        # Migrate existing category data from objects
        migrate_existing_categories(target_conn)
        
        logger.info("Schema update completed successfully")
        
    except Exception as e:
        logger.error(f"Error updating schema: {str(e)}")
        sys.exit(1)
    finally:
        if 'conn' in locals() and conn:
            conn.close()
        if 'target_conn' in locals() and target_conn:
            target_conn.close()

def create_object_categories_table(conn):
    """Create the object_categories junction table if it doesn't exist"""
    try:
        cursor = conn.cursor()
        
        # Check if object_categories table already exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'object_categories'
            );
        """)
        
        table_exists = cursor.fetchone()[0]
        
        if not table_exists:
            logger.info("Creating object_categories table...")
            
            # Create the junction table
            cursor.execute("""
                CREATE TABLE object_categories (
                    object_id INTEGER NOT NULL,
                    category_id INTEGER NOT NULL,
                    added_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
                    PRIMARY KEY (object_id, category_id),
                    FOREIGN KEY (object_id) REFERENCES objects (id) ON DELETE CASCADE,
                    FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE CASCADE
                );
            """)
            
            # Create indexes for better performance
            cursor.execute("""
                CREATE INDEX idx_object_categories_object_id ON object_categories (object_id);
            """)
            
            cursor.execute("""
                CREATE INDEX idx_object_categories_category_id ON object_categories (category_id);
            """)
            
            logger.info("object_categories table created successfully")
        else:
            logger.info("object_categories table already exists")
        
        cursor.close()
    except Exception as e:
        logger.error(f"Error creating object_categories table: {str(e)}")
        raise

def migrate_existing_categories(conn):
    """Migrate existing category data from objects.data to the new junction table"""
    try:
        cursor = conn.cursor()
        
        # First, check if we already have data in the junction table
        cursor.execute("SELECT COUNT(*) FROM object_categories;")
        count = cursor.fetchone()[0]
        
        if count > 0:
            logger.info(f"object_categories table already has {count} records, skipping migration")
            cursor.close()
            return
        
        # Get objects with a category in their data
        logger.info("Fetching objects with category data...")
        cursor.execute("""
            SELECT id, object_type, data 
            FROM objects 
            WHERE data ? 'category' AND data->>'category' != '';
        """)
        
        objects = cursor.fetchall()
        logger.info(f"Found {len(objects)} objects with category data")
        
        # Process each object
        for obj_id, obj_type, obj_data in objects:
            category_name = obj_data['category']
            
            # Find the category in the categories table
            cursor.execute("""
                SELECT id FROM categories 
                WHERE name = %s AND object_type = %s;
            """, (category_name, obj_type))
            
            category_result = cursor.fetchone()
            
            if category_result:
                category_id = category_result[0]
                
                # Insert into the junction table
                cursor.execute("""
                    INSERT INTO object_categories (object_id, category_id, added_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING;
                """, (obj_id, category_id, datetime.utcnow()))
                
                logger.info(f"Migrated category '{category_name}' for object {obj_id}")
            else:
                # If the category doesn't exist yet, create it
                cursor.execute("""
                    INSERT INTO categories (name, object_type, description, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id;
                """, (category_name, obj_type, f"Auto-created from object {obj_id}", 
                      datetime.utcnow(), datetime.utcnow()))
                
                new_category_id = cursor.fetchone()[0]
                
                # Insert into the junction table
                cursor.execute("""
                    INSERT INTO object_categories (object_id, category_id, added_at)
                    VALUES (%s, %s, %s);
                """, (obj_id, new_category_id, datetime.utcnow()))
                
                logger.info(f"Created and migrated category '{category_name}' for object {obj_id}")
        
        logger.info("Category data migration completed")
        cursor.close()
    except Exception as e:
        logger.error(f"Error migrating category data: {str(e)}")
        raise

if __name__ == "__main__":
    update_schema()