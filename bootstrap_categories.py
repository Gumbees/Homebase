#!/usr/bin/env python3
"""
Bootstrap script to populate default categories for new Homebase installations.
This ensures that new operators have sensible defaults to work with.
"""

import os
import sys
from datetime import datetime

# Add the app directory to the path so we can import our models
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import Category

def get_default_categories():
    """Get the default categories that should be created for new installations"""
    return {
        'asset': [
            {'name': 'Electronics', 'description': 'Electronic devices and equipment', 'icon': 'fa-microchip', 'color': 'bg-info'},
            {'name': 'Furniture', 'description': 'Tables, chairs, desks, and other furniture', 'icon': 'fa-chair', 'color': 'bg-secondary'},
            {'name': 'Equipment', 'description': 'Tools and mechanical equipment', 'icon': 'fa-tools', 'color': 'bg-warning'},
            {'name': 'Vehicles', 'description': 'Cars, trucks, and other vehicles', 'icon': 'fa-car', 'color': 'bg-danger'},
            {'name': 'Appliances', 'description': 'Home and kitchen appliances', 'icon': 'fa-blender', 'color': 'bg-primary'},
            {'name': 'Tools', 'description': 'Hand tools and power tools', 'icon': 'fa-hammer', 'color': 'bg-warning'},
            {'name': 'Infrastructure', 'description': 'Building infrastructure and systems', 'icon': 'fa-building', 'color': 'bg-dark'},
            {'name': 'Art', 'description': 'Artwork and decorative items', 'icon': 'fa-palette', 'color': 'bg-purple'},
            {'name': 'Office Equipment', 'description': 'Office machines and equipment', 'icon': 'fa-print', 'color': 'bg-light'}
        ],
        'consumable': [
            {'name': 'Office Supplies', 'description': 'Paper, pens, and office materials', 'icon': 'fa-paperclip', 'color': 'bg-light'},
            {'name': 'Cleaning Supplies', 'description': 'Cleaning products and materials', 'icon': 'fa-spray-can', 'color': 'bg-info'},
            {'name': 'Food', 'description': 'Food items and groceries', 'icon': 'fa-utensils', 'color': 'bg-success'},
            {'name': 'Drinks', 'description': 'Beverages and liquids', 'icon': 'fa-coffee', 'color': 'bg-warning'},
            {'name': 'Medical Supplies', 'description': 'First aid and medical items', 'icon': 'fa-first-aid', 'color': 'bg-danger'},
            {'name': 'Packaging', 'description': 'Boxes, bags, and packaging materials', 'icon': 'fa-box', 'color': 'bg-secondary'},
            {'name': 'Paper Products', 'description': 'Paper towels, toilet paper, etc.', 'icon': 'fa-toilet-paper', 'color': 'bg-light'},
            {'name': 'Kitchen Supplies', 'description': 'Kitchen consumables and supplies', 'icon': 'fa-kitchen-set', 'color': 'bg-primary'},
            {'name': 'Parts', 'description': 'Replacement parts and components', 'icon': 'fa-cog', 'color': 'bg-secondary'},
            {'name': 'Event Tickets', 'description': 'Tickets and passes for events', 'icon': 'fa-ticket', 'color': 'bg-purple'}
        ],
        'component': [
            {'name': 'Computer Components', 'description': 'RAM, CPUs, graphics cards, etc.', 'icon': 'fa-memory', 'color': 'bg-info'},
            {'name': 'Mechanical Parts', 'description': 'Gears, belts, and mechanical components', 'icon': 'fa-cogs', 'color': 'bg-warning'},
            {'name': 'Electrical Components', 'description': 'Wires, switches, and electrical parts', 'icon': 'fa-bolt', 'color': 'bg-danger'},
            {'name': 'Structural Components', 'description': 'Beams, brackets, and structural parts', 'icon': 'fa-cube', 'color': 'bg-dark'},
            {'name': 'Electronic Modules', 'description': 'Circuit boards and electronic modules', 'icon': 'fa-microchip', 'color': 'bg-success'},
            {'name': 'Hardware', 'description': 'Screws, bolts, and hardware components', 'icon': 'fa-screwdriver', 'color': 'bg-secondary'}
        ],
        'service': [
            {'name': 'Subscription', 'description': 'Software and service subscriptions', 'icon': 'fa-calendar-check', 'color': 'bg-primary'},
            {'name': 'Maintenance', 'description': 'Maintenance and repair services', 'icon': 'fa-wrench', 'color': 'bg-warning'},
            {'name': 'Consulting', 'description': 'Professional consulting services', 'icon': 'fa-user-tie', 'color': 'bg-info'},
            {'name': 'Utilities', 'description': 'Electricity, water, gas services', 'icon': 'fa-plug', 'color': 'bg-danger'},
            {'name': 'Internet', 'description': 'Internet and connectivity services', 'icon': 'fa-wifi', 'color': 'bg-success'},
            {'name': 'Cloud Services', 'description': 'Cloud computing and storage services', 'icon': 'fa-cloud', 'color': 'bg-light'},
            {'name': 'Professional Services', 'description': 'Legal, accounting, and other professional services', 'icon': 'fa-briefcase', 'color': 'bg-dark'},
            {'name': 'Communication', 'description': 'Phone, email, and communication services', 'icon': 'fa-phone', 'color': 'bg-primary'}
        ],
        'software': [
            {'name': 'Operating Systems', 'description': 'Windows, macOS, Linux', 'icon': 'fa-desktop', 'color': 'bg-dark'},
            {'name': 'Applications', 'description': 'Desktop and mobile applications', 'icon': 'fa-mobile-alt', 'color': 'bg-primary'},
            {'name': 'Development Tools', 'description': 'IDEs, compilers, and dev tools', 'icon': 'fa-code', 'color': 'bg-success'},
            {'name': 'Security', 'description': 'Antivirus and security software', 'icon': 'fa-shield-alt', 'color': 'bg-danger'},
            {'name': 'Productivity', 'description': 'Office suites and productivity tools', 'icon': 'fa-chart-line', 'color': 'bg-info'},
            {'name': 'Creative', 'description': 'Design and creative software', 'icon': 'fa-paint-brush', 'color': 'bg-purple'},
            {'name': 'Enterprise', 'description': 'Business and enterprise software', 'icon': 'fa-building', 'color': 'bg-warning'},
            {'name': 'Games', 'description': 'Gaming software and platforms', 'icon': 'fa-gamepad', 'color': 'bg-success'},
            {'name': 'Utilities', 'description': 'System utilities and tools', 'icon': 'fa-tools', 'color': 'bg-secondary'}
        ],
        'person': [
            {'name': 'Customer', 'description': 'Customers and clients', 'icon': 'fa-user', 'color': 'bg-primary'},
            {'name': 'Staff', 'description': 'Employees and staff members', 'icon': 'fa-users', 'color': 'bg-info'},
            {'name': 'Vendor Contact', 'description': 'Vendor representatives and contacts', 'icon': 'fa-handshake', 'color': 'bg-success'},
            {'name': 'Service Provider', 'description': 'Service technicians and providers', 'icon': 'fa-user-cog', 'color': 'bg-warning'},
            {'name': 'Attendee', 'description': 'Event attendees and participants', 'icon': 'fa-user-friends', 'color': 'bg-purple'},
            {'name': 'Business Contact', 'description': 'Business contacts and partners', 'icon': 'fa-address-card', 'color': 'bg-secondary'},
            {'name': 'Professional', 'description': 'Professional service providers', 'icon': 'fa-user-tie', 'color': 'bg-dark'}
        ],
        'pet': [
            {'name': 'Dog', 'description': 'Dogs and canine pets', 'icon': 'fa-dog', 'color': 'bg-warning'},
            {'name': 'Cat', 'description': 'Cats and feline pets', 'icon': 'fa-cat', 'color': 'bg-secondary'},
            {'name': 'Bird', 'description': 'Birds and avian pets', 'icon': 'fa-dove', 'color': 'bg-info'},
            {'name': 'Fish', 'description': 'Fish and aquatic pets', 'icon': 'fa-fish', 'color': 'bg-primary'},
            {'name': 'Reptile', 'description': 'Reptiles and amphibians', 'icon': 'fa-spider', 'color': 'bg-success'},
            {'name': 'Small Animal', 'description': 'Rabbits, hamsters, and small pets', 'icon': 'fa-paw', 'color': 'bg-light'}
        ]
    }

