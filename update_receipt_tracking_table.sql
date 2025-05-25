-- Update receipt creation tracking table structure
-- Remove entity_type column and update constraints

-- Drop the old constraint
ALTER TABLE receipt_creation_tracking DROP CONSTRAINT IF EXISTS unique_receipt_creation;

-- Drop the entity_type column
ALTER TABLE receipt_creation_tracking DROP COLUMN IF EXISTS entity_type;

-- Add the new simplified unique constraint
ALTER TABLE receipt_creation_tracking ADD CONSTRAINT unique_receipt_creation 
    UNIQUE(invoice_id, line_item_index, creation_type, entity_id);

-- Display success message
\echo 'Receipt creation tracking table updated successfully - removed entity_type column!' 