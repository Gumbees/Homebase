"""
Migration script to add Organizations and Users entity tables.
This implements the Entity/Object conceptual framework by adding:
- Organizations: Business relationships and vendor management
- Users: System access, profiles, and digital identity
- OrganizationContacts: Links organizations to people objects
- UserPersonMapping: Links users to their corresponding people objects
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
    """Update schema with new Entity tables: Organizations and Users"""
    try:
        logger.info("Starting database schema update for Organizations and Users entities...")
        
        with engine.begin() as conn:
            # Create the new entity tables
            create_organizations_table(conn)
            create_users_table(conn)
            create_organization_contacts_table(conn)
            create_user_person_mapping_table(conn)
            
            # Create other entity tables for future use
            create_notes_table(conn)
            create_calendar_events_table(conn)
            create_collections_table(conn)
            
            # Migrate existing vendor data to organizations
            migrate_vendors_to_organizations(conn)
        
        logger.info("Schema update completed successfully!")
        return True
    except Exception as e:
        logger.error(f"Schema update failed: {str(e)}")
        return False

def create_organizations_table(conn):
    """Create the organizations table for business relationship management"""
    # Check if table exists
    check_sql = text("""
    SELECT tablename 
    FROM pg_catalog.pg_tables 
    WHERE schemaname = 'public' AND tablename = 'organizations'
    """)
    result = conn.execute(check_sql).fetchone()
    
    if not result:
        # Table doesn't exist, create it
        create_sql = text("""
        CREATE TABLE organizations (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            organization_type VARCHAR(50) DEFAULT 'vendor',
            data JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            is_active BOOLEAN DEFAULT TRUE,
            needs_approval BOOLEAN DEFAULT FALSE,
            approved_at TIMESTAMP
        );
        """)
        conn.execute(create_sql)
        
        # Create indexes
        conn.execute(text("CREATE INDEX idx_organizations_name ON organizations(name)"))
        conn.execute(text("CREATE INDEX idx_organizations_type ON organizations(organization_type)"))
        conn.execute(text("CREATE INDEX idx_organizations_active ON organizations(is_active)"))
        
        logger.info("Created organizations table")
    else:
        logger.info("organizations table already exists")

def create_users_table(conn):
    """Create the users table for system access and digital identity"""
    # Check if table exists
    check_sql = text("""
    SELECT tablename 
    FROM pg_catalog.pg_tables 
    WHERE schemaname = 'public' AND tablename = 'users'
    """)
    result = conn.execute(check_sql).fetchone()
    
    if not result:
        # Table doesn't exist, create it
        create_sql = text("""
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(100) UNIQUE NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255),
            data JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            last_login TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE,
            is_admin BOOLEAN DEFAULT FALSE,
            preferences JSONB DEFAULT '{}'
        );
        """)
        conn.execute(create_sql)
        
        # Create indexes
        conn.execute(text("CREATE INDEX idx_users_username ON users(username)"))
        conn.execute(text("CREATE INDEX idx_users_email ON users(email)"))
        conn.execute(text("CREATE INDEX idx_users_active ON users(is_active)"))
        
        logger.info("Created users table")
    else:
        logger.info("users table already exists")

def create_organization_contacts_table(conn):
    """Create the organization_contacts table to link organizations to people objects"""
    # Check if table exists
    check_sql = text("""
    SELECT tablename 
    FROM pg_catalog.pg_tables 
    WHERE schemaname = 'public' AND tablename = 'organization_contacts'
    """)
    result = conn.execute(check_sql).fetchone()
    
    if not result:
        # Table doesn't exist, create it
        create_sql = text("""
        CREATE TABLE organization_contacts (
            id SERIAL PRIMARY KEY,
            organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            person_object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
            contact_type VARCHAR(50) DEFAULT 'primary',
            relationship VARCHAR(100),
            created_at TIMESTAMP DEFAULT NOW(),
            is_active BOOLEAN DEFAULT TRUE
        );
        """)
        conn.execute(create_sql)
        
        # Create indexes
        conn.execute(text("CREATE INDEX idx_orgcontacts_org ON organization_contacts(organization_id)"))
        conn.execute(text("CREATE INDEX idx_orgcontacts_person ON organization_contacts(person_object_id)"))
        conn.execute(text("CREATE UNIQUE INDEX idx_orgcontacts_unique ON organization_contacts(organization_id, person_object_id, contact_type)"))
        
        logger.info("Created organization_contacts table")
    else:
        logger.info("organization_contacts table already exists")

def create_user_person_mapping_table(conn):
    """Create the user_person_mapping table to link users to their corresponding people objects"""
    # Check if table exists
    check_sql = text("""
    SELECT tablename 
    FROM pg_catalog.pg_tables 
    WHERE schemaname = 'public' AND tablename = 'user_person_mapping'
    """)
    result = conn.execute(check_sql).fetchone()
    
    if not result:
        # Table doesn't exist, create it
        create_sql = text("""
        CREATE TABLE user_person_mapping (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            person_object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT NOW(),
            is_primary BOOLEAN DEFAULT TRUE
        );
        """)
        conn.execute(create_sql)
        
        # Create indexes
        conn.execute(text("CREATE INDEX idx_userperson_user ON user_person_mapping(user_id)"))
        conn.execute(text("CREATE INDEX idx_userperson_person ON user_person_mapping(person_object_id)"))
        conn.execute(text("CREATE UNIQUE INDEX idx_userperson_unique ON user_person_mapping(user_id, person_object_id)"))
        
        logger.info("Created user_person_mapping table")
    else:
        logger.info("user_person_mapping table already exists")

def create_notes_table(conn):
    """Create the notes table for documentation and comments"""
    # Check if table exists
    check_sql = text("""
    SELECT tablename 
    FROM pg_catalog.pg_tables 
    WHERE schemaname = 'public' AND tablename = 'notes'
    """)
    result = conn.execute(check_sql).fetchone()
    
    if not result:
        # Table doesn't exist, create it
        create_sql = text("""
        CREATE TABLE notes (
            id SERIAL PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            content TEXT,
            note_type VARCHAR(50) DEFAULT 'general',
            object_id INTEGER REFERENCES objects(id) ON DELETE CASCADE,
            organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            data JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            is_private BOOLEAN DEFAULT FALSE
        );
        """)
        conn.execute(create_sql)
        
        # Create indexes
        conn.execute(text("CREATE INDEX idx_notes_type ON notes(note_type)"))
        conn.execute(text("CREATE INDEX idx_notes_object ON notes(object_id)"))
        conn.execute(text("CREATE INDEX idx_notes_org ON notes(organization_id)"))
        conn.execute(text("CREATE INDEX idx_notes_created ON notes(created_at)"))
        
        logger.info("Created notes table")
    else:
        logger.info("notes table already exists")

def create_calendar_events_table(conn):
    """Create the calendar_events table for scheduled events"""
    # Check if table exists
    check_sql = text("""
    SELECT tablename 
    FROM pg_catalog.pg_tables 
    WHERE schemaname = 'public' AND tablename = 'calendar_events'
    """)
    result = conn.execute(check_sql).fetchone()
    
    if not result:
        # Table doesn't exist, create it
        create_sql = text("""
        CREATE TABLE calendar_events (
            id SERIAL PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            event_type VARCHAR(50) DEFAULT 'maintenance',
            start_time TIMESTAMP NOT NULL,
            end_time TIMESTAMP,
            object_id INTEGER REFERENCES objects(id) ON DELETE CASCADE,
            organization_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            data JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            is_completed BOOLEAN DEFAULT FALSE
        );
        """)
        conn.execute(create_sql)
        
        # Create indexes
        conn.execute(text("CREATE INDEX idx_calendar_start ON calendar_events(start_time)"))
        conn.execute(text("CREATE INDEX idx_calendar_type ON calendar_events(event_type)"))
        conn.execute(text("CREATE INDEX idx_calendar_object ON calendar_events(object_id)"))
        conn.execute(text("CREATE INDEX idx_calendar_completed ON calendar_events(is_completed)"))
        
        logger.info("Created calendar_events table")
    else:
        logger.info("calendar_events table already exists")

def create_collections_table(conn):
    """Create the collections table for grouped object sets"""
    # Check if table exists
    check_sql = text("""
    SELECT tablename 
    FROM pg_catalog.pg_tables 
    WHERE schemaname = 'public' AND tablename = 'collections'
    """)
    result = conn.execute(check_sql).fetchone()
    
    if not result:
        # Table doesn't exist, create it
        create_sql = text("""
        CREATE TABLE collections (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            collection_type VARCHAR(50) DEFAULT 'custom',
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            data JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            is_public BOOLEAN DEFAULT FALSE
        );
        """)
        conn.execute(create_sql)
        
        # Create collection_objects junction table
        conn.execute(text("""
        CREATE TABLE collection_objects (
            id SERIAL PRIMARY KEY,
            collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
            added_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(collection_id, object_id)
        );
        """))
        
        # Create indexes
        conn.execute(text("CREATE INDEX idx_collections_user ON collections(user_id)"))
        conn.execute(text("CREATE INDEX idx_collections_type ON collections(collection_type)"))
        conn.execute(text("CREATE INDEX idx_collection_objects_coll ON collection_objects(collection_id)"))
        conn.execute(text("CREATE INDEX idx_collection_objects_obj ON collection_objects(object_id)"))
        
        logger.info("Created collections and collection_objects tables")
    else:
        logger.info("collections table already exists")

def migrate_vendors_to_organizations(conn):
    """Migrate existing vendor data to the new organizations table"""
    try:
        # Check if vendors table exists and has data
        check_vendors_sql = text("""
        SELECT COUNT(*) FROM information_schema.tables 
        WHERE table_name = 'vendors' AND table_schema = 'public'
        """)
        vendors_exists = conn.execute(check_vendors_sql).scalar()
        
        if vendors_exists:
            # Get vendor count
            vendor_count_sql = text("SELECT COUNT(*) FROM vendors")
            vendor_count = conn.execute(vendor_count_sql).scalar()
            
            if vendor_count > 0:
                # Migrate vendors to organizations
                migrate_sql = text("""
                INSERT INTO organizations (name, organization_type, data, created_at, updated_at, is_active, needs_approval, approved_at)
                SELECT 
                    name,
                    'vendor' as organization_type,
                    COALESCE(contact_info, '{}') as data,
                    created_at,
                    updated_at,
                    true as is_active,
                    needs_approval,
                    approved_at
                FROM vendors
                WHERE NOT EXISTS (
                    SELECT 1 FROM organizations WHERE organizations.name = vendors.name
                )
                """)
                conn.execute(migrate_sql)
                logger.info(f"Migrated {vendor_count} vendors to organizations table")
            else:
                logger.info("No vendors to migrate")
        else:
            logger.info("Vendors table does not exist, skipping migration")
            
    except Exception as e:
        logger.error(f"Error migrating vendors: {str(e)}")
        # Don't raise - this is not critical

if __name__ == "__main__":
    success = update_schema()
    sys.exit(0 if success else 1) 