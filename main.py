import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeDefault
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from aiohttp import web
import os

# Імпорти механіки та моделей
from mechanics import (
    update_prices, check_bets, run_lottery, check_money_supply, 
    process_bank_interest, start_tycoon_battle, process_ipos
)
from models import Item, Meme 
from collection import initialize_collection_cards 
from config import Config
from database import init_db, async_session
from handlers import router

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Глобальна змінна для доступу з інших модулів
bot = None

# --- ФУНКЦІЯ ДЛЯ WEB SERVER (Щоб Render не вбивав бота) ---
async def health_check(request):
    return web.Response(text="Bot is running OK!")

async def start_web_server():
    """Створює простий веб-сервер для Render"""
    app = web.Application()
    app.router.add_get('/', health_check)
    
    port = int(os.environ.get("PORT", 8080))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"🌍 Web server started on port {port}")

async def on_startup(bot_instance: Bot):
    """Ініціалізація при запуску бота"""
    await init_db()
    await initialize_collection_cards()
    
    async with async_session() as session:
        # --- СПИСОК ВАЛЮТ З КАРТИНКАМИ ---
        target_memes = [
            ("W.D", 10.0, 0.03, "https://i.postimg.cc/SNwFGR1F/d1b19f930d9c3e7af98d364106998502.jpg"),
            ("Я.І.П", 1.0, 0.03, "https://i.postimg.cc/GHJ5LL1W/IMG-20251118-191149-858.jpg"),
            ("ДЖАБА", 5.0, 0.03, "https://i.postimg.cc/8jB0ppSg/c86212b356b85f28daee9437dd5d4b21.jpg"),
        ]
        
        shop_data = [
            ("Nokia 3310", 50, "📱", "tech"),
            ("Siemens A52", 100, "📟", "tech"),
            ("Android з AliExpress", 300, "📲", "tech"),
            ("Xiaomi", 500, "📱", "tech"),
            ("iPhone X (Б/У)", 800, "📱", "tech"),
            ("Samsung Galaxy S24", 1200, "📱", "tech"),
            ("iPhone 15", 1500, "📱", "tech"),
            ("iPhone 16 Pro Max", 2500, "🍎", "tech"),
            ("Vertu Signature", 10000, "💎", "tech"),
            ("Gold iPhone з діамантами", 50000, "👑", "tech"),
            ("Маршрутка (проїзний)", 5, "🚌", "auto"),
            ("Велосипед 'Україна'", 150, "🚲", "auto"),
            ("Daewoo Lanos", 2000, "🚙", "auto"),
            ("BMW на бляхах", 5000, "🚗", "auto"),
            ("Toyota Camry 3.5", 15000, "🚕", "auto"),
            ("Tesla Model 3", 35000, "🔋", "auto"),
            ("Porsche Cayenne", 80000, "🏎", "auto"),
            ("Mercedes G-Wagon", 250000, "🚙", "auto"),
            ("Lamborghini Aventador", 500000, "🏎", "auto"),
            ("Bugatti Chiron", 3000000, "🚀", "auto"),
            ("Картонна коробка", 0, "📦", "real_estate"),
            ("Кімната в гуртожитку", 5000, "🛏", "real_estate"),
            ("Гараж на Троєщині", 10000, "🏚", "real_estate"),
            ("Смарт-квартира (20м²)", 30000, "🏢", "real_estate"),
            ("Квартира в Києві", 80000, "🏢", "real_estate"),
            ("Будинок під містом", 150000, "🏡", "real_estate"),
            ("Пентхаус Прамс", 500000, "🌇", "real_estate"),
            ("Вілла в Іспанії", 1500000, "🏖", "real_estate"),
            ("Власний Хмарочос", 10000000, "🏙", "real_estate"),
            ("Приватний Острів", 50000000, "🏝", "real_estate"),
        ]

        # --- ДОДАВАННЯ АКЦІЙ ---
        existing_tickers_result = await session.execute(select(Meme.ticker))
        existing_tickers = existing_tickers_result.scalars().all()
        
        added_count = 0
        for ticker, price, volatility, img_url in target_memes:
            if ticker not in existing_tickers:
                new_meme = Meme(
                    ticker=ticker, 
                    current_price=price, 
                    volatility=volatility, 
                    image_url=img_url
                )
                session.add(new_meme)
                added_count += 1
        
        # --- ДОДАВАННЯ ТОВАРІВ ---
        existing_items = (await session.execute(select(Item.name))).scalars().all()
        
        count_items = 0
        for name, price, emoji, category in shop_data:
            if name not in existing_items:
                session.add(Item(name=name, price=price, emoji=emoji, category=category))
                count_items += 1
        
        if added_count > 0 or count_items > 0:
            await session.commit()
            logging.info(f"✅ Оновлення бази: Акцій: {added_count}, Товарів: {count_items}")
        else:
            logging.info("👌 База актуальна.")

    # --- БУРГЕР МЕНЮ ---
    commands = [
        BotCommand(command="start", description="🔄 Головна"),
        BotCommand(command="profile", description="👤 Профіль і Ранг"),
        BotCommand(command="market", description="📈 Ринок"),
        BotCommand(command="news", description="📰 Новини"),
        BotCommand(command="portfolio", description="💼 Портфель"),
        BotCommand(command="leaderboard", description="🏆 Рейтинг"),
        BotCommand(command="daily", description="🎁 Щоденний бонус"),
        BotCommand(command="shop", description="🛒 Магазин"),
        BotCommand(command="bank", description="🏦 Банк"),
        BotCommand(command="send", description="💸 Відправити гроші"),
        BotCommand(command="bet", description="🎲 Ставки на рух цін"),
        BotCommand(command="margin", description="🎰 Маржинальна торгівля"),
        BotCommand(command="ipo", description="🚀 Нові IPO"),
        BotCommand(command="help", description="ℹ️ Допомога"),
        BotCommand(command="collection", description="🎴 Колекція карт"),
        BotCommand(command="invite", description="🤝 Запросити друзів"),
        # --- НОВІ КОМАНДИ ---
        BotCommand(command="clan", description="🏢 Мій Клан"),
        BotCommand(command="topclans", description="🏆 Рейтинг Кланів"),
        BotCommand(command="services", description="🛠 Послуги та створення клану"),
        # --------------------
    ]
    
    await bot_instance.set_my_commands(commands, scope=BotCommandScopeDefault())
    logging.info("✅ Команди встановлено")

