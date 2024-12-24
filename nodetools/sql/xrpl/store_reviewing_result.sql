INSERT INTO transaction_processing_results 
    (hash, processed, rule_name, response_tx_hash, notes)
VALUES 
    (%s, %s, %s, %s, %s)
ON CONFLICT (hash) DO UPDATE SET
    processed = EXCLUDED.processed,
    rule_name = EXCLUDED.rule_name,
    response_tx_hash = EXCLUDED.response_tx_hash,
    notes = EXCLUDED.notes,
    reviewed_at = CURRENT_TIMESTAMP