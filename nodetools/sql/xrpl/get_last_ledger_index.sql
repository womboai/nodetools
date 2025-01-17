SELECT MAX(ptc.ledger_index) as last_ledger
FROM postfiat_tx_cache ptc
JOIN transaction_memos tm ON ptc.hash = tm.hash
WHERE tm.account = $1;