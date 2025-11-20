-- ============================================================================
-- ASK AILSA - POSTGRESQL SCHEMA
-- Clean, production-ready schema for grant discovery platform
-- ============================================================================

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================================
-- USERS & AUTHENTICATION
-- ============================================================================

CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255),  -- bcrypt hash
    full_name VARCHAR(255),
    organization VARCHAR(255),
    organization_type VARCHAR(50),  -- 'university', 'sme', 'ngo', 'large_enterprise'
    
    -- Profile
    research_areas TEXT[],
    expertise_areas TEXT[],
    budget_min INTEGER,
    budget_max INTEGER,
    preferred_programmes TEXT[],  -- ['horizon_europe', 'digital_europe', 'nihr', 'innovate_uk']
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Search optimization
    CONSTRAINT valid_budget CHECK (budget_max >= budget_min OR budget_min IS NULL)
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_org_type ON users(organization_type);
CREATE INDEX idx_users_active ON users(is_active) WHERE is_active = TRUE;


-- ============================================================================
-- GRANTS - Metadata Only (vectors in Pinecone)
-- ============================================================================

CREATE TABLE grants (
    grant_id VARCHAR(255) PRIMARY KEY,  -- e.g., "horizon_europe:HORIZON-CL5-..."
    source VARCHAR(50) NOT NULL,  -- 'horizon_europe', 'digital_europe', 'nihr', 'innovate_uk'
    
    -- Core fields
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    call_id VARCHAR(255),
    
    -- Status
    status VARCHAR(50),  -- 'Open', 'Closed', 'Forthcoming'
    open_date DATE,
    close_date DATE,
    
    -- Classification
    programme VARCHAR(255),
    programme_area TEXT[],
    tags TEXT[],
    action_type VARCHAR(100),
    
    -- Financial
    budget_min BIGINT,
    budget_max BIGINT,
    funding_rate_percent INTEGER,  -- e.g., 100 for 100% funding
    
    -- Eligibility
    eligible_countries TEXT[],
    organization_types TEXT[],  -- Who can apply
    consortium_required BOOLEAN,
    min_partners INTEGER,
    
    -- Content (summary only, full text in Pinecone)
    description_summary TEXT,  -- First 500 chars
    
    -- Metadata
    scraped_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    pinecone_synced_at TIMESTAMP WITH TIME ZONE,
    
    -- Search optimization
    tsv_title tsvector GENERATED ALWAYS AS (to_tsvector('english', title)) STORED,
    
    CONSTRAINT valid_dates CHECK (close_date >= open_date OR open_date IS NULL)
);

-- Indexes for fast filtering
CREATE INDEX idx_grants_source ON grants(source);
CREATE INDEX idx_grants_status ON grants(status);
CREATE INDEX idx_grants_close_date ON grants(close_date) WHERE status = 'Open';
CREATE INDEX idx_grants_tags ON grants USING GIN(tags);
CREATE INDEX idx_grants_programme ON grants(programme);
CREATE INDEX idx_grants_budget ON grants(budget_min, budget_max);
CREATE INDEX idx_grants_tsv_title ON grants USING GIN(tsv_title);


-- ============================================================================
-- USER INTERACTIONS - Training data for XGBoost
-- ============================================================================

CREATE TABLE user_interactions (
    interaction_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    grant_id VARCHAR(255) NOT NULL REFERENCES grants(grant_id) ON DELETE CASCADE,
    
    action VARCHAR(50) NOT NULL,  -- 'viewed', 'saved', 'dismissed', 'applied', 'shared'
    
    -- Context
    query TEXT,  -- What they searched for
    rank_position INTEGER,  -- Where in results this appeared
    time_spent_seconds INTEGER,  -- Time on page
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    session_id UUID,
    
    -- For XGBoost training labels
    relevance_score DECIMAL(3,2)  -- 0.0 to 1.0 (auto-calculated from action)
);

CREATE INDEX idx_interactions_user ON user_interactions(user_id);
CREATE INDEX idx_interactions_grant ON user_interactions(grant_id);
CREATE INDEX idx_interactions_action ON user_interactions(action);
CREATE INDEX idx_interactions_created ON user_interactions(created_at DESC);

