import os
from dotenv import load_dotenv
from aiogram.filters import Filter
from aiogram.types import Message

load_dotenv()

class Config:
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    
    # --- ЛОГІКА БАЗИ ДАНИХ ---
    _db_url = os.environ.get("DATABASE_URL")
    
    if _db_url:
        # 1. Завжди беремо тільки "чисту" частину посилання до знаку "?"
        if "?" in _db_url:
            _db_url = _db_url.split("?")[0]
        
        # 2. Виправляємо протокол (postgres -> postgresql+asyncpg)
        if _db_url.startswith("postgres://"):
            _db_url = _db_url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif _db_url.startswith("postgresql://"):
            _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
            
        DB_URL = _db_url
    else:
        # Локальна база, якщо змінної немає
        DB_URL = "sqlite+aiosqlite:///meme_exchange.db"
    
    # --- ЕКОНОМІКА ---
    MARKET_IMPACT_FACTOR = 0.002
    NEWS_THRESHOLD = 0.10
    
    # Комісії
    SELL_COMMISSION_DEFAULT = 0.03 
    SELL_COMMISSION_BROKER = 0.01 
    
    # Ставки
    BET_PROFIT_FACTOR = 1.8
    BET_DURATION = 65

    # Ціни
    LICENSE_COST = 50000.0       
    VIP_COST = 5000.0            
    LOTTERY_TICKET = 500.0       
    CLAN_CREATION_COST = 1000000.0 
    TITLE_CHANGE_COST = 10000.0
    # Додаємо ціну за фейк
    FAKE_NEWS_COST = 100000.0
    # --- MARGIN & IPO ---
    IPO_MIN_ENTRY = 1000.0       # Мінімальна сума для входу в IPO
    # Банк
    BANK_INTEREST_RATE = 0.05  # 5% річних
    DEPOSIT_MIN = 1000.0
    DEPOSIT_INTEREST_RATE = 0.10  # 10% за депозит

if not Config.BOT_TOKEN:
    pass

# !!! ПЕРЕВІР, ЩОБ ТУТ БУВ ТВІЙ ID !!!
ADMIN_IDS = [6500735335, 123456789] 

class IsAdmin(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in ADMIN_IDS