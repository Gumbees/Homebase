# Homebase Application Architecture Documentation

## Table of Contents

1. [Overview](#overview)
2. [Core Architecture](#core-architecture)
3. [Database Schema](#database-schema)
4. [Vendor & Organization System](#vendor--organization-system)
5. [Object Management](#object-management)
6. [AI Integration](#ai-integration)
7. [User Interface](#user-interface)
8. [API Endpoints](#api-endpoints)
9. [Business Logic](#business-logic)
10. [Deployment](#deployment)

---

## Overview

Homebase is a comprehensive home inventory and asset management system built with Flask, PostgreSQL, and modern web technologies. It provides intelligent object categorization, vendor management, financial tracking, and organizational relationship management through a hybrid approach that balances simplicity with enterprise-level capabilities.

### Key Features

- **Smart Object Management**: AI-powered categorization and evaluation of assets, consumables, and other items
- **Hybrid Vendor System**: Progressive vendor management from simple metadata to full organizations
- **Organization Relationships**: Complex business relationship modeling with bidirectional connections
- **Receipt Processing**: Automated invoice and receipt processing with vendor extraction
- **Financial Tracking**: Inventory valuation, expense tracking, and approval workflows
- **AI Queue Management**: Intelligent re-evaluation scheduling and processing
- **Modern UI**: Bootstrap 5-based responsive interface

---

## Core Architecture

### Technology Stack

- **Backend**: Flask (Python 3.8+)
- **Database**: PostgreSQL with JSONB support
- **Frontend**: Bootstrap 5, JavaScript ES6+
- **ORM**: SQLAlchemy with Flask-SQLAlchemy
- **Containerization**: Docker with docker-compose
- **AI Integration**: Configurable providers (OpenAI, Anthropic, local models)

### Application Structure

```
homebase/
├── app.py                      # Flask application factory
├── routes.py                   # Main application routes
├── models.py                   # SQLAlchemy models
├── templates/                  # Jinja2 templates
│   ├── base.html              # Base template
│   ├── vendors_hybrid.html    # Vendor management dashboard
│   ├── edit_organization.html # Organization editing
│   └── organization_relationships.html # Relationship management
├── static/                     # Static assets
├── docker-compose.yml         # Container orchestration
├── Dockerfile                 # Container definition
└── requirements.txt           # Python dependencies
```

---

## Database Schema

### Core Tables

#### Objects (`objects`)
The central entity representing any trackable item.

```sql
CREATE TABLE objects (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER REFERENCES invoices(id),
    object_type VARCHAR(50) NOT NULL, -- 'asset', 'consumable', 'component', 'person', 'pet', 'service', 'software'
    data JSONB NOT NULL,              -- Flexible JSON storage for all object properties
    parent_id INTEGER REFERENCES objects(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- AI Evaluation Fields
    last_evaluated_at TIMESTAMP,
    next_evaluation_date TIMESTAMP DEFAULT (NOW() + INTERVAL '90 days'),
    evaluation_confidence FLOAT,
    needs_manual_review BOOLEAN DEFAULT FALSE,
    ai_evaluation_pending BOOLEAN DEFAULT FALSE,
    evaluation_history JSONB DEFAULT '[]'
);
```

#### Organizations (`organizations`)
Modern replacement for the simpler vendor system.

```sql
CREATE TABLE organizations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    organization_type VARCHAR(50) DEFAULT 'vendor', -- 'vendor', 'client', 'service_provider'
    data JSONB NOT NULL DEFAULT '{}',               -- All organization data including linked vendor names
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    needs_approval BOOLEAN DEFAULT FALSE,
    approved_at TIMESTAMP
);
```

#### Organization Relationships (`organization_relationships`)
**NEW**: Complex many-to-many relationships between organizations.

```sql
CREATE TABLE organization_relationships (
    id SERIAL PRIMARY KEY,
    from_organization_id INTEGER NOT NULL REFERENCES organizations(id),
    to_organization_id INTEGER NOT NULL REFERENCES organizations(id),
    relationship_type VARCHAR(50) NOT NULL,        -- 'parent', 'subsidiary', 'partner', 'franchise', etc.
    relationship_label VARCHAR(100),               -- Custom description
    is_bidirectional BOOLEAN DEFAULT FALSE,        -- Auto-creates reverse relationship
    strength INTEGER DEFAULT 5,                    -- 1-10 relationship strength
    relationship_metadata JSONB DEFAULT '{}',      -- Additional relationship data
    start_date TIMESTAMP,                          -- When relationship started
    end_date TIMESTAMP,                            -- When relationship ended
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(from_organization_id, to_organization_id, relationship_type),
    CHECK(from_organization_id != to_organization_id)
);
```

#### Invoices (`invoices`)
Financial transactions and receipts.

```sql
CREATE TABLE invoices (
    id SERIAL PRIMARY KEY,
    invoice_number VARCHAR(50) UNIQUE NOT NULL,
    vendor_id INTEGER REFERENCES vendors(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    is_paid BOOLEAN DEFAULT TRUE,
    data JSONB NOT NULL  -- Flexible invoice data including vendor metadata
);
```

### Relationship Tables

#### Categories (`categories`)
Dynamic categorization system for objects.

#### AI Evaluation Queue (`ai_evaluation_queue`)
Manages scheduled re-evaluation of objects.

#### Task Queue (`task_queue`)
Handles asynchronous processing tasks.

#### User Management
- `users`: System users and digital identity
- `user_person_mapping`: Links users to person objects
- `organization_contacts`: Links organizations to person objects

---

## Vendor & Organization System

### Hybrid Architecture

The Homebase vendor system uses a **hybrid approach** that starts simple and grows with complexity:

#### 1. Metadata Vendors (Simple)
- Automatically extracted from receipts
- Stored as JSON metadata in invoice data
- No formal management required
- Examples: `{"vendor_name": "Amazon", "vendor_address": "Seattle, WA"}`

#### 2. Vendor Name Linking (Intermediate)
- Organizations can "claim" vendor names from metadata
- Multiple vendor names can link to one organization
- Handles business name variations (Amazon, Amazon.com, AWS)
- Smart similarity detection suggests related names

```python
# Organization metadata stores linked vendor names
organization.data = {
    "linked_vendor_names": ["Amazon", "Amazon.com", "AWS", "Amazon Web Services"],
    "contact_info": {...},
    "address": {...}
}
```

#### 3. Full Organizations (Complex)
- Complete business entity management
- Formal approval workflows
- Contact management
- Relationship modeling
- Financial tracking integration

### Progression Path

```
Receipt → Metadata Vendor → Vendor Name Linking → Full Organization → Organization Relationships
   ↓            ↓                    ↓                    ↓                      ↓
Simple     Automatic         As Needed            When Complex         Enterprise Level
```

### Organization Relationships

**NEW FEATURE**: Many-to-many relationships between organizations support complex business networks:

#### Relationship Types
- **parent/subsidiary**: Corporate ownership
- **partner**: Strategic partnerships  
- **franchise/franchisor**: Franchise relationships
- **supplier/customer**: Supply chain
- **division**: Business units
- **joint_venture**: Shared entities
- **acquisition**: Corporate acquisitions
- **competitor**: Market competition
- **alliance**: Strategic alliances

#### Features
- **Bidirectional**: Automatically creates reverse relationships
- **Labeled**: Custom descriptions for specific relationships
- **Strength-based**: 1-10 scale for relationship importance
- **Temporal**: Start/end dates for relationship lifecycle
- **Metadata**: Additional JSON data for complex scenarios

#### Network Visualization
- Multi-level relationship traversal
- Circular reference protection
- Configurable depth limits
- REST API for external integration

---

## Object Management

### Object Types

1. **Assets**: Durable items with long-term value
2. **Consumables**: Items that get used up (with expiration tracking)
3. **Components**: Parts of larger assets
4. **People**: Human contacts and relationships
5. **Pets**: Animal companions with care tracking
6. **Services**: Subscriptions and ongoing services
7. **Software**: Digital tools and licenses

### AI-Powered Features

#### Automatic Categorization
- Objects automatically categorized based on receipt data
- Machine learning suggests appropriate categories
- Categories can be AI-generated or manually created
- Confidence scoring for category assignments

#### Scheduled Re-evaluation
- Objects re-evaluated every 90 days by default
- AI Queue manages processing (30 evaluations/day limit)
- Confidence-based manual review flagging
- Historical evaluation tracking

#### Smart Object Enhancement
- AI analyzes object photos and descriptions
- Suggests missing properties and categorizations
- Identifies relationships between objects
- Estimates values and condition assessments

### Parent-Child Relationships

Objects support hierarchical relationships:
- **Assets** can contain **Components**
- **People** can own **Pets** (many-to-many)
- **Software** can be installed on **Assets**

---

## AI Integration

### Configurable Providers

```python
# AI Settings support multiple providers
ai_providers = {
    'openai': {
        'api_key': 'YOUR_OPENAI_API_KEY_HERE',
        'models': ['gpt-4', 'gpt-3.5-turbo'],
        'endpoint': 'https://api.openai.com/v1'
    },
    'anthropic': {
        'api_key': 'YOUR_ANTHROPIC_API_KEY_HERE',
        'models': ['claude-3-sonnet', 'claude-3-haiku'],
        'endpoint': 'https://api.anthropic.com'
    },
    'llm_studio': {
        'endpoint': 'http://localhost:8080',
        'models': ['local-llama-3'],
        'api_key': None
    }
}
```

### AI Queue Management

#### Daily Processing
- Maximum 30 evaluations per day
- Automatic scheduling for overdue objects
- Smart load balancing across days
- Retry logic for failed evaluations

#### Evaluation Pipeline
1. **Object Selection**: Find objects due for re-evaluation
2. **Context Gathering**: Collect object data, photos, purchase history
3. **AI Analysis**: Send to configured AI provider
4. **Result Processing**: Parse response, update object data
5. **Confidence Assessment**: Flag low-confidence results for manual review
6. **History Tracking**: Store evaluation results and confidence scores

### AI-Driven Features

#### Smart Vendor Matching
- Similarity detection for vendor name variations
- Automatic suggestion of related vendor names
- Business name normalization and standardization

#### Category Suggestion
- Dynamic category creation based on object properties
- Confidence-based category recommendations
- Learning from user corrections and manual categorizations

#### Inventory Insights
- Consumption pattern analysis for consumables
- Asset depreciation tracking
- Purchase recommendation based on usage patterns

---

## User Interface

### Design Principles

1. **Progressive Disclosure**: Start simple, reveal complexity as needed
2. **Context-Aware**: Show relevant actions based on current state
3. **Responsive**: Works on desktop, tablet, and mobile devices
4. **Accessible**: WCAG 2.1 compliant design patterns

### Key UI Components

#### Vendor Dashboard (`vendors_hybrid.html`)
- **Three-panel view**: Metadata vendors, Organizations, Legacy vendors
- **Smart promotion**: One-click vendor → organization conversion
- **Similarity indicators**: Visual highlighting of related vendor names
- **Bulk operations**: Multi-select for batch promotions

#### Organization Editor (`edit_organization.html`)
- **Linked vendor names management**: Add/remove vendor name associations
- **Dynamic validation**: Real-time feedback on vendor name conflicts
- **Contact integration**: Person object linking for organization contacts
- **Relationship navigation**: Direct access to relationship management

#### Relationship Manager (`organization_relationships.html`)
- **Dual-panel layout**: Outgoing and incoming relationships
- **Network visualization**: Interactive organization network display
- **Relationship statistics**: Connection count and strength metrics
- **Bulk relationship operations**: Multi-organization relationship creation

### JavaScript Enhancements

#### Dynamic Loading
```javascript
// Smart vendor name suggestions
fetch('/api/get-similar-vendors/' + encodeURIComponent(vendorName))
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            displaySimilarVendors(data.similar_vendors);
        }
    });
```

#### Real-time Validation
```javascript
// Organization relationship validation
function validateRelationship(fromOrgId, toOrgId, relationshipType) {
    if (fromOrgId === toOrgId) {
        return 'Cannot create relationship with the same organization';
    }
    // Additional validation logic...
}
```

---

## API Endpoints

### Organization Management

#### Core Organization CRUD
```
GET    /vendors                           # Hybrid vendor dashboard
GET    /edit-organization/<int:org_id>    # Organization editor
POST   /create-organization               # Create new organization
POST   /update-organization/<int:org_id>  # Update organization
POST   /delete-organization/<int:org_id>  # Delete organization
```

#### Vendor Name Linking
```
POST   /promote-vendor                    # Convert vendor metadata to organization
POST   /link-vendor-name                  # Link vendor name to existing organization
POST   /unlink-vendor-name               # Remove vendor name from organization
GET    /api/get-similar-vendors/<name>   # Get similar vendor name suggestions
```

#### Organization Relationships
```
GET    /organization-relationships/<int:org_id>        # Relationship management interface
POST   /create-organization-relationship               # Create new relationship
POST   /delete-organization-relationship/<int:rel_id>  # Delete relationship
GET    /api/organization-network/<int:org_id>          # Get organization network data
```

### Object Management
```
GET    /objects                          # Object listing and search
GET    /object/<int:obj_id>             # Object details
POST   /create-object                   # Create new object
POST   /update-object/<int:obj_id>      # Update object
POST   /ai-evaluate-object/<int:obj_id> # Trigger AI evaluation
```

### AI and Processing
```
GET    /ai-queue                        # AI evaluation queue status
POST   /schedule-evaluation/<int:obj_id> # Schedule object for AI evaluation
GET    /approvals-queue                 # Manual approval queue
POST   /approve-object/<int:obj_id>     # Approve object changes
```

### Financial and Reporting
```
GET    /inventory-valuation-report      # Current inventory value
GET    /vendor-spending-report          # Spending analysis by vendor/organization
GET    /reports                         # General reporting dashboard
```

---

## Business Logic

### Vendor Evolution Workflow

```python
def promote_vendor_to_organization(vendor_name, vendor_data):
    """
    Promotes a metadata vendor to a full organization.
    Handles name linking and data migration.
    """
    # 1. Create organization
    org = Organization.create(
        name=vendor_name,
        organization_type='vendor',
        data=vendor_data
    )
    
    # 2. Link vendor name
    if 'linked_vendor_names' not in org.data:
        org.data['linked_vendor_names'] = []
    org.data['linked_vendor_names'].append(vendor_name)
    
    # 3. Find similar vendor names
    similar_names = find_similar_vendor_names(vendor_name)
    for similar_name in similar_names:
        if should_auto_link(vendor_name, similar_name):
            org.data['linked_vendor_names'].append(similar_name)
    
    # 4. Update invoices to reference organization
    update_invoices_with_organization(vendor_name, org.id)
    
    return org
```

### Organization Relationship Logic

```python
def create_bidirectional_relationship(from_org_id, to_org_id, relationship_type):
    """
    Creates a bidirectional relationship between organizations.
    Automatically handles reverse relationship creation.
    """
    # Create primary relationship
    primary = OrganizationRelationship.create_relationship(
        from_org_id=from_org_id,
        to_org_id=to_org_id,
        relationship_type=relationship_type,
        is_bidirectional=True
    )
    
    # Automatic reverse relationship is handled in the model
    return primary
```

### AI Evaluation Pipeline

```python
def process_ai_evaluation_queue():
    """
    Daily processing of AI evaluation queue.
    Respects rate limits and handles errors gracefully.
    """
    daily_limit = 30
    pending_evaluations = AIEvaluationQueue.get_daily_queue(limit=daily_limit)
    
    for evaluation in pending_evaluations:
        try:
            # Get object and context
            obj = evaluation.object
            context = gather_object_context(obj)
            
            # Send to AI provider
            ai_provider = AISettings.get_default_provider()
            result = ai_provider.evaluate_object(obj, context)
            
            # Process result
            if result.confidence >= 0.8:
                obj.record_evaluation(result)
                evaluation.status = 'completed'
            else:
                obj.needs_manual_review = True
                evaluation.status = 'needs_review'
                
        except Exception as e:
            evaluation.status = 'failed'
            evaluation.error_message = str(e)
            evaluation.attempts += 1
```

### Smart Vendor Matching

```python
def find_similar_vendor_names(vendor_name):
    """
    Finds similar vendor names using fuzzy matching and business logic.
    """
    # Normalize the name
    normalized = normalize_vendor_name(vendor_name)
    
    # Get all existing vendor names
    existing_vendors = get_all_vendor_names()
    
    similar_vendors = []
    for existing in existing_vendors:
        similarity = calculate_similarity(normalized, existing)
        if similarity > 0.7:  # Threshold for similarity
            similar_vendors.append({
                'name': existing,
                'similarity': similarity,
                'reason': get_similarity_reason(vendor_name, existing)
            })
    
    return sorted(similar_vendors, key=lambda x: x['similarity'], reverse=True)
```

---

## Deployment

### Container Setup

```yaml
# docker-compose.yml
version: '3.8'
services:
  web:
    build: .
    ports:
      - "5000:5000"
    environment:
      - DATABASE_URL=postgresql://user:password@db:5432/homebase
      - FLASK_ENV=production
    depends_on:
      - db
      
  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=homebase
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data
      
volumes:
  postgres_data:
```

### Database Migration

```bash
# Run the organization relationships migration
python create_organization_relationships_table.py

# Initialize default AI settings
python -c "
from app import create_app, db
from models import AISettings
app = create_app()
with app.app_context():
    AISettings.initialize_defaults()
    db.session.commit()
"
```

### Environment Configuration

```bash
# Required environment variables
export DATABASE_URL="postgresql://user:password@localhost:5432/homebase"
export FLASK_SECRET_KEY="your-secret-key-here"
export AI_PROVIDER_OPENAI_API_KEY="your_openai_key_here"
export AI_PROVIDER_ANTHROPIC_API_KEY="your_anthropic_key_here"
```

### Production Considerations

1. **Database Backup**: Regular PostgreSQL backups with point-in-time recovery
2. **AI Rate Limiting**: Respect provider rate limits and implement backoff
3. **File Storage**: Configure persistent storage for object attachments
4. **Monitoring**: Log aggregation and application performance monitoring
5. **Security**: HTTPS, secure headers, input validation
6. **Scaling**: Horizontal scaling for web tier, read replicas for database

---

## Summary

The Homebase application represents a sophisticated approach to home inventory management that grows with user needs:

- **Starts Simple**: Automatic vendor extraction from receipts
- **Grows Intelligently**: Smart vendor name linking and organization promotion
- **Scales to Enterprise**: Complex organizational relationship modeling
- **AI-Powered**: Intelligent categorization and evaluation
- **User-Friendly**: Progressive disclosure and context-aware interfaces

The hybrid vendor system and organization relationship model provide a realistic foundation for managing everything from simple household purchases to complex business ecosystems, making Homebase suitable for personal use while being extensible to small business and enterprise applications.

### Key Innovations

1. **Hybrid Vendor Architecture**: Bridges gap between simple and complex vendor management
2. **Smart Name Linking**: Handles real-world business name variations
3. **Bidirectional Relationships**: Automatic reverse relationship management
4. **AI Queue Management**: Intelligent scheduling and rate limiting
5. **Progressive UI**: Reveals complexity only when needed

This architecture ensures Homebase remains accessible to casual users while providing the depth needed for serious inventory and relationship management. 