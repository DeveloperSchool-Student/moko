from decimal import Decimal
import random
import asyncio
import io
import pandas as pd
import mplfinance as mpf
import matplotlib
from datetime import datetime, timedelta

from sqlalchemy import select, delete, func
from aiogram import Bot
from models import IPO, IPOApplication, TycoonBattle, PlayerBet, Portfolio
from database import async_session
from config import Config, ADMIN_IDS
from models import User, Meme, PriceHistory, News, Bet, LotteryTicket


matplotlib.use('Agg')


# --- ШАБЛОНИ НОВИН ---
NEWS_UP = [
    "🚀 {ticker} летить на Місяць! Інвестори в шоці!",
    "📈 Кити закуповують {ticker}. Ціна стрімко росте!",
    "🤑 Ходять чутки, що Ілон Маск купив {ticker}...",
    "🔥 {ticker} пробиває стелю! Тримайте свої капелюхи!",
    "🐂 Бичачий тренд по {ticker}. Всі купують!"
]

NEWS_DOWN = [
    "📉 {ticker} стрімко падає! Паніка на біржі!",
    "😱 Хтось злив величезну кількість {ticker}...",
    "🔻 Бульбашка {ticker} луснула? Інвестори плачуть.",
    "🐻 Ведмеді атакують {ticker}. Рятуйся хто може!",
    "🩸 Кровава лазня по {ticker}. Ціна летить у прірву."
]
# --- УТИЛІТА ДЛЯ ПЕРЕТВОРЕННЯ FLOAT В DECIMAL ---
def d(value):
    return Decimal(str(value))
async def update_prices(bot=None): # Додали bot як параметр для сповіщень про Margin Call
    """Оновлення цін та перевірка Margin Call"""
    async with async_session() as session:
        memes = (await session.execute(select(Meme))).scalars().all()
        
        for meme in memes:
            current_price = meme.current_price # Це вже Decimal
            volatility = meme.volatility
            
            # Логіка руху (як і раніше, але з Decimal)
            # random.uniform повертає float, тому конвертуємо
            
            # Динамічна волатильність
            dynamic_volatility = float(volatility) * (1 - (float(current_price) / 20000))
            dynamic_volatility = max(0.01, dynamic_volatility)
            
            change_percent = random.uniform(-dynamic_volatility, dynamic_volatility)
            
            # Маніпуляція
            if meme.manipulation_mode == "UP":
                change_percent = abs(random.uniform(0.02, 0.05))
                meme.manipulation_remaining -= 1
            elif meme.manipulation_mode == "DOWN":
                change_percent = -abs(random.uniform(0.02, 0.05))
                meme.manipulation_remaining -= 1
                
            if meme.manipulation_remaining <= 0:
                meme.manipulation_mode = "NONE"

            # Вплив об'єму
            volume_impact = meme.trade_volume * Config.MARKET_IMPACT_FACTOR
            volume_impact = max(-0.15, min(0.15, volume_impact))
            
            total_change = Decimal(change_percent) + Decimal(volume_impact)
            
            new_price = current_price * (1 + total_change)
            meme.current_price = max(d(0.0001), new_price)
            meme.trade_volume = 0 # Скидання об'єму

            # Збереження історії
            history = PriceHistory(meme_id=meme.id, price=meme.current_price)
            session.add(history)
            
            # 7. Податок
            if abs(meme.trade_volume) > 10_000:
                tax = meme.trade_volume * 0.01
                meme.trade_volume -= int(tax)

        # 8. Дефляція
        now = datetime.utcnow()
        if now.day == 1 and now.hour == 0:
            users = (await session.execute(select(User))).scalars().all()
            for user in users:
                user_balance_float = float(user.balance)
                if user_balance_float > 1000:
                    user.balance = user_balance_float * 0.995

        # --- MARGIN CALL CHECK ---
        # Перевіряємо всіх боржників
        debtors = (await session.execute(select(User).where(User.loan_balance > 0))).scalars().all()
        
        for debtor in debtors:
            # 1. Рахуємо вартість портфеля
            pf_items = (await session.execute(select(Portfolio).where(Portfolio.user_id == debtor.id))).scalars().all()
            portfolio_value = Decimal(0)
            
            user_memes_cache = {} # Кеш для цін
            
            for item in pf_items:
                # Оптимізація: краще завантажити ціни заздалегідь, але тут ок
                if item.meme_id not in user_memes_cache:
                    m = await session.get(Meme, item.meme_id)
                    user_memes_cache[item.meme_id] = m.current_price
                
                portfolio_value += user_memes_cache[item.meme_id] * item.quantity
            
            total_assets = portfolio_value + debtor.balance
            debt = debtor.loan_balance
            
            # Equity = Активи - Борги
            equity = total_assets - debt
            
            # Якщо активи 0, а борг є - це банкрутство
            if total_assets == 0:
                margin_level = Decimal(0)
            else:
                margin_level = equity / total_assets

            # Якщо рівень маржі нижче 30% (0.3) -> ЛІКВІДАЦІЯ
            if margin_level < Decimal(Config.MARGIN_MAINTENANCE_REQ):
                # Продаємо портфель, щоб покрити борг
                liquidation_text = f"🚨 <b>MARGIN CALL!</b>\nРівень здоров'я: {margin_level*100:.1f}%\n"
                
                for item in pf_items:
                    price = user_memes_cache[item.meme_id]
                    revenue = price * item.quantity
                    
                    # Продаємо все
                    debtor.balance += revenue
                    session.delete(item) # Видаляємо акції
                    liquidation_text += f"🔻 Продано {item.quantity} шт (за ${revenue:,.2f})\n"
                
                # Списуємо борг з балансу
                repay_amount = min(debtor.balance, debt)
                debtor.balance -= repay_amount
                debtor.loan_balance -= repay_amount
                
                # Штраф за ліквідацію (5%)
                penalty = repay_amount * d(0.05)
                debtor.balance -= penalty
                
                if bot:
                    try:
                        await bot.send_message(debtor.telegram_id, liquidation_text + f"\n💸 Списано борг: ${repay_amount:,.2f}\n⚠️ Штраф: ${penalty:,.2f}", parse_mode="HTML")
                    except: pass
        
        await session.commit()
