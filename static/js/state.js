export const state = {
  watchlist: [], watchlistData: {}, tickerStatus: {},
  portfolio: [], portfolioHoldings: {}, portfolioData: {},
  editingTicker: null, lastDetail: null, market: null,
  priceHistoryCache: {}, chartRegistry: {},
  pfSortCol: sessionStorage.getItem("pfSortCol") ?? "total",
  pfSortDir: Number(sessionStorage.getItem("pfSortDir") ?? -1),
  wlSortCol: sessionStorage.getItem("wlSortCol") ?? "ticker",
  wlSortDir: Number(sessionStorage.getItem("wlSortDir") ?? 1),
  wlFilters: JSON.parse(sessionStorage.getItem("wlFilters") ?? '{"action":"","signal":"","sector":""}'),
};
