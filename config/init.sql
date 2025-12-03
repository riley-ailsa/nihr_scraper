-- NIHR Scraper Database Initialization
-- Creates grants table if it doesn't exist

CREATE TABLE IF NOT EXISTS grants (
    grant_id VARCHAR(255) PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    call_id VARCHAR(255),
    status VARCHAR(50),
    open_date DATE,
    close_date DATE,
    tags TEXT[],
    description_summary TEXT,
    budget_min BIGINT,
    budget_max BIGINT,
    scraped_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_grants_source ON grants(source);
CREATE INDEX IF NOT EXISTS idx_grants_status ON grants(status);
CREATE INDEX IF NOT EXISTS idx_grants_close_date ON grants(close_date);
CREATE INDEX IF NOT EXISTS idx_grants_scraped_at ON grants(scraped_at);

-- Grant permissions
GRANT ALL PRIVILEGES ON TABLE grants TO postgres;