async def process_ipos(bot):
    """Обробка завершених IPO"""
    async with async_session() as session:
        now = datetime.utcnow()
        # Шукаємо активні IPO, час яких вийшов
        ipos = (await session.execute(select(IPO).where(IPO.is_active == True, IPO.end_time <= now))).scalars().all()
        
        for ipo in ipos:
            ipo.is_active = False
            
            # Отримуємо всі заявки
            apps = (await session.execute(select(IPOApplication).where(IPOApplication.ipo_id == ipo.id))).scalars().all()
            
            total_requested_shares = sum(app.shares_requested for app in apps)
            if total_requested_shares == 0:
                continue # IPO провалилось, ніхто не купив
                
            # Коефіцієнт попиту
            demand_ratio = Decimal(total_requested_shares) / Decimal(ipo.total_supply)
            
            final_price = ipo.start_price
            msg_header = ""
            
            if demand_ratio > 1:
                # Ажіотаж! Ціна росте, акцій дають менше
                final_price = ipo.start_price * (1 + (Decimal(0.1) * demand_ratio)) # +10% за кожен x перевищення
                fill_percent = Decimal(1) / demand_ratio
                msg_header = f"🚀 <b>IPO {ipo.ticker} ВИБУХНУЛО!</b>\nПопит перевищив пропозицію в {demand_ratio:.1f}x!"
            else:
                # Провал або норм. Якщо провал (<0.5), ціна падає
                if demand_ratio < 0.5:
                    final_price = ipo.start_price * d(0.8) # -20%
                    msg_header = f"📉 <b>IPO {ipo.ticker} пройшло слабо...</b>\nЦіна знижена."
                else:
                    msg_header = f"✅ <b>IPO {ipo.ticker} успішне!</b>"
                fill_percent = Decimal(1)
            
            # Створення акції (Meme)
            new_meme = Meme(
                ticker=ipo.ticker,
                current_price=final_price,
                volatility=d(0.05),
                total_supply=ipo.total_supply,
                available_supply=0, # Все роздамо, що залишиться - спалимо або на ринок
                image_url=ipo.image_url
            )
            session.add(new_meme)
            await session.flush() # Щоб отримати ID
            
            market_supply = 0
            
            # Роздача слонів
            for app in apps:
                user = await session.get(User, app.user_id)
                
                # Скільки акцій реально отримує
                shares_received = int(app.shares_requested * float(fill_percent))
                if shares_received == 0 and app.shares_requested > 0:
                    shares_received = 1 # Втішний приз
                
                cost = shares_received * ipo.start_price # Купують по старій ціні (або по новій? зазвичай IPO купують по стартовій, а відкривається по новій)
                # Гроші вже списані при заявці (app.amount_invested)
                
                # Розрахунок решти (якщо був овербукінг і дали менше акцій)
                spent = shares_received * ipo.start_price
                refund = app.amount_invested - spent
                
                if refund > 0:
                    user.balance += refund
                
                # Додаємо акції
                portfolio = Portfolio(user_id=user.id, meme_id=new_meme.id, quantity=shares_received)
                session.add(portfolio)
                
                market_supply += shares_received
                
                try:
                    profit_pct = (final_price - ipo.start_price) / ipo.start_price * 100
                    await bot.send_message(
                        user.telegram_id,
                        f"📊 <b>Результати IPO {ipo.ticker}</b>\n\n"
                        f"Отримано акцій: {shares_received}\n"
                        f"Ціна лістингу: ${final_price:.2f} ({profit_pct:+.1f}%)\n"
                        f"Повернення коштів: ${refund:.2f}"
                    , parse_mode="HTML")
                except: pass
            
            # Оновлюємо available_supply
            new_meme.available_supply = ipo.total_supply - market_supply
            new_meme.trade_volume = market_supply # Щоб ціна зразу почала рухатись
            
            # Оголошення всім
            # Тут можна додати broadcast logic
            
        await session.commit()
