"""Telegram bot initialization."""
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings

# Initialize bot
bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

# Initialize dispatcher with FSM storage
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
