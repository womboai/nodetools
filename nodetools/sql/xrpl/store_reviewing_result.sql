INSERT INTO transaction_processing_results 
    (hash, processed, rule_name, response_tx_hash, notes)
VALUES 
    ($1, $2, $3, $4, $5)
ON CONFLICT (hash) DO UPDATE SET
    processed = EXCLUDED.processed,
    rule_name = EXCLUDED.rule_name,
    response_tx_hash = EXCLUDED.response_tx_hash,
    notes = EXCLUDED.notes,
    reviewed_at = CURRENT_TIMESTAMP