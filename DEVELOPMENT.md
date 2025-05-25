# 🛠️ Development Guide - Homebase

This guide covers the development setup, architecture, and contribution guidelines for the Homebase project.

## 🏗️ Architecture Overview

### Technology Stack
- **Backend**: Flask 3.1+ with Python 3.11+
- **Database**: PostgreSQL 15+ with SQLAlchemy ORM and JSONB for flexible data storage
- **AI Integration**: OpenAI GPT-4o exclusively for superior image processing and QR/UPC code cropping
- **MCP Server**: FastAPI-based Model Context Protocol server for AI abstraction
- **Frontend**: HTML templates with Bootstrap/CSS and JavaScript
- **Deployment**: Docker & Docker Compose
- **Package Management**: UV (recommended) or pip

### Project Structure

```
homebase/
├── app.py                          # Flask application entry point
├── main.py                         # Alternative entry point
├── routes.py                       # Main Flask routes and handlers
├── models.py                       # SQLAlchemy database models
├── mcp_client.py                   # MCP server client integration
├── 
├── AI Services/
│   ├── openai_utils.py            # OpenAI GPT-4o integration (active)
│   ├── ocr_utils.py               # OCR and image processing (OpenAI-powered)

│   ├── claude_utils.py            # Anthropic Claude integration (removed)
│   └── llm_studio_utils.py        # Local LLM Studio integration (removed)
│
├── MCP Server/
│   ├── mcp-server/
│   │   ├── main.py                # FastAPI MCP server application
│   │   ├── schemas.py             # Pydantic models and schemas
│   │   ├── prompt_manager.py      # Prompt template management
│   │   ├── ai_providers.py        # AI provider implementations
│   │   ├── requirements.txt       # MCP server dependencies
│   │   └── Dockerfile             # MCP server container
│   └── prompts/
│       ├── templates/             # Jinja2 prompt templates
│       └── schemas/               # JSON schemas for structured output
│
├── Database Management/
│   ├── update_db.py               # General database updates
│   ├── update_db_categories.py    # Category system updates
│   ├── update_db_ai_queue.py      # AI queue management
│   ├── update_db_multi_categories.py
│   └── update_db_object_attachments.py
│
├── Infrastructure/
│   ├── queue_processor.py         # Background task processing
│   ├── log_utils.py              # Logging utilities
│   ├── init.sql                  # Database initialization
│   ├── Dockerfile                # Main app container configuration
│   └── docker-compose.yml        # Multi-service orchestration
│
├── Frontend/
│   ├── templates/                 # Jinja2 HTML templates
│   └── static/                   # CSS, JS, and image assets
│       ├── css/
│       ├── js/
│       └── images/
│
└── Configuration/
    ├── requirements.txt           # Python dependencies
    ├── pyproject.toml            # Project metadata and dependencies
    ├── uv.lock                   # Lock file for UV package manager
    ├── stack.env.example         # Environment variable template
    ├── .gitignore               # Version control exclusions
    └── migrate_env.py            # Migration script for .env → stack.env
```

## 🚀 Development Setup

### 1. Prerequisites
- Python 3.11 or higher
- PostgreSQL 15+ (or use Docker)
- Git
- UV package manager (recommended) or pip

### 2. Environment Setup

**Clone and prepare the repository:**
```bash
git clone https://github.com/yourusername/homebase.git
cd homebase
```

**Set up environment variables:**
```bash
cp stack.env.example stack.env
```

Edit `stack.env` with your configuration:
```env
# Database Configuration
DATABASE_URL=postgresql://homebase:homebase@localhost:5432/homebase

# MCP Server Configuration
MCP_SERVER_URL=http://mcp-server:8080

# AI Service API Keys (required)
OPENAI_API_KEY=your_openai_api_key_here

# Security
SESSION_SECRET=your_secure_random_secret_key_here
```

### 3. Installation Options

#### Option A: Docker Development (Recommended)
```bash
# Start all services including PostgreSQL and MCP server
docker-compose up --build

# The application will be available at http://localhost:5000
# The MCP server will be available at http://localhost:8080
```

#### Option B: Local Development
```bash
# Install dependencies with UV (recommended)
uv sync

# Or with pip
pip install -r requirements.txt

# Start PostgreSQL (if not using Docker)
# Configure DATABASE_URL in stack.env

# Start MCP server (in separate terminal)
cd mcp-server
pip install -r requirements.txt
python main.py

# Run the application
python app.py
# Or with UV
uv run python app.py
```

