import os
from dotenv import load_dotenv

load_dotenv()

TICKERS: list[str] = []
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://stocki:stocki@localhost:5432/stocki",
)
