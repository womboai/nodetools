SELECT hash, ledger_index
FROM postfiat_tx_cache 
WHERE hash = ANY($1)
AND xmin::text = txid_current()::text