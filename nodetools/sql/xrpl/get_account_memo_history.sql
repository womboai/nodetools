WITH base_query AS (
    SELECT 
        *,
        CASE
            WHEN destination = %s THEN 'INCOMING'
            ELSE 'OUTGOING'
        END as direction,
        CASE
            WHEN destination = %s THEN pft_absolute_amount
            ELSE -pft_absolute_amount
        END as directional_pft,
        CASE
            WHEN account = %s THEN destination
            ELSE account
        END as user_account,
        destination || '__' || hash as unique_key
    FROM memo_detail_view
    WHERE (account = %s OR destination = %s)
)
SELECT 
    base_query.*,
    COALESCE(
        CASE 
            WHEN main_memo_data->>'MemoFormat' IS NOT NULL THEN
                CASE 
                    -- Handle \x prefix if present
                    WHEN POSITION('\x' in main_memo_data->>'MemoFormat') = 1 THEN 
                        COALESCE(NULLIF(
                            TRY_CAST(decode(substring(main_memo_data->>'MemoFormat' from 3), 'hex')::text AS text),
                            ''), main_memo_data->>'MemoFormat')
                    -- Direct hex decode attempt
                    ELSE 
                        COALESCE(NULLIF(
                            TRY_CAST(decode(main_memo_data->>'MemoFormat', 'hex')::text AS text),
                            ''), main_memo_data->>'MemoFormat')
                END
            ELSE ''
        END, ''
    ) as memo_format,
    COALESCE(
        CASE 
            WHEN main_memo_data->>'MemoType' IS NOT NULL THEN
                CASE 
                    -- Handle \x prefix if present
                    WHEN POSITION('\x' in main_memo_data->>'MemoType') = 1 THEN 
                        COALESCE(NULLIF(
                            TRY_CAST(decode(substring(main_memo_data->>'MemoType' from 3), 'hex')::text AS text),
                            ''), main_memo_data->>'MemoType')
                    -- Direct hex decode attempt
                    ELSE 
                        COALESCE(NULLIF(
                            TRY_CAST(decode(main_memo_data->>'MemoType', 'hex')::text AS text),
                            ''), main_memo_data->>'MemoType')
                END
            ELSE ''
        END, ''
    ) as memo_type,
    COALESCE(
        CASE 
            WHEN main_memo_data->>'MemoData' IS NOT NULL THEN
                CASE 
                    -- Handle \x prefix if present
                    WHEN POSITION('\x' in main_memo_data->>'MemoData') = 1 THEN 
                        COALESCE(NULLIF(
                            TRY_CAST(decode(substring(main_memo_data->>'MemoData' from 3), 'hex')::text AS text),
                            ''), main_memo_data->>'MemoData')
                    -- Direct hex decode attempt
                    ELSE 
                        COALESCE(NULLIF(
                            TRY_CAST(decode(main_memo_data->>'MemoData', 'hex')::text AS text),
                            ''), main_memo_data->>'MemoData')
                END
            ELSE ''
        END, ''
    ) as memo_data
FROM base_query