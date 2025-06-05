-- Blueprint for normalized job scraper schema

-- Companies table stores unique company info
CREATE TABLE IF NOT EXISTS %SCHEMA%.companies (
    id BIGINT PRIMARY KEY,
    title_en TEXT,
    title_fa TEXT,
    about TEXT,
    company_logo TEXT
);

-- Job boards table stores job board metadata
CREATE TABLE IF NOT EXISTS %SCHEMA%.job_boards (
    id INT PRIMARY KEY,
    title_en TEXT,
    title_fa TEXT,
    organization_color TEXT
);

-- Countries, provinces and cities for location normalization
CREATE TABLE IF NOT EXISTS %SCHEMA%.countries (
    id INT PRIMARY KEY,
    title_en TEXT,
    title_fa TEXT
);

CREATE TABLE IF NOT EXISTS %SCHEMA%.provinces (
    id INT PRIMARY KEY,
    title_en TEXT,
    title_fa TEXT,
    country_id INT REFERENCES %SCHEMA%.countries(id)
);

CREATE TABLE IF NOT EXISTS %SCHEMA%.cities (
    id INT PRIMARY KEY,
    title_en TEXT,
    title_fa TEXT,
    province_id INT REFERENCES %SCHEMA%.provinces(id)
);

-- Work types reference
CREATE TABLE IF NOT EXISTS %SCHEMA%.work_types (
    id INT PRIMARY KEY,
    title_en TEXT,
    title_fa TEXT
);

-- Categories table supports hierarchy via parent_id
CREATE TABLE IF NOT EXISTS %SCHEMA%.categories (
    id INT PRIMARY KEY,
    title_en TEXT,
    title_fa TEXT,
    parent_id INT REFERENCES %SCHEMA%.categories(id)
);

-- Core jobs table referencing companies and boards
CREATE TABLE IF NOT EXISTS %SCHEMA%.jobs (
    id TEXT PRIMARY KEY,
    title TEXT,
    url TEXT,
    gender TEXT,
    salary TEXT,
    company_id BIGINT REFERENCES %SCHEMA%.companies(id),
    job_board_id INT REFERENCES %SCHEMA%.job_boards(id),
    raw_data JSONB,
    job_board_title_en TEXT,
    job_board_title_fa TEXT,
    primary_city TEXT,
    work_type TEXT,
    category TEXT,
    parent_cat TEXT,
    sub_cat TEXT,
    tag_no_experience INT DEFAULT 0,
    tag_remote INT DEFAULT 0,
    tag_part_time INT DEFAULT 0,
    tag_internship INT DEFAULT 0,
    tag_military_exemption INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Many-to-many tables
CREATE TABLE IF NOT EXISTS %SCHEMA%.job_locations (
    job_id TEXT REFERENCES %SCHEMA%.jobs(id),
    city_id INT REFERENCES %SCHEMA%.cities(id),
    PRIMARY KEY (job_id, city_id)
);

CREATE TABLE IF NOT EXISTS %SCHEMA%.job_work_types (
    job_id TEXT REFERENCES %SCHEMA%.jobs(id),
    work_type_id INT REFERENCES %SCHEMA%.work_types(id),
    PRIMARY KEY (job_id, work_type_id)
);

CREATE TABLE IF NOT EXISTS %SCHEMA%.job_categories (
    job_id TEXT REFERENCES %SCHEMA%.jobs(id),
    category_id INT REFERENCES %SCHEMA%.categories(id),
    PRIMARY KEY (job_id, category_id)
);

-- Tags and link table
CREATE TABLE IF NOT EXISTS %SCHEMA%.tags (
    id SERIAL PRIMARY KEY,
    tag_text TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS %SCHEMA%.job_tags (
    job_id TEXT REFERENCES %SCHEMA%.jobs(id),
    tag_id INT REFERENCES %SCHEMA%.tags(id),
    PRIMARY KEY (job_id, tag_id)
);

-- Trigger function to update updated_at timestamp
CREATE OR REPLACE FUNCTION %SCHEMA%.update_jobs_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE 'plpgsql';

DROP TRIGGER IF EXISTS trg_jobs_timestamp ON %SCHEMA%.jobs;
CREATE TRIGGER trg_jobs_timestamp
BEFORE UPDATE ON %SCHEMA%.jobs
FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.update_jobs_timestamp();
