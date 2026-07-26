export const state = {
  watchlist: [], watchlistData: {}, tickerStatus: {},
  portfolio: [], portfolioHoldings: {}, portfolioData: {},
  editingTicker: null, lastDetail: null,
  priceHistoryCache: {}, chartRegistry: {},
  pfSortCol: sessionStorage.getItem("pfSortCol") ?? "total",
  pfSortDir: Number(sessionStorage.getItem("pfSortDir") ?? -1),
  wlSortCol: sessionStorage.getItem("wlSortCol") ?? "ticker",
  wlSortDir: Number(sessionStorage.getItem("wlSortDir") ?? 1),
};
