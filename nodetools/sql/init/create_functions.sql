-- Function to find a response to a request transaction
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
    transaction_result VARCHAR(50),
    datetime TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        tm.hash,
        tm.account,
        tm.destination,
        tm.memo_type,
        tm.memo_format,
        tm.memo_data,
        tm.transaction_result,
        tm.datetime
    FROM transaction_memos tm
    WHERE 
        tm.destination = request_account
        AND tm.transaction_result = 'tesSUCCESS'
        AND (
            NOT require_after_request 
            OR tm.datetime > request_time
        )
        AND tm.memo_type LIKE response_memo_type
        AND (response_memo_format IS NULL OR tm.memo_format = response_memo_format)
        AND (response_memo_data IS NULL OR tm.memo_data LIKE response_memo_data)
    ORDER BY tm.datetime ASC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Function to decode hex-encoded memos
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

-- Function to process raw transaction data and insert into transaction_memos
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

-- Function to update PFT holders and balances when transactions are processed
CREATE OR REPLACE FUNCTION update_pft_holders()
RETURNS TRIGGER AS $$
DECLARE
    meta_parsed JSONB;
    current_balance NUMERIC;
BEGIN
    -- Skip if transaction wasn't successful
    IF NEW.transaction_result != 'tesSUCCESS' THEN
        RETURN NEW;
    END IF;

    -- Process sender's balance
    IF NEW.account IS NOT NULL AND NEW.pft_amount IS NOT NULL THEN
        -- Get current balance or default to 0
        SELECT balance INTO current_balance
        FROM pft_holders
        WHERE account = NEW.account;

        IF current_balance IS NULL THEN
            current_balance := 0;
        END IF;

        -- Update sender's balance (subtract amount sent)
        INSERT INTO pft_holders (account, balance, last_updated, last_tx_hash)
        VALUES (
            NEW.account,
            current_balance - NEW.pft_amount,
            NEW.datetime,
            NEW.hash
        )
        ON CONFLICT (account) DO UPDATE
        SET 
            balance = EXCLUDED.balance,
            last_updated = EXCLUDED.last_updated,
            last_tx_hash = EXCLUDED.last_tx_hash;
    END IF;

    -- Process recipient's balance
    IF NEW.destination IS NOT NULL AND NEW.pft_amount IS NOT NULL THEN
        -- Get current balance or default to 0
        SELECT balance INTO current_balance
        FROM pft_holders
        WHERE account = NEW.destination;

        IF current_balance IS NULL THEN
            current_balance := 0;
        END IF;

        -- Update recipient's balance (add amount received)
        INSERT INTO pft_holders (account, balance, last_updated, last_tx_hash)
        VALUES (
            NEW.destination,
            current_balance + NEW.pft_amount,
            NEW.datetime,
            NEW.hash
        )
        ON CONFLICT (account) DO UPDATE
        SET 
            balance = EXCLUDED.balance,
            last_updated = EXCLUDED.last_updated,
            last_tx_hash = EXCLUDED.last_tx_hash;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;