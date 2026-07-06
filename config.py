import os
from dotenv import load_dotenv

load_dotenv()

TICKERS: list[str] = ["SOFI"]
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://stockdesk:stockdesk@localhost:5432/stockdesk",
)
