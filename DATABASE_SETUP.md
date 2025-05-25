# Database Setup Guide

This guide covers database initialization for new Homebase installations.

## Automatic Database Initialization

Homebase automatically initializes the database when you launch the application for the first time. This includes:

### ✅ What Gets Set Up Automatically

1. **Database Tables**: All required tables for inventory, receipts, AI, users, etc.
2. **Performance Optimizations**: 
   - Indexes for fast queries
   - TOAST configuration for efficient binary data storage
   - Metadata views for queries without loading attachment data
3. **Default Settings**: AI provider settings (OpenAI configuration)
4. **Required Data**: Essential categories and system defaults

### 🔍 Checking Database Status

You can check your database initialization status in the **Settings** page:

1. Navigate to `/settings` in your browser
2. Scroll down to the **Database Status** section
3. The status will show:
   - ✅ **Tables Created**: All required database tables exist
   - ✅ **Database Optimized**: Performance optimizations applied
   - ✅ **AI Settings Initialized**: Default AI configuration set up

### 🛠️ Manual Database Initialization

If automatic initialization fails or you need to reinitialize:

#### Option 1: Via Web Interface (Recommended)
1. Go to Settings → Database Status
2. Click **"Force Initialize Database"**
3. Confirm the action

#### Option 2: Via Command Line
```bash
# Run the initialization script directly
python db_init.py
```

#### Option 3: Via Docker
```bash
# If running in Docker, execute inside the container
docker exec -it <web-container-name> python db_init.py
```

## Database Performance Optimizations

The initialization includes several performance optimizations specifically for attachment storage:

### TOAST Configuration
- Large binary data (receipt images, attachments) stored externally
- Prevents memory bloat when querying metadata
- Configures PostgreSQL for optimal binary data handling

### Indexes
- **Attachment Metadata**: Fast queries without loading binary data
- **Object Relationships**: Efficient lookup of related items
- **Date-based Queries**: Optimized receipt and calendar searches

### Deferred Loading
- Binary attachment data only loaded when actually needed
- Metadata queries exclude large binary columns
- Significant memory usage reduction

## Troubleshooting

### Database Connection Issues
```
Error: Database initialization failed
```
**Solution**: Check your `DATABASE_URL` environment variable and ensure PostgreSQL is running.

### Permission Issues
```
Error: Permission denied for relation attachments
```
**Solution**: Ensure your database user has CREATE, ALTER, and INDEX permissions.

### Missing Tables After Initialization
**Solution**: 
1. Check the application logs for specific errors
2. Use the "Force Initialize Database" button in Settings
3. Verify your database user has sufficient permissions

### Optimization Already Applied
If you see "Database optimizations already applied, skipping..." this is normal and means your database is already optimized.

## Environment Variables

Ensure these environment variables are set:

```bash
DATABASE_URL=postgresql://homebase:homebase@localhost:5432/homebase
OPENAI_API_KEY=your_openai_api_key_here  # Optional but recommended
```

## Database Schema

The initialization creates these main table groups:

### Core Tables
- `invoices`, `invoice_line_items`, `attachments`
- `objects`, `object_categories`, `categories`
- `vendors`, `organizations`

### AI & Automation
- `ai_settings`, `ai_evaluation_queue`
- `task_queue`, `reminders`

### User & Entity Management
- `users`, `user_person_mapping`, `user_aliases`
- `organization_contacts`, `notes`, `calendar_events`

### Collections & Tracking
- `collections`, `collection_objects`
- `receipt_creation_tracking`

## Post-Installation Steps

After database initialization:

1. **Configure AI Settings**: Add your OpenAI API key in Settings
2. **Create Your First User**: Navigate to Users → Add User
3. **Upload a Receipt**: Test the system with a sample receipt
4. **Check AI Queue**: Verify AI processing is working

## Performance Monitoring

Monitor these aspects after initialization:

- **Query Performance**: Most queries should be under 100ms
- **Memory Usage**: Should remain stable even with many attachments
- **Storage Growth**: TOAST tables will grow with attachments

## Backup Recommendations

After initialization, set up regular backups:

```bash
# Full database backup
pg_dump -h localhost -U homebase -d homebase > homebase_backup.sql

# Schema-only backup
pg_dump -h localhost -U homebase -d homebase --schema-only > homebase_schema.sql
```

## Support

If you encounter issues during database initialization:

1. Check the application logs: `logs/homebase.log`
2. Verify PostgreSQL is running: `docker ps` or `systemctl status postgresql`
3. Test database connection: `psql -h localhost -U homebase -d homebase`
4. Review environment variables and Docker configuration

The database initialization is designed to be idempotent - you can run it multiple times safely. 