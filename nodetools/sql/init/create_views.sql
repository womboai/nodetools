DROP VIEW IF EXISTS decoded_memos;
DROP VIEW IF EXISTS enriched_transaction_results;

CREATE VIEW decoded_memos AS
WITH parsed_json AS (
    SELECT
        ptc.*,
        tx_json::jsonb as tx_json_parsed,
        meta::jsonb as meta_parsed
    FROM postfiat_tx_cache ptc
)
SELECT 
    p.*,
    (p.tx_json_parsed->>'Account') as account,
    (p.tx_json_parsed->>'Destination') as destination,
    (p.tx_json_parsed->>'Fee') as fee,
    (p.tx_json_parsed->>'Flags')::float as flags,
    (p.tx_json_parsed->>'LastLedgerSequence')::bigint as lastledgersequence,
    (p.tx_json_parsed->>'Sequence')::bigint as sequence,
    (p.tx_json_parsed->>'TransactionType') as transactiontype,
    tm.memo_format,
    tm.memo_type,
    tm.memo_data,
    p.meta_parsed->>'TransactionResult' as transaction_result,
    (p.tx_json_parsed->'Memos') IS NOT NULL as has_memos,
    (p.close_time_iso::timestamp) as datetime,
    COALESCE((p.meta_parsed->'delivered_amount'->>'value')::float, 0) as pft_absolute_amount,
    (p.close_time_iso::timestamp)::date as simple_date,
    (p.tx_json_parsed->'Memos'->0->'Memo') as main_memo_data
FROM parsed_json p
LEFT JOIN transaction_memos tm ON p.hash = tm.hash;

CREATE VIEW enriched_transaction_results AS
SELECT 
    r.hash,
    r.processed,
    r.rule_name,
    r.response_tx_hash,
    r.notes,
    r.reviewed_at,
    m.account,
    m.destination,
    m.pft_amount,
    m.xrp_fee,
    m.memo_format,
    m.memo_type,
    m.memo_data,
    m.transaction_time,
    m.transaction_result
FROM transaction_processing_results r
LEFT JOIN transaction_memos m ON r.hash = m.hash;