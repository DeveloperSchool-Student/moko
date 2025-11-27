"""
Система колекційних карт для мем-акцій
"""
import random
from sqlalchemy import select, func
from database import async_session
from aiogram import Bot

# --- FIX: Import models from models.py instead of defining them here ---
from models import User, Meme, CollectionCard, UserCollection

# --- КОНФІГУРАЦІЯ РІДКОСТІ ---

RARITY_CONFIG = {
    "common": {
        "emoji": "⚪️",
        "chance": 0.01,     # 1%
        "multiplier": 1.05,  # +5% до прибутку
        "color": "білий"
    },
    "rare": {
        "emoji": "🔵",
        "chance": 0.005,    # 0.5%
        "multiplier": 1.15,
        "color": "синій"
    },
    "epic": {
        "emoji": "🟣",
        "chance": 0.001,    # 0.1%
        "multiplier": 1.30,
        "color": "фіолетовий"
    },
    "legendary": {
        "emoji": "🟡",
        "chance": 0.0001,   # 0.01%
        "multiplier": 1.50,
        "color": "золотий"
    }
}

# --- ОСНОВНІ ФУНКЦІЇ ---

async def initialize_collection_cards():
    """Створює колекційні карти для всіх мемів (викликати при старті бота)"""
    async with async_session() as session:
        # Перевіряємо, чи вже є карти
        existing = (await session.execute(select(CollectionCard))).scalars().first()
        if existing:
            return  # Вже ініціалізовано
        
        # Отримуємо всі меми
        memes = (await session.execute(select(Meme))).scalars().all()
        
        for meme in memes:
            # Створюємо 4 варіації для кожного мему
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
        
        await session.commit()


async def try_drop_card(user_id: int, meme_id: int, bot: Bot) -> bool:
    """
    Перевіряє дроп карти при покупці акції
    """
    async with async_session() as session:
        # Отримуємо всі можливі карти цього мему
        cards = (await session.execute(
            select(CollectionCard).where(CollectionCard.meme_id == meme_id)
        )).scalars().all()
        
        if not cards:
            return False
        
        # Сортуємо від legendary до common
        cards = sorted(cards, key=lambda x: x.drop_chance)
        
        # Перевіряємо дроп для кожної рідкості
        for card in cards:
            roll = random.random()
            
            if roll < card.drop_chance:
                # КАРТА ВИПАЛА! 🎉
                
                # Перевіряємо, чи вже є така карта у користувача
                existing = (await session.execute(
                    select(UserCollection).where(
                        UserCollection.user_id == user_id,
                        UserCollection.card_id == card.id
                    )
                )).scalar_one_or_none()
                
                if existing:
                    # Дублікат
                    user = (await session.execute(
                        select(User).where(User.id == user_id)
                    )).scalar_one()
                    
                    duplicate_bonus = 100 * float(card.bonus_multiplier) # Fixed type casting
                    user.balance = float(user.balance) + duplicate_bonus
                    
                    await session.commit()
                    
                    await bot.send_message(
                        user.telegram_id,
                        f"🔁 <b>Дублікат карти!</b>\n\n"
                        f"{card.emoji} <b>{card.name}</b>\n"
                        f"Ти вже маєш цю карту.\n"
                        f"Компенсація: <b>${duplicate_bonus:.0f}</b>",
                        parse_mode="HTML"
                    )
                    return True
                
                # Додаємо нову карту
                user_card = UserCollection(
                    user_id=user_id,
                    card_id=card.id,
                    is_new=True
                )
                session.add(user_card)
                await session.commit()
                
                # Отримуємо користувача для повідомлення
                user = (await session.execute(
                    select(User).where(User.id == user_id)
                )).scalar_one()
                
                meme = await session.get(Meme, meme_id)
                
                # Відправляємо круте повідомлення
                rarity_emoji = "✨" * (4 - list(RARITY_CONFIG.keys()).index(card.rarity))
                
                await bot.send_message(
                    user.telegram_id,
                    f"{rarity_emoji}\n"
                    f"🎊 <b>КОЛЕКЦІЙНА КАРТА!</b> 🎊\n"
                    f"{rarity_emoji}\n\n"
                    f"{card.emoji} <b>{card.name}</b>\n"
                    f"🎨 Рідкість: <b>{RARITY_CONFIG[card.rarity]['color'].upper()}</b>\n"
                    f"📈 Бонус прибутку: <b>+{(card.bonus_multiplier - 1) * 100:.0f}%</b>\n\n"
                    f"💡 Цю карту отримано при покупці {meme.ticker}!\n"
                    f"Перевір свою колекцію: /collection",
                    parse_mode="HTML"
                )
                
                return True
        
        return False


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