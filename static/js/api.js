export async function fetchLists() { const r = await fetch("/api/lists"); return r.json(); }
export async function fetchWatchlist(tickers) { const r = await fetch("/api/watchlist?tickers=" + tickers.join(",")); return r.json(); }
export async function fetchStatus(tickers) { const r = await fetch("/api/status?tickers=" + tickers.join(",")); return r.json(); }
export async function fetchPortfolioPrices() { const r = await fetch("/api/portfolio/prices"); return r.json(); }
