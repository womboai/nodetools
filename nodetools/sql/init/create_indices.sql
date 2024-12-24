-- Indices for postfiat_tx_cache table
CREATE INDEX IF NOT EXISTS idx_account_destination
    ON transaction_memos(account, destination);
CREATE INDEX IF NOT EXISTS idx_close_time_iso
    ON postfiat_tx_cache(close_time_iso DESC);
CREATE INDEX IF NOT EXISTS idx_memo_fields 
    ON transaction_memos(memo_type, memo_format, memo_data);