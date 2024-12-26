CREATE TABLE IF NOT EXISTS postfiat_tx_cache (
    hash VARCHAR(255) PRIMARY KEY,
    ledger_index BIGINT,
    close_time_iso VARCHAR(255),
    meta TEXT,
    tx_json TEXT,
    validated BOOLEAN
);

CREATE TABLE IF NOT EXISTS transaction_memos (
    hash VARCHAR(255) PRIMARY KEY,
    account VARCHAR(255),
    destination VARCHAR(255),
    pft_amount NUMERIC,
    xrp_fee NUMERIC,
    memo_format TEXT DEFAULT '',
    memo_type TEXT DEFAULT '',
    memo_data TEXT DEFAULT '',
    transaction_time TIMESTAMP,
    transaction_result VARCHAR(50),
    FOREIGN KEY (hash) REFERENCES postfiat_tx_cache(hash)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transaction_processing_results (
    hash VARCHAR(255) PRIMARY KEY,
    processed BOOLEAN NOT NULL,
    rule_name VARCHAR(255),
    response_tx_hash VARCHAR(255),
    notes TEXT,
    reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (hash) REFERENCES postfiat_tx_cache(hash)
);

CREATE TABLE IF NOT EXISTS pft_holders (
    account VARCHAR(255) PRIMARY KEY,
    balance NUMERIC NOT NULL DEFAULT 0,
    last_updated TIMESTAMP NOT NULL,
    last_tx_hash VARCHAR(255)
);