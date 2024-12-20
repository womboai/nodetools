DROP TRIGGER IF EXISTS process_tx_memos_trigger ON postfiat_tx_cache;
DROP FUNCTION IF EXISTS find_transaction_response(text, text, timestamp, text, text, text, boolean);

CREATE OR REPLACE FUNCTION find_transaction_response(
    request_account TEXT,      -- Account that made the request
    request_destination TEXT,  -- Destination account of the request
    request_time TIMESTAMP,    -- Timestamp of the request
    response_memo_type TEXT,   -- Expected memo_type of the response
    response_memo_format TEXT DEFAULT NULL,  -- Optional: expected memo_format
    response_memo_data TEXT DEFAULT NULL,    -- Optional: expected memo_data
    require_after_request BOOLEAN DEFAULT TRUE  -- Optional: require the response to be after the request
) RETURNS TABLE (
    hash VARCHAR(255),
    account VARCHAR(255),
    destination VARCHAR(255),
    memo_type TEXT,
    memo_format TEXT,
    memo_data TEXT,
    transaction_result VARCHAR(255),
    close_time_iso TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        d.hash::VARCHAR(255),
        (d.tx_json_parsed->>'Account')::VARCHAR(255) as account,
        (d.tx_json_parsed->>'Destination')::VARCHAR(255) as destination,
        d.memo_type,
        d.memo_format,
        d.memo_data,
        d.transaction_result::VARCHAR(255),
        d.close_time_iso::timestamp
    FROM decoded_memos d
    WHERE 
        d.tx_json_parsed->>'Destination' = request_account
        AND d.transaction_result = 'tesSUCCESS'
        AND (
            NOT require_after_request 
            OR d.close_time_iso::timestamp > request_time
        )
        AND d.memo_type = response_memo_type
        AND (response_memo_format IS NULL OR d.memo_format = response_memo_format)
        AND (response_memo_data IS NULL OR d.memo_data LIKE response_memo_data)
    ORDER BY d.close_time_iso ASC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION decode_hex_memo(memo_text TEXT) 
RETURNS TEXT AS $$
BEGIN
    RETURN CASE 
        WHEN memo_text IS NULL THEN ''
        WHEN POSITION('\x' in memo_text) = 1 THEN 
            convert_from(decode(substring(memo_text from 3), 'hex'), 'UTF8')
        ELSE 
            convert_from(decode(memo_text, 'hex'), 'UTF8')
    END;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION process_tx_memos() 
RETURNS TRIGGER AS $$
BEGIN
    -- Only process if there are memos
    IF (NEW.tx_json::jsonb->'Memos') IS NOT NULL THEN
        INSERT INTO transaction_memos (
            hash,
            memo_format,
            memo_type,
            memo_data
        ) VALUES (
            NEW.hash,
            decode_hex_memo((NEW.tx_json::jsonb->'Memos'->0->'Memo'->>'MemoFormat')),
            decode_hex_memo((NEW.tx_json::jsonb->'Memos'->0->'Memo'->>'MemoType')),
            decode_hex_memo((NEW.tx_json::jsonb->'Memos'->0->'Memo'->>'MemoData'))
        )
        ON CONFLICT (hash) 
        DO UPDATE SET
            memo_format = EXCLUDED.memo_format,
            memo_type = EXCLUDED.memo_type,
            memo_data = EXCLUDED.memo_data;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER process_tx_memos_trigger
    AFTER INSERT OR UPDATE ON postfiat_tx_cache
    FOR EACH ROW
    EXECUTE FUNCTION process_tx_memos();