async def check_money_supply(bot: Bot):
    """Моніторинг грошової маси та антиінфляційні заходи"""
    async with async_session() as session:
        # Рахуємо загальну кількість грошей в системі
        result = await session.execute(
            select(
                func.coalesce(func.sum(User.balance), 0) + 
                func.coalesce(func.sum(User.bank_balance), 0)
            )
        )
        total_money = result.scalar() or 0
        
        # Якщо грошова маса занадто велика
        if total_money > 10_000_000:  # 10 мільйонів - критичний рівень
            # 1. Збільшуємо податки
            Config.SELL_COMMISSION_DEFAULT = 0.05  # 5% замість 3%
            
            # 2. Зменшуємо винагороди
            Config.BET_PROFIT_FACTOR = 1.5  # Замість 1.8
            
            # 3. Сповіщення адмінів
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"⚠️ <b>УВАГА! Висока інфляція.</b>\n\n"
                        f"Загальна грошова маса: ${total_money:,.2f}\n"
                        f"Активовано антикризові заходи:\n"
                        f"• Комісія продажу: 5%\n"
                        f"• Коефіцієнт ставок: 1.5x",
                        parse_mode="HTML"
                    )
                except:
                    pass

def _generate_chart_sync(data, ticker):
    """Синхронна генерація графіку"""
    if not data:
        return None
    
    df = pd.DataFrame(data, columns=['Date', 'Price'])
    df['Date'] = pd.to_datetime(df['Date'])
    df.set_index('Date', inplace=True)
    
    # Fake OHLC для лінійного графіку
    df['Open'] = df['Price']
    df['High'] = df['Price'] * 1.01
    df['Low'] = df['Price'] * 0.99
    df['Close'] = df['Price']
    
    buf = io.BytesIO()
    mpf.plot(
        df, 
        type='line', 
        style='yahoo', 
        title=f'{ticker} Price History',
        ylabel='Price ($)',
        savefig=dict(fname=buf, format='png', dpi=100)
    )
    buf.seek(0)
    return buf

async def get_meme_chart(meme_id: int, ticker: str):
    """Генерація графіку ціни акції"""
    async with async_session() as session:
        query = select(PriceHistory).where(
            PriceHistory.meme_id == meme_id
        ).order_by(
            PriceHistory.timestamp.desc()
        ).limit(50)
        
        result = await session.execute(query)
        history = result.scalars().all()
        
        if not history:
            return None
        
        # Реверсуємо для правильного порядку (старе -> нове)
        data = [{"Date": h.timestamp, "Price": float(h.price)} for h in reversed(history)]
        
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _generate_chart_sync, data, ticker)