### 4. Database Setup

The application automatically creates database tables on first run. For manual database management:

```bash
# Run database migrations/updates
python update_db.py

# Initialize categories
python update_db_categories.py

# Set up AI evaluation queue
python update_db_ai_queue.py
```

## 🏛️ Database Architecture

### 📋 Data Model Concepts

#### Entities vs Objects

Homebase uses two different approaches for data storage to balance structure with flexibility:

**🏢 Entities** - Structured Database Tables
- **Purpose**: Governance, relationships, and structured data
- **Examples**: `invoices`, `organizations`, `calendar_events`, `users`, `vendors`
- **Characteristics**: 
  - Fixed schema with defined columns
  - Enforced relationships via foreign keys
  - Optimized for queries and reporting
  - Used for core business logic and integrations

**🧱 Objects** - Flexible JSON-Based Records  
- **Purpose**: Dynamic, evolving data with varied schemas
- **Storage**: Single `objects` table with JSONB `data` column
- **Examples**: Assets, consumables, people, pets, components
- **Characteristics**:
  - Flexible schema stored as JSON
  - Can evolve without database migrations  
  - AI-processed with confidence scoring
  - Categorized and tagged dynamically

**Receipt Creation Tracking**
The `receipt_creation_tracking` table bridges both concepts:
- `creation_type`: What type was created ('object', 'invoice', 'organization', 'calendar_event')
- `creation_id`: The primary key of the created record (regardless of table)
- `line_item_index`: Which receipt line item created it (null for receipt-level items)

### 🎛️ AI Queue Checkbox System

The AI Queue uses a sophisticated checkbox-based creation system that allows users to selectively create related items from receipts:

#### User Interface Flow
1. **Receipt Analysis**: AI processes receipt and identifies potential creations
2. **Checkbox Selection**: User sees checkboxes for:
   - 📄 Invoice (always checked by default)
   - 🏢 Organization (if vendor detected)
   - 📅 Calendar Event (if event detected)
   - 📦 Objects (per line item, if items detected)
   - 👤 People (if people detected)

3. **Selective Creation**: Only checked items get created
4. **Automatic Relationships**: Created items are automatically linked to each other

#### Implementation Details

**Route**: `/approve-receipt-with-selections/<int:task_id>`
- Handles `POST` requests with checkbox selections
- Calls `process_receipt_task_enhanced()` with selections
- Tracks all creations in `receipt_creation_tracking`

**Creation Logic**:
```python
# Line item objects (granular tracking)
for line_idx in create_objects:
    if not ReceiptCreationTracking.is_created(invoice.id, 'object', line_idx):
        obj = create_object_from_line_item(item, invoice, line_idx)
        ReceiptCreationTracking.track_creation(
            invoice_id=invoice.id,
            line_item_index=line_idx,  # Specific line item
            creation_type='object',
            creation_id=obj.id
        )

# Receipt-level entities (receipt tracking)
if create_organization:
    if not ReceiptCreationTracking.is_created(invoice.id, 'organization', None):
        org = Organization.get_or_create(vendor_name)
        ReceiptCreationTracking.track_creation(
            invoice_id=invoice.id,
            line_item_index=None,  # Receipt level
            creation_type='organization',
            creation_id=org.id
        )
```

#### Smart UI Prevention

Once items are created, the UI adapts:

**AI Queue**: Shows what was already created, disables duplicate creation
**Receipts Page**: Hides creation buttons for items that already exist

### Enhanced QR Code & UPC Code Processing

The system now automatically detects, crops, and saves QR codes and UPC/barcode images from receipts:

#### Attachment Types
- **`qr_code`**: Text data extracted from QR codes
- **`qr_code_image`**: Cropped image of the QR code itself (base64 stored as JPEG)
- **`upc_code`**: Text data extracted from UPC/barcodes  
- **`upc_code_image`**: Cropped image of the UPC/barcode (base64 stored as JPEG)
- **`confirmation_code`**: Text confirmation codes for events/tickets

