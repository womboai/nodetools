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
        WHEN $1 = TRUE THEN TRUE  -- include_processed is TRUE
        ELSE (p.hash IS NULL or p.processed = FALSE)     -- include null or false processed
    END
ORDER BY 
    CASE WHEN $2 = 'close_time_iso ASC' THEN close_time_iso END ASC,
    CASE WHEN $3 = 'close_time_iso DESC' THEN close_time_iso END DESC
LIMIT CASE 
    WHEN CAST($4 AS INTEGER) IS NULL THEN NULL 
    ELSE CAST($5 AS INTEGER)::integer 
END