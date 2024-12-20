CREATE TABLE IF NOT EXISTS postfiat_tx_cache (
    close_time_iso VARCHAR(255),
    hash VARCHAR(255) PRIMARY KEY,
    ledger_hash VARCHAR(255),
    ledger_index BIGINT,
    meta TEXT,
    tx_json TEXT,
    validated BOOLEAN,
    account VARCHAR(255),
    delivermax TEXT,
    destination VARCHAR(255),
    fee VARCHAR(20),
    flags FLOAT,
    lastledgersequence BIGINT,
    sequence BIGINT,
    signingpubkey TEXT,
    transactiontype VARCHAR(50),
    txnsignature TEXT,
    date BIGINT,
    memos TEXT
);

CREATE TABLE IF NOT EXISTS transaction_memos (
    hash VARCHAR(255) PRIMARY KEY,
    memo_format TEXT DEFAULT '',
    memo_type TEXT DEFAULT '',
    memo_data TEXT DEFAULT '',
    FOREIGN KEY (hash) REFERENCES postfiat_tx_cache(hash)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transaction_processing_results (
    hash VARCHAR(255) PRIMARY KEY,
    processed BOOLEAN NOT NULL,
    rule_name VARCHAR(255),
    response_tx_hash VARCHAR(255),
    notes TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (hash) REFERENCES postfiat_tx_cache(hash)
);