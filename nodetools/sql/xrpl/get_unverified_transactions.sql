SELECT 
    m.*,
    p.processed,
    p.rule_name,
    p.response_tx_hash,
    p.notes,
    p.reviewed_at
FROM decoded_memos m
LEFT JOIN transaction_processing_results p ON m.hash = p.hash
WHERE 
    CASE 
        WHEN %s = TRUE THEN TRUE  -- include_processed is TRUE
        ELSE (p.hash IS NULL or p.processed = FALSE)     -- include null or false processed
    END
ORDER BY 
    CASE WHEN %s = 'close_time_iso ASC' THEN close_time_iso END ASC,
    CASE WHEN %s = 'close_time_iso DESC' THEN close_time_iso END DESC
LIMIT CASE 
    WHEN %s IS NULL THEN NULL 
    ELSE %s::integer 
END