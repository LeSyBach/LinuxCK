CREATE TABLE IF NOT EXISTS exchanges (id TEXT PRIMARY KEY);
INSERT INTO exchanges VALUES ('binance'),('okx'),('bybit') ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS workers (
    id TEXT PRIMARY KEY, exchange TEXT UNIQUE NOT NULL REFERENCES exchanges,
    last_heartbeat TIMESTAMPTZ, data JSONB NOT NULL DEFAULT '{}'
);
INSERT INTO workers(id,exchange) VALUES ('worker-2','binance'),('worker-3','okx'),('worker-4','bybit')
ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS received_messages (
    id TEXT PRIMARY KEY, received_at TIMESTAMPTZ NOT NULL DEFAULT now(), worker_id TEXT NOT NULL REFERENCES workers,
    body JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS market_prices (
    id TEXT PRIMARY KEY REFERENCES received_messages, exchange TEXT NOT NULL REFERENCES exchanges,
    symbol TEXT NOT NULL, price NUMERIC NOT NULL CHECK(price > 0),
    collected_at TIMESTAMPTZ NOT NULL, source_timestamp TIMESTAMPTZ, data JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS market_tickers (LIKE market_prices INCLUDING ALL);
CREATE TABLE IF NOT EXISTS market_klines (LIKE market_prices INCLUDING ALL);
CREATE INDEX IF NOT EXISTS prices_lookup ON market_prices(symbol, exchange, collected_at DESC);
CREATE INDEX IF NOT EXISTS prices_source ON market_prices(source_timestamp);
CREATE INDEX IF NOT EXISTS tickers_lookup ON market_tickers(exchange, symbol, collected_at, source_timestamp);
CREATE INDEX IF NOT EXISTS klines_lookup ON market_klines(exchange, symbol, collected_at, source_timestamp);
CREATE UNIQUE INDEX IF NOT EXISTS klines_natural_key ON market_klines(exchange,symbol,(data->>'interval'),(data->>'open_time'));
CREATE TABLE IF NOT EXISTS price_comparisons (
    symbol TEXT NOT NULL, window_end TIMESTAMPTZ NOT NULL, data JSONB NOT NULL,
    PRIMARY KEY(symbol,window_end)
);
CREATE TABLE IF NOT EXISTS alerts (
    symbol TEXT NOT NULL, window_end TIMESTAMPTZ NOT NULL, kind TEXT NOT NULL,
    state TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), body TEXT NOT NULL,
    PRIMARY KEY(symbol,window_end,kind)
);
CREATE TABLE IF NOT EXISTS system_events (
    id BIGSERIAL PRIMARY KEY, at TIMESTAMPTZ NOT NULL DEFAULT now(), event TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comparison_pending (
    symbol TEXT NOT NULL, collected_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(symbol,collected_at)
);
CREATE INDEX IF NOT EXISTS comparison_pending_time ON comparison_pending(collected_at);
