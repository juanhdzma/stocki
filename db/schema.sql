CREATE TABLE IF NOT EXISTS fundamentals_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT    NOT NULL,
    period      TEXT    NOT NULL,
    data_json   TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (ticker, period)
);

CREATE TABLE IF NOT EXISTS market_snapshot (
    ticker       TEXT PRIMARY KEY,
    data_json    TEXT NOT NULL,
    refreshed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scores_cache (
    ticker      TEXT PRIMARY KEY,
    scores_json TEXT NOT NULL,
    computed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS watchlist (
    ticker     TEXT PRIMARY KEY,
    list_type  TEXT NOT NULL DEFAULT 'watchlist',
    added_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fetch_timestamps (
    ticker      TEXT NOT NULL,
    data_type   TEXT NOT NULL,
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (ticker, data_type)
);

INSERT OR IGNORE INTO watchlist (ticker) VALUES
    ('AVGO'),('PLTR'),('NVDA'),('NOW'),('SOFI'),('RKLB'),('TSM'),('MU'),('GOOGL'),('VRT'),
    ('INTC'),('AAOI'),('ACN'),('ADBE'),('ADI'),('AFRM'),('AMAT'),('AMD'),('AME'),('ARM'),
    ('ASML'),('AVAV'),('AXTI'),('BE'),('CEG'),('CGNX'),('CIB'),('CRM'),('CRWD'),('CRWV'),
    ('EPAM'),('ERII'),('GEV'),('GMED'),('IONQ'),('ISRG'),('JBL'),('KTOS'),('LITE'),('LLY'),
    ('LMT'),('MDT'),('MELI'),('META'),('MNST'),('MP'),('MRVL'),('MSFT'),('NBIS'),('NFLX'),
    ('NNE'),('NOVT'),('NPCE'),('NU'),('OUST'),('PRCT'),('QBTS'),('QCOM'),('QNT'),('SNDK'),
    ('SOI.PA'),('SPCX'),('STM'),('STX'),('SYK'),('TER'),('TKR'),('TSLA'),('TTD'),('USAR'),
    ('VST'),('WDC'),('ZS'),('MOG-A');
