import asyncio
import os
import socket
import time

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "").strip()
PROXY_URL = os.getenv("PROXY_URL", "").strip() or None

async def main():
    print("=== Nexa Search: проверка Telegram API ===")
    print("PROXY_URL:", PROXY_URL or "не указан")
    try:
        ip = socket.gethostbyname("api.telegram.org")
        print("DNS api.telegram.org ->", ip)
    except Exception as e:
        print("DNS ошибка:", e)

    if not TOKEN or TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        print("❌ Укажи BOT_TOKEN в .env")
        return

    session = AiohttpSession(proxy=PROXY_URL) if PROXY_URL else AiohttpSession()
    bot = Bot(TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    start = time.time()
    try:
        me = await bot.get_me()
        print("HTTP статус: 200")
        print("Бот:", f"@{me.username}", "ID:", me.id)
        print("Время:", round(time.time() - start, 2), "сек")
        print("✅✅ Соединение работает. Можно запускать bot.py")
    except Exception as e:
        print("❌ Соединение не работает:", repr(e))
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