def bootstrap_categories():
    """Bootstrap default categories into the database"""
    with app.app_context():
        print("Bootstrapping default categories...")
        
        categories_data = get_default_categories()
        categories_created = 0
        categories_skipped = 0
        
        for object_type, categories in categories_data.items():
            print(f"\nProcessing {object_type} categories:")
            
            for cat_data in categories:
                # Check if category already exists
                existing = Category.query.filter_by(
                    name=cat_data['name'],
                    object_type=object_type
                ).first()
                
                if existing:
                    print(f"  ✓ {cat_data['name']} (already exists)")
                    categories_skipped += 1
                    continue
                
                # Create new category
                category = Category(
                    name=cat_data['name'],
                    object_type=object_type,
                    description=cat_data['description'],
                    icon=cat_data.get('icon'),
                    color=cat_data.get('color'),
                    is_default=True,
                    confidence_score=1.0,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                
                db.session.add(category)
                print(f"  + {cat_data['name']}")
                categories_created += 1
        
        try:
            db.session.commit()
            print(f"\n✅ Bootstrap complete!")
            print(f"   Created: {categories_created} categories")
            print(f"   Skipped: {categories_skipped} categories (already existed)")
            print(f"   Total: {categories_created + categories_skipped} categories processed")
            
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Error committing categories: {e}")
            return False
            
        return True

if __name__ == "__main__":
    print("Homebase Category Bootstrap Script")
    print("==================================")
    
    success = bootstrap_categories()
    
    if success:
        print("\n🎉 Categories bootstrap completed successfully!")
        print("Your Homebase installation now has default categories that will help AI")
        print("make better suggestions for object classification.")
    else:
        print("\n💥 Categories bootstrap failed. Check the error messages above.")
        sys.exit(1) 