"""
Система колекційних карт для мем-акцій
"""
import random
from sqlalchemy import select, func
from database import async_session
from aiogram import Bot
from models import User, Meme, CollectionCard, UserCollection

# --- КОНФІГУРАЦІЯ РІДКОСТІ ---
# Я трохи підняв шанси для тесту (Common 1% -> 5%). Можна змінити назад.
RARITY_CONFIG = {
    "common": {
        "emoji": "⚪️",
        "chance": 0.05,     # 5% (було 0.01)
        "multiplier": 1.05,
        "color": "білий"
    },
    "rare": {
        "emoji": "🔵",
        "chance": 0.02,     # 2% (було 0.005)
        "multiplier": 1.15,
        "color": "синій"
    },
    "epic": {
        "emoji": "🟣",
        "chance": 0.005,    # 0.5% (було 0.001)
        "multiplier": 1.30,
        "color": "фіолетовий"
    },
    "legendary": {
        "emoji": "🟡",
        "chance": 0.001,    # 0.1% (було 0.0001)
        "multiplier": 1.50,
        "color": "золотий"
    }
}

# --- ДОПОМІЖНА ФУНКЦІЯ СТВОРЕННЯ КАРТ ---
async def create_cards_for_meme(session, meme):
    """Генерує 4 типи карт для переданого об'єкта Meme"""
    # Перевіряємо, чи вже є карти для цього мему
    existing = (await session.execute(
        select(CollectionCard).where(CollectionCard.meme_id == meme.id)
    )).first()
    
    if existing:
        return # Карти вже є

    variants = [
        ("common", f"Звичайна {meme.ticker}"),
        ("rare", f"Рідкісна {meme.ticker}"),
        ("epic", f"Епічна {meme.ticker}"),
        ("legendary", f"Легендарна {meme.ticker}")
    ]
    
    for rarity, name in variants:
        config = RARITY_CONFIG[rarity]
        card = CollectionCard(
            meme_id=meme.id,
            rarity=rarity,
            name=name,
            emoji=config["emoji"],
            drop_chance=config["chance"],
            bonus_multiplier=config["multiplier"]
        )
        session.add(card)

# --- ОСНОВНІ ФУНКЦІЇ ---

async def initialize_collection_cards():
    """Створює колекційні карти при старті, якщо їх немає"""
    async with async_session() as session:
        memes = (await session.execute(select(Meme))).scalars().all()
        
        for meme in memes:
            await create_cards_for_meme(session, meme)
        
        await session.commit()

async def try_drop_card(user_id: int, meme_id: int, bot: Bot) -> bool:
    """Перевіряє дроп карти при покупці акції"""
    async with async_session() as session:
        # Отримуємо карти цього мему
        cards = (await session.execute(
            select(CollectionCard).where(CollectionCard.meme_id == meme_id)
        )).scalars().all()
        
        # ЯКЩО КАРТ НЕМАЄ (наприклад, нова акція) - Створити їх на льоту!
        if not cards:
            meme = await session.get(Meme, meme_id)
            if meme:
                await create_cards_for_meme(session, meme)
                await session.commit()
                # Знову отримуємо карти
                cards = (await session.execute(
                    select(CollectionCard).where(CollectionCard.meme_id == meme_id)
                )).scalars().all()
            else:
                return False

        if not cards:
            return False
        
        # Сортуємо: Legendary перевіряємо першою, Common - останньою
        # Але тут логіка така: ми робимо roll для КОЖНОЇ карти окремо.
        # Можна виграти кілька карт за раз (теоретично).
        cards = sorted(cards, key=lambda x: x.drop_chance) # Від найменшого шансу (legendary) до найбільшого? 
        # Ні, sorted по зростанню numbers. Legendary (0.001) -> Common (0.05).
        
        for card in cards:
            roll = random.random() # 0.0 до 1.0
            
            if roll < float(card.drop_chance):
                # КАРТА ВИПАЛА!
                
                # Перевірка на дублікат
                existing = (await session.execute(
                    select(UserCollection).where(
                        UserCollection.user_id == user_id,
                        UserCollection.card_id == card.id
                    )
                )).scalar_one_or_none()
                
                user = await session.get(User, user_id)
                meme = await session.get(Meme, meme_id) # Отримуємо об'єкт Meme для повідомлення
                
                if existing:
                    # Компенсація за дублікат
                    duplicate_bonus = 100 * float(card.bonus_multiplier)
                    user.balance = float(user.balance) + duplicate_bonus
                    await session.commit()
                    
                    try:
                        await bot.send_message(
                            user.telegram_id,
                            f"🔁 <b>Дублікат карти!</b>\n"
                            f"{card.emoji} <b>{card.name}</b>\n"
                            f"Компенсація: <b>${duplicate_bonus:.0f}</b>",
                            parse_mode="HTML"
                        )
                    except: pass
                    return True # Повертаємо True, щоб не спамити (одна карта за раз)
                
                # Нова карта
                user_card = UserCollection(
                    user_id=user_id,
                    card_id=card.id,
                    is_new=True
                )
                session.add(user_card)
                await session.commit()
                
                # Красиве повідомлення
                rarity_emoji = "✨"
                color_name = RARITY_CONFIG[card.rarity]['color'].upper()
                
                try:
                    await bot.send_message(
                        user.telegram_id,
                        f"{rarity_emoji} <b>НОВА КОЛЕКЦІЙНА КАРТА!</b> {rarity_emoji}\n\n"
                        f"{card.emoji} <b>{card.name}</b>\n"
                        f"🎨 Рідкість: <b>{color_name}</b>\n"
                        f"📈 Бонус до прибутку: <b>+{(card.bonus_multiplier - 1) * 100:.0f}%</b>\n\n"
                        f"💡 Отримано при покупці {meme.ticker}",
                        parse_mode="HTML"
                    )
                except: pass
                
                return True # Випала одна карта - виходимо (щоб не випало 4 за раз)
        
        return False

