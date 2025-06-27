CREATE TABLE IF NOT EXISTS %SCHEMA%.scrape_batches (
    id TEXT PRIMARY KEY,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    status TEXT NOT NULL,
    pages_processed INT DEFAULT 0
);
