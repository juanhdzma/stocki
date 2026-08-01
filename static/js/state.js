const DEFAULT_FILTERS = { action: "", signal: "", sector: "", flag: "", search: "" };

// Runs at module import, before main.js. A throw here (storage blocked in private mode, or a
// corrupted hand-edited value) would blank the whole app with no recovery — fall back to defaults.
function readPersisted() {
  try {
    return {
      wlSortCol: sessionStorage.getItem("wlSortCol") ?? "ticker",
      wlSortDir: Number(sessionStorage.getItem("wlSortDir") ?? 1) || 1,
      wlFilters: { ...DEFAULT_FILTERS, ...JSON.parse(sessionStorage.getItem("wlFilters") ?? "{}") },
    };
  } catch {
    return { wlSortCol: "ticker", wlSortDir: 1, wlFilters: { ...DEFAULT_FILTERS } };
  }
}

export const state = {
  watchlist: [], watchlistData: {}, tickerStatus: {},
  favorites: [],
  lastDetail: null, market: null, homeLoadedAt: null,
  priceHistoryCache: {}, chartRegistry: {},
  ...readPersisted(),
};
