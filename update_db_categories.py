#!/usr/bin/env python3
"""
Migration script to add categories table and populate default categories.
"""

import sys
import logging
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

# Default categories by object type
DEFAULT_CATEGORIES = {
    'asset': [
        {
            'name': 'Electronics',
            'description': 'Electronic devices and equipment',
            'icon': 'fa-microchip',
            'color': 'bg-info'
        },
        {
            'name': 'Furniture',
            'description': 'Tables, chairs, desks, and other furniture',
            'icon': 'fa-chair',
            'color': 'bg-secondary'
        },
        {
            'name': 'Equipment',
            'description': 'Tools and mechanical equipment',
            'icon': 'fa-tools',
            'color': 'bg-warning'
        },
        {
            'name': 'Vehicles',
            'description': 'Cars, trucks, and other vehicles',
            'icon': 'fa-car',
            'color': 'bg-danger'
        },
        {
            'name': 'Appliances',
            'description': 'Home and kitchen appliances',
            'icon': 'fa-blender',
            'color': 'bg-primary'
        }
    ],
    'consumable': [
        {
            'name': 'Office supplies',
            'description': 'Paper, pens, staples, and other office consumables',
            'icon': 'fa-paperclip',
            'color': 'bg-secondary'
        },
        {
            'name': 'Cleaning supplies',
            'description': 'Cleaning products and materials',
            'icon': 'fa-broom',
            'color': 'bg-info'
        },
        {
            'name': 'Food',
            'description': 'Food items and ingredients',
            'icon': 'fa-utensils',
            'color': 'bg-success'
        },
        {
            'name': 'Medical supplies',
            'description': 'First aid and medical consumables',
            'icon': 'fa-first-aid',
            'color': 'bg-danger'
        },
        {
            'name': 'Parts',
            'description': 'Replacement parts that get used up',
            'icon': 'fa-cogs',
            'color': 'bg-warning'
        }
    ],
    'component': [
        {
            'name': 'Computer components',
            'description': 'RAM, hard drives, CPUs and other PC components',
            'icon': 'fa-memory',
            'color': 'bg-info'
        },
        {
            'name': 'Mechanical parts',
            'description': 'Gears, motors, and other mechanical components',
            'icon': 'fa-cog',
            'color': 'bg-warning'
        },
        {
            'name': 'Electrical components',
            'description': 'Wires, connectors, and electrical parts',
            'icon': 'fa-bolt',
            'color': 'bg-danger'
        },
        {
            'name': 'Structural components',
            'description': 'Frames, supports, and structural elements',
            'icon': 'fa-cubes',
            'color': 'bg-secondary'
        }
    ],
    'person': [
        {
            'name': 'Employee',
            'description': 'Current full-time or part-time employees',
            'icon': 'fa-user-tie',
            'color': 'bg-primary'
        },
        {
            'name': 'Contractor',
            'description': 'Independent contractors and temporary workers',
            'icon': 'fa-user-cog',
            'color': 'bg-info'
        },
        {
            'name': 'Family member',
            'description': 'Family members and dependents',
            'icon': 'fa-users',
            'color': 'bg-success'
        },
        {
            'name': 'Client',
            'description': 'Clients and customers',
            'icon': 'fa-user-check',
            'color': 'bg-warning'
        }
    ],
    'pet': [
        {
            'name': 'Dog',
            'description': 'Dogs and puppies',
            'icon': 'fa-dog',
            'color': 'bg-primary'
        },
        {
            'name': 'Cat',
            'description': 'Cats and kittens',
            'icon': 'fa-cat',
            'color': 'bg-info'
        },
        {
            'name': 'Bird',
            'description': 'Pet birds of all types',
            'icon': 'fa-dove',
            'color': 'bg-success'
        },
        {
            'name': 'Fish',
            'description': 'Aquarium fish and aquatic pets',
            'icon': 'fa-fish',
            'color': 'bg-warning'
        },
        {
            'name': 'Other',
            'description': 'Other types of pets',
            'icon': 'fa-paw',
            'color': 'bg-secondary'
        }
    ],
    'service': [
        {
            'name': 'Subscription',
            'description': 'Recurring subscription services',
            'icon': 'fa-sync',
            'color': 'bg-primary'
        },
        {
            'name': 'Maintenance',
            'description': 'Regular maintenance services',
            'icon': 'fa-tools',
            'color': 'bg-info'
        },
        {
            'name': 'Consulting',
            'description': 'Professional consulting services',
            'icon': 'fa-user-tie',
            'color': 'bg-success'
        },
        {
            'name': 'Utilities',
            'description': 'Utility services like power, water, etc.',
            'icon': 'fa-bolt',
            'color': 'bg-warning'
        }
    ],
    'software': [
        {
            'name': 'Applications',
            'description': 'Desktop and mobile applications',
            'icon': 'fa-window-restore',
            'color': 'bg-primary'
        },
        {
            'name': 'Operating systems',
            'description': 'Operating system software',
            'icon': 'fa-desktop',
            'color': 'bg-info'
        },
        {
            'name': 'Development tools',
            'description': 'Software development tools and environments',
            'icon': 'fa-code',
            'color': 'bg-success'
        },
        {
            'name': 'Business software',
            'description': 'Business and productivity software',
            'icon': 'fa-briefcase',
            'color': 'bg-warning'
        },
        {
            'name': 'SaaS',
            'description': 'Software as a Service subscriptions',
            'icon': 'fa-cloud',
            'color': 'bg-secondary'
        }
    ],
    'other': [
        {
            'name': 'Miscellaneous',
            'description': 'Items that don\'t fit other categories',
            'icon': 'fa-box',
            'color': 'bg-secondary'
        },
        {
            'name': 'Documentation',
            'description': 'Documents, manuals, and records',
            'icon': 'fa-file-alt',
            'color': 'bg-info'
        },
        {
            'name': 'Decorative',
            'description': 'Decorative items and artwork',
            'icon': 'fa-paint-brush',
            'color': 'bg-success'
        }
    ]
}

