# 🏠 Homebase - AI-Powered Home Inventory Management System

Homebase is a comprehensive home inventory management system that combines receipt processing, asset tracking, and AI-powered categorization to help you manage your household items, track expenses, and maintain organized records of your belongings.

## ✨ Features

### 📄 Receipt & Bill Processing
- **AI-Powered OCR**: Upload receipts in various formats (JPG, PNG, PDF) with automatic text extraction
- **Multi-AI Support**: Choose between OpenAI, Claude (Anthropic), or local LLM Studio for processing
- **Smart Line Item Detection**: Automatically extracts individual items from receipts
- **Vendor Recognition**: Identifies and tracks vendors automatically
- **Invoice Management**: Converts receipts to structured invoice data

### 🏠 Inventory Management
- **Multi-Type Objects**: Track assets, consumables, components, persons, pets, services, and software
- **Smart Categorization**: AI-suggested categories for better organization
- **Asset Relationships**: Link components to parent assets, track person-pet relationships
- **Photo Attachments**: Store multiple photos and documents for each item
- **Depreciation Tracking**: Monitor asset values and useful life

### 🤖 AI Integration
- **Receipt Analysis**: Automatic extraction of vendor, date, total, and line items
- **Object Evaluation**: AI analyzes photos to suggest categorization and details
- **Smart Linking**: Automatically connects receipts to existing inventory items
- **Confidence Scoring**: AI provides confidence levels for all suggestions
- **Queue Management**: Rate-limited AI processing to manage API costs

### 📊 Data Management
- **PostgreSQL Database**: Robust data storage with JSONB fields for flexible schemas
- **Vendor Tracking**: Maintain vendor contact information and purchase history
- **Category System**: Organized categories by object type with icons and colors
- **Reminders & Tasks**: Shopping lists, maintenance reminders, and task queues
- **Audit Trail**: Complete history of evaluations and changes

### 🔄 Automation
- **Scheduled Re-evaluation**: Objects are re-evaluated every 90 days
- **Expiration Tracking**: Monitor consumable expiration dates
- **Stock Management**: Track inventory levels and reorder thresholds
- **Background Processing**: Queued tasks for heavy operations

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL 15+
- Docker and Docker Compose (optional)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/homebase.git
   cd homebase
   ```

2. **Set up environment variables**
   ```bash
   cp stack.env.example stack.env
   # Edit stack.env with your configuration
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   # OR using uv (recommended)
   uv sync
   ```

4. **Run with Docker (recommended)**
   ```bash
   docker-compose up
   ```

5. **Or run locally**
   ```bash
   # Start PostgreSQL database
   # Configure DATABASE_URL in stack.env
   python app.py
   ```

The application will be available at `http://localhost:5000`

## 🛠️ Configuration

### Environment Variables

All configuration is done through the `stack.env` file:

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string | Yes | - |
| `SESSION_SECRET` | Flask session secret key | No | `development_secret_key` |
| `OPENAI_API_KEY` | OpenAI API key for GPT models | No | - |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude models | No | - |
| `LLM_STUDIO_ENDPOINT` | Local LLM Studio endpoint | No | `http://localhost:1234` |

### AI Provider Configuration

Homebase supports multiple AI providers:

- **OpenAI**: GPT-4 Vision for receipt and image analysis
- **Claude (Anthropic)**: Claude-3.5 Sonnet for enhanced analysis
- **LLM Studio**: Local models for privacy-focused processing

Configure your preferred provider in the application settings after first run.

## 📱 Usage

### Adding Receipts
1. Navigate to **Receipt Upload**
2. Upload your receipt (JPG, PNG, or PDF)
3. Choose your AI model (Claude recommended)
4. Review the extracted data and line items
5. Optionally create inventory objects from line items

### Managing Inventory
1. Go to **Inventory** to view all objects
2. Click **Add Object** to manually add items
3. Upload photos for AI analysis
4. Set categories, depreciation, and relationships

### Viewing Reports
- **Receipts**: View all processed receipts and invoices
- **Bills**: Track unpaid bills with due dates
- **Reminders**: Manage shopping lists and maintenance tasks

## 🏗️ Architecture

### Database Schema
- **Objects**: Central table for all tracked items (assets, consumables, etc.)
- **Invoices & Line Items**: Financial transaction records
- **Attachments**: Binary storage for receipts and photos
- **Categories**: Hierarchical organization system
- **AI Queue**: Managed processing queue for AI operations

### AI Processing Pipeline
1. Upload → OCR/Text Extraction → AI Analysis → Data Extraction → Database Storage
2. Background evaluation queue processes objects on schedule
3. Confidence scoring determines when manual review is needed

## 🔒 Security & Privacy

- Environment variables for sensitive configuration
- Optional local AI processing with LLM Studio
- PostgreSQL with proper data types and constraints
- Session-based authentication
- File upload size limits and type validation

## 🤝 Contributing

See [DEVELOPMENT.md](DEVELOPMENT.md) for development setup, architecture details, and contribution guidelines.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For support, please open an issue on GitHub or contact the development team.

## 🙏 Acknowledgments

- OpenAI for GPT-4 Vision API
- Anthropic for Claude AI models
- Flask and SQLAlchemy communities
- The open-source OCR and PDF processing libraries 