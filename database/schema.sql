-- MyLife OS 统一数据库（PostgreSQL；SQLite 测试时由 database.py 自动转换）
CREATE TABLE IF NOT EXISTS users (id BIGSERIAL PRIMARY KEY, name TEXT, timezone TEXT DEFAULT 'Asia/Kuala_Lumpur', settings TEXT);
CREATE TABLE IF NOT EXISTS integrations (id BIGSERIAL PRIMARY KEY, provider TEXT NOT NULL, status TEXT DEFAULT 'not_connected', scopes TEXT, updated_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS products (id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, url TEXT UNIQUE NOT NULL, volume_ml REAL, target_price REAL, created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS price_history (id BIGSERIAL PRIMARY KEY, product_id BIGINT NOT NULL REFERENCES products(id), price REAL NOT NULL, currency TEXT DEFAULT 'MYR', checked_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS expenses (id BIGSERIAL PRIMARY KEY, vendor TEXT, amount REAL, category TEXT, spent_on DATE, source TEXT);
CREATE TABLE IF NOT EXISTS subscriptions (id BIGSERIAL PRIMARY KEY, name TEXT, amount REAL, cycle TEXT, next_due DATE);
CREATE TABLE IF NOT EXISTS travel_prices (id BIGSERIAL PRIMARY KEY, kind TEXT, route_or_hotel TEXT, price REAL, currency TEXT, checked_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS properties (id BIGSERIAL PRIMARY KEY, title TEXT, url TEXT UNIQUE, price REAL, location TEXT, first_seen TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS jobs (id BIGSERIAL PRIMARY KEY, title TEXT, company TEXT, url TEXT UNIQUE, salary TEXT, location TEXT, first_seen TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS inventory (id BIGSERIAL PRIMARY KEY, item TEXT, quantity REAL, restock_days INTEGER, last_restocked DATE);
CREATE TABLE IF NOT EXISTS news (id BIGSERIAL PRIMARY KEY, title TEXT, url TEXT UNIQUE, summary TEXT, published_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS emails (id BIGSERIAL PRIMARY KEY, message_id TEXT UNIQUE, category TEXT, summary TEXT, action_needed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS calendar_events (id BIGSERIAL PRIMARY KEY, event_id TEXT UNIQUE, title TEXT, starts_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS tasks (id BIGSERIAL PRIMARY KEY, title TEXT, due_on DATE, status TEXT DEFAULT 'open', source TEXT);
CREATE TABLE IF NOT EXISTS notifications (id BIGSERIAL PRIMARY KEY, dedup_key TEXT UNIQUE NOT NULL, channel TEXT, title TEXT, status TEXT, sent_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS scraper_logs (id BIGSERIAL PRIMARY KEY, module TEXT, target TEXT, status TEXT, error TEXT, run_at TIMESTAMPTZ DEFAULT NOW());
