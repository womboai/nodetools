CREATE TABLE IF NOT EXISTS discord_notifications (
    hash VARCHAR(255) PRIMARY KEY,
    notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (hash) REFERENCES postfiat_tx_cache(hash)
);