async def main():
    global bot
    
    # 1. Запускаємо веб-сервер
    await start_web_server()

    # 2. Запускаємо бота
    bot = Bot(token=Config.BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    
    # 3. Scheduler
    scheduler = AsyncIOScheduler(timezone="UTC")
    
    # --- ОСНОВНИЙ ЦИКЛ ОНОВЛЕННЯ ЦІН ---
    # (Викликається 1 раз, передаємо bot для сповіщень про Margin Call)
    scheduler.add_job(update_prices, "interval", seconds=60, args=[bot]) 
    
    scheduler.add_job(check_bets, "interval", seconds=10, args=[bot])
    scheduler.add_job(run_lottery, "cron", hour=12, minute=0, args=[bot])
    scheduler.add_job(check_money_supply, "interval", hours=6, args=[bot])
    scheduler.add_job(process_bank_interest, "cron", hour=0, minute=0, args=[bot])
    scheduler.add_job(start_tycoon_battle, "cron", hour=18, minute=0, args=[bot, scheduler])
    scheduler.add_job(process_ipos, "interval", seconds=60, args=[bot])
    
    scheduler.start()
    logging.info("⏰ Scheduler запущено")
    
    # 4. Ініціалізація
    await on_startup(bot)
    
    # 5. Polling
    logging.info("🤖 Bot started polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Bot stopped!")