SELECT 
    ptc.*,
    tm.account,
    tm.destination,
    tm.pft_amount,
    tm.xrp_fee,
    tm.memo_format,
    tm.memo_type,
    tm.memo_data,
    tm.transaction_time,
    tm.transaction_result
FROM postfiat_tx_cache ptc
JOIN transaction_memos tm ON ptc.hash = tm.hash
WHERE tm.account IN (%(wallet_addresses)s)
OR tm.destination IN (%(wallet_addresses)s)