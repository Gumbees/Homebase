-- Database Optimization for Attachment Performance
-- Run this script to optimize attachment storage and retrieval

-- Create indexes for attachment queries (without the binary data column)
CREATE INDEX IF NOT EXISTS idx_attachments_invoice_id ON attachments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_attachments_file_type ON attachments(file_type);
CREATE INDEX IF NOT EXISTS idx_attachments_upload_date ON attachments(upload_date);

-- Similar indexes for object attachments
CREATE INDEX IF NOT EXISTS idx_object_attachments_object_id ON object_attachments(object_id);
CREATE INDEX IF NOT EXISTS idx_object_attachments_file_type ON object_attachments(file_type);
CREATE INDEX IF NOT EXISTS idx_object_attachments_upload_date ON object_attachments(upload_date);

-- Exclude binary data columns from BTREE indexes (PostgreSQL handles this automatically with TOAST)
-- But we can create partial indexes for common queries

-- Index for getting attachment metadata (without file_data)
CREATE INDEX IF NOT EXISTS idx_attachments_metadata ON attachments(id, invoice_id, filename, file_type, upload_date);
CREATE INDEX IF NOT EXISTS idx_object_attachments_metadata ON object_attachments(id, object_id, filename, file_type, upload_date);

-- Configure TOAST compression for large binary data
-- PostgreSQL automatically moves large values to TOAST tables, but we can optimize the threshold

-- For attachments table
ALTER TABLE attachments ALTER COLUMN file_data SET STORAGE EXTENDED;

-- For object_attachments table  
ALTER TABLE object_attachments ALTER COLUMN file_data SET STORAGE EXTENDED;

-- Create a view for attachment metadata without binary data
CREATE OR REPLACE VIEW attachment_metadata AS
SELECT 
    id,
    invoice_id,
    filename,
    file_type,
    upload_date,
    pg_column_size(file_data) as file_size_bytes
FROM attachments;

CREATE OR REPLACE VIEW object_attachment_metadata AS
SELECT 
    id,
    object_id,
    filename,
    file_type,
    attachment_type,
    description,
    upload_date,
    ai_analyzed,
    pg_column_size(file_data) as file_size_bytes
FROM object_attachments;

-- Grant permissions on views
GRANT SELECT ON attachment_metadata TO PUBLIC;
GRANT SELECT ON object_attachment_metadata TO PUBLIC;

-- Add comments for documentation
COMMENT ON INDEX idx_attachments_invoice_id IS 'Index for fast attachment lookup by invoice/receipt';
COMMENT ON INDEX idx_attachments_file_type IS 'Index for filtering attachments by file type';
COMMENT ON INDEX idx_object_attachments_object_id IS 'Index for fast attachment lookup by object';

COMMENT ON VIEW attachment_metadata IS 'View of attachment metadata without binary data for performance';
COMMENT ON VIEW object_attachment_metadata IS 'View of object attachment metadata without binary data for performance';

-- Analyze tables to update statistics
ANALYZE attachments;
ANALYZE object_attachments; 