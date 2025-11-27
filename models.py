from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, String, DateTime, ForeignKey, Integer, UniqueConstraint, Boolean, Numeric
from datetime import datetime
from database import Base
from decimal import Decimal

# --- КОРИСТУВАЧІ ТА КЛАНИ ---

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128), nullable=True)
    
    # Фінанси (Numeric для точності)
    balance: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=500.0)
    bank_balance: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0.0)
    deposit_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0.0)
    
    # Маржинальна торгівля
    loan_balance: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0.0)
    
    # Статуси та дати
    last_bonus_date: Mapped[datetime] = mapped_column(DateTime, nullable=True, index=True)
    last_interest_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    deposit_end_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    has_license: Mapped[bool] = mapped_column(Boolean, default=False)
    vip_until: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    custom_title: Mapped[str] = mapped_column(String(32), nullable=True)
    clan_id: Mapped[int] = mapped_column(ForeignKey("clans.id"), nullable=True, index=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    referrer_id: Mapped[int] = mapped_column(BigInteger, nullable=True, index=True)

class Clan(Base):
    __tablename__ = "clans"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    treasury: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0.0)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0.0)

# --- РИНОК АКЦІЙ ---

class Meme(Base):
    __tablename__ = "memes"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    current_price: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    volatility: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    image_url: Mapped[str] = mapped_column(String(256), nullable=True)
    manipulation_mode: Mapped[str] = mapped_column(String(10), default="NONE")
    manipulation_remaining: Mapped[int] = mapped_column(Integer, default=0)
    trade_volume: Mapped[int] = mapped_column(Integer, default=0)
    total_supply: Mapped[int] = mapped_column(Integer, default=1_000_000)
    available_supply: Mapped[int] = mapped_column(Integer, default=1_000_000)

class Portfolio(Base):
    __tablename__ = "portfolio"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    meme_id: Mapped[int] = mapped_column(ForeignKey("memes.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint('user_id', 'meme_id', name='_user_meme_uc'),)

class PriceHistory(Base):
    __tablename__ = "price_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    meme_id: Mapped[int] = mapped_column(ForeignKey("memes.id"), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class News(Base):
    __tablename__ = "news"
    id: Mapped[int] = mapped_column(primary_key=True)
    meme_id: Mapped[int] = mapped_column(ForeignKey("memes.id"), index=True, nullable=True)
    ticker: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(String(256))
    change_percent: Mapped[float] = mapped_column(Numeric(10, 2))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

# --- IPO ---

class IPO(Base):
    __tablename__ = "ipos"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), unique=True)
    start_price: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    total_supply: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    end_time: Mapped[datetime] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    image_url: Mapped[str] = mapped_column(String(256), nullable=True)

class IPOApplication(Base):
    __tablename__ = "ipo_applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    ipo_id: Mapped[int] = mapped_column(ForeignKey("ipos.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount_invested: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    shares_requested: Mapped[int] = mapped_column(Integer)

# --- МАГАЗИН ТА ПРЕДМЕТИ ---

class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    emoji: Mapped[str] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(20), index=True)

class UserItem(Base):
    __tablename__ = "user_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    __table_args__ = (UniqueConstraint('user_id', 'item_id', name='_user_item_uc'),)

# --- ІГРОВІ МЕХАНІКИ (СТАВКИ, ЛОТЕРЕЯ, БИТВИ) ---

class Bet(Base):
    __tablename__ = "bets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    meme_id: Mapped[int] = mapped_column(ForeignKey("memes.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    direction: Mapped[str] = mapped_column(String(5))
    start_price: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    end_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

class LotteryTicket(Base):
    __tablename__ = "lottery_tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    purchased_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class TycoonBattle(Base):
    __tablename__ = "battles"
    id: Mapped[int] = mapped_column(primary_key=True)
    player1_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    player2_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    p1_start_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    p2_start_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    start_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    end_time: Mapped[datetime] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class PlayerBet(Base):
    __tablename__ = "player_bets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    battle_id: Mapped[int] = mapped_column(ForeignKey("battles.id"), index=True)
    target_player_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))

# --- КОЛЕКЦІЙНІ КАРТИ ---

class CollectionCard(Base):
    __tablename__ = "collection_cards"
    id: Mapped[int] = mapped_column(primary_key=True)
    meme_id: Mapped[int] = mapped_column(ForeignKey("memes.id"), index=True)
    rarity: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(64))
    emoji: Mapped[str] = mapped_column(String(10))
    drop_chance: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    bonus_multiplier: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("1.0"))

class UserCollection(Base):
    __tablename__ = "user_collections"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("collection_cards.id"), index=True)
    obtained_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_new: Mapped[bool] = mapped_column(Boolean, default=True)

# --- ПРОМОКОДИ (БУЛИ ВІДСУТНІ) ---

class PromoCode(Base):
    __tablename__ = "promocodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    valid_until: Mapped[datetime] = mapped_column(DateTime)

class UsedPromo(Base):
    __tablename__ = "used_promos"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    promo_id: Mapped[int] = mapped_column(ForeignKey("promocodes.id"), index=True)
    activated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('user_id', 'promo_id', name='_user_promo_uc'),)