"""
Database initialization module for Homebase.

This module ensures that when the application launches with a blank database,
all necessary tables, indexes, optimizations, and default data are set up correctly.
"""

import os
import logging
from sqlalchemy import text
from app import app, db
from models import AISettings

logger = logging.getLogger(__name__)

def initialize_database():
    """
    Complete database initialization for first launch.
    
    This function:
    1. Creates all tables
    2. Applies database optimizations (indexes, TOAST settings)
    3. Initializes default AI settings
    4. Sets up any other required default data
    
    Returns:
        bool: True if successful, False otherwise
    """
    with app.app_context():
        try:
            logger.info("🔄 Starting database initialization...")
            
            # Step 1: Create all tables
            logger.info("📋 Creating database tables...")
            db.create_all()
            logger.info("✅ Database tables created successfully")
            
            # Step 2: Apply database optimizations
            logger.info("⚡ Applying database optimizations...")
            apply_database_optimizations()
            logger.info("✅ Database optimizations applied successfully")
            
            # Step 3: Initialize default AI settings
            logger.info("🤖 Initializing AI settings...")
            AISettings.initialize_defaults()
            logger.info("✅ AI settings initialized successfully")
            
            # Step 4: Commit all changes
            db.session.commit()
            logger.info("💾 All changes committed to database")
            
            logger.info("🎉 Database initialization completed successfully!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {str(e)}")
            db.session.rollback()
            return False

def apply_database_optimizations():
    """
    Apply database optimizations for attachment performance.
    
    This includes:
    - Indexes for efficient queries
    - TOAST configuration for binary data
    - Metadata views for queries without binary data
    """
    try:
        # Check if optimizations are already applied
        if check_optimizations_applied():
            logger.info("Database optimizations already applied, skipping...")
            return
            
        logger.info("Applying database indexes...")
        
        # Create indexes for attachment queries (without the binary data column)
        optimization_queries = [
            "CREATE INDEX IF NOT EXISTS idx_attachments_invoice_id ON attachments(invoice_id)",
            "CREATE INDEX IF NOT EXISTS idx_attachments_file_type ON attachments(file_type)",
            "CREATE INDEX IF NOT EXISTS idx_attachments_upload_date ON attachments(upload_date)",
            
            # Similar indexes for object attachments
            "CREATE INDEX IF NOT EXISTS idx_object_attachments_object_id ON object_attachments(object_id)",
            "CREATE INDEX IF NOT EXISTS idx_object_attachments_file_type ON object_attachments(file_type)",
            "CREATE INDEX IF NOT EXISTS idx_object_attachments_upload_date ON object_attachments(upload_date)",
            
            # Composite indexes for metadata queries (excludes binary data)
            "CREATE INDEX IF NOT EXISTS idx_attachments_metadata ON attachments(id, invoice_id, filename, file_type, upload_date)",
            "CREATE INDEX IF NOT EXISTS idx_object_attachments_metadata ON object_attachments(id, object_id, filename, file_type, upload_date)",
        ]
        
        for query in optimization_queries:
            db.session.execute(text(query))
        
        logger.info("Configuring TOAST storage for binary data...")
        
        # Configure TOAST storage for binary data columns
        toast_queries = [
            "ALTER TABLE attachments ALTER COLUMN file_data SET STORAGE EXTERNAL",
            "ALTER TABLE object_attachments ALTER COLUMN file_data SET STORAGE EXTERNAL",
        ]
        
        for query in toast_queries:
            db.session.execute(text(query))
        
        logger.info("Creating metadata views...")
        
        # Create views for metadata-only queries
        view_queries = [
            """
            CREATE OR REPLACE VIEW attachment_metadata AS
            SELECT id, invoice_id, filename, file_type, upload_date,
                   octet_length(file_data) as file_size_bytes
            FROM attachments
            """,
            
            """
            CREATE OR REPLACE VIEW object_attachment_metadata AS
            SELECT id, object_id, filename, file_type, attachment_type, 
                   description, upload_date, ai_analyzed,
                   octet_length(file_data) as file_size_bytes
            FROM object_attachments
            """
        ]
        
        for query in view_queries:
            db.session.execute(text(query))
        
        # Update table statistics for optimal query planning
        db.session.execute(text("ANALYZE attachments"))
        db.session.execute(text("ANALYZE object_attachments"))
        
        logger.info("Database optimizations applied successfully")
        
    except Exception as e:
        logger.error(f"Error applying database optimizations: {str(e)}")
        raise

def check_optimizations_applied():
    """
    Check if database optimizations have already been applied.
    
    Returns:
        bool: True if optimizations are already applied
    """
    try:
        # Check for one of our key indexes
        result = db.session.execute(text("""
            SELECT 1 FROM pg_indexes 
            WHERE indexname = 'idx_attachments_metadata' 
            LIMIT 1
        """)).fetchone()
        
        return result is not None
        
    except Exception:
        return False

def verify_database_setup():
    """
    Verify that the database is properly set up with all required components.
    
    Returns:
        dict: Status report of database setup
    """
    with app.app_context():
        try:
            report = {
                'status': 'success',
                'tables_created': False,
                'optimizations_applied': False,
                'ai_settings_initialized': False,
                'missing_tables': [],
                'errors': []
            }
            
            # Check that all expected tables exist
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            existing_tables = set(inspector.get_table_names())
            
            expected_tables = {
                'vendors', 'invoices', 'invoice_line_items', 'attachments',
                'objects', 'object_categories', 'object_attachments', 'categories',
                'person_pet_associations', 'ai_evaluation_queue', 'ai_settings',
                'task_queue', 'reminders', 'organizations', 'organization_relationships',
                'organization_contacts', 'users', 'user_person_mapping', 'user_aliases',
                'notes', 'calendar_events', 'collection_objects', 'collections',
                'receipt_creation_tracking'
            }
            
            missing_tables = expected_tables - existing_tables
            report['missing_tables'] = list(missing_tables)
            report['tables_created'] = len(missing_tables) == 0
            
            # Check if optimizations are applied
            report['optimizations_applied'] = check_optimizations_applied()
            
            # Check if AI settings are initialized
            ai_settings_count = AISettings.query.count()
            report['ai_settings_initialized'] = ai_settings_count > 0
            
            # Overall status
            if missing_tables or not report['optimizations_applied'] or not report['ai_settings_initialized']:
                report['status'] = 'incomplete'
            
            return report
            
        except Exception as e:
            logger.error(f"Error verifying database setup: {str(e)}")
            return {
                'status': 'error',
                'error': str(e),
                'tables_created': False,
                'optimizations_applied': False,
                'ai_settings_initialized': False
            }

def initialize_if_needed():
    """
    Check if database needs initialization and initialize if needed.
    This is the main function to call on application startup.
    
    Returns:
        bool: True if database is ready (was already initialized or successfully initialized)
    """
    try:
        # Quick check - if AI settings exist, assume database is initialized
        with app.app_context():
            ai_settings_count = AISettings.query.count()
            
            if ai_settings_count > 0:
                logger.info("Database appears to be already initialized")
                return True
            
            # Database needs initialization
            logger.info("Database needs initialization, starting setup...")
            return initialize_database()
            
    except Exception as e:
        logger.error(f"Error checking database initialization status: {str(e)}")
        # Try to initialize anyway
        logger.info("Attempting to initialize database...")
        return initialize_database()

if __name__ == "__main__":
    # Allow running this script directly for manual database initialization
    if initialize_database():
        print("✅ Database initialization completed successfully!")
    else:
        print("❌ Database initialization failed!")
        exit(1) 