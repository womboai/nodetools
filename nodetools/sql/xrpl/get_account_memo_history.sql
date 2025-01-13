WITH base_query AS (
    SELECT 
        hash,
        account,
        destination,
        pft_amount,
        xrp_fee,
        memo_format,
        memo_type,
        memo_data,
        datetime,
        transaction_result,
        CASE
            WHEN destination = $1 THEN 'INCOMING'
            ELSE 'OUTGOING'
        END as direction,
        CASE
            WHEN destination = $1 THEN pft_amount
            ELSE -pft_amount
        END as directional_pft,
        CASE
            WHEN account = $1 THEN destination
            ELSE account
        END as user_account
    FROM transaction_memos
    WHERE (account = $1 OR destination = $1)
)
SELECT * FROM base_query 
WHERE 1=1
    AND CASE WHEN $2 THEN pft_amount IS NOT NULL ELSE TRUE END
    AND CASE WHEN $3::text IS NOT NULL THEN memo_type LIKE $3::text ELSE TRUE END
ORDER BY datetime DESC