def update_schema():
    """Update schema with categories functionality"""
    try:
        # Get database URL from environment variable
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            logger.error("DATABASE_URL environment variable is not set")
            sys.exit(1)
        
        logger.info("Starting database schema update for Categories...")
        
        # Connect to the database
        conn = psycopg2.connect(database_url)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        
        # Create categories table if it doesn't exist
        with conn.cursor() as cur:
            # Create categories table if it doesn't exist
            try:
                logger.info("Creating categories table if it doesn't exist...")
                create_categories_table(conn)
            except Exception as e:
                # Table might already exist
                logger.info(f"Note: {str(e)}")
                
            # Check if we have default categories
            try:
                cur.execute("SELECT COUNT(*) FROM categories WHERE is_default = TRUE;")
                count_result = cur.fetchone()
                default_count = count_result[0] if count_result else 0
            except Exception:
                default_count = 0
            
            if default_count == 0:
                logger.info("No default categories found, adding them...")
                # Insert default categories whether table is new or existing
                insert_default_categories(conn)
            else:
                logger.info(f"Found {default_count} default categories already")
                
        logger.info("Committing changes...")
        conn.commit()
        logger.info("Schema update completed successfully!")
        
    except Exception as e:
        logger.error(f"Error updating schema: {e}")
        sys.exit(1)
        
def create_categories_table(conn):
    """Create the categories table if it doesn't exist"""
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            object_type VARCHAR(50) NOT NULL,
            description VARCHAR(255),
            icon VARCHAR(50),
            color VARCHAR(20),
            is_default BOOLEAN DEFAULT false,
            confidence_score FLOAT DEFAULT 0.8,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            UNIQUE(name, object_type)
        );
        
        CREATE INDEX IF NOT EXISTS idx_categories_object_type ON categories(object_type);
        """)
        logger.info("categories table created successfully")

def insert_default_categories(conn):
    """Insert default categories for each object type"""
    now = datetime.utcnow()
    
    with conn.cursor() as cur:
        # Add defaults for each object type
        for object_type, categories in DEFAULT_CATEGORIES.items():
            for category in categories:
                try:
                    cur.execute("""
                    INSERT INTO categories 
                    (name, object_type, description, icon, color, is_default, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        category['name'],
                        object_type,
                        category['description'],
                        category['icon'],
                        category['color'],
                        True,  # is_default = True
                        now,
                        now
                    ))
                except Exception as e:
                    logger.warning(f"Could not insert category {category['name']} for {object_type}: {e}")
    
    logger.info(f"Inserted default categories for all object types")

if __name__ == "__main__":
    update_schema()