async def check_bets(bot: Bot):
    """Перевіряє ставки, час яких вийшов"""
    async with async_session() as session:
        now = datetime.utcnow()
        query = select(Bet).where(Bet.processed == False, Bet.end_time <= now)
        bets = (await session.execute(query)).scalars().all()
        
        for bet in bets:
            user = await session.get(User, bet.user_id)
            meme = await session.get(Meme, bet.meme_id)
            
            if not user or not meme:
                bet.processed = True
                continue

            won = False
            if bet.direction == "UP" and meme.current_price > bet.start_price:
                won = True
            elif bet.direction == "DOWN" and meme.current_price < bet.start_price:
                won = True
            
            if won:
                # FIX: Перетворюємо множник з float в Decimal перед множенням
                payout = bet.amount * Decimal(str(Config.BET_PROFIT_FACTOR))
                user.balance += payout
                text = f"✅ <b>ПЕРЕМОГА!</b>\n{meme.ticker}: ${bet.start_price:.2f} -> ${meme.current_price:.2f}\n💰 Виграш: <b>+${payout:.2f}</b>"
            else:
                text = f"❌ <b>ПРОГРАШ...</b>\n{meme.ticker}: ${bet.start_price:.2f} -> ${meme.current_price:.2f}\n💸 Втрачено: ${bet.amount:.2f}"
            
            bet.processed = True
            try:
                await bot.send_message(user.telegram_id, text, parse_mode="HTML")
            except: pass
        
        await session.commit()

async def run_lottery(bot: Bot):
    """Запускається раз на добу: обирає переможця"""
    async with async_session() as session:
        # Рахуємо квитки
        tickets_result = await session.execute(select(LotteryTicket))
        tickets = tickets_result.scalars().all()
        
        if not tickets:
            return
        
        # Розрахунок банку
        total_pot = len(tickets) * Config.LOTTERY_TICKET
        prize = total_pot * 0.8  # 80% переможцю
        
        # Обираємо переможця
        winner_ticket = random.choice(tickets)
        winner_user = await session.get(User, winner_ticket.user_id)
        
        if winner_user:
            winner_user.balance = float(winner_user.balance) + prize
            
            # Сповіщення переможця
            try:
                await bot.send_message(
                    winner_user.telegram_id,
                    f"🎉 <b>ДЖЕКПОТ ЛОТЕРЕЇ!</b>\n\n"
                    f"Ти виграв у лотерею!\n"
                    f"Всього учасників: {len(tickets)}\n"
                    f"Твій виграш: <b>${prize:.2f}</b>\n\n"
                    f"Гроші зараховано на баланс!",
                    parse_mode="HTML"
                )
            except:
                pass
        
        # Очищаємо таблицю квитків
        await session.execute(delete(LotteryTicket))
        await session.commit()

async def process_bank_interest(bot: Bot):
    """Нараховує відсотки по банківським рахункам"""
    async with async_session() as session:
        now = datetime.utcnow()
        users = (await session.execute(select(User))).scalars().all()
        
        # Перетворюємо float константи в Decimal один раз
        DECIMAL_BANK_RATE = Decimal(str(Config.BANK_INTEREST_RATE))
        DECIMAL_DEPOSIT_RATE = Decimal(str(Config.DEPOSIT_INTEREST_RATE))

        for user in users:
            # Звичайний рахунок
            if user.bank_balance > 0:
                if not user.last_interest_date or (now - user.last_interest_date).days >= 1:
                    daily_rate = DECIMAL_BANK_RATE / Decimal(365)
                    interest = user.bank_balance * daily_rate
                    user.bank_balance += interest
                    user.last_interest_date = now
            
            # Депозити
            if user.deposit_amount > 0 and user.deposit_end_date:
                if now >= user.deposit_end_date:
                    total = user.deposit_amount * (Decimal(1) + DECIMAL_DEPOSIT_RATE)
                    user.bank_balance += total
                    
                    profit = total - user.deposit_amount
                    user.deposit_amount = Decimal(0)
                    user.deposit_end_date = None
                    
                    try:
                        await bot.send_message(user.telegram_id, f"🏦 <b>Депозит завершено!</b>\nПовернуто: <b>${total:.2f}</b> (Прибуток: ${profit:.2f})", parse_mode="HTML")
                    except: pass
        
        await session.commit()
    
