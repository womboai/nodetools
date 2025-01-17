SELECT 
    ptc.*,
    tm.account,
    tm.destination,
    tm.pft_amount,
    tm.xrp_fee,
    tm.memo_format,
    tm.memo_type,
    tm.memo_data,
    tm.datetime,
    tm.transaction_result
FROM postfiat_tx_cache ptc
JOIN transaction_memos tm ON ptc.hash = tm.hash
WHERE tm.account IN ($1)
OR tm.destination IN ($1)