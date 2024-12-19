WITH decoded_memos AS (
    SELECT 
        c.*,
        COALESCE(
            CASE 
                WHEN main_memo_data->>'MemoFormat' IS NOT NULL THEN
                    CASE 
                        WHEN POSITION('\x' in main_memo_data->>'MemoFormat') = 1 THEN 
                            convert_from(decode(substring(main_memo_data->>'MemoFormat' from 3), 'hex'), 'UTF8')
                        ELSE 
                            convert_from(decode(main_memo_data->>'MemoFormat', 'hex'), 'UTF8')
                    END
                ELSE ''
            END, ''
        ) as memo_format,
        COALESCE(
            CASE 
                WHEN main_memo_data->>'MemoType' IS NOT NULL THEN
                    CASE 
                        WHEN POSITION('\x' in main_memo_data->>'MemoType') = 1 THEN 
                            convert_from(decode(substring(main_memo_data->>'MemoType' from 3), 'hex'), 'UTF8')
                        ELSE 
                            convert_from(decode(main_memo_data->>'MemoType', 'hex'), 'UTF8')
                    END
                ELSE ''
            END, ''
        ) as memo_type,
        COALESCE(
            CASE 
                WHEN main_memo_data->>'MemoData' IS NOT NULL THEN
                    CASE 
                        WHEN POSITION('\x' in main_memo_data->>'MemoData') = 1 THEN 
                            convert_from(decode(substring(main_memo_data->>'MemoData' from 3), 'hex'), 'UTF8')
                        ELSE 
                            convert_from(decode(main_memo_data->>'MemoData', 'hex'), 'UTF8')
                    END
                ELSE ''
            END, ''
        ) as memo_data
    FROM memo_detail_view c
)
SELECT 
    m.*,
    p.processed,
    p.rule_name,
    p.response_tx_hash,
    p.notes,
    p.processed_at
FROM decoded_memos m
LEFT JOIN transaction_processing_results p ON m.hash = p.hash
WHERE 
    CASE 
        WHEN %s = TRUE THEN TRUE  -- include_processed is TRUE
        ELSE p.hash IS NULL      -- only unprocessed transactions
    END
ORDER BY 
    CASE WHEN %s = 'close_time_iso ASC' THEN close_time_iso END ASC,
    CASE WHEN %s = 'close_time_iso DESC' THEN close_time_iso END DESC
LIMIT CASE 
    WHEN %s IS NULL THEN NULL 
    ELSE %s::integer 
END