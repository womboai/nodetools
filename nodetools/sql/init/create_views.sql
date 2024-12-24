DROP VIEW IF EXISTS decoded_memos;

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