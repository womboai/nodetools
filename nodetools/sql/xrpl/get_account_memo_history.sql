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
    FROM decoded_memos
    WHERE (account = %s OR destination = %s)
)
SELECT * FROM base_query