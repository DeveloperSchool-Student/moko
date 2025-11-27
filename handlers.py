from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from numpy import quantile
from sqlalchemy import delete, update
from sqlalchemy import select, desc
from database import async_session
from mechanics import get_meme_chart
from config import IsAdmin, ADMIN_IDS, Config
import re
import asyncio
import random
from mechanics import d # наша утиліта
from models import IPO, IPOApplication
from decimal import Decimal
from datetime import datetime, timedelta
from models import PriceHistory, User, Meme, Portfolio, PromoCode, UsedPromo, News, Item, UserItem, Bet, Clan, LotteryTicket
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func
from models import TycoonBattle, PlayerBet, Portfolio
# На початку файлу додати:
from collection import (
    get_user_collection, 
    mark_cards_as_seen, 
    get_collection_stats,
    try_drop_card,
    RARITY_CONFIG
)

router = Router()

ITEMS_PER_PAGE = 5

# --- 10 РАНГІВ ПРОГРЕСУ ---
def calculate_rank(net_worth):
    if net_worth < 500: return "🦠 Планктон"
    if net_worth < 1500: return "🔰 Барон"
    if net_worth < 3000: return "⚔️ Віконт"
    if net_worth < 5000: return "🎖 Граф"
    if net_worth < 10000: return "👑 Маркіз"
    if net_worth < 25000: return "🏰 Герцог"
    if net_worth < 50000: return "👑 Король"
    if net_worth < 100000: return "🐙 Кракен"
    if net_worth < 500000: return "🗽 Вовк з Уолл-стріт"
    return "🚀 Імператор"

# --- ДОПОМІЖНІ ФУНКЦІЇ ---
async def get_user(session, telegram_id):
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()

async def get_net_worth(session, user):
    pf_items = await session.execute(select(Portfolio).where(Portfolio.user_id == user.id))
    items = pf_items.scalars().all()
    stock_value = 0
    for item in items:
        meme = await session.get(Meme, item.meme_id)
        if meme:
            stock_value += item.quantity * float(meme.current_price)
    return float(user.balance) + stock_value

# --- ОБРОБНИКИ ---

# --- ЗАМІНИ ЦІ ФУНКЦІЇ В handlers.py ---

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    args = message.text.split()
    referrer_candidate = None
    
    if len(args) > 1 and args[1].isdigit():
        referrer_candidate = int(args[1])

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        
        if not user:
            # Реєстрація нового гравця
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                referrer_id=referrer_candidate if referrer_candidate != message.from_user.id else None
            )
            session.add(user)
            # 500 вже є дефолтним у моделі, але для ясності:
            start_text = "🚀 <b>Ласкаво просимо на Meme Stock Exchange!</b>\n\nТвій старт: <b>$500</b>.\n"

            if referrer_candidate and referrer_candidate != message.from_user.id:
                referrer_user = (await session.execute(
                    select(User).where(User.telegram_id == referrer_candidate)
                )).scalar_one_or_none()
                
                if referrer_user:
                    reward = Decimal("500.0")  # FIX: Decimal
                    user.balance += reward
                    referrer_user.balance += reward
                    
                    start_text += f"🎁 Ти перейшов за посиланням друга! Отримано бонус: <b>+${reward}</b>\n"
                    try:
                        await message.bot.send_message(referrer_user.telegram_id, f"🤝 <b>Новий реферал!</b>\nТвій бонус: <b>+${reward}</b>", parse_mode="HTML")
                    except: pass

            await session.commit()
            await message.answer(start_text + "\nТисни /help щоб дізнатись правила.", parse_mode="HTML")
        else:
            if user.username != message.from_user.username:
                user.username = message.from_user.username
                await session.commit()
            await message.answer(f"👋 З поверненням! Твій кеш: ${user.balance:,.2f}")

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        "📖 <b>Як грати?</b>\n\n"
        "1. <b>Ринок живий:</b> Ціни змінюються кожні 60 секунд автоматично (+ на ринок впливають гравці)\n"
        "2. <b>Ціль:</b> Купуй дешево, продавай дорого.\n"
        "3. <b>Ранги:</b> Збільшуй капітал, щоб пройти шлях від Планктона до Імператора.\n\n"
        "<b>Команди:</b>\n"
        "/market - Купити/Продати акції\n"
        "/portfolio - Твої активи\n"
        "/send - Відправити гроші іншому гравцю\n"
        "/bet - Ставки на рух цін\n"
        "/profile - Твій ранг і статистика\n"
        "/leaderboard - Рейтинг гравців\n"
        "/daily - Щоденний бонус\n"
        "/news - Останні новини біржі\n"
        "/shop - Магазин розкоші\n"
        "/bank - Банківські послуги\n"
        "/services - Додаткові послуги\n"
        "/invite - Запросити друзів\n"
        "/fake - Запустити фейкову новину ($100k)\n"
        "/collection - Твоя колекція карт\n"
        "/help - Ця довідка\n\n"
        "Успіхів на біржі! 💰📈\n"
        "Зв'язатися з підтримкою: @hedgehogMSM"
    )
    await message.answer(text, parse_mode="HTML")

# --- РИНОК ---

async def generate_market_keyboard(page: int, user_id: int):
    async with async_session() as session:
        total_memes = (await session.execute(select(Meme))).scalars().all()
        total_pages = (len(total_memes) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        
        offset = page * ITEMS_PER_PAGE
        memes_query = select(Meme).limit(ITEMS_PER_PAGE).offset(offset)
        memes = (await session.execute(memes_query)).scalars().all()

        kb = []
        row = []
        for meme in memes:
            btn_text = f"{meme.ticker} ${float(meme.current_price):.2f}"
            row.append(InlineKeyboardButton(text=btn_text, callback_data=f"view_{meme.id}"))
            if len(row) == 2:
                kb.append(row)
                row = []
        if row: 
            kb.append(row)

        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"market_page_{page-1}_{user_id}"))
        
        nav_row.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data=f"market_ignore_{user_id}"))
        
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"market_page_{page+1}_{user_id}"))
            
        kb.append(nav_row)
        return InlineKeyboardMarkup(inline_keyboard=kb)

@router.message(Command("news"))
async def cmd_news(message: types.Message):
    async with async_session() as session:
        query = select(News).order_by(News.timestamp.desc()).limit(5)
        result = await session.execute(query)
        news_list = result.scalars().all()
        
        if not news_list:
            return await message.answer("📭 На ринку поки що тихо... Новин немає.")
        
        text = "📰 <b>Свіжі Новини Біржі</b>\n────────────────\n\n"
        
        for news in news_list:
            time_str = news.timestamp.strftime("%H:%M")
            text += f"🕒 <b>{time_str}</b> | {news.content}\n\n"
            
        await message.answer(text, parse_mode="HTML")

@router.message(Command("market"))
async def cmd_market(message: types.Message):
    kb = await generate_market_keyboard(0, message.from_user.id)
    await message.answer("📈 <b>Ринок Акцій</b>\nОбирай актив:", reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("market_page_"))
async def cb_market_page(callback: types.CallbackQuery):
    _, _, page_str, original_user_id_str = callback.data.split("_")
    page = int(page_str)
    original_user_id = int(original_user_id_str)

    if callback.from_user.id != original_user_id:
        return await callback.answer("🚫 Це не твій ринок. Тисни /market", show_alert=True)

    kb = await generate_market_keyboard(page, original_user_id)
    
    if callback.message.content_type == types.ContentType.PHOTO:
        await callback.message.delete()
        await callback.message.answer("📈 <b>Ринок Акцій</b>\nОбирай актив:", reply_markup=kb, parse_mode="HTML")
    else:
        try:
            await callback.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            await callback.answer()

@router.callback_query(F.data.startswith("market_ignore_"))
async def cb_market_ignore(callback: types.CallbackQuery):
    original_user_id = int(callback.data.split("_")[2])
    if callback.from_user.id != original_user_id:
        return await callback.answer("🚫 Це не твій ринок. Тисни /market", show_alert=True)
    await callback.answer("Це номер сторінки")

# --- ДЕТАЛІ ТА ТОРГІВЛЯ ---