#### Implementation
```python
# Enhanced object creation with QR/UPC processing
def create_object_from_line_item(item, invoice, line_idx):
    # ... object creation logic ...
    
    # Process digital assets
    digital_assets = extracted_metadata.get('digital_assets', {})
    
    # Create QR code attachments - both text and image
    qr_code_data = digital_assets.get('qr_code')
    qr_code_image = digital_assets.get('qr_code_image')  # base64 image
    
    if qr_code_image:
        # Save cropped QR code image
        qr_image_data = base64.b64decode(qr_code_image)
        qr_image_attachment = ObjectAttachment(
            object_id=obj.id,
            filename=f"qr_code_{obj.id}.jpg",
            file_data=qr_image_data,
            file_type='image/jpeg',
            attachment_type='qr_code_image',
            description='AI-cropped QR code from receipt'
        )
```

#### UI Enhancements
- **Visual Indicators**: Special badges for AI-cropped images
- **View Links**: Direct viewing of cropped QR codes and UPC codes
- **Type Differentiation**: Clear distinction between text data and cropped images

**Example Logic**:
```python
# Check if line item object already created
line_item_created = ReceiptCreationTracking.is_created(
    invoice_id=receipt.id,
    creation_type='object',
    line_item_index=0  # First line item
)

# Check if calendar event already created  
event_created = ReceiptCreationTracking.is_created(
    invoice_id=receipt.id,
    creation_type='calendar_event',
    line_item_index=None  # Receipt level
)
```

#### Benefits
- **No Duplicates**: Impossible to create the same thing twice
- **User Control**: Full control over what gets created
- **Performance**: Efficient tracking without complex queries
- **Clarity**: Clear indication of what was created when

### Core Models

#### Objects (`objects` table)
Central entity for all tracked items with flexible JSONB data storage:
- **Types**: asset, consumable, component, person, pet, service, software
- **Relationships**: Self-referential for components, many-to-many with categories
- **AI Features**: Evaluation queue, confidence scoring, manual review flags

#### Invoices & Line Items (`invoices`, `invoice_line_items`)
Financial transaction records:
- Links to vendors and objects
- JSONB data for flexible receipt information
- Support for both receipts (paid) and bills (unpaid)

#### AI Evaluation Queue (`ai_evaluation_queue`)
Manages scheduled AI processing:
- Rate limiting (30 evaluations per day)
- Retry logic and error handling
- Priority-based processing

#### Categories (`categories`)
Hierarchical organization system:
- Type-specific categories (asset categories, consumable categories, etc.)
- AI confidence scoring for suggested categories
- Icon and color customization

### Database Design Principles

1. **JSONB for Flexibility**: Core data stored in JSONB fields for schema evolution
2. **Proper Indexing**: Strategic indexes on frequently queried fields
3. **Referential Integrity**: Foreign keys with proper CASCADE behaviors
4. **Audit Trail**: Created/updated timestamps on all entities
5. **Soft Deletion**: Flags rather than hard deletes where appropriate

## 🤖 MCP Server Architecture

### Model Context Protocol (MCP) Server

The MCP server is a **FastAPI-based microservice** that centralizes all AI operations:

#### Key Benefits:
- **Centralized Prompt Management**: All AI prompts stored as versioned templates
- **Provider Abstraction**: Seamless switching between OpenAI, Claude, and local models
- **Structured Outputs**: JSON schema enforcement for consistent AI responses
- **Rate Limiting & Metrics**: Built-in usage tracking and cost monitoring
- **Template Versioning**: A/B testing and prompt optimization capabilities
- **Health Monitoring**: Real-time provider availability checking

#### Architecture Components:

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Main Flask    │───▶│   MCP Server    │───▶│  AI Providers   │
│   Application   │    │   (FastAPI)     │    │ Claude/OpenAI/  │
│                 │    │                 │    │  LLM Studio     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │                       ▼                       │
         │              ┌─────────────────┐              │
         │              │ Prompt Manager  │              │
         │              │   (Jinja2)      │              │
         │              └─────────────────┘              │
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   PostgreSQL    │    │ Prompt Templates│    │   Metrics &     │
│   Database      │    │   (YAML/JSON)   │    │   Monitoring    │
│   (JSONB)       │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### AI Service Abstraction Layer

#### Simplified Integration (OpenAI Exclusive)
The system now uses OpenAI GPT-4o exclusively. Legacy `claude_utils.py` and `llm_studio_utils.py` modules have been removed.

#### Current Integration
```python
# OpenAI-exclusive approach via MCP client
from mcp_client import analyze_receipt_sync

result = analyze_receipt_sync(
    image_data=receipt_bytes,
    filename="receipt.jpg", 
    provider="openai"  # Only provider supported
)
```

