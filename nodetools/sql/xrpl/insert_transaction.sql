INSERT INTO postfiat_tx_cache (
    hash,
    ledger_index,
    close_time_iso,
    tx_json,
    meta,
    validated
) VALUES (
    $1,
    $2,
    $3,
    $4,
    $5,
    $6
) ON CONFLICT (hash) DO NOTHING