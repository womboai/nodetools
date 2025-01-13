SELECT 
    hash,
    datetime,
    memo_data,
    CASE 
        WHEN account = $1 THEN 'OUTGOING'
        ELSE 'INCOMING'
    END as direction
FROM transaction_memos
WHERE 
    ((account = $1 AND destination = $2) OR (account = $2 AND destination = $1))
    AND memo_type LIKE '%HANDSHAKE%'
ORDER BY datetime DESC;
