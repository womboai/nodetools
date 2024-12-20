CREATE TABLE IF NOT EXISTS foundation_discord (
    hash VARCHAR(255) PRIMARY KEY,
    memo_data TEXT,
    memo_type VARCHAR(255),
    memo_format VARCHAR(255),
    datetime TIMESTAMP,
    url TEXT,
    directional_pft FLOAT,
    account VARCHAR(255),
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);