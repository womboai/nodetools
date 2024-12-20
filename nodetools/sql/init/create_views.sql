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
    tm.memo_format,
    tm.memo_type,
    tm.memo_data,
    p.meta_parsed->>'TransactionResult' as transaction_result,
    (p.tx_json_parsed->'Memos') IS NOT NULL as has_memos,
    (p.close_time_iso::timestamp) as datetime,
    COALESCE((p.tx_json_parsed->'DeliverMax'->>'value')::float, 0) as pft_absolute_amount,
    (p.close_time_iso::timestamp)::date as simple_date,
    (p.tx_json_parsed->'Memos'->0->'Memo') as main_memo_data
FROM parsed_json p
LEFT JOIN transaction_memos tm ON p.hash = tm.hash;