@router.callback_query(F.data.startswith("view_"))
async def cb_view_meme(callback: types.CallbackQuery):
    meme_id = int(callback.data.split("_")[1])
    telegram_id = callback.from_user.id
    
    async with async_session() as session:
        meme = await session.get(Meme, meme_id)
        if not meme: 
            return await callback.answer("Акція зникла", show_alert=True)
        
        user = await get_user(session, telegram_id)
        
        if not user:
            return await callback.answer("⚠️ Спочатку натисни /start", show_alert=True)

        pf_item = (await session.execute(
            select(Portfolio).where(Portfolio.user_id==user.id, Portfolio.meme_id==meme.id)
        )).scalar_one_or_none()

        user_quantity = pf_item.quantity if pf_item else 0

        supply_percent = 0
        if meme.total_supply > 0:
            supply_percent = (meme.available_supply / meme.total_supply) * 100

        text = (
            f"📊 <b>{meme.ticker}</b>\n"
            f"Ціна: <b>${float(meme.current_price):.4f}</b>\n"
            f"Волатильність: {float(meme.volatility)*100:.0f}% (Ризик)\n"
            f"📦 Доступно: <b>{meme.available_supply:,}</b> шт ({supply_percent:.1f}%)\n"
            f"💼 Твої акції: <b>{user_quantity} шт</b>"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 Купити", callback_data=f"prompt_buy_{meme.id}_{telegram_id}"),
                InlineKeyboardButton(text="🔴 Продати", callback_data=f"prompt_sell_{meme.id}_{telegram_id}")
            ],
            [InlineKeyboardButton(text="📉 Графік", callback_data=f"chart_{meme.id}_{meme.ticker}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"market_page_0_{telegram_id}")]
        ])
        
        try:
            await callback.message.delete()
        except:
            pass

        if meme.image_url:
            await callback.message.answer_photo(photo=meme.image_url, caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")

# --- НОВІ ОБРОБНИКИ ДЛЯ ВИБОРУ КІЛЬКОСТІ ---

@router.callback_query(F.data.startswith("prompt_buy_"))
async def cb_prompt_buy(callback: types.CallbackQuery):
    _, _, meme_id_str, original_user_id_str = callback.data.split("_")
    meme_id = int(meme_id_str)
    original_user_id = int(original_user_id_str)
    
    if callback.from_user.id != original_user_id:
        return await callback.answer("🚫 Ця дія не для тебе. Тисни /market", show_alert=True)
    
    async with async_session() as session:
        user = await get_user(session, original_user_id)
        meme = await session.get(Meme, meme_id)

        if not user or not meme: 
            return await callback.answer("Сталася помилка.", show_alert=True)

        price = float(meme.current_price) if float(meme.current_price) > 0 else 0.01
        
        raw_max_buy = int(float(user.balance) // price)
        
        SAFE_LIMIT = 1_000_000_000
        max_buy = min(raw_max_buy, SAFE_LIMIT)
        
        if max_buy < 1:
            return await callback.answer(
                f"❌ Недостатньо коштів.\nПотрібно: ${price:.2f}\nТвій баланс: ${float(user.balance):.2f}", 
                show_alert=True
            )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="1 шт", callback_data=f"buy_EXECUTE_{meme.id}_1_{original_user_id}"),
                InlineKeyboardButton(text="5 шт", callback_data=f"buy_EXECUTE_{meme.id}_5_{original_user_id}"),
                InlineKeyboardButton(text="10 шт", callback_data=f"buy_EXECUTE_{meme.id}_10_{original_user_id}"),
            ],
            [
                InlineKeyboardButton(text=f"MAX ({max_buy} шт)", callback_data=f"buy_EXECUTE_{meme.id}_{max_buy}_{original_user_id}"),
            ],
            [
                InlineKeyboardButton(text="🔙 Скасувати", callback_data=f"view_{meme.id}")
            ]
        ])
        
        text = (
            f"🛒 <b>Купити {meme.ticker}</b> (Ціна: ${float(meme.current_price):.4f})\n"
            f"Баланс: ${float(user.balance):.2f}\n\n"
            f"Скільки ти хочеш купити? (Максимум {max_buy} шт)"
        )

        await callback.message.delete()
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("prompt_sell_"))
async def cb_prompt_sell(callback: types.CallbackQuery):
    _, _, meme_id_str, original_user_id_str = callback.data.split("_")
    meme_id = int(meme_id_str)
    original_user_id = int(original_user_id_str)
    
    if callback.from_user.id != original_user_id:
        return await callback.answer("🚫 Ця дія не для тебе. Тисни /market", show_alert=True)
    
    async with async_session() as session:
        user = await get_user(session, original_user_id)
        meme = await session.get(Meme, meme_id)

        pf_item = (await session.execute(
            select(Portfolio).where(Portfolio.user_id==user.id, Portfolio.meme_id==meme.id)
        )).scalar_one_or_none()
        
        user_quantity = pf_item.quantity if pf_item else 0
        
        if user_quantity < 1:
            return await callback.answer(f"❌ У тебе немає акцій {meme.ticker} для продажу.", show_alert=True)

        current_com = Config.SELL_COMMISSION_BROKER if user.has_license else Config.SELL_COMMISSION_DEFAULT
        com_percent = current_com * 100

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="1 шт", callback_data=f"sell_EXECUTE_{meme.id}_1_{original_user_id}"),
                InlineKeyboardButton(text="5 шт", callback_data=f"sell_EXECUTE_{meme.id}_5_{original_user_id}"),
                InlineKeyboardButton(text="10 шт", callback_data=f"sell_EXECUTE_{meme.id}_10_{original_user_id}"),
            ],
            [
                InlineKeyboardButton(text=f"ВСЕ ({user_quantity} шт)", callback_data=f"sell_EXECUTE_{meme.id}_{user_quantity}_{original_user_id}"),
            ],
            [
                InlineKeyboardButton(text="🔙 Скасувати", callback_data=f"view_{meme.id}")
            ]
        ])
        
        text = (
            f"💸 <b>Продати {meme.ticker}</b>\n"
            f"Ціна ринку: ${float(meme.current_price):.4f}\n"
            f"📉 <b>Комісія біржі: {com_percent:.0f}%</b>\n\n"
            f"Твої акції: <b>{user_quantity} шт</b>\n"
            f"Скільки продаємо?"
        )

        await callback.message.delete()
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")

# Продовжується у частині 2...
# Продовження handlers.py - частина 2

# --- У cb_execute_buy (знайди та заміни функцію повністю) ---
@router.callback_query(F.data.startswith("buy_EXECUTE_"))
async def cb_execute_buy(callback: types.CallbackQuery):
    _, _, meme_id_str, quantity_str, original_user_id_str = callback.data.split("_")
    meme_id = int(meme_id_str)
    quantity = int(quantity_str) # <--- Ось правильна змінна
    original_user_id = int(original_user_id_str)

    if callback.from_user.id != original_user_id:
        return await callback.answer("🚫 Ця дія не для тебе.", show_alert=True)
    
    async with async_session() as session:
        user = await get_user(session, original_user_id)
        meme = await session.get(Meme, meme_id)
        
        # Перевірка наявності
        if meme.available_supply < quantity: # Використовуємо quantity
             return await callback.answer(
                f"❌ Дефіцит! Доступно лише {meme.available_supply} шт.", 
                show_alert=True
            )

        total_cost = float(meme.current_price) * quantity # Використовуємо quantity

        if float(user.balance) < total_cost:
            return await callback.answer("❌ Не вистачає коштів!", show_alert=True)

        user.balance = float(user.balance) - total_cost
        
        # Зменшуємо пропозицію
        meme.available_supply -= quantity # Використовуємо quantity
        
        pf_item = (await session.execute(
            select(Portfolio).where(Portfolio.user_id==user.id, Portfolio.meme_id==meme.id)
        )).scalar_one_or_none()
        
        if pf_item: 
            pf_item.quantity += quantity # Використовуємо quantity
        else: 
            session.add(Portfolio(user_id=user.id, meme_id=meme.id, quantity=quantity)) # Використовуємо quantity
        
        meme.trade_volume += quantity # Використовуємо quantity
        
        # Перевіряємо дроп колекційної карти
        await try_drop_card(user.id, meme.id, callback.bot)
    
        await session.commit()
        await callback.answer(f"✅ +{quantity} {meme.ticker}. Залишилось на ринку: {meme.available_supply}")
        
        new_callback = callback.model_copy(update={"data": f"view_{meme.id}"})
        await cb_view_meme(new_callback)

@router.callback_query(F.data.startswith("sell_EXECUTE_"))
async def cb_execute_sell(callback: types.CallbackQuery):
    _, _, meme_id_str, quantity_str, original_user_id_str = callback.data.split("_")
    meme_id = int(meme_id_str)
    quantity = int(quantity_str)
    original_user_id = int(original_user_id_str)

    if callback.from_user.id != original_user_id:
        return await callback.answer("🚫 Ця дія не для тебе.", show_alert=True)

    async with async_session() as session:
        user = await get_user(session, original_user_id)
        meme = await session.get(Meme, meme_id)
        
        pf_item = (await session.execute(
            select(Portfolio).where(Portfolio.user_id == user.id, Portfolio.meme_id == meme.id)
        )).scalar_one_or_none()

        if not pf_item:
            return await callback.answer("❌ Акцій вже немає.", show_alert=True)

        amount_to_sell = min(quantity, pf_item.quantity)

        current_commission_rate = Config.SELL_COMMISSION_BROKER if user.has_license else Config.SELL_COMMISSION_DEFAULT
        
        # Шукай функцію: async def cb_execute_sell(...)
        # ... всередині блоку async with async_session() as session:

        gross_total = float(meme.current_price) * amount_to_sell
        commission = gross_total * current_commission_rate
        net_income = gross_total - commission
        
        # 👇 ЗАМІНИТИ ЦЕЙ РЯДОК
        user.balance = float(user.balance) + net_income
        
        pf_item.quantity -= amount_to_sell
        if pf_item.quantity == 0:
            await session.delete(pf_item)
            
        # --- ПОВЕРТАЄМО АКЦІЇ НА РИНОК ---
        meme.available_supply += amount_to_sell
        # Опціонально: перевіряємо, щоб не перевищити total_supply (хоча це рідко можливо)
        if meme.available_supply > meme.total_supply:
            meme.available_supply = meme.total_supply
        # ---------------------------------
        
        meme.trade_volume -= amount_to_sell
        
        await session.commit()
        
        status_icon = "📜" if user.has_license else ""
        
        await callback.answer(
            f"💵 Продано {amount_to_sell} {meme.ticker} {status_icon}\n"
            f"Отримано: ${net_income:.2f}\n"
            f"Комісія: ${commission:.2f} ({current_commission_rate*100:.0f}%)",
            show_alert=True
        )
        
        new_callback = callback.model_copy(update={"data": f"view_{meme.id}"})
        await cb_view_meme(new_callback)

