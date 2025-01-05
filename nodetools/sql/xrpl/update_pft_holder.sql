INSERT INTO pft_holders (
    account,
    balance,
    last_updated,
    last_tx_hash
)
VALUES (
    $1,
    $2,
    CURRENT_TIMESTAMP,
    NULLIF($3, '')  -- Convert empty string to NULL if passed
)
ON CONFLICT (account) DO UPDATE
SET 
    balance = EXCLUDED.balance,
    last_updated = EXCLUDED.last_updated,
    -- Only update last_tx_hash if new value is not NULL
    last_tx_hash = CASE 
        WHEN EXCLUDED.last_tx_hash IS NOT NULL THEN EXCLUDED.last_tx_hash 
        ELSE pft_holders.last_tx_hash 
    END;