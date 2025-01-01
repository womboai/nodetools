DROP TRIGGER IF EXISTS process_tx_memos_trigger ON postfiat_tx_cache;
DROP FUNCTION IF EXISTS find_transaction_response(text, text, timestamp, text, text, text, boolean);

CREATE OR REPLACE FUNCTION find_transaction_response(
    request_account TEXT,      -- Account that made the request
    request_destination TEXT,  -- Destination account of the request
    request_time TEXT,         -- Timestamp of the request
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
            OR d.close_time_iso::timestamp > request_time::timestamp
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
            account,
            destination,
            pft_amount,
            xrp_fee,
            memo_format,
            memo_type,
            memo_data,
            datetime,
            transaction_result
        ) VALUES (
            NEW.hash,
            (NEW.tx_json::jsonb->>'Account'),
            (NEW.tx_json::jsonb->>'Destination'),
            NULLIF((NEW.meta::jsonb->'delivered_amount'->>'value')::NUMERIC, 0),
            NULLIF((NEW.tx_json::jsonb->>'Fee')::NUMERIC, 0) / 1000000,
            decode_hex_memo((NEW.tx_json::jsonb->'Memos'->0->'Memo'->>'MemoFormat')),
            decode_hex_memo((NEW.tx_json::jsonb->'Memos'->0->'Memo'->>'MemoType')),
            decode_hex_memo((NEW.tx_json::jsonb->'Memos'->0->'Memo'->>'MemoData')),
            (NEW.close_time_iso::timestamp),
            (NEW.meta::jsonb->>'TransactionResult')
        )
        ON CONFLICT (hash) 
        DO UPDATE SET
            account = EXCLUDED.account,
            destination = EXCLUDED.destination,
            pft_amount = EXCLUDED.pft_amount,
            xrp_fee = EXCLUDED.xrp_fee,
            memo_format = EXCLUDED.memo_format,
            memo_type = EXCLUDED.memo_type,
            memo_data = EXCLUDED.memo_data,
            datetime = EXCLUDED.datetime,
            transaction_result = EXCLUDED.transaction_result;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER process_tx_memos_trigger
    AFTER INSERT OR UPDATE ON postfiat_tx_cache
    FOR EACH ROW
    EXECUTE FUNCTION process_tx_memos();

-- Function to update PFT holders and balances when transactions are processed
CREATE OR REPLACE FUNCTION update_pft_holders()
RETURNS TRIGGER AS $$
DECLARE
    affected_node JSONB;
    final_fields JSONB;
    previous_fields JSONB;
    account_address TEXT;
    new_balance NUMERIC;
    pft_issuer TEXT;
    meta_parsed JSONB;
BEGIN
    -- Set issuer based on database name
    pft_issuer := CASE 
        WHEN current_database() LIKE '%_testnet' THEN 'rLX2tgumpiUE6kjr757Ao8HWiJzC8uuBSN'
        ELSE 'rnQUEEg8yyjrwk9FhyXpKavHyCRJM9BDMW'
    END;

    -- Skip if no meta data exists
    IF NEW.meta IS NULL THEN
        RETURN NEW;
    END IF;

    -- Try to parse meta as JSON
    BEGIN
        meta_parsed := NEW.meta::jsonb;
    EXCEPTION WHEN OTHERS THEN
        RETURN NEW;
    END;

    -- Only process successful PFT transactions
    IF meta_parsed->>'TransactionResult' != 'tesSUCCESS' THEN
        RETURN NEW;
    END IF;

    -- Only process if AffectedNodes exists and is an array
    IF meta_parsed->'AffectedNodes' IS NULL OR jsonb_typeof(meta_parsed->'AffectedNodes') != 'array' THEN
        RETURN NEW;
    END IF;

    -- Iterate through affected nodes
    -- In XRPL transactions, the AffectedNodes array in the metadata shows all ledger entries that were modified by the transaction.
    FOR affected_node IN 
        SELECT jsonb_array_elements(meta_parsed->'AffectedNodes')
    LOOP
        -- Only process RippleState entries for PFT
        IF affected_node->'ModifiedNode'->>'LedgerEntryType' = 'RippleState' 
           AND affected_node->'ModifiedNode'->'FinalFields'->'Balance'->>'currency' = 'PFT' THEN
            
            final_fields := affected_node->'ModifiedNode'->'FinalFields';
            previous_fields := affected_node->'ModifiedNode'->'PreviousFields';

            -- Get the non-issuer account
            IF final_fields->'LowLimit'->>'issuer' != pft_issuer THEN
                account_address := final_fields->'LowLimit'->>'issuer';
                new_balance := (final_fields->'Balance'->>'value')::NUMERIC;
            ELSIF final_fields->'HighLimit'->>'issuer' != pft_issuer THEN
                account_address := final_fields->'HighLimit'->>'issuer';
                -- Negate the balance for high limit accounts
                new_balance := -(final_fields->'Balance'->>'value')::NUMERIC;
            END IF;

            -- Update or insert the balance
            INSERT INTO pft_holders (account, balance, last_updated, last_tx_hash)
            VALUES (
                account_address,
                new_balance,
                NEW.close_time_iso::timestamp,
                NEW.hash
            )
            ON CONFLICT (account) DO UPDATE
            SET 
                balance = EXCLUDED.balance,
                last_updated = EXCLUDED.last_updated,
                last_tx_hash = EXCLUDED.last_tx_hash;
        END IF;
    END LOOP;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
CREATE TRIGGER update_pft_holders_trigger
    AFTER INSERT ON postfiat_tx_cache
    FOR EACH ROW
    EXECUTE FUNCTION update_pft_holders();