@router.callback_query(F.data.startswith("chart_"))
async def cb_chart(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    meme_id = int(parts[1])
    ticker = parts[2]
    
    # Відправляємо "action", щоб користувач бачив, що бот думає
    await callback.bot.send_chat_action(chat_id=callback.from_user.id, action="upload_photo")
    
    chart_buf = await get_meme_chart(meme_id, ticker)
    
    if chart_buf:
        # FIX: Використовуємо getvalue()
        photo = BufferedInputFile(chart_buf.getvalue(), filename=f"{ticker}.png")
        await callback.message.answer_photo(photo, caption=f"Графік {ticker}")
        await callback.answer() # Закриваємо годинник на кнопці
    else:
        await callback.answer("Дані ще збираються... Спробуй через хвилину.", show_alert=True)

@router.message(Command("portfolio"))
async def cmd_portfolio(message: types.Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user: 
            return await message.answer("⚠️ Натисни /start")
        
        pf_items = (await session.execute(
            select(Portfolio).where(Portfolio.user_id == user.id)
        )).scalars().all()
        
        text = f"💼 <b>Портфель</b> | Кеш: ${float(user.balance):.2f}\n\n"
        total = float(user.balance)
        
        for item in pf_items:
            meme = await session.get(Meme, item.meme_id)
            if meme:
                val = item.quantity * float(meme.current_price)
                total += val
                text += f"🔹 <b>{meme.ticker}</b>: {item.quantity} шт (${val:.2f})\n"
        
        text += f"\n💰 Разом: <b>${total:.2f}</b>"
        await message.answer(text, parse_mode="HTML")

@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: types.Message):
    async with async_session() as session:
        users = (await session.execute(
            select(User).order_by(desc(User.balance)).limit(10)
        )).scalars().all()
        
        text = "🏆 <b>ТОП Гравців</b>\n\n"
        
        for i, u in enumerate(users, 1):
            if u.username:
                name = f"@{u.username}"
            elif u.full_name:
                name = u.full_name
            else:
                name = f"ID {u.telegram_id}"
            
            medal = ""
            if i == 1: medal = "🥇"
            elif i == 2: medal = "🥈"
            elif i == 3: medal = "🥉"
            
            text += f"{i}. {medal} <b>{name}</b>: ${float(u.balance):.2f}\n"
            
        await message.answer(text, parse_mode="HTML")

@router.message(Command("daily"))
async def cmd_daily(message: types.Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user: return await message.answer("⚠️ Натисни /start")

        now = datetime.utcnow()
        if user.last_bonus_date:
            delta = now - user.last_bonus_date
            if delta < timedelta(days=1):
                wait_time = timedelta(days=1) - delta
                hours, remainder = divmod(int(wait_time.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                return await message.answer(f"⏳ <b>Рано!</b> Чекай ще: <b>{hours} год {minutes} хв</b>", parse_mode="HTML")

        bonus_amount = Decimal(random.randint(100, 500)) # FIX: Decimal
        user.balance += bonus_amount
        user.last_bonus_date = now
        
        await session.commit()
        await message.answer(f"🎁 <b>Щоденний бонус!</b>\nТи отримав: <b>${bonus_amount}</b>\nПоточний баланс: <b>${user.balance:,.2f}</b>", parse_mode="HTML")

# --- ПРОМОКОДИ ---

@router.message(Command("newcode"), IsAdmin())
async def cmd_create_promo(message: types.Message):
    try:
        parts = message.text.split()
        if len(parts) != 4:
            raise ValueError
        
        code_name = parts[1].upper()
        amount = float(parts[2])
        minutes = int(parts[3])
        
        valid_until = datetime.utcnow() + timedelta(minutes=minutes)
        
    except ValueError:
        return await message.answer(
            "❌ Формат: <code>/newcode НАЗВА СУМА ХВИЛИНИ</code>\n"
            "Приклад: /newcode GAME 500 60", 
            parse_mode="HTML"
        )

    async with async_session() as session:
        existing = await session.execute(
            select(PromoCode).where(PromoCode.code == code_name)
        )
        if existing.scalar_one_or_none():
            return await message.answer("❌ Такий код вже існує!")

        new_promo = PromoCode(code=code_name, amount=amount, valid_until=valid_until)
        session.add(new_promo)
        await session.commit()
        
        await message.answer(
            f"✅ <b>Промокод створено!</b>\n\n"
            f"🔑 Код: <code>{code_name}</code>\n"
            f"💰 Сума: ${amount}\n"
            f"⏳ Дія: {minutes} хв (до {valid_until.strftime('%H:%M UTC')})",
            parse_mode="HTML"
        )

@router.message(Command("use"))
async def cmd_use_promo(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer(
            "✏️ Введи код. Приклад: <code>/use GAME</code>", 
            parse_mode="HTML"
        )
    
    code_input = parts[1].upper().strip()
    
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user: 
            return await message.answer("⚠️ Спочатку тисни /start")
        
        promo = (await session.execute(
            select(PromoCode).where(PromoCode.code == code_input)
        )).scalar_one_or_none()
        
        if not promo:
            return await message.answer("❌ Такого коду не існує.")
            
        if datetime.utcnow() > promo.valid_until:
            return await message.answer(
                "⏰️ <b>Термін дії коду вийшов!</b> Ти не встиг.", 
                parse_mode="HTML"
            )
        
        used_check = await session.execute(
            select(UsedPromo).where(
                UsedPromo.user_id == user.id, 
                UsedPromo.promo_id == promo.id
            )
        )
        if used_check.scalar_one_or_none():
            return await message.answer("❌ Ти вже активував цей код.")
            
        # 👇 FIX: Конфлікт Decimal += float
        user.balance = float(user.balance) + float(promo.amount)
        
        usage_record = UsedPromo(user_id=user.id, promo_id=promo.id)
        session.add(usage_record)
        
        await session.commit()
        
        await message.answer(
            f"🎉 <b>Успіх!</b>\nТи отримав <b>${promo.amount}</b>!\n"
            f"Баланс: ${float(user.balance):.2f}", 
            parse_mode="HTML"
        )

@router.message(Command("send"))
async def cmd_send(message: types.Message):
    args = message.text.split()
    if len(args) != 3: return await message.answer("💸 Приклад: <code>/send 500 @friend</code>", parse_mode="HTML")

    try:
        amount = Decimal(args[1]) # FIX: Decimal
        target_input = args[2]
    except: return await message.answer("❌ Сума має бути числом.")

    if amount <= 0: return await message.answer("❌ Сума > 0.")

    async with async_session() as session:
        sender = await get_user(session, message.from_user.id)
        if not sender: return await message.answer("⚠️ Тисни /start")

        if sender.balance < amount: return await message.answer("❌ Недостатньо коштів.")

        recipient = None
        if target_input.startswith("@"):
            recipient = (await session.execute(select(User).where(User.username == target_input[1:]))).scalar_one_or_none()
        elif target_input.isdigit():
            recipient = (await session.execute(select(User).where(User.telegram_id == int(target_input)))).scalar_one_or_none()

        if not recipient: return await message.answer("❌ Користувача не знайдено.")
        if recipient.id == sender.id: return await message.answer("❌ Собі не можна.")

        sender.balance -= amount
        recipient.balance += amount
        
        await session.commit()
        await message.answer(f"✅ Відправлено <b>${amount}</b> користувачу {recipient.full_name}", parse_mode="HTML")
        try:
            await message.bot.send_message(recipient.telegram_id, f"💸 Вам надійшло: <b>${amount}</b> від {sender.full_name}", parse_mode="HTML")
        except: pass

@router.message(Command("privacy"))
async def cmd_privacy(message: types.Message):
    text = (
        "🔒 <b>Політика конфіденційності та Умови використання</b>\n\n"
        
        "<b>1. Збір даних</b>\n"
        "Ми зберігаємо лише необхідний мінімум даних для функціонування гри:\n"
        "• Ваш Telegram ID (для ідентифікації акаунту).\n"
        "• Ваше Ім'я та Username (для відображення в рейтингах).\n"
        "• Ігрову статистику (баланс, портфель акцій).\n\n"
        
        "<b>2. Використання даних</b>\n"
        "Ваші дані використовуються виключно для забезпечення ігрового процесу. "
        "Ми не передаємо їх третім особам і не використовуємо для реклами.\n\n"
        
        "<b>3. ВІДМОВА ВІД ВІДПОВІДАЛЬНОСТІ (ВАЖЛИВО)</b>\n"
        "⚠️ <b>Цей бот є ГРО-СИМУЛЯТОРОМ.</b>\n"
        "• Всі гроші в боті ($) є <b>віртуальними</b> і не мають жодної реальної цінності.\n"
        "• Їх неможливо вивести, обміняти на реальні гроші або товари.\n"
        "• Гра не є фінансовою порадою, біржею або платформою для азартних ігор.\n"
        "• Адміністрація не несе відповідальності за ваші віртуальні збитки.\n\n"
        
        "<b>4. Видалення даних</b>\n"
        "Якщо ви хочете видалити свій акаунт і всі дані про себе, будь ласка, зв'яжіться з адміністратором.\n\n"
        
        "<i>Використовуючи цього бота, ви автоматично погоджуєтесь із цими правилами.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Згорнути", callback_data="delete_msg")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@router.callback_query(F.data == "delete_msg")
async def cb_delete_msg(callback: types.CallbackQuery):
    await callback.message.delete()

# Продовжується у частині 3...
# Продовження handlers.py - частина 3

# --- СТАВКИ ---

@router.message(Command("bet"))
async def cmd_bet(message: types.Message):
    args = message.text.split()
    if len(args) != 4:
        return await message.answer("🎰 Приклад: <code>/bet BTC UP 100</code>", parse_mode="HTML")

    ticker_input = args[1].upper()
    direction_input = args[2].upper()
    try:
        amount = Decimal(args[3]) # FIX: Decimal
    except:
        return await message.answer("❌ Сума має бути числом.")

    if direction_input not in ["UP", "DOWN"]:
        return await message.answer("❌ Напрямок: UP або DOWN.")
    if amount <= 0: 
        return await message.answer("❌ Ставка має бути більше 0.")

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user: return await message.answer("⚠️ Тисни /start")
        
        if user.balance < amount:
            return await message.answer(f"❌ Недостатньо коштів. Баланс: ${user.balance:,.2f}")

        meme = (await session.execute(select(Meme).where(Meme.ticker == ticker_input))).scalar_one_or_none()
        if not meme: return await message.answer(f"❌ Акцію {ticker_input} не знайдено.")

        user.balance -= amount # FIX: Direct subtraction
        
        end_time = datetime.utcnow() + timedelta(seconds=Config.BET_DURATION)
        new_bet = Bet(
            user_id=user.id,
            meme_id=meme.id,
            amount=amount,
            direction=direction_input,
            start_price=meme.current_price,
            end_time=end_time
        )
        session.add(new_bet)
        await session.commit()
        
        await message.answer(f"🎲 <b>Ставку прийнято!</b>\nСума: <b>${amount}</b> на {direction_input}", parse_mode="HTML")

# --- БАНК ---

@router.message(Command("bank"))
async def cmd_bank(message: types.Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return await message.answer("⚠️ Натисни /start")
        
        text = (
            f"🏦 <b>Банк</b>\n\n"
            f"💵 Твій баланс: <b>${float(user.balance):.2f}</b>\n"
            f"🏦 На рахунку: <b>${float(user.bank_balance):.2f}</b>\n"
            f"📈 Відсоток: <b>{Config.BANK_INTEREST_RATE*100:.1f}%</b> річних\n\n"
        )
        
        if user.deposit_amount > 0 and user.deposit_end_date:
            days_left = (user.deposit_end_date - datetime.utcnow()).days
            text += (
                f"💎 <b>Депозит активний</b>\n"
                f"Сума: ${float(user.deposit_amount):.2f}\n"
                f"Залишилось: {days_left} днів\n"
                f"Відсоток: {Config.DEPOSIT_INTEREST_RATE*100:.0f}%\n\n"
            )
        
        text += (
            "<b>Команди:</b>\n"
            "/deposit [СУМА] [ДНІ] - Відкрити депозит\n"
            "/withdraw [СУМА] - Зняти з рахунку\n"
            "/transfer [СУМА] - Поповнити рахунок"
        )
        
        await message.answer(text, parse_mode="HTML")

@router.message(Command("deposit"))
async def cmd_deposit(message: types.Message):
    args = message.text.split()
    if len(args) != 3: return await message.answer("📈 Приклад: /deposit 1000 30", parse_mode="HTML")
    
    try:
        amount = Decimal(args[1]) # FIX
        days = int(args[2])
    except: return await message.answer("❌ Некоректні дані.")
    
    if amount < Decimal(Config.DEPOSIT_MIN): return await message.answer(f"❌ Мінімум ${Config.DEPOSIT_MIN}")
    
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if user.deposit_amount > 0: return await message.answer("❌ Вже є активний депозит.")
        if user.balance < amount: return await message.answer("❌ Немає грошей.")
        
        user.balance -= amount
        user.deposit_amount += amount
        user.deposit_end_date = datetime.utcnow() + timedelta(days=days)
        
        await session.commit()
        await message.answer(f"✅ Депозит ${amount} на {days} днів відкрито!")

@router.message(Command("withdraw"))
async def cmd_withdraw(message: types.Message):
    args = message.text.split()
    try:
        amount = Decimal(args[1]) # FIX
    except: return await message.answer("❌ Число?")
    
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if user.bank_balance < amount: return await message.answer("❌ Немає стільки в банку.")
        
        user.bank_balance -= amount
        user.balance += amount
        await session.commit()
        await message.answer(f"✅ Знято: ${amount}. Баланс: ${user.balance}")

@router.message(Command("transfer"))
async def cmd_transfer_to_bank(message: types.Message):
    args = message.text.split()
    if len(args) != 2:
        return await message.answer(
            "🏦 Формат: <code>/transfer СУМА</code>\nПриклад: /transfer 5000",
            parse_mode="HTML"
        )
    
    try:
        amount = float(args[1])
    except ValueError:
        return await message.answer("❌ Сума має бути числом.")
    
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return await message.answer("⚠️ Натисни /start")
        
        if float(user.balance) < amount:
            return await message.answer("❌ Недостатньо коштів.")
        
        # 👇 REPLACE THIS BLOCK
        user.balance = float(user.balance) - amount
        user.bank_balance = float(user.bank_balance) + amount
        
        await session.commit()
        
        await message.answer(
            f"✅ Переведено на рахунок: <b>${amount:.2f}</b>\n"
            f"На рахунку: ${float(user.bank_balance):.2f}",
            parse_mode="HTML"
        )

# --- МАГАЗИН ---

@router.message(Command("shop"))
async def cmd_shop(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Нерухомість", callback_data="shop_cat_real_estate_0")],
        [InlineKeyboardButton(text="🚗 Автомобілі", callback_data="shop_cat_auto_0")],
        [InlineKeyboardButton(text="📱 Техніка", callback_data="shop_cat_tech_0")],
    ])
    
    await message.answer(
        "🛒 <b>Магазин Розкоші</b>\n\n"
        "Обери категорію, щоб витратити свої мільйони:", 
        reply_markup=kb, 
        parse_mode="HTML"
    )

async def generate_shop_keyboard(category: str, page: int, user_id: int):
    async with async_session() as session:
        query = select(Item).where(Item.category == category).order_by(Item.price)
        all_items = (await session.execute(query)).scalars().all()
        
        ITEMS_PER_PAGE = 5
        total_pages = (len(all_items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        
        offset = page * ITEMS_PER_PAGE
        items_on_page = all_items[offset : offset + ITEMS_PER_PAGE]
        
        kb = []
        for item in items_on_page:
            btn_text = f"{item.emoji} {item.name} — ${float(item.price):,.0f}"
            kb.append([InlineKeyboardButton(
                text=btn_text, 
                callback_data=f"buy_item_{item.id}_{user_id}"
            )])
            
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(
                text="⬅️", 
                callback_data=f"shop_cat_{category}_{page-1}"
            ))
        
        nav_row.append(InlineKeyboardButton(
            text=f"📄 {page+1}/{total_pages}", 
            callback_data="ignore"
        ))
        
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(
                text="➡️", 
                callback_data=f"shop_cat_{category}_{page+1}"
            ))
            
        kb.append(nav_row)
        kb.append([InlineKeyboardButton(
            text="🔙 В меню магазину", 
            callback_data="shop_menu"
        )])
        
        return InlineKeyboardMarkup(inline_keyboard=kb)

@router.callback_query(F.data == "shop_menu")
async def cb_shop_menu_back(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Нерухомість", callback_data="shop_cat_real_estate_0")],
        [InlineKeyboardButton(text="🚗 Автомобілі", callback_data="shop_cat_auto_0")],
        [InlineKeyboardButton(text="📱 Техніка", callback_data="shop_cat_tech_0")],
    ])
    await callback.message.edit_text(
        "🛒 <b>Магазин Розкоші</b>\nОбери категорію:", 
        reply_markup=kb, 
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("shop_cat_"))
async def cb_shop_category(callback: types.CallbackQuery):
    clean_data = callback.data[9:]
    category, page_str = clean_data.rsplit("_", 1)
    page = int(page_str)
    
    kb = await generate_shop_keyboard(category, page, callback.from_user.id)
    
    cat_names = {
        "real_estate": "🏠 Нерухомість", 
        "auto": "🚗 Автопарк", 
        "tech": "📱 Техніка"
    }
    cat_title = cat_names.get(category, category)
    
    try:
        await callback.message.edit_text(
            f"🛒 <b>{cat_title}</b> (Сторінка {page+1})\nТисни на товар, щоб купити:", 
            reply_markup=kb, 
            parse_mode="HTML"
        )
    except Exception:
        await callback.answer()

@router.callback_query(F.data.startswith("buy_item_"))
async def cb_buy_item(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    item_id = int(parts[2])
    original_user_id = int(parts[3])
    
    if callback.from_user.id != original_user_id:
        return await callback.answer("🚫 Це не твій магазин.", show_alert=True)
    
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        item = await session.get(Item, item_id)
        
        if not item: 
            return await callback.answer("Товар зник.")
        
        has_item = (await session.execute(
            select(UserItem).where(
                UserItem.user_id == user.id, 
                UserItem.item_id == item.id
            )
        )).scalar_one_or_none()
        
        if has_item:
            return await callback.answer(
                f"😎 У тебе вже є {item.name}!", 
                show_alert=True
            )
            
        if float(user.balance) < float(item.price):
            return await callback.answer(
                f"❌ Тобі не вистачає ${float(item.price) - float(user.balance):.2f}", 
                show_alert=True
            )
            
        user.balance = float(user.balance) - float(item.price)
        session.add(UserItem(user_id=user.id, item_id=item.id))
        await session.commit()
        
        await callback.answer(f"✅ Куплено: {item.name}!", show_alert=True)

@router.message(Command("invite"))
async def cmd_invite(message: types.Message):
    bot_username = (await message.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={message.from_user.id}"
    
    text = (
        "🤝 <b>Партнерська програма</b>\n\n"
        "Запрошуй друзів і заробляй легкі гроші!\n"
        "За кожного друга ви <b>ОБИДВА</b> отримаєте по <b>$500</b>.\n\n"
        "👇 <b>Твоє посилання:</b>\n"
        f"<code>{link}</code>\n\n"
        "(Натисни на посилання, щоб скопіювати)"
    )
    await message.answer(text, parse_mode="HTML")

# Продовжується у частині 4...
# Продовження handlers.py - частина 4 (фінал)

# --- ПОСЛУГИ ---

@router.message(Command("services"))
async def cmd_services(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Ліцензія Брокера ($50k)", callback_data="buy_service_license")],
        [InlineKeyboardButton(text="🕵️ VIP Інсайд ($5k/год)", callback_data="buy_service_vip")],
        [InlineKeyboardButton(text="🎫 Лотерея ($500)", callback_data="menu_lottery")],
        [InlineKeyboardButton(text="🏷 Змінити Титул ($10k)", callback_data="buy_service_title")],
        [InlineKeyboardButton(text="🏢 Хедж-Фонди (Клани)", callback_data="menu_clans")]
    ])
    await message.answer("🛠 <b>Додаткові Послуги</b>", reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("buy_service_"))
async def cb_buy_service(callback: types.CallbackQuery):
    service = callback.data.split("_")[2]
    user_id = callback.from_user.id
    
    async with async_session() as session:
        user = await get_user(session, user_id)
        
        if service == "license":
            if user.has_license:
                return await callback.answer("✅ У тебе вже є ліцензія!", show_alert=True)
            if float(user.balance) < Config.LICENSE_COST:
                return await callback.answer("❌ Не вистачає грошей.", show_alert=True)
            
            # 👇 ВИПРАВЛЕНО
            user.balance = float(user.balance) - Config.LICENSE_COST
            user.has_license = True
            await session.commit()
            await callback.answer("✅ Ліцензію придбано! Комісія тепер 1%.", show_alert=True)

        elif service == "vip":
            now = datetime.utcnow()
            if user.vip_until and user.vip_until > now:
                return await callback.answer(
                    f"✅ VIP активний до {user.vip_until.strftime('%H:%M')}", 
                    show_alert=True
                )
            
            if float(user.balance) < Config.VIP_COST:
                return await callback.answer("❌ Не вистачає грошей.", show_alert=True)
            
            # 👇 ВИПРАВЛЕНО
            user.balance = float(user.balance) - Config.VIP_COST
            user.vip_until = now + timedelta(hours=1)
            await session.commit()
            await callback.answer("✅ VIP активовано на 1 годину!", show_alert=True)

        elif service == "title":
            await callback.answer("Введи команду: /settitle ТвійТитул", show_alert=True)

@router.message(Command("settitle"))
async def cmd_set_title(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) != 2:
        return await message.answer(
            f"✏️ Використання: <code>/settitle Імператор</code>\n"
            f"Вартість: ${Config.TITLE_CHANGE_COST}", 
            parse_mode="HTML"
        )
    
    new_title = args[1]
    if len(new_title) > 20: 
        return await message.answer("❌ Занадто довгий титул.")

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if float(user.balance) < Config.TITLE_CHANGE_COST:
            return await message.answer("❌ Недостатньо коштів.")
        
        # 👇 ВИПРАВЛЕНО
        user.balance = float(user.balance) - Config.TITLE_CHANGE_COST
        user.custom_title = new_title
        await session.commit()
        await message.answer(
            f"✅ Титул змінено на: <b>{new_title}</b>", 
            parse_mode="HTML"
        )
@router.message(Command("fake"))
async def cmd_fake_news(message: types.Message):
    """
    Публікація фейкової новини за гроші.
    Використання: /fake "Текст новини"
    """
    # Отримуємо текст після команди
    news_content = message.text.replace("/fake", "", 1).strip()
    
    # Видаляємо лапки, якщо користувач їх ввів
    news_content = news_content.strip('"').strip("'")

    if not news_content or len(news_content) < 5:
        return await message.answer(
            f"🤥 <b>Запустити плітку</b>\n"
            f"Ціна: <b>${Config.FAKE_NEWS_COST:,.0f}</b>\n\n"
            f"Використання: <code>/fake Ілон Маск купує W.D!</code>",
            parse_mode="HTML"
        )

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return await message.answer("⚠️ Спочатку натисни /start")

        if float(user.balance) < Config.FAKE_NEWS_COST:
            return await message.answer(
                f"❌ Недостатньо коштів для підкупу ЗМІ.\n"
                f"Потрібно: ${Config.FAKE_NEWS_COST:,.2f}",
                parse_mode="HTML"
            )

        # Списуємо гроші
        user.balance = float(user.balance) - Config.FAKE_NEWS_COST
        
        # Додаємо новину в базу (без прив'язки до тікера, або загальну)
        # Використовуємо 'MARKET' як умовний тікер для загальних новин
        fake_news = News(
            meme_id=None, # Загальна новина
            ticker="INSIDER",
            content=f"⚠️ {news_content}", 
            change_percent=0.0
        )
        session.add(fake_news)
        await session.commit()

        # Відправляємо повідомлення всім (імітація масової розсилки)
        # Або просто додаємо в стрічку /news, але повідомимо гравця про успіх
        await message.answer(
            f"✅ <b>Плітку запущено!</b>\n"
            f"З рахунку списано ${Config.FAKE_NEWS_COST:,.0f}.\n"
            f"Перевір /news через хвилину.", 
            parse_mode="HTML"
        )
# --- ЛОТЕРЕЯ ---

@router.callback_query(F.data == "menu_lottery")
async def cb_lottery_menu(callback: types.CallbackQuery):
    async with async_session() as session:
        tickets_count = (await session.execute(
            select(func.count(LotteryTicket.id))
        )).scalar()
        pot = tickets_count * Config.LOTTERY_TICKET
        win_amount = pot * 0.8
        
        text = (
            f"🎰 <b>Щоденна Лотерея</b>\n\n"
            f"🎟 Квиток коштує: <b>${Config.LOTTERY_TICKET}</b>\n"
            f"💰 В банку зараз: <b>${pot:.2f}</b>\n"
            f"🏆 Переможець отримає: <b>${win_amount:.2f}</b>\n\n"
            f"Розігрaш раз на добу!"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎟 Купити квиток", callback_data="buy_ticket")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="delete_msg")]
        ])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "buy_ticket")
async def cb_buy_ticket(callback: types.CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        
        if float(user.balance) < Config.LOTTERY_TICKET:
            return await callback.answer("❌ Немає грошей.", show_alert=True)
            
        # 👇 ВИПРАВЛЕНО
        user.balance = float(user.balance) - Config.LOTTERY_TICKET
        session.add(LotteryTicket(user_id=user.id))
        await session.commit()
        
        await callback.answer("✅ Квиток куплено! Удачі!", show_alert=True)

# --- КЛАНИ ---

@router.callback_query(F.data == "menu_clans")
async def cb_clans_menu(callback: types.CallbackQuery):
    text = (
        "🏢 <b>Хедж-Фонди (Клани)</b>\n\n"
        "Створи свій фонд або приєднайся до існуючого!\n"
        f"Вартість реєстрації фонду: <b>${Config.CLAN_CREATION_COST:,.0f}</b>\n\n"
        "Команди:\n"
        "/createclan [НАЗВА] - Створити\n"
        "/joinclan [ID] - Приєднатися\n"
        "/clan - Інформація про твій фонд\n"
        "/topclans - Рейтинг фондів"
    )
    await callback.message.edit_text(text, parse_mode="HTML")

@router.message(Command("createclan"))
async def cmd_create_clan(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) != 2: 
        return await message.answer(
            "✏️ Введи назву. Приклад: `/createclan Wolves`", 
            parse_mode="HTML"
        )
    
    name = args[1]
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        
        if user.clan_id:
            return await message.answer("❌ Ти вже у клані.")
        if float(user.balance) < Config.CLAN_CREATION_COST:
            return await message.answer(f"❌ Потрібно ${Config.CLAN_CREATION_COST:,.0f}")
            
        exists = (await session.execute(
            select(Clan).where(Clan.name == name)
        )).scalar_one_or_none()
        if exists: 
            return await message.answer("❌ Така назва зайнята.")
        
        # 👇 ВИПРАВЛЕНО
        user.balance = float(user.balance) - Config.CLAN_CREATION_COST
        new_clan = Clan(name=name, owner_id=user.id)
        session.add(new_clan)
        await session.flush()
        
        user.clan_id = new_clan.id
        await session.commit()
        
        await message.answer(
            f"✅ Фонд <b>{name}</b> створено! ID: <code>{new_clan.id}</code>", 
            parse_mode="HTML"
        )

@router.message(Command("joinclan"))
async def cmd_join_clan(message: types.Message):
    args = message.text.split()
    if len(args) != 2: 
        return await message.answer(
            "✏️ Введи ID. Приклад: `/joinclan 1`", 
            parse_mode="HTML"
        )
    
    try:
        clan_id = int(args[1])
    except:
        return await message.answer("❌ ID має бути числом.")
        
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        clan = await session.get(Clan, clan_id)
        
        if not clan: 
            return await message.answer("❌ Клан не знайдено.")
        if user.clan_id: 
            return await message.answer("❌ Ти вже у клані.")
        
        user.clan_id = clan.id
        await session.commit()
        await message.answer(
            f"✅ Ти приєднався до <b>{clan.name}</b>!", 
            parse_mode="HTML"
        )

@router.message(Command("clan"))
async def cmd_my_clan(message: types.Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user.clan_id: 
            return await message.answer("⚠️ Ти не в клані.")
        
        clan = await session.get(Clan, user.clan_id)
        
        members = (await session.execute(
            select(User).where(User.clan_id == clan.id)
        )).scalars().all()
        
        total_wealth = 0
        for m in members:
            total_wealth += await get_net_worth(session, m)
            
        text = (
            f"🏢 <b>{clan.name}</b> (ID: {clan.id})\n"
            f"👥 Учасників: {len(members)}\n"
            f"💰 Загальний капітал: <b>${total_wealth:,.2f}</b>\n"
        )
        await message.answer(text, parse_mode="HTML")

@router.message(Command("topclans"))
async def cmd_top_clans(message: types.Message):
    async with async_session() as session:
        clans = (await session.execute(select(Clan))).scalars().all()
        
        clan_data = []
        for clan in clans:
            members = (await session.execute(
                select(User).where(User.clan_id == clan.id)
            )).scalars().all()
            
            total = 0
            for m in members:
                total += await get_net_worth(session, m)
            
            clan_data.append((clan.name, total, len(members)))
        
        clan_data.sort(key=lambda x: x[1], reverse=True)
        
        text = "🏆 <b>ТОП Хедж-Фондів</b>\n\n"
        for i, (name, worth, count) in enumerate(clan_data[:10], 1):
            text += f"{i}. <b>{name}</b>: ${worth:,.2f} ({count} чол.)\n"
        
        await message.answer(text, parse_mode="HTML")

# --- ПРОФІЛЬ ---

@router.message(Command("profile"))
async def cmd_profile(message: types.Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user: 
            return await message.answer("⚠️ Натисни /start")

        net_worth = await get_net_worth(session, user)
        
        if user.custom_title:
            rank = f"✨ {user.custom_title}"
        else:
            rank = calculate_rank(net_worth)

        clan_info = ""
        if user.clan_id:
            clan = await session.get(Clan, user.clan_id)
            if clan: 
                clan_info = f"🏢 Фонд: {clan.name}\n"

        vip_status = ""
        if user.vip_until and user.vip_until > datetime.utcnow():
            vip_status = f"🕵️ VIP до {user.vip_until.strftime('%H:%M')}\n"
        
        license_status = "✅ Брокер" if user.has_license else "❌ Немає"

        text = (
            f"👤 <b>Твій Профіль</b>\n"
            f"────────────────\n"
            f"🏆 Ранг: <b>{rank}</b>\n"
            f"{clan_info}"
            f"{vip_status}"
            f"📜 Ліцензія: {license_status}\n"
            f"💵 Готівка: ${float(user.balance):.2f}\n"
            f"🏦 Банк: ${float(user.bank_balance):.2f}\n"
            f"📈 Всього активів: <b>${net_worth:.2f}</b>\n"
            f"────────────────"
        )
        
        try:
            user_photos = await message.bot.get_user_profile_photos(message.from_user.id)
            if user_photos.total_count > 0:
                photo_id = user_photos.photos[0][-1].file_id
                await message.answer_photo(photo=photo_id, caption=text, parse_mode="HTML")
            else:
                await message.answer(text, parse_mode="HTML")
        except Exception:
            await message.answer(text, parse_mode="HTML")

# --- АДМІН КОМАНДИ ---
@router.message(Command("setsupply"), IsAdmin())
async def cmd_set_supply(message: types.Message):
    """
    Встановити загальну та доступну кількість акцій.
    Приклад: /setsupply DOGE 500000
    """
    args = message.text.split()
    if len(args) != 3:
        return await message.answer("❌ Формат: `/setsupply TICKER COUNT`")
    
    ticker = args[1].upper()
    try:
        new_supply = int(args[2])
    except ValueError:
        return await message.answer("❌ Кількість має бути цілим числом.")

    async with async_session() as session:
        meme = (await session.execute(
            select(Meme).where(Meme.ticker == ticker)
        )).scalar_one_or_none()
        
        if not meme:
            return await message.answer(f"❌ Акцію {ticker} не знайдено.")
        
        # Змінюємо Total Supply
        meme.total_supply = new_supply
        
        # Розраховуємо, скільки акцій вже на руках у гравців
        # (Total - Available = Bought). 
        # Але тут ми просто скидаємо available до нового ліміту, 
        # або (краще) розраховуємо чесно:
        
        result = await session.execute(
            select(func.sum(Portfolio.quantity)).where(Portfolio.meme_id == meme.id)
        )
        already_owned = result.scalar() or 0
        
        new_available = new_supply - already_owned
        
        if new_available < 0:
            # Якщо зменшили так сильно, що акцій на руках більше, ніж існує
            new_available = 0
            await message.answer(f"⚠️ Увага: Гравці мають {already_owned} шт, а ліміт тепер {new_supply}. Доступно: 0.")
        
        meme.available_supply = new_available
        
        await session.commit()
        
        await message.answer(
            f"✅ <b>Оновлено {ticker}</b>\n"
            f"Загальний ліміт: {new_supply:,}\n"
            f"На руках у гравців: {already_owned:,}\n"
            f"Доступно для покупки: {new_available:,}",
            parse_mode="HTML"
        )
@router.message(Command(re.compile(r"adm_(\w+)_(\d+)_(\w+)")), IsAdmin())
async def cmd_admin_manipulate(message: types.Message):
    match = re.match(r"/adm_(\w+)_(\d+)_(\w+)", message.text)
    if not match:
        return await message.answer(
            "❌ Помилка формату. Спробуй: /adm_TICKER_COUNT_DIRECTION. (Напр: /adm_DOGE_5_UP)"
        )

    ticker, count_str, direction = match.groups()
    
    direction = direction.upper()
    if direction not in ['UP', 'DOWN', 'NONE']:
        return await message.answer("❌ Напрямок має бути UP, DOWN або NONE.")
    
    try:
        count = int(count_str)
        if count <= 0 or count > 60:
            return await message.answer("❌ Кількість хвилин має бути від 1 до 60.")
    except ValueError:
        return await message.answer("❌ Кількість має бути числом.")
        
    async with async_session() as session:
        meme_query = select(Meme).where(Meme.ticker == ticker.upper())
        meme = (await session.execute(meme_query)).scalar_one_or_none()
        
        if not meme:
            return await message.answer(
                f"❌ Акцію з тікером <b>{ticker.upper()}</b> не знайдено."
            )
            
        meme.manipulation_mode = direction
        meme.manipulation_remaining = count
        await session.commit()
        
        if direction == 'NONE':
             await message.answer(
                 f"✅ Маніпуляцію цiною <b>{meme.ticker}</b> скасовано.",
                 parse_mode="HTML"
             )
        else:
             await message.answer(
                f"🔥 <b>Успіх!</b> Встановлено маніпуляцію для <b>{meme.ticker}</b>:\n"
                f"Напрямок: <b>{direction}</b>\n"
                f"Тривалість: <b>{count} хв</b>",
                parse_mode="HTML"
            )

@router.message(Command("broadcast"), IsAdmin())
async def cmd_broadcast(message: types.Message):
    content = message.text.replace("/broadcast", "", 1).strip()
    
    if not content:
        return await message.answer(
            "❌ <b>Помилка!</b> Введи текст повідомлення.\n"
            "Приклад: <code>/broadcast Знижки на DOGE!</code>", 
            parse_mode="HTML"
        )

    start_msg = await message.answer(f"⏳ Починаю розсилку для гравців...")
    
    async with async_session() as session:
        result = await session.execute(select(User.telegram_id))
        users_ids = result.scalars().all()

    count_success = 0
    count_error = 0
    
    for user_id in users_ids:
        try:
            text = f"📢 <b>ОГОЛОШЕННЯ ВІД БІРЖІ</b>\n\n{content}"
            
            await message.bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")
            count_success += 1
            
            await asyncio.sleep(0.05)
            
        except Exception:
            count_error += 1

    await start_msg.edit_text(
        f"✅ <b>Розсилка завершена!</b>\n\n"
        f"📨 Відправлено: <b>{count_success}</b>\n"
        f"🚫 Не доставлено (блокували): <b>{count_error}</b>",
        parse_mode="HTML"
    )

@router.message(Command("vipbroadcast"), IsAdmin())
async def cmd_vip_broadcast(message: types.Message):
    content = message.text.replace("/vipbroadcast", "", 1).strip()
    if not content: 
        return await message.answer("Введи текст.")
    
    async with async_session() as session:
        now = datetime.utcnow()
        query = select(User).where(User.vip_until > now)
        vips = (await session.execute(query)).scalars().all()
        
        count = 0
        for vip in vips:
            try:
                await message.bot.send_message(
                    vip.telegram_id,
                    f"🕵️ <b>ІНСАЙДЕРСЬКА ІНФО</b>\n\n{content}",
                    parse_mode="HTML"
                )
                count += 1
                await asyncio.sleep(0.05)
            except: 
                pass
            
        await message.answer(f"✅ Відправлено {count} VIP-ам.")

@router.message(Command("addstock"), IsAdmin())
async def cmd_add_stock(message: types.Message):
    """
    Додавання нової акції.
    Формат: /addstock ТІКЕР ЦІНА ВОЛАТИЛЬНІСТЬ КІЛЬКІСТЬ [КАРТИНКА]
    """
    try:
        args = message.text.split()
        
        # Перевіряємо, чи достатньо аргументів
        if len(args) < 5:
            return await message.answer(
                "❌ <b>Помилка формату!</b>\n\n"
                "Правильно: <code>/addstock TICKER PRICE VOL SUPPLY [URL]</code>\n"
                "Приклад: <code>/addstock DOGE 0.5 0.05 1000000</code>",
                parse_mode="HTML"
            )

        ticker = args[1].upper()
        price = float(args[2])
        volatility = float(args[3])
        
        # Обробляємо кількість (прибираємо коми та підкреслення, якщо адмін написав 1,000,000)
        total_supply = int(args[4].replace(",", "").replace("_", ""))
        
        # Картинка йде 5-м параметром (індекс 5), якщо вона є
        image_url = args[5] if len(args) > 5 else None
        
        async with async_session() as session:
            exists = await session.execute(
                select(Meme).where(Meme.ticker == ticker)
            )
            if exists.scalar_one_or_none():
                return await message.answer(f"❌ Акція {ticker} вже існує.")
            
            new_meme = Meme(
                ticker=ticker,
                current_price=price,
                volatility=volatility,
                image_url=image_url,
                total_supply=total_supply,      # <-- Встановлюємо введену кількість
                available_supply=total_supply   # <-- Всі акції спочатку доступні
            )
            session.add(new_meme)
            await session.commit()
            
        await message.answer(
            f"✅ <b>Акцію додано!</b>\n"
            f"🏷 {ticker}\n"
            f"💵 ${price}\n"
            f"📦 Кількість: {total_supply:,}", 
            parse_mode="HTML"
        )
        
    except ValueError:
        await message.answer("❌ Перевір дані. Ціна та волатильність мають бути числами (через крапку), а кількість - цілим числом.")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

@router.message(Command("economy"), IsAdmin())
async def cmd_economy(message: types.Message):
    """Команда для перегляду стану економіки"""
    async with async_session() as session:
        total_users = (await session.execute(select(func.count(User.id)))).scalar()
        
        result = await session.execute(
            select(
                func.coalesce(func.sum(User.balance), 0) + 
                func.coalesce(func.sum(User.bank_balance), 0)
            )
        )
        total_money = result.scalar() or 0
        
        avg_balance = (await session.execute(
            select(func.avg(User.balance))
        )).scalar() or 0
        
        text = (
            "📊 <b>Стан економіки</b>\n\n"
            f"👥 Користувачів: {total_users}\n"
            f"💵 Грошова маса: ${total_money:,.2f}\n"
            f"📈 Середній баланс: ${avg_balance:.2f}\n\n"
            f"⚙️ Комісія продажу: {Config.SELL_COMMISSION_DEFAULT*100:.0f}%\n"
            f"🎲 Коефіцієнт ставок: {Config.BET_PROFIT_FACTOR}x"
        )
        
        await message.answer(text, parse_mode="HTML")

@router.message(Command("reset_world"), IsAdmin())
async def cmd_reset_world(message: types.Message):
    """НЕБЕЗПЕЧНА команда - скидає всю гру"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ ТАК, СКИНУТИ ВСЕ", callback_data="confirm_reset"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="delete_msg")
        ]
    ])
    
    await message.answer(
        "⚠️ <b>УВАГА!</b>\n\n"
        "Це видалить ВСІ дані:\n"
        "• Баланси гравців\n"
        "• Портфелі\n"
        "• Історію цін\n"
        "• Ставки та квитки\n\n"
        "Підтвердити?",
        reply_markup=kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "confirm_reset")
async def cb_confirm_reset(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🚫 Тільки адміни!", show_alert=True)
    
    async with async_session() as session:
        # 1. Розриваємо зв'язок User -> Clan (щоб можна було видалити Клани)
        await session.execute(
            update(User).values(clan_id=None)
        )
        
        # 2. Видаляємо всі залежні таблиці (порядок важливий!)
        await session.execute(delete(Portfolio))      # Спочатку портфель
        await session.execute(delete(Bet))            # Ставки
        await session.execute(delete(LotteryTicket))  # Квитки
        await session.execute(delete(UserItem))       # Предмети
        await session.execute(delete(UsedPromo))      # Використані промокоди
        
        # 3. Тепер безпечно видаляти Клани (юзери на них вже не посилаються)
        await session.execute(delete(Clan))
        
        # 4. Видаляємо історію ринку
        await session.execute(delete(PriceHistory))
        await session.execute(delete(News))
        
        # 5. Нарешті видаляємо самих користувачів
        await session.execute(delete(User))
        
        await session.commit()
    
    await callback.message.edit_text(
        "💣 <b>Світ скинуто!</b>\n\nВсі дані видалено.", 
        parse_mode="HTML"
    )
    
@router.message(Command("betplayer"))
async def cmd_bet_player(message: types.Message):
    """Ставка на гравця у битві"""
    args = message.text.split()
    if len(args) != 3:
        return await message.answer(
            "🤼 <b>Ставка на дуель</b>\n"
            "Формат: <code>/betplayer @USERNAME СУМА</code>\n"
            "Приклад: /betplayer @elonmusk 1000",
            parse_mode="HTML"
        )
    
    target_username = args[1].replace("@", "")
    try:
        amount = float(args[2])
    except:
        return await message.answer("❌ Сума має бути числом.")
        
    async with async_session() as session:
        # 1. Шукаємо активну битву
        battle = (await session.execute(
            select(TycoonBattle).where(TycoonBattle.is_active == True)
        )).scalar_one_or_none()
        
        if not battle:
            return await message.answer("❌ Зараз немає активних битв магнатів.")
            
        user = await get_user(session, message.from_user.id)
        if float(user.balance) < amount:
            return await message.answer("❌ Недостатньо коштів.")
            
        # 2. Шукаємо ціль
        target = (await session.execute(
            select(User).where(User.username == target_username)
        )).scalar_one_or_none()
        
        if not target:
            return await message.answer("❌ Гравця не знайдено.")
            
        if target.id not in [battle.player1_id, battle.player2_id]:
            return await message.answer("❌ Цей гравець не бере участі в поточній битві.")
            
        # 3. Приймаємо ставку
        user.balance = float(user.balance) - amount
        
        new_bet = PlayerBet(
            user_id=user.id,
            battle_id=battle.id,
            target_player_id=target.id,
            amount=amount
        )
        session.add(new_bet)
        await session.commit()
        
        await message.answer(
            f"✅ Ставка <b>${amount}</b> на перемогу <b>{target.full_name}</b> прийнята!",
            parse_mode="HTML"
        )
        


@router.message(Command("collection"))
async def cmd_collection(message: types.Message):
    """Показує колекцію користувача"""
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return await message.answer("⚠️ Натисни /start")
    
    # Отримуємо колекцію
    collection = await get_user_collection(user.id)
    
    if collection['total'] == 0:
        return await message.answer(
            "📦 <b>Твоя колекція порожня</b>\n\n"
            "💡 Купуй акції, щоб отримувати рідкісні карти!\n"
            "Кожна покупка має шанс дропнути колекційну карту.\n\n"
            "Шанси дропу:\n"
            "⚪️ Звичайна: 1%\n"
            "🔵 Рідкісна: 0.5%\n"
            "🟣 Епічна: 0.1%\n"
            "🟡 Легендарна: 0.01%",
            parse_mode="HTML"
        )
    
    # Формуємо текст колекції
    text = (
        f"🎨 <b>Твоя Колекція</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Прогрес: <b>{collection['total']}</b> карт "
        f"(<b>{collection['completion']:.1f}%</b>)\n"
        f"💰 Загальний бонус: <b>+{(collection['total_bonus'] - 1) * 100:.0f}%</b>\n\n"
    )
    
    # Статистика по рідкості
    text += "📈 <b>За рідкістю:</b>\n"
    for rarity, count in collection['by_rarity'].items():
        if count > 0:
            emoji = RARITY_CONFIG[rarity]['emoji']
            name = RARITY_CONFIG[rarity]['color'].capitalize()
            text += f"{emoji} {name}: <b>{count}</b>\n"
    
    text += "\n━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Показуємо останні 10 карт
    text += "🎴 <b>Останні карти:</b>\n\n"
    
    for i, card in enumerate(collection['cards'][:10], 1):
        new_badge = " 🆕" if card['is_new'] else ""
        text += (
            f"{i}. {card['emoji']} <b>{card['name']}</b>{new_badge}\n"
            f"   └ {card['ticker']} | +{(card['bonus'] - 1) * 100:.0f}%\n"
        )
    
    if collection['total'] > 10:
        text += f"\n<i>... і ще {collection['total'] - 10} карт</i>"
    
    # Кнопки
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Повна колекція", callback_data=f"full_collection_{message.from_user.id}_0")],
        [InlineKeyboardButton(text="🔄 Оновити", callback_data=f"refresh_collection_{message.from_user.id}")]
    ])
    
    # Позначаємо карти як переглянуті
    await mark_cards_as_seen(user.id)
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("refresh_collection_"))
async def cb_refresh_collection(callback: types.CallbackQuery):
    """Оновлює відображення колекції"""
    user_id = int(callback.data.split("_")[2])
    
    if callback.from_user.id != user_id:
        return await callback.answer("🚫 Це не твоя колекція", show_alert=True)
    
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
    
    collection = await get_user_collection(user.id)
    
    text = (
        f"🎨 <b>Твоя Колекція</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Прогрес: <b>{collection['total']}</b> карт "
        f"(<b>{collection['completion']:.1f}%</b>)\n"
        f"💰 Загальний бонус: <b>+{(collection['total_bonus'] - 1) * 100:.0f}%</b>\n\n"
    )
    
    text += "📈 <b>За рідкістю:</b>\n"
    for rarity, count in collection['by_rarity'].items():
        if count > 0:
            emoji = RARITY_CONFIG[rarity]['emoji']
            name = RARITY_CONFIG[rarity]['color'].capitalize()
            text += f"{emoji} {name}: <b>{count}</b>\n"
    
    text += "\n━━━━━━━━━━━━━━━━━━━\n\n"
    text += "🎴 <b>Останні карти:</b>\n\n"
    
    for i, card in enumerate(collection['cards'][:10], 1):
        text += (
            f"{i}. {card['emoji']} <b>{card['name']}</b>\n"
            f"   └ {card['ticker']} | +{(card['bonus'] - 1) * 100:.0f}%\n"
        )
    
    if collection['total'] > 10:
        text += f"\n<i>... і ще {collection['total'] - 10} карт</i>"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Повна колекція", callback_data=f"full_collection_{callback.from_user.id}_0")],
        [InlineKeyboardButton(text="🔄 Оновити", callback_data=f"refresh_collection_{callback.from_user.id}")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer("✅ Оновлено!")


@router.callback_query(F.data.startswith("full_collection_"))
async def cb_full_collection(callback: types.CallbackQuery):
    """Показує повну колекцію з пагінацією"""
    parts = callback.data.split("_")
    user_id = int(parts[2])
    page = int(parts[3])
    
    if callback.from_user.id != user_id:
        return await callback.answer("🚫 Це не твоя колекція", show_alert=True)
    
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
    
    collection = await get_user_collection(user.id)
    
    CARDS_PER_PAGE = 5
    total_pages = (collection['total'] + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE
    
    start_idx = page * CARDS_PER_PAGE
    end_idx = start_idx + CARDS_PER_PAGE
    
    page_cards = collection['cards'][start_idx:end_idx]
    
    text = (
        f"📋 <b>Повна Колекція</b> (Сторінка {page + 1}/{total_pages})\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    for i, card in enumerate(page_cards, start_idx + 1):
        obtained_str = card['obtained'].strftime("%d.%m.%Y")
        text += (
            f"{i}. {card['emoji']} <b>{card['name']}</b>\n"
            f"   🎫 {card['ticker']}\n"
            f"   📈 Бонус: +{(card['bonus'] - 1) * 100:.0f}%\n"
            f"   📅 Отримано: {obtained_str}\n\n"
        )
    
    # Навігація
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(
            text="⬅️",
            callback_data=f"full_collection_{user_id}_{page - 1}"
        ))
    
    nav_row.append(InlineKeyboardButton(
        text=f"📄 {page + 1}/{total_pages}",
        callback_data="ignore"
    ))
    
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(
            text="➡️",
            callback_data=f"full_collection_{user_id}_{page + 1}"
        ))
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        nav_row,
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"refresh_collection_{user_id}")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("cardstats"), IsAdmin())
async def cmd_card_stats(message: types.Message):
    """Статистика по картам (для адміна)"""
    stats = await get_collection_stats()
    
    text = (
        f"📊 <b>Статистика Колекцій</b>\n\n"
        f"🎴 Всього карт у грі: <b>{stats['total_cards']}</b>\n"
        f"✅ Отримано гравцями: <b>{stats['total_collected']}</b>\n"
        f"🟡 Легендарних отримано: <b>{stats['legendary_obtained']}</b>\n"
        f"📈 Середньо на гравця: <b>{stats['avg_per_user']:.1f}</b>\n"
    )
    
    await message.answer(text, parse_mode="HTML")
    
# --- MARGIN TRADING HANDLERS ---

@router.message(Command("margin"))
async def cmd_margin_help(message: types.Message):
    await message.answer(
        "🎰 <b>Маржинальна Торгівля</b>\n\n"
        "Бери в борг під заставу своїх акцій!\n"
        "Але обережно: якщо ціна впаде, банк забере все (Margin Call).\n\n"
        "<b>Команди:</b>\n"
        "<code>/buy_margin TICKER SUM</code> - Купити акцію з плечем\n"
        "<code>/repay SUM</code> - Повернути борг\n"
        "<code>/status</code> - Стан твого маржинального рахунку",
        parse_mode="HTML"
    )

@router.message(Command("status"))
async def cmd_margin_status(message: types.Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        
        # Рахуємо вартість портфеля
        pf_items = (await session.execute(select(Portfolio).where(Portfolio.user_id==user.id))).scalars().all()
        pf_value = Decimal(0)
        for item in pf_items:
            meme = await session.get(Meme, item.meme_id)
            pf_value += meme.current_price * item.quantity
            
        equity = (user.balance + pf_value) - user.loan_balance
        total_assets = user.balance + pf_value
        
        if total_assets > 0:
            health = (equity / total_assets) * 100
        else:
            health = 100.0
            
        emoji = "🟢" if health > 50 else "🟡" if health > 30 else "🔴"
        
        text = (
            f"🏦 <b>Твій статус</b>\n"
            f"💵 Готівка: ${user.balance:,.2f}\n"
            f"💼 Акції: ${pf_value:,.2f}\n"
            f"💳 Борг: ${user.loan_balance:,.2f}\n\n"
            f"📉 <b>Рівень здоров'я: {emoji} {health:.1f}%</b>\n"
            f"(Margin Call при < {Config.MARGIN_MAINTENANCE_REQ*100}%)"
        )
        await message.answer(text, parse_mode="HTML")

@router.message(Command("buy_margin"))
async def cmd_buy_margin(message: types.Message):
    args = message.text.split()
    if len(args) != 3:
        return await message.answer("❌ Формат: `/buy_margin DOGE 5000`")
    
    ticker = args[1].upper()
    try:
        amount_to_spend = Decimal(args[2])
    except:
        return await message.answer("❌ Сума має бути числом.")
        
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        meme = (await session.execute(select(Meme).where(Meme.ticker == ticker))).scalar_one_or_none()
        
        if not meme: return await message.answer("❌ Акцію не знайдено.")
        
        # Рахуємо максимальну купівельну спроможність
        # Max Loan = Portfolio Value
        # Total Power = Cash + Max Loan - Current Loan
        pf_value = Decimal(0) # ... (тут треба порахувати портфель, як у функції вище)
        pf_items = (await session.execute(select(Portfolio).where(Portfolio.user_id==user.id))).scalars().all()
        for item in pf_items:
            m = await session.get(Meme, item.meme_id)
            pf_value += m.current_price * item.quantity

        max_loan = pf_value * Decimal(Config.MARGIN_MAX_LEVERAGE) # наприклад, 1:1, тобто можна позичити стільки ж, скільки маєш
        available_loan = max_loan - user.loan_balance
        
        # Якщо своїх грошей вистачає, використовуємо їх
        if user.balance >= amount_to_spend:
            user.balance -= amount_to_spend
            loan_part = Decimal(0)
        else:
            # Треба позичати
            needed = amount_to_spend - user.balance
            if needed > available_loan:
                 return await message.answer(f"❌ Банк не дає такий кредит. Доступно в борг: ${available_loan:,.2f}")
            
            # Використовуємо весь кеш
            loan_part = needed
            user.balance = Decimal(0)
            user.loan_balance += loan_part

        # Купуємо акції
        quantity = int(amount_to_spend // meme.current_price)
        if quantity == 0: return await message.answer("❌ Мало грошей.")
        
        pf_item = (await session.execute(select(Portfolio).where(Portfolio.user_id==user.id, Portfolio.meme_id==meme.id))).scalar_one_or_none()
        if pf_item:
            pf_item.quantity += quantity
        else:
            session.add(Portfolio(user_id=user.id, meme_id=meme.id, quantity=quantity))
            
        meme.trade_volume += quantity
        
        await session.commit()
        await message.answer(
            f"✅ Куплено {quantity} {meme.ticker} з плечем!\n"
            f"Взято в борг: ${loan_part:,.2f}"
        )

# --- IPO HANDLERS ---

@router.message(Command("create_ipo"), IsAdmin())
async def cmd_create_ipo(message: types.Message):
    args = message.text.split()
    
    # Перевіряємо, чи достатньо аргументів (мінімум 4 параметри + сама команда = 5 слів)
    if len(args) < 5:
        return await message.answer(
            "❌ <b>Формат команди:</b>\n"
            "<code>/create_ipo ТІКЕР ЦІНА КІЛЬКІСТЬ ХВИЛИНИ [ПОСИЛАННЯ]</code>\n\n"
            "Приклад з картинкою:\n"
            "<code>/create_ipo HAMSTER 0.05 1000000 60 https://i.imgur.com/hamster.jpg</code>\n\n"
            "Приклад без картинки:\n"
            "<code>/create_ipo HAMSTER 0.05 1000000 60</code>",
            parse_mode="HTML"
        )
    
    ticker = args[1].upper()
    
    try:
        price = Decimal(args[2])
        # Прибираємо коми та підкреслення, якщо адмін ввів "1,000,000"
        supply = int(args[3].replace(",", "").replace("_", ""))
        minutes = int(args[4])
    except ValueError:
        return await message.answer("❌ Ціна, кількість та хвилини мають бути числами.")
    
    # 5-й аргумент (індекс 5) - це картинка, якщо вона є
    image_url = args[5] if len(args) > 5 else None
    
    async with async_session() as session:
        # Перевіряємо, чи немає вже такого IPO
        exists_ipo = await session.execute(select(IPO).where(IPO.ticker == ticker, IPO.is_active == True))
        if exists_ipo.scalar_one_or_none():
             return await message.answer(f"❌ IPO {ticker} вже активне!")
             
        # Перевіряємо, чи немає такої акції на ринку
        exists_meme = await session.execute(select(Meme).where(Meme.ticker == ticker))
        if exists_meme.scalar_one_or_none():
             return await message.answer(f"❌ Акція {ticker} вже існує на ринку! Використовуй інший тікер.")

        end_time = datetime.utcnow() + timedelta(minutes=minutes)
        new_ipo = IPO(
            ticker=ticker,
            start_price=price,
            total_supply=supply,
            end_time=end_time,
            image_url=image_url # Зберігаємо URL
        )
        session.add(new_ipo)
        await session.commit()
        
    # Формуємо красиве повідомлення про успіх
    text = (
        f"📢 <b>IPO {ticker} оголошено!</b>\n\n"
        f"💵 Стартова ціна: <b>${price}</b>\n"
        f"📦 Саплай: <b>{supply:,}</b> шт\n"
        f"⏳ Збір заявок: <b>{minutes} хв</b>"
    )
    
    # Якщо є картинка, відправляємо фото з підписом
    if image_url:
        try:
            await message.answer_photo(image_url, caption=text, parse_mode="HTML")
        except:
            await message.answer(text + "\n<i>(Картинку не вдалося завантажити, але IPO створено)</i>", parse_mode="HTML")
    else:
        await message.answer(text, parse_mode="HTML")

@router.message(Command("ipo"))
async def cmd_list_ipo(message: types.Message):
    async with async_session() as session:
        ipos = (await session.execute(select(IPO).where(IPO.is_active == True))).scalars().all()
        
        if not ipos: return await message.answer("📭 Зараз немає активних IPO.")
        
        text = "🚀 <b>Активні IPO</b>\n\n"
        for ipo in ipos:
            time_left = int((ipo.end_time - datetime.utcnow()).total_seconds() / 60)
            text += (
                f"🔹 <b>{ipo.ticker}</b> | Ціна: ${ipo.start_price}\n"
                f"📦 Саплай: {ipo.total_supply:,}\n"
                f"⏳ Кінець через: {time_left} хв\n"
                f"👉 Участь: <code>/join_ipo {ipo.ticker} СУМА</code>\n\n"
            )
        await message.answer(text, parse_mode="HTML")

@router.message(Command("join_ipo"))
async def cmd_join_ipo(message: types.Message):
    args = message.text.split()
    if len(args) != 3: return await message.answer("❌ Приклад: `/join_ipo HAMSTER 1000`")
    
    ticker = args[1].upper()
    amount = Decimal(args[2])
    
    async with async_session() as session:
        ipo = (await session.execute(select(IPO).where(IPO.ticker == ticker, IPO.is_active == True))).scalar_one_or_none()
        if not ipo: return await message.answer("❌ IPO не знайдено.")
        
        user = await get_user(session, message.from_user.id)
        if user.balance < amount: return await message.answer("❌ Немає грошей.")
        
        user.balance -= amount
        
        shares = int(amount // ipo.start_price)
        
        app = IPOApplication(
            ipo_id=ipo.id,
            user_id=user.id,
            amount_invested=amount,
            shares_requested=shares
        )
        session.add(app)
        await session.commit()
        
        await message.answer(f"✅ Заявка на {shares} акцій {ticker} прийнята! Гроші заблоковано.")