### Prompt Management System

#### Template Structure
```yaml
# prompts/templates/receipt_analysis.yaml
name: "receipt_analysis"
description: "Analyzes receipt images and extracts structured data"
content: |
  You are an expert at analyzing receipts and extracting structured data.
  
  Analyze the provided receipt image and extract:
  - vendor_name: The business name
  - date: Transaction date in YYYY-MM-DD format
  - total_amount: Total amount paid (numeric)
  # ... detailed instructions
  
  Return the data as valid JSON matching the receipt_data schema.
variables: []
output_schema: "receipt_data"
version: "1.0"
```

#### Benefits:
- **Version Control**: Track prompt changes and performance
- **A/B Testing**: Compare different prompt versions
- **Reusability**: Shared prompts across different contexts
- **Validation**: Automatic syntax and schema checking

### AI Provider Implementation

#### OpenAI GPT-4o Integration (Exclusive)
- **Model**: GPT-4o for all vision and text analysis operations
- **Key Features**:
  - **QR Code Cropping**: Automatically detects and crops QR codes from receipts
  - **UPC/Barcode Extraction**: Identifies and extracts barcode images with high accuracy
  - **No Image Size Limits**: Processes high-resolution images without compression
  - **Enhanced Metadata Extraction**: Superior detection of serial numbers, model numbers, and product details
- **Strengths**: Advanced vision capabilities, consistent results, image cropping, fast processing
- **Cost**: ~$2.50-15 per 1K tokens depending on input/output (vision vs text)

#### Legacy Provider Support (Removed)
- **Claude (Anthropic)**: Removed in favor of OpenAI's superior image processing
- **LLM Studio**: Removed to simplify architecture and ensure consistent results
- **Benefits of Single Provider**: Consistent API behavior, simplified maintenance, predictable costs

### MCP API Endpoints

#### Core Endpoints:
- `POST /ai/process` - Generic AI processing
- `POST /ai/receipt/analyze` - Receipt analysis
- `POST /ai/object/categorize` - Object categorization  
- `POST /ai/vendor/extract` - Vendor extraction

#### Management Endpoints:
- `GET /health` - Server health check
- `GET /providers` - Available AI providers
- `GET /prompts/templates` - List prompt templates
- `POST /prompts/templates/{name}` - Update templates
- `GET /metrics` - Usage metrics

## 🔧 Development Workflow

### Code Style and Standards
- **Python**: PEP 8 compliance, type hints where beneficial
- **SQL**: Use SQLAlchemy ORM, avoid raw SQL unless necessary
- **HTML/CSS**: Semantic markup, responsive design
- **JavaScript**: ES6+, minimal dependencies
- **AI Prompts**: Use Jinja2 templating, include confidence scoring

### Logging
Comprehensive logging system via `log_utils.py`:
```python
from log_utils import get_logger, log_function_call

logger = get_logger(__name__)

@log_function_call
def my_function():
    logger.info("Function executed successfully")
```

MCP server uses structured logging with JSON output for better observability.

### Error Handling
- Database transactions with proper rollback
- Graceful degradation when MCP server or OpenAI API unavailable
- Automatic fallback to basic receipt processing when AI fails
- User-friendly error messages with confidence indicators
- Enhanced attachment handling for QR code and UPC code images

### Testing Strategy
- Unit tests for core business logic
- Integration tests for MCP server endpoints
- Database transaction testing with JSONB queries
- Mock AI responses for consistent testing
- Prompt template validation and A/B testing

## 🔄 Background Processing

### Queue System
The application uses multiple queue systems:

#### AI Evaluation Queue
- **Purpose**: Schedule object re-evaluation every 90 days
- **Rate Limiting**: 30 evaluations per day via MCP server
- **Processing**: `queue_processor.py` handles background execution

#### Task Queue
- **Purpose**: General background tasks (expiration tracking, stock checks)
- **Priority System**: 1-10 priority levels
- **Retry Logic**: Exponential backoff for failed tasks

### Queue Processor
```bash
# Run background queue processor
python queue_processor.py
```

## 🧪 Testing

### Unit Tests
```bash
# Run unit tests
python -m pytest tests/

# With coverage
python -m pytest --cov=. tests/
```

### MCP Server Tests
```bash
# Test MCP server endpoints
cd mcp-server
python -m pytest tests/

# Test AI providers (requires API keys)
python -m pytest tests/test_providers.py
```