-- Auto-calculate relevance score from action
CREATE OR REPLACE FUNCTION calculate_relevance_score()
RETURNS TRIGGER AS $$
BEGIN
    NEW.relevance_score := CASE NEW.action
        WHEN 'applied' THEN 1.0
        WHEN 'saved' THEN 0.8
        WHEN 'shared' THEN 0.7
        WHEN 'viewed' THEN 0.5
        WHEN 'dismissed' THEN 0.0
        ELSE 0.3
    END;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_relevance_score
    BEFORE INSERT ON user_interactions
    FOR EACH ROW
    EXECUTE FUNCTION calculate_relevance_score();


-- ============================================================================
-- SAVED GRANTS - User bookmarks
-- ============================================================================

CREATE TABLE saved_grants (
    saved_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    grant_id VARCHAR(255) NOT NULL REFERENCES grants(grant_id) ON DELETE CASCADE,
    
    notes TEXT,
    tags TEXT[],  -- User's custom tags
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(user_id, grant_id)
);

CREATE INDEX idx_saved_grants_user ON saved_grants(user_id);
CREATE INDEX idx_saved_grants_created ON saved_grants(created_at DESC);


-- ============================================================================
-- CLIENT MANAGEMENT (Your 4-5 clients)
-- ============================================================================

CREATE TABLE clients (
    client_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_name VARCHAR(255) NOT NULL,
    
    -- Subscription
    plan_type VARCHAR(50),  -- 'free', 'basic', 'professional', 'enterprise'
    max_users INTEGER,
    features JSONB,  -- Flexible feature flags
    
    -- Contact
    primary_contact_email VARCHAR(255),
    billing_email VARCHAR(255),
    
    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    subscription_ends_at TIMESTAMP WITH TIME ZONE
);

-- Link users to clients
CREATE TABLE client_users (
    client_id UUID REFERENCES clients(client_id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    role VARCHAR(50) DEFAULT 'member',  -- 'admin', 'member', 'viewer'
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    PRIMARY KEY (client_id, user_id)
);


-- ============================================================================
-- AGENT SESSIONS (Future: For bespoke agents)
-- ============================================================================

CREATE TABLE agent_sessions (
    session_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    agent_type VARCHAR(50),  -- 'discovery', 'application_helper', 'strategy'
    
    -- Context
    context JSONB,  -- Agent memory/state
    
    -- Metrics
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_interaction TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    interaction_count INTEGER DEFAULT 0,
    
    -- Pinecone namespace for this session's memory
    pinecone_namespace VARCHAR(255)
);

CREATE INDEX idx_agent_sessions_user ON agent_sessions(user_id);


-- ============================================================================
-- ANALYTICS - Query/usage tracking
-- ============================================================================

CREATE TABLE search_queries (
    query_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
    
    query_text TEXT NOT NULL,
    filters JSONB,  -- Applied filters
    
    results_count INTEGER,
    clicks_count INTEGER DEFAULT 0,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_search_queries_user ON search_queries(user_id);
CREATE INDEX idx_search_queries_created ON search_queries(created_at DESC);


-- ============================================================================
-- FUNCTIONS & TRIGGERS
-- ============================================================================

-- Auto-update updated_at timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_grants_updated_at
    BEFORE UPDATE ON grants
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


-- ============================================================================
-- VIEWS - Useful queries
-- ============================================================================

-- Active open grants
CREATE VIEW active_grants AS
SELECT *
FROM grants
WHERE status = 'Open'
  AND (close_date IS NULL OR close_date >= CURRENT_DATE)
ORDER BY close_date ASC NULLS LAST;

-- User engagement summary
CREATE VIEW user_engagement AS
SELECT 
    u.user_id,
    u.email,
    COUNT(DISTINCT i.grant_id) as grants_viewed,
    COUNT(DISTINCT s.grant_id) as grants_saved,
    COUNT(DISTINCT CASE WHEN i.action = 'applied' THEN i.grant_id END) as grants_applied,
    MAX(i.created_at) as last_activity
FROM users u
LEFT JOIN user_interactions i ON u.user_id = i.user_id
LEFT JOIN saved_grants s ON u.user_id = s.user_id
GROUP BY u.user_id, u.email;
