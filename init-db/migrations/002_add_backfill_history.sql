CREATE TABLE IF NOT EXISTS %SCHEMA%.backfill_history (
    id SERIAL PRIMARY KEY,
    start_page INT,
    end_page INT,
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
