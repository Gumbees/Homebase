-- Create receipt creation tracking table
CREATE TABLE IF NOT EXISTS receipt_creation_tracking (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER REFERENCES invoices(id) NOT NULL,
    line_item_index INTEGER,
    creation_type VARCHAR(50) NOT NULL,
    entity_id INTEGER NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by_task_id INTEGER REFERENCES task_queue(id),
    metadata JSONB DEFAULT '{}',
    CONSTRAINT unique_receipt_creation UNIQUE(invoice_id, line_item_index, creation_type, entity_id)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_receipt_tracking_creation_type ON receipt_creation_tracking(creation_type);
CREATE INDEX IF NOT EXISTS idx_receipt_tracking_invoice_id ON receipt_creation_tracking(invoice_id);

-- Display success message
\echo 'Receipt creation tracking table created successfully!' 