# ... (Решта функцій get_user_collection і т.д. залишаються без змін) ...
async def get_user_collection(user_id: int) -> dict:
    """Повертає колекцію користувача з статистикою"""
    async with async_session() as session:
        # Отримуємо карти користувача
        user_cards = (await session.execute(
            select(UserCollection).where(UserCollection.user_id == user_id)
        )).scalars().all()
        
        # Загальна кількість карт у грі
        total_cards = (await session.execute(
            select(func.count(CollectionCard.id))
        )).scalar()
        
        # Збираємо деталі
        cards_data = []
        by_rarity = {"common": 0, "rare": 0, "epic": 0, "legendary": 0}
        total_bonus = 1.0
        
        for uc in user_cards:
            card = await session.get(CollectionCard, uc.card_id)
            meme = await session.get(Meme, card.meme_id)
            
            cards_data.append({
                'id': card.id,
                'name': card.name,
                'emoji': card.emoji,
                'rarity': card.rarity,
                'ticker': meme.ticker,
                'bonus': card.bonus_multiplier,
                'obtained': uc.obtained_at,
                'is_new': uc.is_new
            })
            
            by_rarity[card.rarity] += 1
            total_bonus += (card.bonus_multiplier - 1)
        
        return {
            'cards': sorted(cards_data, key=lambda x: x['obtained'], reverse=True),
            'total': len(user_cards),
            'by_rarity': by_rarity,
            'completion': (len(user_cards) / total_cards * 100) if total_cards > 0 else 0,
            'total_bonus': total_bonus
        }


async def apply_collection_bonus(user_id: int, base_profit: float) -> float:
    """Застосовує бонус від колекції до прибутку"""
    async with async_session() as session:
        user_cards = (await session.execute(
            select(UserCollection).where(UserCollection.user_id == user_id)
        )).scalars().all()
        
        total_multiplier = 1.0
        
        for uc in user_cards:
            card = await session.get(CollectionCard, uc.card_id)
            # Додаємо бонус
            total_multiplier += (card.bonus_multiplier - 1)
        
        return base_profit * total_multiplier


async def mark_cards_as_seen(user_id: int):
    """Позначає всі карти користувача як переглянуті"""
    async with async_session() as session:
        cards = (await session.execute(
            select(UserCollection).where(
                UserCollection.user_id == user_id,
                UserCollection.is_new == True
            )
        )).scalars().all()
        
        for card in cards:
            card.is_new = False
        
        await session.commit()


async def get_collection_stats() -> dict:
    """Повертає глобальну статистику по картам"""
    async with async_session() as session:
        total_cards = (await session.execute(
            select(func.count(CollectionCard.id))
        )).scalar()
        
        total_collected = (await session.execute(
            select(func.count(UserCollection.id))
        )).scalar()
        
        # Найрідкісніша отримана карта
        legendary_count = (await session.execute(
            select(func.count(UserCollection.id))
            .join(CollectionCard)
            .where(CollectionCard.rarity == "legendary")
        )).scalar()
        
        user_count = (await session.execute(select(func.count(User.id)))).scalar()
        avg = total_collected / max(1, user_count)

        return {
            'total_cards': total_cards,
            'total_collected': total_collected,
            'legendary_obtained': legendary_count,
            'avg_per_user': avg
        }