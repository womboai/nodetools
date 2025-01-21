SELECT COUNT(*) as count 
FROM postfiat_tx_cache 
WHERE hash = ANY($1)
AND xmin::text = txid_current()::text