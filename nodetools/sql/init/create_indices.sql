CREATE INDEX IF NOT EXISTS idx_account_destination
    ON transaction_memos(account, destination);
CREATE INDEX IF NOT EXISTS idx_close_time_iso
    ON postfiat_tx_cache(close_time_iso DESC);
CREATE INDEX IF NOT EXISTS idx_memo_fields 
    ON transaction_memos(memo_type, memo_format, memo_data);
CREATE INDEX IF NOT EXISTS idx_pft_holders_balance
    ON pft_holders(balance);
CREATE INDEX IF NOT EXISTS idx_authorized_addresses_source 
    ON authorized_addresses(auth_source, auth_source_user_id);
