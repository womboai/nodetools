DROP TRIGGER IF EXISTS process_tx_memos_trigger ON postfiat_tx_cache;
DROP TRIGGER IF EXISTS update_pft_holders_trigger ON transaction_memos;

CREATE TRIGGER update_pft_holders_trigger
    AFTER INSERT ON transaction_memos
    FOR EACH ROW
    EXECUTE FUNCTION update_pft_holders();

CREATE TRIGGER process_tx_memos_trigger
    AFTER INSERT OR UPDATE ON postfiat_tx_cache
    FOR EACH ROW
    EXECUTE FUNCTION process_tx_memos();