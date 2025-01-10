SELECT 
    m.*,
    p.processed,
    p.rule_name,
    p.response_tx_hash,
    p.notes,
    p.reviewed_at
FROM transaction_memos m
LEFT JOIN transaction_processing_results p ON m.hash = p.hash
WHERE m.hash = $1