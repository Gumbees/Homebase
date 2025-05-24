"""
Migration script to update the database with Object Attachments functionality.
This adds the object_attachments table to allow objects to have multiple photos and documents.
"""
import sys
import logging
from datetime import datetime
from sqlalchemy import create_engine, text, MetaData, Table, Column, Integer, String, DateTime, Boolean, ForeignKey, inspect
from sqlalchemy.dialects.postgresql import JSONB, BYTEA
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Connect to the database
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL environment variable is not set")
    sys.exit(1)
    
engine = create_engine(DATABASE_URL)

def update_schema():
    """Update schema with Object Attachments functionality"""
    logger.info("Starting database schema update for Object Attachments...")
    
    try:
        with engine.connect() as conn:
            # Create a transaction
            with conn.begin():
                # Create object_attachments table if it doesn't exist
                create_object_attachments_table(conn)
                logger.info("Committing changes...")
                
        logger.info("Schema update completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Schema update failed: {str(e)}")
        return False

def create_object_attachments_table(conn):
    """Create the object_attachments table if it doesn't exist"""
    # Check if table exists
    check_sql = text("""
    SELECT tablename 
    FROM pg_catalog.pg_tables 
    WHERE schemaname = 'public' AND tablename = 'object_attachments'
    """)
    result = conn.execute(check_sql).fetchone()
    
    if not result:
        # Table doesn't exist, create it
        create_sql = text("""
        CREATE TABLE object_attachments (
            id SERIAL PRIMARY KEY,
            object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
            filename VARCHAR(255) NOT NULL,
            file_data BYTEA NOT NULL,
            file_type VARCHAR(100),
            attachment_type VARCHAR(50) DEFAULT 'photo',
            description VARCHAR(255),
            upload_date TIMESTAMP DEFAULT NOW(),
            ai_analyzed BOOLEAN DEFAULT FALSE,
            ai_analysis_result JSONB
        );
        """)
        conn.execute(create_sql)
        
        # Create index on object_id for faster lookups
        conn.execute(text("CREATE INDEX idx_object_attachments_object_id ON object_attachments(object_id)"))
        
        # Create index on attachment_type for filtering by type
        conn.execute(text("CREATE INDEX idx_object_attachments_type ON object_attachments(attachment_type)"))
        
        logger.info("Created object_attachments table")
    else:
        logger.info("object_attachments table already exists")

if __name__ == "__main__":
    success = update_schema()
    sys.exit(0 if success else 1)