-- Rename entity_id to creation_id for clarity
-- This makes it clear we're storing the ID of whatever was created, not an "entity" ID

-- Drop the constraint first
ALTER TABLE receipt_creation_tracking DROP CONSTRAINT IF EXISTS unique_receipt_creation;

-- Rename the column
ALTER TABLE receipt_creation_tracking RENAME COLUMN entity_id TO creation_id;

-- Recreate the constraint with the new column name
ALTER TABLE receipt_creation_tracking ADD CONSTRAINT unique_receipt_creation 
    UNIQUE(invoice_id, line_item_index, creation_type, creation_id);

-- Display success message
\echo 'Renamed entity_id to creation_id successfully!' 