# --- БИТВА МАГНАТІВ ---

async def start_tycoon_battle(bot: Bot, scheduler):
    """Запускає битву між випадковими топами"""
    async with async_session() as session:
        # 1. Беремо топ-10 гравців
        top_users = (await session.execute(
            select(User).order_by(User.balance.desc()).limit(10)
        )).scalars().all()
        
        if len(top_users) < 2:
            return # Мало гравців для битви

        # 2. Обираємо двох випадкових
        p1, p2 = random.sample(top_users, 2)
        
        # 3. Створюємо битву на 20 хвилин
        end_time = datetime.utcnow() + timedelta(minutes=20)
        
        battle = TycoonBattle(
            player1_id=p1.id,
            player2_id=p2.id,
            p1_start_balance=float(p1.balance),
            p2_start_balance=float(p2.balance),
            end_time=end_time,
            is_active=True
        )
        session.add(battle)
        await session.commit()
        
        # 4. Сповіщаємо всіх (через broadcast логіку або в чат)
        text = (
            f"⚔️ <b>БИТВА МАГНАТІВ ПОЧАЛАСЯ!</b> ⚔️\n\n"
            f"🤼 У лівому куті: <b>{p1.full_name}</b>\n"
            f"🤼 У правому куті: <b>{p2.full_name}</b>\n\n"
            f"⏱ Час: <b>20 хвилин</b>\n"
            f"🏆 Ціль: Заробити найбільше грошей за цей час!\n\n"
            f"👇 <b>Робіть ставки на переможця:</b>\n"
            f"<code>/betplayer @{p1.username or p1.telegram_id} 500</code>\n"
            f"<code>/betplayer @{p2.username or p2.telegram_id} 500</code>"
        )
        
        # Розсилаємо (спрощено: просто в консоль або адмінам, 
        # але краще додати users loop як у broadcast, тут для прикладу всім адмінам)
        for admin_id in ADMIN_IDS:
             try: await bot.send_message(admin_id, text, parse_mode="HTML")
             except: pass
             
        # Плануємо кінець битви
        scheduler.add_job(end_tycoon_battle, "date", run_date=end_time, args=[bot, battle.id])

async def end_tycoon_battle(bot: Bot, battle_id: int):
    """Завершує битву і роздає нагороди"""
    async with async_session() as session:
        battle = await session.get(TycoonBattle, battle_id)
        if not battle or not battle.is_active:
            return
            
        battle.is_active = False
        
        p1 = await session.get(User, battle.player1_id)
        p2 = await session.get(User, battle.player2_id)
        
        # Рахуємо прибуток (Current - Start)
        p1_profit = float(p1.balance) - float(battle.p1_start_balance)
        p2_profit = float(p2.balance) - float(battle.p2_start_balance)
        
        winner_id = None
        loser_id = None
        
        if p1_profit > p2_profit:
            winner_id = p1.id
            winner_name = p1.full_name
            loser_id = p2.id
        elif p2_profit > p1_profit:
            winner_id = p2.id
            winner_name = p2.full_name
            loser_id = p1.id
        else:
            winner_name = "Нічия"

        result_text = (
            f"🏁 <b>БИТВА ЗАВЕРШЕНА!</b>\n\n"
            f"🥇 Переможець: <b>{winner_name}</b>\n"
            f"📈 {p1.full_name}: ${p1_profit:,.2f}\n"
            f"📈 {p2.full_name}: ${p2_profit:,.2f}\n"
        )

        # Виплачуємо ставки
        if winner_id:
            bets = (await session.execute(
                select(PlayerBet).where(PlayerBet.battle_id == battle.id)
            )).scalars().all()
            
            for bet in bets:
                user = await session.get(User, bet.user_id)
                if bet.target_player_id == winner_id:
                    # Коефіцієнт 2x
                    win_amount = float(bet.amount) * 2
                    user.balance = float(user.balance) + win_amount
                    try:
                        await bot.send_message(user.telegram_id, f"💰 Твоя ставка зіграла! Виграш: ${win_amount}")
                    except: pass
        
        await session.commit()
        
        # Сповіщаємо адмінів (або всіх)
        for admin_id in ADMIN_IDS:
             try: await bot.send_message(admin_id, result_text, parse_mode="HTML")
             except: pass