"""
Migration script to update the database with AI Queue related fields.
This adds re-evaluation tracking fields to Object model and creates the AI evaluation queue table.
"""
import json
import os
import sys
import logging
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get database URL from environment
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    logger.error("DATABASE_URL environment variable not set!")
    sys.exit(1)

# Database connection
engine = create_engine(DATABASE_URL)

def update_schema():
    """Update schema with new columns for AI Queue functionality"""
    try:
        logger.info("Starting database schema update for AI Queue...")
        
        # Add columns to objects table for AI re-evaluation tracking - this needs to be committed first
        with engine.begin() as conn:
            # Add columns to objects table for AI re-evaluation tracking
            add_columns_to_objects_table(conn)
            
            # Commit the transaction to ensure columns are created before checking them
            logger.info("Committing column additions...")
        
        # After columns are created, create the queue table
        with engine.begin() as conn:
            # Create AI evaluation queue table if it doesn't exist
            create_ai_queue_table(conn)
            
            # Initialize next evaluation dates for existing objects
            initialize_object_evaluation_dates(conn)
        
        logger.info("Schema update completed successfully!")
        return True
    except Exception as e:
        logger.error(f"Schema update failed: {str(e)}")
        return False

def add_columns_to_objects_table(conn):
    """Add new columns to the objects table for AI re-evaluation tracking"""
    columns_to_add = [
        "last_evaluated_at TIMESTAMP",
        "next_evaluation_date TIMESTAMP DEFAULT (NOW() + INTERVAL '90 days')",
        "evaluation_confidence FLOAT",
        "needs_manual_review BOOLEAN DEFAULT FALSE",
        "ai_evaluation_pending BOOLEAN DEFAULT FALSE",
        "evaluation_history JSONB DEFAULT '[]'"
    ]
    
    for column in columns_to_add:
        column_name = column.split()[0]
        try:
            # Check if column exists
            check_sql = text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'objects' AND column_name = '{column_name}'
            """)
            result = conn.execute(check_sql).fetchone()
            
            if not result:
                # Column doesn't exist, add it
                alter_sql = text(f"ALTER TABLE objects ADD COLUMN {column}")
                conn.execute(alter_sql)
                logger.info(f"Added column '{column_name}' to objects table")
            else:
                logger.info(f"Column '{column_name}' already exists")
        except Exception as e:
            logger.error(f"Error adding column '{column_name}': {str(e)}")
            raise

def create_ai_queue_table(conn):
    """Create the AI evaluation queue table if it doesn't exist"""
    # Check if table exists
    check_sql = text("""
    SELECT tablename 
    FROM pg_catalog.pg_tables 
    WHERE schemaname = 'public' AND tablename = 'ai_evaluation_queue'
    """)
    result = conn.execute(check_sql).fetchone()
    
    if not result:
        # Table doesn't exist, create it
        create_sql = text("""
        CREATE TABLE ai_evaluation_queue (
            id SERIAL PRIMARY KEY,
            object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
            scheduled_date TIMESTAMP NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            last_attempt TIMESTAMP,
            attempts INTEGER DEFAULT 0,
            result JSONB,
            created_at TIMESTAMP DEFAULT NOW(),
            completed_at TIMESTAMP,
            error_message TEXT
        );
        """)
        conn.execute(create_sql)
        
        # Create index on scheduled_date for faster querying
        conn.execute(text("CREATE INDEX idx_aievalqueue_scheddate ON ai_evaluation_queue(scheduled_date)"))
        
        # Create index on object_id and status for faster lookups
        conn.execute(text("CREATE INDEX idx_aievalqueue_obj_status ON ai_evaluation_queue(object_id, status)"))
        
        logger.info("Created ai_evaluation_queue table")
    else:
        logger.info("ai_evaluation_queue table already exists")

def initialize_object_evaluation_dates(conn):
    """Initialize next_evaluation_date for existing objects"""
    try:
        # Count objects without next_evaluation_date
        count_sql = text("""
        SELECT COUNT(*) FROM objects 
        WHERE next_evaluation_date IS NULL
        """)
        count_result = conn.execute(count_sql).scalar()
        
        if count_result > 0:
            # Initialize with a spread over the next 90 days to avoid all objects
            # coming up for re-evaluation on the same day
            update_sql = text("""
            UPDATE objects 
            SET next_evaluation_date = NOW() + (random() * INTERVAL '90 days')
            WHERE next_evaluation_date IS NULL
            """)
            conn.execute(update_sql)
            logger.info(f"Initialized next_evaluation_date for {count_result} objects")
        else:
            logger.info("All objects already have next_evaluation_date set")
    except Exception as e:
        logger.error(f"Error initializing next_evaluation_date: {str(e)}")
        raise

if __name__ == "__main__":
    success = update_schema()
    sys.exit(0 if success else 1)