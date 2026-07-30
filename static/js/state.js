export const state = {
  watchlist: [], watchlistData: {}, tickerStatus: {},
  favorites: [],
  lastDetail: null, market: null, homeLoadedAt: null,
  priceHistoryCache: {}, chartRegistry: {},
  wlSortCol: sessionStorage.getItem("wlSortCol") ?? "ticker",
  wlSortDir: Number(sessionStorage.getItem("wlSortDir") ?? 1),
  wlFilters: JSON.parse(sessionStorage.getItem("wlFilters") ?? '{"action":"","signal":"","sector":"","flag":"","search":""}'),
};
