from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()


class Settings(BaseModel):
    app_name: str = "polymarket-ai-bot"
    live_trading: bool = False
    max_trade_size_usdc: float = 5.0
    max_daily_loss_usdc: float = 10.0
    max_position_per_market_usdc: float = 20.0


settings = Settings(
    live_trading=os.getenv("LIVE_TRADING", "false").lower() == "true",
    max_trade_size_usdc=float(os.getenv("MAX_TRADE_SIZE_USDC", "5")),
    max_daily_loss_usdc=float(os.getenv("MAX_DAILY_LOSS_USDC", "10")),
    max_position_per_market_usdc=float(os.getenv("MAX_POSITION_PER_MARKET_USDC", "20")),
)
