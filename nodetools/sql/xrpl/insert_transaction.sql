INSERT INTO postfiat_tx_cache (
    hash,
    ledger_index,
    close_time_iso,
    tx_json,
    meta,
    validated
) VALUES (
    %(hash)s,
    %(ledger_index)s,
    %(close_time_iso)s,
    %(tx_json)s,
    %(meta)s,
    %(validated)s
) ON CONFLICT (hash) DO NOTHING