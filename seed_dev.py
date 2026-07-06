"""Populate the DB with fake data for local UI testing (no network needed)."""
import sys
from db.cache import get_db, write_snapshot, write_fundamentals, write_scores
from core.scorers.composite import compute_all_scores

MOCK = {
    "AVAV": {
        "price": 181.0, "market_cap": 3.4e9, "week52_low": 105.0, "week52_high": 199.0,
        "trailing_pe": 34.0, "forward_pe": 27.0, "peg_ratio": 1.4,
        "target_low": 190.0, "target_mean": 225.0, "target_high": 265.0,
        "short_percent_of_float": 0.035, "put_call_ratio": 0.68, "beta": 0.85,
        "returns": {
            "ticker_return_1m": 0.07,  "spy_return_1m": 0.02,
            "ticker_return_3m": 0.18,  "spy_return_3m": 0.06,
            "ticker_return_6m": 0.32,  "spy_return_6m": 0.10,
            "ticker_return_12m": 0.62, "spy_return_12m": 0.22,
        },
    },
    "TSLA": {
        "price": 252.0, "market_cap": 810e9, "week52_low": 138.8, "week52_high": 299.3,
        "trailing_pe": 62.0, "forward_pe": 48.0, "peg_ratio": 2.8,
        "target_low": 115.0, "target_mean": 280.0, "target_high": 450.0,
        "short_percent_of_float": 0.028, "put_call_ratio": 0.82, "beta": 1.85,
        "returns": {
            "ticker_return_1m": 0.09,  "spy_return_1m": 0.02,
            "ticker_return_3m": 0.22,  "spy_return_3m": 0.06,
            "ticker_return_6m": 0.41,  "spy_return_6m": 0.10,
            "ticker_return_12m": 0.83, "spy_return_12m": 0.22,
        },
    },
    "MU": {
        "price": 86.0, "market_cap": 96e9, "week52_low": 55.1, "week52_high": 119.8,
        "trailing_pe": 14.5, "forward_pe": 11.0, "peg_ratio": 0.75,
        "target_low": 95.0, "target_mean": 118.0, "target_high": 140.0,
        "short_percent_of_float": 0.055, "put_call_ratio": 0.92, "beta": 1.12,
        "returns": {
            "ticker_return_1m": 0.03,  "spy_return_1m": 0.02,
            "ticker_return_3m": -0.04, "spy_return_3m": 0.06,
            "ticker_return_6m": 0.08,  "spy_return_6m": 0.10,
            "ticker_return_12m": 0.22, "spy_return_12m": 0.22,
        },
    },
}

FUNDS = {
    "AVAV": [
        ("2024", {"type":"annual","revenue":2.0e9,"gross_profit":0.82e9,"gross_margin":0.41,
                  "ebit":0.31e9,"net_income":0.26e9,"total_debt":0.08e9,"total_equity":1.55e9,
                  "total_assets":2.5e9,"current_assets":0.85e9,"current_liabilities":0.38e9,
                  "retained_earnings":0.52e9,"shares_outstanding":28e6,"fcf":0.22e9,
                  "interest_expense":4e6,"buybacks":-0.05e9,"cash":0.32e9,"total_liabilities":0.95e9,
                  "operating_cash_flow":0.27e9}),
        ("2023", {"type":"annual","revenue":1.6e9,"gross_profit":0.64e9,"gross_margin":0.40,
                  "ebit":0.22e9,"net_income":0.18e9,"total_debt":0.09e9,"total_equity":1.25e9,
                  "total_assets":2.0e9,"current_assets":0.72e9,"current_liabilities":0.42e9,
                  "retained_earnings":0.40e9,"shares_outstanding":29e6,"fcf":0.16e9,
                  "interest_expense":5e6,"buybacks":-0.03e9,"cash":0.28e9,"total_liabilities":0.75e9,
                  "operating_cash_flow":0.20e9}),
    ],
    "TSLA": [
        ("2024", {"type":"annual","revenue":97.7e9,"gross_profit":17.9e9,"gross_margin":0.183,
                  "ebit":7.1e9,"net_income":7.3e9,"total_debt":7.5e9,"total_equity":72.9e9,
                  "total_assets":122.1e9,"current_assets":36.7e9,"current_liabilities":30.9e9,
                  "retained_earnings":18.3e9,"shares_outstanding":3.21e9,"fcf":3.6e9,
                  "interest_expense":215e6,"buybacks":0,"cash":36.6e9,"total_liabilities":49.2e9,
                  "operating_cash_flow":14.9e9}),
        ("2023", {"type":"annual","revenue":96.8e9,"gross_profit":17.7e9,"gross_margin":0.183,
                  "ebit":8.9e9,"net_income":15e9,"total_debt":7.2e9,"total_equity":62.6e9,
                  "total_assets":106.6e9,"current_assets":32.1e9,"current_liabilities":28.7e9,
                  "retained_earnings":9.9e9,"shares_outstanding":3.17e9,"fcf":4.4e9,
                  "interest_expense":156e6,"buybacks":0,"cash":29.1e9,"total_liabilities":44.0e9,
                  "operating_cash_flow":13.3e9}),
    ],
    "MU": [
        ("2024", {"type":"annual","revenue":25.1e9,"gross_profit":10.3e9,"gross_margin":0.41,
                  "ebit":7.1e9,"net_income":5.8e9,"total_debt":12.4e9,"total_equity":46.4e9,
                  "total_assets":69.8e9,"current_assets":23.5e9,"current_liabilities":9.3e9,
                  "retained_earnings":23.8e9,"shares_outstanding":1.10e9,"fcf":2.7e9,
                  "interest_expense":454e6,"buybacks":-0.6e9,"cash":9.1e9,"total_liabilities":23.4e9,
                  "operating_cash_flow":12.4e9}),
        ("2023", {"type":"annual","revenue":15.5e9,"gross_profit":2.1e9,"gross_margin":0.135,
                  "ebit":-5.9e9,"net_income":-5.8e9,"total_debt":13.4e9,"total_equity":42.5e9,
                  "total_assets":67.3e9,"current_assets":21.7e9,"current_liabilities":8.0e9,
                  "retained_earnings":20.9e9,"shares_outstanding":1.10e9,"fcf":-4.0e9,
                  "interest_expense":444e6,"buybacks":-0.3e9,"cash":11.1e9,"total_liabilities":24.8e9,
                  "operating_cash_flow":1.6e9}),
    ],
}

def main():
    conn = get_db()
    for ticker, snap_data in MOCK.items():
        snap = {**snap_data, "insider_transactions": []}
        write_snapshot(conn, ticker, snap)
        for period, fund_data in FUNDS[ticker]:
            write_fundamentals(conn, ticker, period, fund_data)
        scores = compute_all_scores(ticker, conn)
        write_scores(conn, ticker, scores)
        print(f"  {ticker}: score={scores['score']}")
    conn.close()
    print("✅ DB seeded — restart the container or hit /api/portfolio")

if __name__ == "__main__":
    main()
