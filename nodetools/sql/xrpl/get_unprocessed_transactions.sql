SELECT 
    tm.*,
    p.processed,
    p.rule_name,
    p.response_tx_hash,
    p.notes,
    p.reviewed_at
FROM transaction_memos tm
LEFT JOIN transaction_processing_results p ON tm.hash = p.hash
WHERE 
    CASE 
        WHEN $1 = TRUE THEN TRUE  -- include_processed is TRUE
        ELSE (p.hash IS NULL or p.processed = FALSE)     -- include null or false processed
    END
ORDER BY 
    CASE WHEN $2 = 'datetime ASC' THEN tm.datetime END ASC,
    CASE WHEN $2 = 'datetime DESC' THEN tm.datetime END DESC
OFFSET CASE
    WHEN CAST($3 AS INTEGER) IS NULL THEN 0
    ELSE CAST($3 AS INTEGER)::integer
END
LIMIT CASE 
    WHEN CAST($4 AS INTEGER) IS NULL THEN NULL 
    ELSE CAST($4 AS INTEGER)::integer 
END
