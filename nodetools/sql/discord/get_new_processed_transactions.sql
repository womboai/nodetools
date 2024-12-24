SELECT 
    dm.*,
    tpr.processed,
    tpr.rule_name,
    tpr.response_tx_hash,
    tpr.notes,
    tpr.reviewed_at
FROM decoded_memos dm
JOIN transaction_processing_results tpr ON dm.hash = tpr.hash
LEFT JOIN discord_notifications dn ON dm.hash = dn.hash
WHERE tpr.processed = TRUE 
AND dm.datetime > %s  -- Only notify transactions after node start
AND (dn.hash IS NULL)      -- Haven't been notified yet
AND (
    dm.pft_absolute_amount != 0  -- Has PFT
    OR dm.memo_type = ANY(%s)    -- System memo types we want to display
)
ORDER BY dm.close_time_iso ASC;