from app import db, app
from sqlalchemy import text
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def update_schema():
    with app.app_context():
        try:
            # Check if objects table already exists
            result = db.session.execute(text("SELECT to_regclass('public.objects')")).scalar()
            
            if result is None:
                logger.info("Creating objects table and migrating from assets...")
                
                # Step 1: Create the objects table 
                db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS objects (
                    id SERIAL PRIMARY KEY,
                    invoice_id INTEGER REFERENCES invoices(id),
                    object_type VARCHAR(50) NOT NULL,
                    data JSONB NOT NULL,
                    parent_id INTEGER REFERENCES objects(id),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """))
                
                # Step 2: Create index on object_type
                db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_objects_object_type ON objects(object_type)"))
                
                # Step 4: Create the person_pet_associations table
                db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS person_pet_associations (
                    id SERIAL PRIMARY KEY,
                    person_id INTEGER REFERENCES objects(id) NOT NULL,
                    object_id INTEGER REFERENCES objects(id) NOT NULL,
                    relationship_type VARCHAR(50) DEFAULT 'owner',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """))
                
                db.session.commit()
                logger.info("Tables created successfully!")
            
            # Check if objects table is empty but assets table has data
            objects_count = db.session.execute(text("SELECT COUNT(*) FROM objects")).scalar()
            assets_count = db.session.execute(text("SELECT COUNT(*) FROM assets")).scalar()
            
            if objects_count == 0 and assets_count > 0:
                logger.info(f"Found {assets_count} assets to migrate to objects table...")
                
                # Migrate data from assets to objects
                db.session.execute(text("""
                INSERT INTO objects (invoice_id, object_type, data, created_at, updated_at)
                SELECT invoice_id, 'asset', data, created_at, updated_at FROM assets
                """))
                
                db.session.commit()
                logger.info(f"Successfully migrated {assets_count} assets to objects table!")
            else:
                logger.info(f"No migration needed. Objects: {objects_count}, Assets: {assets_count}")
            
            # Check if task_queue table already exists to avoid duplication issues
            task_queue_exists = db.session.execute(text("SELECT to_regclass('public.task_queue')")).scalar() is not None
            
            if not task_queue_exists:
                # Check if sequence already exists (this is the problematic part)
                seq_exists = db.session.execute(text("SELECT to_regclass('public.task_queue_id_seq')")).scalar() is not None
                
                if seq_exists:
                    logger.info("task_queue_id_seq already exists, dropping it first")
                    db.session.execute(text("DROP SEQUENCE IF EXISTS task_queue_id_seq"))
                    db.session.commit()
                
                logger.info("Creating task_queue table...")
                # Now create the task_queue table
                db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS task_queue (
                    id SERIAL PRIMARY KEY,
                    task_type VARCHAR(50) NOT NULL,
                    object_id INTEGER REFERENCES objects(id),
                    execute_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                    status VARCHAR(20),
                    priority INTEGER,
                    data JSONB NOT NULL,
                    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
                    last_attempt TIMESTAMP WITHOUT TIME ZONE,
                    attempts INTEGER DEFAULT 0,
                    completed_at TIMESTAMP WITHOUT TIME ZONE,
                    result JSONB,
                    error_message TEXT
                )
                """))
                
                # Create indexes for better performance
                db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_task_queue_task_type ON task_queue(task_type)"))
                db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_task_queue_execute_at ON task_queue(execute_at)"))
                db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status)"))
                
                db.session.commit()
                logger.info("task_queue table created successfully!")
            else:
                logger.info("task_queue table already exists, skipping creation")
                
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error during migration: {str(e)}")
            raise

if __name__ == '__main__':
    update_schema()