### Database Tests
```bash
# Test database models and JSONB queries
python -m pytest tests/test_models.py
```

### Prompt Testing
```bash
# Validate prompt templates
curl http://localhost:8080/prompts/templates/receipt_analysis

# Test prompt rendering (OpenAI only)
curl -X POST http://localhost:8080/ai/process \
  -H "Content-Type: application/json" \
  -d '{"prompt_type": "receipt_analysis", "provider": "openai", "context": {}}'
```

## 🚀 Deployment

### Production Environment Variables
```env
# Required
DATABASE_URL=postgresql://user:password@host:port/database
SESSION_SECRET=your_production_secret_key
MCP_SERVER_URL=http://mcp-server:8080

# AI Services (required)
OPENAI_API_KEY=your_production_openai_key
```

### Docker Production Deployment
```bash
# Build production images
docker-compose -f docker-compose.yml -f docker-compose.prod.yml build

# Run with external database
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Performance Considerations
- **Database Indexing**: Ensure GIN indexes on frequently queried JSONB fields
- **MCP Server Scaling**: Can be horizontally scaled with load balancer
- **AI Rate Limiting**: Configure appropriate daily limits for OpenAI API
- **File Storage**: Consider external storage for large attachment volumes and cropped images
- **Caching**: Implement Redis caching for frequently accessed data
- **Image Processing**: No size limits means larger storage requirements for high-resolution images

## 🤝 Contributing

### Pull Request Process
1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Make your changes with appropriate tests
4. Ensure all tests pass (including MCP server tests)
5. Update documentation if needed
6. Submit a pull request with detailed description

### Code Review Guidelines
- **Functionality**: Does the code solve the intended problem?
- **Performance**: Are there any performance implications?
- **Security**: Are there any security vulnerabilities?
- **Maintainability**: Is the code readable and well-documented?
- **AI Integration**: Does it use the MCP server appropriately?

### Feature Development Guidelines
1. **Database Changes**: Always include migration scripts
2. **AI Integration**: Use OpenAI GPT-4o exclusively via MCP server
3. **Prompt Changes**: Update templates via MCP server API
4. **UI Changes**: Ensure responsive design and accessibility
5. **API Changes**: Maintain backward compatibility when possible
6. **Image Processing**: Leverage OpenAI's image cropping capabilities for QR/UPC codes

## 🐛 Debugging

### Common Issues

#### Database Connection Issues
```bash
# Check PostgreSQL connection
python -c "import os; from sqlalchemy import create_engine; engine = create_engine(os.environ.get('DATABASE_URL')); print('Connection successful')"

# Test JSONB queries
python -c "from app import db; from models import Object; print(Object.query.filter(Object.data['name'].astext == 'test').first())"
```

#### MCP Server Issues
```bash
# Test MCP server health
curl http://localhost:8080/health

# Test OpenAI connectivity
curl -X POST http://localhost:8080/providers/openai/test
```

#### AI Processing Issues
- Check MCP server logs: `docker-compose logs mcp-server`
- Verify API keys in environment variables
- Test individual providers via MCP endpoints
- Check prompt template syntax

### Logging and Monitoring
- Application logs: `logs/homebase.log`
- MCP server logs: JSON structured logging
- Database query logging: Enable SQLAlchemy echo
- AI usage metrics: Available via `/metrics` endpoint

## 📊 Monitoring and Metrics

### Key Metrics to Monitor
- **Database Performance**: Query execution times, JSONB query optimization
- **MCP Server Performance**: Response times, success rates per provider
- **AI Processing**: Confidence scores, processing times, token usage
- **Queue Health**: Pending tasks, failed tasks, processing rates
- **User Activity**: Upload frequency, error rates, feature usage

### Health Checks
```bash
# Application health
curl http://localhost:5000/

# MCP server health  
curl http://localhost:8080/health

# Database health
python -c "from app import db; print('DB OK' if db.engine.execute('SELECT 1').scalar() == 1 else 'DB ERROR')"

# AI providers health
curl http://localhost:8080/providers
```

### Metrics Dashboard
The MCP server provides detailed metrics:
```bash
# Get comprehensive usage metrics
curl http://localhost:8080/metrics
```

This development guide provides a comprehensive foundation for contributing to and extending the Homebase project with its new MCP server architecture. The modular design allows for easy scaling, testing, and maintenance of AI functionality while maintaining clean separation of concerns. 