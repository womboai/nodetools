SELECT 
    account,
    balance,
    last_updated,
    last_tx_hash
FROM pft_holders
WHERE account = $1;