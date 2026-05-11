import asyncio
import html
import os
import random
import re
import string
import time
from datetime import datetime
from typing import Optional

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    FSInputFile,
)
from dotenv import load_dotenv

import database as db

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
APP_NAME = os.getenv("APP_NAME", "Nexa Search").strip()
PREMIUM_NAME = os.getenv("PREMIUM_NAME", "Nexa Premium").strip()
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "IKLINYSHKA").strip().lstrip("@")
ADMIN_IDS = {1805647541} | {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()}
PREMIUM_IDS = {int(x) for x in os.getenv("PREMIUM_IDS", "").replace(" ", "").split(",") if x.isdigit()}
FREE_ATTEMPTS = int(os.getenv("FREE_ATTEMPTS", "3"))
DAILY_RESTORE_ATTEMPTS = int(os.getenv("DAILY_RESTORE_ATTEMPTS", "4"))
REFERRAL_BONUS_ATTEMPTS = int(os.getenv("REFERRAL_BONUS_ATTEMPTS", "2"))
SEARCH_COOLDOWN_SECONDS = int(os.getenv("SEARCH_COOLDOWN_SECONDS", "3"))
SEARCH_ANIMATION_SECONDS = int(os.getenv("SEARCH_ANIMATION_SECONDS", "1"))
FAST_SEARCH_BATCH = int(os.getenv("FAST_SEARCH_BATCH", "32"))
MAX_SEARCH_TRIES = int(os.getenv("MAX_SEARCH_TRIES", "3000"))
BEAUTY_FIRST_TRIES = int(os.getenv("BEAUTY_FIRST_TRIES", "350"))
# По умолчанию строгий режим: сначала красивые варианты, затем более широкий подбор.
# Доп. web-проверки можно включить в .env, но они часто дают ложные отказы из-за антибота/заглушек.
WEB_DOUBLE_CHECK = os.getenv("WEB_DOUBLE_CHECK", "1").strip().lower() in {"1", "true", "yes", "on"}
FRAGMENT_DOUBLE_CHECK = os.getenv("FRAGMENT_DOUBLE_CHECK", "1").strip().lower() in {"1", "true", "yes", "on"}
STRICT_USERNAME_CHECK = os.getenv("STRICT_USERNAME_CHECK", "1").strip().lower() in {"1", "true", "yes", "on"}
# Ускорение: сначала быстрый отсев пачкой через Bot API, затем строгая финальная сверка только для кандидатов.
STRICT_FINAL_ONLY = os.getenv("STRICT_FINAL_ONLY", "1").strip().lower() in {"1", "true", "yes", "on"}
FINAL_VERIFY_LIMIT = int(os.getenv("FINAL_VERIFY_LIMIT", "10"))
DEFAULT_SEARCH_MODE = os.getenv("DEFAULT_SEARCH_MODE", "turbo").strip().lower()
WELCOME_PHOTO_PATH = os.getenv("WELCOME_PHOTO_PATH", "welcome.jpg").strip()
MAX_SEARCH_SECONDS = int(os.getenv("MAX_SEARCH_SECONDS", "120"))
SEARCH_MODES = {"turbo", "balance", "strict", "beauty"}

MODE_PRESETS = {
    # v33: режимы настроены так, чтобы бот штатно отдавал результат, а не зависал на слишком строгих web-проверках.
    # Telegram Bot API остаётся обязательным быстрым фильтром во всех режимах.
    "turbo": {
        "title": "⚡ Турбо",
        "short": "самый быстрый вывод результата",
        "eta": "до 20 сек.; быстрый подбор + финальная сверка t.me/Fragment.",
        "batch": 260,
        "max_tries": 70000,
        "beauty_tries": 8,
        "final_limit": 25,
        "time_limit": 20,
        "web": True,
        "fragment": True,
        "strict": True,
    },
    "balance": {
        "title": "✅ Баланс",
        "short": "быстро + нормальная сверка",
        "eta": "до 20 сек.; быстрый подбор + t.me/Fragment без зависания.",
        "batch": 360,
        "max_tries": 60000,
        "beauty_tries": 25,
        "final_limit": 20,
        "time_limit": 20,
        "web": True,
        "fragment": True,
        "strict": True,
    },
    "strict": {
        "title": "🛡 Строгий",
        "short": "дольше, но аккуратнее",
        "eta": "до 20 сек.; больше сверок, но без минутного зависания.",
        "batch": 180,
        "max_tries": 60000,
        "beauty_tries": 60,
        "final_limit": 20,
        "time_limit": 20,
        "web": True,
        "fragment": True,
        "strict": True,
    },
    "beauty": {
        "title": "💎 Красивый",
        "short": "сначала слово/вайб, потом запасной генератор",
        "eta": "до 20 сек.; сначала красивые связки, затем быстрый запасной подбор.",
        "batch": 320,
        "max_tries": 60000,
        "beauty_tries": 80,
        "final_limit": 20,
        "time_limit": 20,
        "web": True,
        "fragment": True,
        "strict": True,
    },
}
POLLING_RETRY_SECONDS = int(os.getenv("POLLING_RETRY_SECONDS", "10"))
PROXY_URL = os.getenv("PROXY_URL", "").strip() or None
PRICE_PREMIUM_1_DAY = int(os.getenv("PRICE_PREMIUM_1_DAY", "99"))
PRICE_PREMIUM_7_DAYS = int(os.getenv("PRICE_PREMIUM_7_DAYS", "349"))
PRICE_PREMIUM_14_DAYS = int(os.getenv("PRICE_PREMIUM_14_DAYS", "599"))
PRICE_PREMIUM_31_DAYS = int(os.getenv("PRICE_PREMIUM_31_DAYS", "999"))
PRICE_PREMIUM_60_DAYS = int(os.getenv("PRICE_PREMIUM_60_DAYS", "1699"))
PRICE_PREMIUM_180_DAYS = int(os.getenv("PRICE_PREMIUM_180_DAYS", "3499"))
PRICE_PREMIUM_365_DAYS = int(os.getenv("PRICE_PREMIUM_365_DAYS", "5999"))

def premium_price_for_days(days: int) -> int:
    return {
        1: PRICE_PREMIUM_1_DAY,
        7: PRICE_PREMIUM_7_DAYS,
        14: PRICE_PREMIUM_14_DAYS,
        31: PRICE_PREMIUM_31_DAYS,
        60: PRICE_PREMIUM_60_DAYS,
        180: PRICE_PREMIUM_180_DAYS,
        365: PRICE_PREMIUM_365_DAYS,
    }.get(days, PRICE_PREMIUM_31_DAYS)


def parse_premium_duration(raw: str | None) -> tuple[int | None, str]:
    """Admin duration parser. None = forever. Supports 1h, 1d, 1w, 1m, 30d, 365d."""
    if not raw:
        return None, "навсегда"
    value = raw.strip().lower().replace(" ", "")
    if value in {"forever", "permanent", "perm", "inf", "infinite", "навсегда", "вечный", "вечка"}:
        return None, "навсегда"
    m = re.fullmatch(r"(\d+)(h|ч|час|часов|d|д|день|дней|w|н|нед|week|weeks|m|м|мес|month|months|y|г|год|лет)?", value)
    if not m:
        raise ValueError("bad_duration")
    num = int(m.group(1))
    unit = m.group(2) or "d"
    if num <= 0:
        raise ValueError("bad_duration")
    if unit in {"h", "ч", "час", "часов"}:
        return num * 3600, f"{num} ч."
    if unit in {"d", "д", "день", "дней"}:
        return num * 86400, f"{num} д."
    if unit in {"w", "н", "нед", "week", "weeks"}:
        return num * 7 * 86400, f"{num} нед."
    if unit in {"m", "м", "мес", "month", "months"}:
        return num * 31 * 86400, f"{num} мес."
    if unit in {"y", "г", "год", "лет"}:
        return num * 365 * 86400, f"{num} г."
    raise ValueError("bad_duration")

if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
    raise SystemExit("Укажи BOT_TOKEN в .env")

session = AiohttpSession(proxy=PROXY_URL) if PROXY_URL else AiohttpSession()
bot = Bot(BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
BOT_USERNAME: Optional[str] = None

SEARCH_CFG: dict[int, dict[str, int | bool]] = {}

ROOTS = [
    "vibe", "luna", "moon", "star", "nova", "mira", "kira", "nexa", "aura", "soft", "mimi", "neko",
    "yuki", "runa", "lily", "miko", "sora", "zora", "kira", "miya", "navi", "faye", "lumi", "noir",
    "ruby", "koko", "riko", "mina", "alisa", "dara", "lira", "niko", "suki", "vivi", "kity", "toki",
    "angel", "dream", "glow", "flow", "pure", "cute", "bunny", "cloud", "pixel", "fairy", "velvet",
]
PREFIXES = ["x", "i", "my", "ur", "the", "im", "go", "hi", "yo"]
SUFFIXES = ["ly", "ix", "io", "er", "in", "on", "ex", "is", "ua", "me", "go", "xo", "ka", "ya", "ny", "fy"]

# Генератор без бездушного набора букв: слово + мягкий хвост / короткая связка.
WORD_BASES = [
    "luna", "moon", "star", "nova", "mira", "kira", "nexa", "aura", "soft", "mimi", "neko",
    "yuki", "runa", "lily", "miko", "sora", "zora", "miya", "navi", "faye", "lumi", "noir",
    "ruby", "koko", "riko", "mina", "lira", "niko", "suki", "vivi", "toki", "angel",
    "dream", "glow", "flow", "pure", "cute", "bunny", "cloud", "pixel", "fairy", "velvet",
    "honey", "charm", "mint", "pearl", "dolly", "kitty", "milky", "cosy", "lovely", "berry"
]
WORD_TAILS = {
    0: [""],
    1: ["x", "y", "i", "o", "a", "u"],
    2: ["ly", "io", "me", "go", "xo", "ka", "ya", "ny", "is", "ix"],
    3: ["luv", "ily", "owo", "kio", "mio", "nya", "sky", "ray"],
    4: ["core", "wave", "land", "soft", "star"],
}
VOWELS = "aeiouy"
CONSONANTS = "bcdfghklmnprstvwxyz"

USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{4,31}$")
# Строгий локальный фильтр для публичного имени профиля Telegram.
# Он отсекает варианты, которые Telegram может показать как «Некорректное имя пользователя».
PROFILE_USERNAME_RE = re.compile(r"^[a-z][a-z0-9]{4,31}$")
BAD_RESERVED_PARTS = ("telegram", "support", "admin", "helpdesk")


def clean_check_username(username: str) -> str:
    return (username or "").strip().lstrip("@").lower()


def is_unsettable_profile_username(username: str) -> bool:
    cand = clean_check_username(username)
    if not USERNAME_RE.match(cand):
        return True
    if any(part in cand for part in BAD_RESERVED_PARTS):
        return True
    if "__" in cand or cand.endswith("_"):
        return True
    if len(set(cand.replace("_", ""))) <= 2:
        return True
    if re.search(r"(.)\1\1", cand):
        return True
    return False


def is_valid_profile_username(candidate: str, length: int, with_digits: bool) -> bool:
    cand = candidate.strip().lower()
    if len(cand) != length:
        return False
    if not PROFILE_USERNAME_RE.match(cand):
        return False
    if not with_digits and not cand.isalpha():
        return False
    if any(part in cand for part in BAD_RESERVED_PARTS):
        return False
    # Убираем совсем мусорные или часто отклоняемые варианты.
    if len(set(cand)) <= 2:
        return False
    if re.search(r"(.)\1\1", cand):
        return False
    return True


def ts() -> int:
    return int(time.time())


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_premium(user) -> bool:
    return bool(user and int(user["premium_until"] or 0) > ts())


def premium_text(user) -> str:
    if not is_premium(user):
        return "обычный"
    until = int(user["premium_until"])
    if until > 4000000000:
        return "Premium навсегда"
    left = max(0, until - ts())
    if left < 86400:
        left_text = f"осталось {left // 3600} ч. {(left % 3600) // 60} мин."
    else:
        left_text = f"осталось {left // 86400} д."
    return "Premium до " + datetime.fromtimestamp(until).strftime("%d.%m.%Y %H:%M") + f" ({left_text})"




def normalize_search_mode(mode: object) -> str:
    mode = str(mode or DEFAULT_SEARCH_MODE).strip().lower()
    return mode if mode in SEARCH_MODES else "turbo"


def mode_title(mode: object) -> str:
    mode = normalize_search_mode(mode)
    return MODE_PRESETS[mode]["title"]


def mode_eta(mode: object) -> str:
    mode = normalize_search_mode(mode)
    return MODE_PRESETS[mode]["eta"]


def mode_description_text() -> str:
    return (
        "<b>🚀 Режим поиска</b>\n"
        "<i>Выбери стиль работы под себя: быстрее, точнее или красивее.</i>\n\n"
        "<blockquote>"
        "<b>⚡ Турбо</b>\n"
        "Самый быстрый реролл. Бот старается отдать вариант почти сразу.\n"
        "⏱ Ожидание: <code>2–15 сек.</code>\n"
        "Лучше для частого реролла.\n"
        "</blockquote>\n\n"
        "<blockquote>"
        "<b>✅ Баланс</b>\n"
        "Золотая середина: быстро, но с дополнительной сверкой.\n"
        "⏱ Ожидание: <code>20–45 сек.</code>\n"
        "Лучше для обычного поиска.\n"
        "</blockquote>\n\n"
        "<blockquote>"
        "<b>🛡 Строгий</b>\n"
        "Больше проверок перед выдачей результата.\n"
        "⏱ Ожидание: <code>45–90 сек.</code>\n"
        "Лучше, если важна точность.\n"
        "</blockquote>\n\n"
        "<blockquote>"
        "<b>💎 Красивый</b>\n"
        "Сначала пробует мягкие и читабельные связки: слово + аккуратный хвост.\n"
        "⏱ Ожидание: <code>30–60 сек.</code>\n"
        "Лучше для красивого ника.\n"
        "</blockquote>\n\n"
        "<b>Важно:</b> если за лимит времени ничего не нашлось, жми <b>🔁 Искать ещё</b> — бот сделает новый реролл."
    )

def esc(value: object) -> str:
    return html.escape(str(value))


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
        for row in rows
    ])


def main_kb(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [("🚀 Быстрый поиск", "search_menu"), ("🚀 Режим", "mode_info")],
        [("👤 Профиль", "profile"), ("💎 Premium", "premium_menu")],
        [("🎁 Рефералка", "refs"), ("📌 Мои username", "my_names")],
        [("📄 Правила", "rules"), ("📩 Поддержка", "support")],
    ]
    if is_admin(user_id):
        rows.append([("⚙️ Админ панель", "admin")])
    return kb(rows)


def back_main_kb() -> InlineKeyboardMarkup:
    return kb([[("◀️ Главное меню", "main")]])


def search_menu_kb(user) -> InlineKeyboardMarkup:
    rows = [
        [("💎 5 символов", "len:5")],
        [("✨ 6 символов", "len:6"), ("🌙 7 символов", "len:7")],
        [("👤 Профиль", "profile"), ("📌 Мои ники", "my_names")],
        [("◀️ Главное меню", "main")],
    ]
    return kb(rows)


def digit_menu_kb(length: int) -> InlineKeyboardMarkup:
    return kb([
        [("🌿 Только буквы", f"digits:{length}:0")],
        [("🔢 Буквы + цифры", f"digits:{length}:1")],
        [("👤 Профиль", "profile"), ("💎 Premium", "premium_menu")],
        [("◀️ Назад", "search_menu")],
    ])



def mode_menu_kb(length: int, with_digits: bool) -> InlineKeyboardMarkup:
    return kb([
        [("⚡ Турбо", f"mode:{length}:{int(with_digits)}:turbo"), ("✅ Баланс", f"mode:{length}:{int(with_digits)}:balance")],
        [("🛡 Строгий", f"mode:{length}:{int(with_digits)}:strict"), ("💎 Красивый", f"mode:{length}:{int(with_digits)}:beauty")],
        [("◀️ Назад", f"len:{length}"), ("🏠 Главное меню", "main")],
    ])

def premium_kb() -> InlineKeyboardMarkup:
    return kb([
        [(f"⚡ 1 день — {PRICE_PREMIUM_1_DAY} ⭐", "buy:1"), (f"🌙 7 дней — {PRICE_PREMIUM_7_DAYS} ⭐", "buy:7")],
        [(f"💎 14 дней — {PRICE_PREMIUM_14_DAYS} ⭐", "buy:14")],
        [(f"👑 31 день — {PRICE_PREMIUM_31_DAYS} ⭐", "buy:31")],
        [(f"🚀 60 дней — {PRICE_PREMIUM_60_DAYS} ⭐", "buy:60")],
        [(f"🌌 180 дней — {PRICE_PREMIUM_180_DAYS} ⭐", "buy:180")],
        [(f"🪽 365 дней — {PRICE_PREMIUM_365_DAYS} ⭐", "buy:365")],
        [("🚀 Попробовать поиск", "search_menu")],
        [("🎁 Получить запросы бесплатно", "refs")],
        [("◀️ Главное меню", "main")],
    ])




def result_kb(username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Искать ещё", callback_data="do_search")],
        [InlineKeyboardButton(text="🌐 Открыть в Telegram", url=f"https://t.me/{username}")],
        [InlineKeyboardButton(text="🧩 Открыть на Fragment", url=f"https://fragment.com/username/{username}")],
        [InlineKeyboardButton(text="⚙️ Изменить настройки", callback_data="search_menu")],
        [InlineKeyboardButton(text="📌 Мои ники", callback_data="my_names"), InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main")],
    ])

def admin_kb() -> InlineKeyboardMarkup:
    return kb([
        [("📊 Статистика", "adm_stats"), ("👥 Пользователи", "adm_users")],
        [("📌 Найденные ники", "adm_found")],
        [("💎 Premium-команды", "adm_premium_help")],
        [("◀️ Главное меню", "main")],
    ])


async def safe_delete(chat_id: int, message_id: Optional[int]) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


async def clear_user_message(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        pass


async def screen(chat_id: int, user_id: int, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None) -> Message:
    user = db.get_user(user_id)
    last_id = int(user["last_msg_id"] or 0) if user else 0
    if last_id:
        try:
            msg = await bot.edit_message_text(chat_id=chat_id, message_id=last_id, text=text, reply_markup=reply_markup)
            return msg
        except Exception:
            await safe_delete(chat_id, last_id)
    msg = await bot.send_message(chat_id, text, reply_markup=reply_markup, disable_web_page_preview=True)
    db.save_last_msg(user_id, msg.message_id)
    return msg


async def send_main_menu(chat_id: int, user_id: int) -> Message:
    """Главное меню всегда отправляется с welcome-картинкой, если она есть."""
    user = db.get_user(user_id)
    last_id = int(user["last_msg_id"] or 0) if user else 0
    await safe_delete(chat_id, last_id)

    photo_path = WELCOME_PHOTO_PATH
    if not os.path.isabs(photo_path):
        photo_path = os.path.join(os.path.dirname(__file__), photo_path)

    if os.path.exists(photo_path):
        msg = await bot.send_photo(
            chat_id=chat_id,
            photo=FSInputFile(photo_path),
            caption=render_main(user),
            reply_markup=main_kb(user_id),
        )
    else:
        msg = await bot.send_message(chat_id, render_main(user), reply_markup=main_kb(user_id), disable_web_page_preview=True)
    db.save_last_msg(user_id, msg.message_id)
    return msg


async def answer_cb(call: CallbackQuery, text: Optional[str] = None, alert: bool = False) -> None:
    try:
        await call.answer(text or "", show_alert=alert)
    except Exception:
        pass


async def register_if_needed(user_id: int, first_name: str = "", username: str = "", ref_by: Optional[int] = None) -> None:
    user, created = db.ensure_user(user_id, first_name, username, ref_by, FREE_ATTEMPTS)
    if created and ref_by and ref_by != user_id and db.get_user(ref_by):
        db.record_referral(ref_by, REFERRAL_BONUS_ATTEMPTS)
        try:
            await bot.send_message(ref_by, f"🎁 По твоей ссылке пришёл новый пользователь. Начислено +{REFERRAL_BONUS_ATTEMPTS} запроса.")
        except Exception:
            pass
    # PREMIUM_IDS из .env — запасной список постоянного доступа.
    # Не перезаписываем активную временную подписку, чтобы /premium ID 1h/1d работал корректно.
    current = db.get_user(user_id)
    if user_id in PREMIUM_IDS and not is_premium(current):
        db.set_premium(user_id, None)


def parse_ref(args: Optional[str], user_id: int) -> Optional[int]:
    if not args:
        return None
    arg = args.strip()
    if arg.startswith("ref_"):
        arg = arg[4:]
    if arg.isdigit():
        rid = int(arg)
        if rid != user_id:
            return rid
    return None


def render_main(user) -> str:
    return (
        f"<b>🔎 {esc(APP_NAME)}</b>\n"
        "<i>красивый поиск свободных Telegram username</i>\n\n"
        "<b>Что умеет бот:</b>\n"
        "• подбирает аккуратные имена: слово + красивая связка;\n"
        "• проверяет Telegram, web-страницу t.me и Fragment;\n"
        "• не показывает варианты, которые уже заняты человеком или выставлены на Fragment;\n"
        "• показывает результат в формате <code>@name</code>;\n"
        "• сохраняет последние найденные варианты;\n"
        "• чистит чат и работает в одном красивом экране;\n"
        "• поддерживает лимиты, Premium и рефералку.\n\n"
        "<b>Режим:</b> быстрый поиск без искусственного ожидания 10 секунд.\n"
        f"<b>Статус:</b> {esc(premium_text(user))}\n"
        f"<b>Запросов:</b> <code>{int(user['attempts'])}</code>"
    )


def render_profile(user) -> str:
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{user['user_id']}" if BOT_USERNAME else "бот ещё запускается"
    return (
        "<b>👤 Личный кабинет</b>\n\n"
        f"<b>ID:</b> <code>{user['user_id']}</code>\n"
        f"<b>Статус:</b> {esc(premium_text(user))}\n"
        f"<b>Запросов:</b> <code>{int(user['attempts'])}</code>\n"
        f"<b>Приглашено:</b> <code>{int(user['total_referrals'])}</code>\n\n"
        "<b>Реферальная ссылка:</b>\n"
        f"<code>{esc(link)}</code>"
    )


def render_search_menu(user) -> str:
    return (
        "<b>🚀 Быстрый поиск username</b>\n\n"
        "Выбери длину ника. Чем короче username, тем сложнее найти свободный вариант.\n\n"
        "<b>Доступно:</b>\n"
        "• <b>6–7 символов</b> — обычный поиск;\n"
        "• <b>5 символов</b> — Premium;\n"
        "• формат с цифрами обычно находится быстрее.\n\n"
        f"<b>Запросов:</b> <code>{int(user['attempts'])}</code>\n"
        f"<b>Статус:</b> {esc(premium_text(user))}"
    )


def render_refs(user) -> str:
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{user['user_id']}" if BOT_USERNAME else "бот ещё запускается"
    return (
        "<b>🎁 Реферальная система</b>\n\n"
        f"За каждого нового друга ты получаешь <b>+{REFERRAL_BONUS_ATTEMPTS} запроса</b>.\n\n"
        f"<b>Приглашено:</b> <code>{int(user['total_referrals'])}</code>\n\n"
        "<b>Твоя ссылка:</b>\n"
        f"<code>{esc(link)}</code>"
    )


def clean_username(u: str) -> str:
    # Для результата не используем подчёркивания: так меньше шансов получить
    # «Некорректное имя пользователя» в настройках Telegram.
    u = re.sub(r"[^a-zA-Z0-9]", "", u).lower()
    if u and not u[0].isalpha():
        u = random.choice(string.ascii_lowercase) + u[1:]
    return u


def make_pronounceable(length: int) -> str:
    s = random.choice(string.ascii_lowercase)
    while len(s) < length:
        if s[-1] in VOWELS:
            s += random.choice(CONSONANTS)
        else:
            s += random.choice(VOWELS)
    return s[:length]


def wordmix_candidate(length: int, with_digits: bool, beauty_first: bool = False) -> str:
    """Красивый подбор: основа-слово + аккуратный хвост.
    Никакого режима вида qxprw: только читабельные куски, которые выглядят как ник.
    """
    bases = WORD_BASES[:]
    if beauty_first:
        # В начале чаще берём самые мягкие/вайбовые основы.
        bases = [
            "luna", "miko", "neko", "yuki", "mimi", "aura", "sora", "lumi", "kira", "miya",
            "soft", "moon", "star", "nova", "fairy", "bunny", "kitty", "honey", "milky", "pearl",
        ] + bases

    for _ in range(500):
        base = clean_username(random.choice(bases))

        # 1) Идеальное попадание словом: angel, dream, charm, kitty и т.п.
        if len(base) == length:
            cand = base
        # 2) Слово + мягкий хвост: luna + x = lunax, miko + ly = mikoly.
        elif len(base) < length:
            need = length - len(base)
            tails = WORD_TAILS.get(need, [])
            if not tails:
                continue
            cand = base + random.choice(tails)
        # 3) Для короткой длины берём аккуратное сокращение слова, но не случайный набор.
        else:
            # lovely -> lovel, bunny -> bunny, velvet -> velve
            cand = base[:length]

        cand = clean_username(cand)

        # С цифрами: слово остаётся читаемым, цифра только в конце.
        if with_digits and len(cand) >= 5:
            cand = cand[:-1] + random.choice("23456789")

        if is_valid_profile_username(cand, length, with_digits):
            return cand

    # Последний запасной вариант тоже читабельный: произносимая связка, а не qxprw.
    cand = make_pronounceable(length)
    if with_digits and len(cand) >= 5:
        cand = cand[:-1] + random.choice("23456789")
    return clean_username(cand)[:length]


def random_letters_candidate(length: int, with_digits: bool) -> str:
    """Быстрый запасной вариант для 5–7 символов, но без заведомо некорректных ников."""
    alphabet = string.ascii_lowercase + ("23456789" if with_digits else "")
    for _ in range(200):
        s = random.choice(string.ascii_lowercase)
        while len(s) < length:
            s += random.choice(alphabet)
        s = clean_username(s[:length])
        if is_valid_profile_username(s, length, with_digits):
            return s
    # почти никогда не понадобится, но пусть будет безопасный запасной вариант
    return make_pronounceable(length)[:length]


def fit_exact_length(candidate: str, length: int, with_digits: bool) -> Optional[str]:
    """Жёстко приводит кандидат к выбранной длине.
    Если в фильтре стоит 5 — на выход допускается только 5 символов,
    если 6 — только 6, если 7 — только 7.
    """
    cand = clean_username(candidate)

    if len(cand) > length:
        cand = cand[:length]

    if len(cand) < length:
        alphabet = string.ascii_lowercase + ("23456789" if with_digits else "")
        while len(cand) < length:
            cand += random.choice(alphabet)

    cand = clean_username(cand)[:length]

    if not is_valid_profile_username(cand, length, with_digits):
        return None
    return cand


def smart_candidate(length: int, with_digits: bool, beauty_first: bool = False) -> str:
    """Сначала красивые словесные связки, затем более широкий генератор.
    На выходе всегда стараемся вернуть ровно выбранную длину: 5/6/7 символов.
    """
    if beauty_first:
        cand = wordmix_candidate(length, with_digits, beauty_first=True)
        fixed = fit_exact_length(cand, length, with_digits)
        return fixed or random_letters_candidate(length, with_digits)

    r = random.random()
    if r < 0.35:
        cand = wordmix_candidate(length, with_digits, beauty_first=False)
    elif r < 0.65:
        cand = make_pronounceable(length)
        if with_digits and len(cand) >= 5:
            cand = cand[:-1] + random.choice("23456789")
    else:
        cand = random_letters_candidate(length, with_digits)

    fixed = fit_exact_length(cand, length, with_digits)
    return fixed or random_letters_candidate(length, with_digits)


async def check_tme_available(username: str, session: aiohttp.ClientSession) -> tuple[bool, str]:
    """Public t.me check for ordinary profile/channel/bot usage and marketplace redirect text."""
    try:
        async with session.get(
            f"https://t.me/{username}",
            allow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
            },
        ) as r:
            text = await r.text(errors="ignore")
            low = text.lower()
            uname = username.lower()

            # Clear signs that the name opens a real Telegram entity.
            occupied_markers = [
                "tgme_page_title",
                "tgme_page_extra",
                "tgme_page_description",
                "tgme_action_button_new",
                "send message",
                "if you have telegram, you can contact",
                "you can contact",
                "view in telegram",
                "open in telegram",
                "subscribers",
                "members",
                f"https://t.me/{uname}",
                f"tg://resolve?domain={uname}",
                f"@{uname}",
            ]

            marketplace_markers = [
                "this link is already taken",
                "this username is already taken",
                "this username is taken",
                "this username is not available",
                "username is unavailable",
                "already taken",
                "username is taken",
                "available on fragment",
                "available for sale",
                "available for purchase",
                "buy it on fragment",
                "you can buy it",
                "you can purchase",
                "this username can be purchased",
                "for sale",
                "on sale",
                "auction",
                "fragment.com/username",
            ]

            not_found_markers = [
                "username not found",
                "user not found",
                "tgme_page_not_found",
                "tgme_username_link_not_found",
                "if you have telegram, you can create",
                "this channel doesn't exist",
            ]

            if any(m in low for m in marketplace_markers):
                return False, "tme_marketplace_or_taken"
            if r.status == 200 and any(m in low for m in occupied_markers):
                return False, "tme_used"
            if r.status in {404, 410} or any(m in low for m in not_found_markers):
                return True, "tme_not_found"

            return (False, "tme_unclear") if STRICT_USERNAME_CHECK else (True, "tme_unclear_allowed")
    except Exception:
        return (False, "tme_network_unclear") if STRICT_USERNAME_CHECK else (True, "tme_network_skipped")


async def check_fragment_available(username: str, session: aiohttp.ClientSession) -> tuple[bool, str]:
    """Public Fragment check. Rejects sale, auction and collectible username pages."""
    username = clean_check_username(username)
    if is_unsettable_profile_username(username):
        return False, "invalid_or_unsettable"
    try:
        async with session.get(
            f"https://fragment.com/username/{username}",
            allow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
            },
        ) as r:
            text = await r.text(errors="ignore")
            low = re.sub(r"\s+", " ", html.unescape(text)).lower()
            uname = username.lower()
            final_url = str(r.url).lower()

            exact_markers = [
                f"/username/{uname}",
                f"@{uname}",
                f"{uname}.t.me",
                f">{uname}<",
                f"username/{uname}",
            ]
            belongs_to_username = any(m in low for m in exact_markers) or f"/username/{uname}" in final_url

            not_found_markers = [
                "not found",
                "page not found",
                "username not found",
                "no results found",
                "nothing found",
            ]
            if r.status in {404, 410} or (not belongs_to_username and any(m in low for m in not_found_markers)):
                return True, "fragment_not_listed"

            busy_markers = [
                "for sale",
                "on sale",
                "listed for sale",
                "put on sale",
                "sale price",
                "buy now",
                "make an offer",
                "available for purchase",
                "available",
                "minimum bid",
                "place bid",
                "place a bid",
                "start auction",
                "start an auction",
                "highest bid",
                "current bid",
                "bid history",
                "on auction",
                "auction",
                "auction ends",
                "sold for",
                "sold",
                "taken",
                "unavailable",
                "owned by",
                "owner",
                "ownership history",
                "auction ended",
                "collectible username",
                "telegram username",
                "web address",
                "ton web 3.0 address",
                "fragment bid",
            ]

            if belongs_to_username and any(m in low for m in busy_markers):
                return False, "fragment_listed_sale_auction_sold_or_owned"
            if belongs_to_username:
                return False, "fragment_username_page_exists"

            return (False, "fragment_unclear") if STRICT_USERNAME_CHECK else (True, "fragment_unclear_allowed")
    except Exception:
        return (False, "fragment_network_unclear") if STRICT_USERNAME_CHECK else (True, "fragment_network_skipped")


async def check_bot_api_available(username: str) -> tuple[bool, str]:
    """Fast first-pass check via Telegram Bot API only. No login/session usage."""
    username = clean_check_username(username)
    if is_unsettable_profile_username(username):
        return False, "invalid_or_unsettable"
    try:
        await bot.get_chat(f"@{username}")
        return False, "taken_bot_api"
    except TelegramBadRequest as e:
        msg = str(e).lower()
        # Для Bot API это нормальный сигнал, что публичный чат/профиль не найден.
        if any(x in msg for x in ["chat not found", "username not found"]):
            return True, "bot_api_not_found"
        if any(x in msg for x in ["username_invalid", "invalid username", "not enough rights", "forbidden"]):
            return False, "bot_api_unsettable_or_forbidden"
        return False, "unknown_bot_api"
    except TelegramRetryAfter as e:
        await asyncio.sleep(min(int(e.retry_after) + 1, 5))
        return False, "retry_later"
    except Exception:
        return (False, "bot_api_network_unclear") if STRICT_USERNAME_CHECK else (True, "bot_api_network_skipped")


async def final_verify_username(username: str, session: aiohttp.ClientSession, mode: str = "turbo") -> tuple[bool, str]:
    """Final check only for promising candidates, so search stays fast."""
    username = clean_check_username(username)
    if is_unsettable_profile_username(username):
        return False, "invalid_or_unsettable"
    preset = MODE_PRESETS[normalize_search_mode(mode)]
    old_strict = globals().get("STRICT_USERNAME_CHECK", True)
    globals()["STRICT_USERNAME_CHECK"] = bool(preset["strict"])
    try:
        if bool(preset["fragment"]):
            ok, reason = await check_fragment_available(username, session)
            if not ok:
                return False, reason
        ok, reason = await check_bot_api_available(username)
        if not ok:
            return False, reason
        if bool(preset["web"]):
            ok, reason = await check_tme_available(username, session)
            if not ok:
                return False, reason
        return True, "available_checked"
    finally:
        globals()["STRICT_USERNAME_CHECK"] = old_strict


async def check_username_available(username: str) -> tuple[bool, str]:
    """Safe full check: no account login, no user sessions, no automatic username claiming."""
    username = clean_check_username(username)
    if is_unsettable_profile_username(username):
        return False, "invalid_or_unsettable"
    timeout = aiohttp.ClientTimeout(total=2.2, connect=0.8, sock_read=1.2)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        return await final_verify_username(username, s, "strict")


async def quick_check_candidate(username: str, session: aiohttp.ClientSession, mode: str) -> tuple[bool, str]:
    """Fast safe check: Fragment first, then Telegram public/API availability."""
    username = clean_check_username(username)
    if is_unsettable_profile_username(username):
        return False, "invalid_or_unsettable"
    mode = normalize_search_mode(mode)
    preset = MODE_PRESETS[mode]

    old_strict = globals().get("STRICT_USERNAME_CHECK", True)
    globals()["STRICT_USERNAME_CHECK"] = bool(preset["strict"])
    try:
        if bool(preset["fragment"]):
            ok, reason = await check_fragment_available(username, session)
            if not ok:
                return False, reason

        ok, reason = await check_bot_api_available(username)
        if not ok:
            return False, reason

        if bool(preset["web"]):
            ok, reason = await check_tme_available(username, session)
            if not ok:
                return False, reason

        return True, "ok_checked"
    finally:
        globals()["STRICT_USERNAME_CHECK"] = old_strict


async def find_available_username(length: int, with_digits: bool, mode: str = "turbo") -> Optional[str]:
    mode = normalize_search_mode(mode)
    preset = MODE_PRESETS[mode]
    seen: set[str] = set()
    tries = 0
    batch_size = max(20, min(int(preset["batch"]), 260))
    max_tries = int(preset["max_tries"])
    beauty_tries = int(preset["beauty_tries"])
    time_limit = int(preset.get("time_limit", MAX_SEARCH_SECONDS))
    deadline = time.monotonic() + max(3, time_limit)

    # Short network timeout: result or reroll, no hanging.
    timeout = aiohttp.ClientTimeout(total=1.15, connect=0.35, sock_read=0.65)
    connector = aiohttp.TCPConnector(limit=120, ttl_dns_cache=300)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as web_session:
        while tries < max_tries and time.monotonic() < deadline:
            candidates: list[str] = []
            while len(candidates) < batch_size and tries < max_tries and time.monotonic() < deadline:
                cand = smart_candidate(length, with_digits, beauty_first=(mode == "beauty" or tries < beauty_tries))
                tries += 1
                cand = fit_exact_length(cand, length, with_digits)
                if not cand or cand in seen:
                    continue
                seen.add(cand)
                candidates.append(cand)

            if not candidates:
                continue

            sem = asyncio.Semaphore(80 if mode != "strict" else 18)

            async def limited_check(c: str):
                async with sem:
                    try:
                        return c, await quick_check_candidate(c, web_session, mode)
                    except Exception:
                        return c, (False, "check_error")

            tasks = [asyncio.create_task(limited_check(c)) for c in candidates]
            try:
                for task in asyncio.as_completed(tasks, timeout=max(0.2, deadline - time.monotonic())):
                    cand, res = await task
                    ok, _reason = res
                    if ok and len(cand) == length:
                        for t in tasks:
                            if not t.done():
                                t.cancel()
                        return cand
            except asyncio.TimeoutError:
                pass
            finally:
                for t in tasks:
                    if not t.done():
                        t.cancel()

            await asyncio.sleep(0)

    return None

async def edit_search_status(chat_id: int, message_id: int, length: int, with_digits: bool, mode: str = "turbo", step: int = 0) -> None:
    dots = "." * ((step % 3) + 1)
    label = "с цифрами" if with_digits else "только буквы"
    tail = "Турбо-режим: пачками отсеиваю занятые варианты, строгая сверка только в финале."
    if WEB_DOUBLE_CHECK or FRAGMENT_DOUBLE_CHECK:
        tail = "Красивые связки слов → быстрый web-отсев → результат без зависания."
    text = (
        f"<b>✨ Сначала ищу красивые варианты{dots}</b>\n\n"
        f"<b>Длина:</b> <code>{length} символов</code>\n"
        f"<b>Формат:</b> <code>{label}</code>\n\n"
        f"{tail}\n\n⏱ <b>Максимум ожидания:</b> <code>{int(MODE_PRESETS[normalize_search_mode(mode)].get('time_limit', MAX_SEARCH_SECONDS))} сек.</code>"
    )
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
    except Exception:
        pass


async def search_with_live_status(chat_id: int, message_id: int, length: int, with_digits: bool, mode: str = "turbo") -> Optional[str]:
    mode = normalize_search_mode(mode)
    preset = MODE_PRESETS[mode]
    hard_limit = int(preset.get("time_limit", MAX_SEARCH_SECONDS))
    task = asyncio.create_task(find_available_username(length, with_digits, mode))
    step = 0
    started = time.monotonic()
    while not task.done():
        if time.monotonic() - started >= hard_limit:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return None
        await edit_search_status(chat_id, message_id, length, with_digits, mode, step)
        step += 1
        await asyncio.sleep(0.35)
    return await task

@dp.message(Command("start"))
async def start(message: Message, command: CommandObject) -> None:
    ref_by = parse_ref(command.args, message.from_user.id)
    await register_if_needed(message.from_user.id, message.from_user.first_name or "", message.from_user.username or "", ref_by)
    await clear_user_message(message)
    db.restore_attempts_if_needed(message.from_user.id, DAILY_RESTORE_ATTEMPTS)
    await send_main_menu(message.chat.id, message.from_user.id)


@dp.message(Command("id"))
async def id_cmd(message: Message) -> None:
    await register_if_needed(message.from_user.id, message.from_user.first_name or "", message.from_user.username or "")
    # /id не трогает главное меню: отправляет отдельное сообщение без кнопок и не сохраняет его как last_msg_id.
    await bot.send_message(message.chat.id, f"Ваш id: <code>{message.from_user.id}</code>")

@dp.message(Command("premium"))
async def premium_cmd(message: Message, command: CommandObject) -> None:
    await register_if_needed(message.from_user.id, message.from_user.first_name or "", message.from_user.username or "")
    await clear_user_message(message)
    if not is_admin(message.from_user.id):
        await screen(message.chat.id, message.from_user.id, "<b>Недостаточно прав.</b>", back_main_kb())
        return
    args = (command.args or "").split()
    if not args or not args[0].isdigit():
        await screen(
            message.chat.id,
            message.from_user.id,
            "<b>Команда Premium:</b>\n"
            "<code>/premium 728805373</code> — навсегда\n"
            "<code>/premium 728805373 1h</code> — 1 час\n"
            "<code>/premium 728805373 1d</code> — 1 день\n"
            "<code>/premium 728805373 1m</code> — 1 месяц\n"
            "<code>/premium 728805373 30d</code> — 30 дней",
            admin_kb(),
        )
        return
    target = int(args[0])
    try:
        seconds, label = parse_premium_duration(args[1] if len(args) > 1 else None)
    except ValueError:
        await screen(message.chat.id, message.from_user.id, "<b>Неверный срок.</b> Примеры: <code>1h</code>, <code>1d</code>, <code>1m</code>, <code>30d</code>.", admin_kb())
        return
    db.ensure_user(target, "", "", None, FREE_ATTEMPTS)
    until = db.set_premium_seconds(target, seconds, replace=True)
    text = "навсегда" if until > 4000000000 else datetime.fromtimestamp(until).strftime("%d.%m.%Y %H:%M")
    await screen(message.chat.id, message.from_user.id, f"<b>💎 Premium выдан.</b>\n\nID: <code>{target}</code>\nСрок: <code>{esc(label)}</code>\nАктивен до: <code>{esc(text)}</code>", admin_kb())

@dp.message(Command("unpremium"))
async def unpremium_cmd(message: Message, command: CommandObject) -> None:
    await register_if_needed(message.from_user.id, message.from_user.first_name or "", message.from_user.username or "")
    await clear_user_message(message)
    if not is_admin(message.from_user.id):
        await screen(message.chat.id, message.from_user.id, "<b>Недостаточно прав.</b>", back_main_kb())
        return
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await screen(message.chat.id, message.from_user.id, "<b>Команда:</b> <code>/unpremium ID</code>", admin_kb())
        return
    target = int(arg)
    db.ensure_user(target, "", "", None, FREE_ATTEMPTS)
    db.remove_premium(target)
    await screen(message.chat.id, message.from_user.id, f"<b>Premium снят.</b>\n\nID: <code>{target}</code>", admin_kb())


@dp.message(Command("ban"))
async def ban_cmd(message: Message, command: CommandObject) -> None:
    await register_if_needed(message.from_user.id, message.from_user.first_name or "", message.from_user.username or "")
    await clear_user_message(message)
    if not is_admin(message.from_user.id):
        return
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await screen(message.chat.id, message.from_user.id, "<b>Команда:</b> <code>/ban ID</code>", admin_kb())
        return
    db.ensure_user(int(arg), "", "", None, FREE_ATTEMPTS)
    db.update_user(int(arg), is_banned=1)
    await screen(message.chat.id, message.from_user.id, f"Пользователь <code>{arg}</code> заблокирован.", admin_kb())


@dp.message(Command("unban"))
async def unban_cmd(message: Message, command: CommandObject) -> None:
    await register_if_needed(message.from_user.id, message.from_user.first_name or "", message.from_user.username or "")
    await clear_user_message(message)
    if not is_admin(message.from_user.id):
        return
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await screen(message.chat.id, message.from_user.id, "<b>Команда:</b> <code>/unban ID</code>", admin_kb())
        return
    db.update_user(int(arg), is_banned=0)
    await screen(message.chat.id, message.from_user.id, f"Пользователь <code>{arg}</code> разблокирован.", admin_kb())


@dp.message(Command("broadcast"))
async def broadcast_cmd(message: Message, command: CommandObject) -> None:
    await register_if_needed(message.from_user.id, message.from_user.first_name or "", message.from_user.username or "")
    await clear_user_message(message)
    if not is_admin(message.from_user.id):
        return
    text = (command.args or "").strip()
    if not text:
        await screen(message.chat.id, message.from_user.id, "<b>Команда:</b> <code>/broadcast текст</code>", admin_kb())
        return
    sent = 0
    for uid in db.all_user_ids():
        try:
            await bot.send_message(uid, text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await screen(message.chat.id, message.from_user.id, f"<b>Рассылка завершена.</b>\nДоставлено: <code>{sent}</code>", admin_kb())


@dp.message(Command("admin"))
async def admin_cmd(message: Message) -> None:
    await register_if_needed(message.from_user.id, message.from_user.first_name or "", message.from_user.username or "")
    await clear_user_message(message)
    if not is_admin(message.from_user.id):
        await screen(message.chat.id, message.from_user.id, "<b>Недостаточно прав.</b>", back_main_kb())
        return
    await screen(message.chat.id, message.from_user.id, "<b>⚙️ Админ панель</b>\n\nВыбери нужный раздел.", admin_kb())


@dp.message()
async def any_message(message: Message) -> None:
    await register_if_needed(message.from_user.id, message.from_user.first_name or "", message.from_user.username or "")
    await clear_user_message(message)
    user = db.get_user(message.from_user.id)
    if user and int(user["is_banned"]):
        return
    await send_main_menu(message.chat.id, message.from_user.id)


@dp.callback_query(F.data == "main")
async def cb_main(call: CallbackQuery) -> None:
    await answer_cb(call)
    await register_if_needed(call.from_user.id, call.from_user.first_name or "", call.from_user.username or "")
    db.restore_attempts_if_needed(call.from_user.id, DAILY_RESTORE_ATTEMPTS)
    await send_main_menu(call.message.chat.id, call.from_user.id)


@dp.callback_query(F.data == "profile")
async def cb_profile(call: CallbackQuery) -> None:
    await answer_cb(call)
    user = db.get_user(call.from_user.id)
    await screen(call.message.chat.id, call.from_user.id, render_profile(user), back_main_kb())


@dp.callback_query(F.data == "refs")
async def cb_refs(call: CallbackQuery) -> None:
    await answer_cb(call)
    user = db.get_user(call.from_user.id)
    await screen(call.message.chat.id, call.from_user.id, render_refs(user), back_main_kb())


@dp.callback_query(F.data == "rules")
async def cb_rules(call: CallbackQuery) -> None:
    await answer_cb(call)
    text = (
        "<b>📄 Правила</b>\n\n"
        "• Один поиск расходует 1 запрос.\n"
        "• Бесплатные запросы восстанавливаются раз в 24 часа.\n"
        "• 5-буквенные username доступны с Premium.\n"
        "• Проверка работает без искусственной задержки 10 секунд.\n"
        "• Дополнительно проверяется t.me и Fragment, чтобы не показывать ник, который занят человеком или продаётся.\n"
        "• Username показывается в формате <code>@username</code> для быстрого копирования.\n"
        "• Бот не просит код Telegram, не хранит пользовательские сессии и не меняет username автоматически."
    )
    await screen(call.message.chat.id, call.from_user.id, text, back_main_kb())


@dp.callback_query(F.data == "support")
async def cb_support(call: CallbackQuery) -> None:
    await answer_cb(call)
    text = f"<b>📩 Поддержка</b>\n\nПо вопросам работы бота: @{esc(SUPPORT_USERNAME)}"
    await screen(call.message.chat.id, call.from_user.id, text, back_main_kb())


@dp.callback_query(F.data == "mode_info")
async def cb_mode_info(call: CallbackQuery) -> None:
    await answer_cb(call)
    await screen(
        call.message.chat.id,
        call.from_user.id,
        mode_description_text(),
        kb([[('🚀 Перейти к поиску', 'search_menu')], [('◀️ Главное меню', 'main')]])
    )


@dp.callback_query(F.data == "search_menu")
async def cb_search_menu(call: CallbackQuery) -> None:
    await answer_cb(call)
    user = db.get_user(call.from_user.id)
    if int(user["is_banned"]):
        await screen(call.message.chat.id, call.from_user.id, "<b>Доступ ограничен.</b>", None)
        return
    db.restore_attempts_if_needed(call.from_user.id, DAILY_RESTORE_ATTEMPTS)
    user = db.get_user(call.from_user.id)
    await screen(call.message.chat.id, call.from_user.id, render_search_menu(user), search_menu_kb(user))


@dp.callback_query(F.data.startswith("len:"))
async def cb_len(call: CallbackQuery) -> None:
    await answer_cb(call)
    length = int(call.data.split(":")[1])
    user = db.get_user(call.from_user.id)
    if length == 5 and not is_premium(user):
        await screen(call.message.chat.id, call.from_user.id, "<b>💎 5 букв доступны только с Premium.</b>\n\nМожно выбрать 6–7 букв или подключить Premium.", premium_kb())
        return
    text = f"<b>🔎 Настройка поиска</b>\n\nДлина: <code>{length}</code>\n\nВыбери формат username."
    await screen(call.message.chat.id, call.from_user.id, text, digit_menu_kb(length))


@dp.callback_query(F.data.startswith("digits:"))
async def cb_digits(call: CallbackQuery) -> None:
    await answer_cb(call)
    _, length_s, dig_s = call.data.split(":")
    length = int(length_s)
    with_digits = bool(int(dig_s))
    SEARCH_CFG[call.from_user.id] = {"length": length, "digits": with_digits, "mode": DEFAULT_SEARCH_MODE}
    label = "с цифрами" if with_digits else "только буквы"
    text = (
        "<b>🎚 Выбор режима</b>\n\n"
        f"Длина: <code>{length}</code>\n"
        f"Формат: <code>{label}</code>\n\n"
        "Выбери скорость/точность. В любом режиме генератор делает красивые связки: слово + аккуратный хвост."
    )
    await screen(call.message.chat.id, call.from_user.id, text, mode_menu_kb(length, with_digits))


@dp.callback_query(F.data.startswith("mode:"))
async def cb_mode(call: CallbackQuery) -> None:
    await answer_cb(call)
    _, length_s, dig_s, mode_raw = call.data.split(":")
    length = int(length_s)
    with_digits = bool(int(dig_s))
    mode = normalize_search_mode(mode_raw)
    SEARCH_CFG[call.from_user.id] = {"length": length, "digits": with_digits, "mode": mode}
    label = "с цифрами" if with_digits else "только буквы"
    preset = MODE_PRESETS[mode]
    text = (
        "<b>🔎 Всё готово</b>\n\n"
        f"<b>Длина:</b> <code>{length} символов</code>\n"
        f"<b>Формат:</b> <code>{label}</code>\n"
        f"<b>Режим:</b> {preset['title']} — {preset['short']}\n"
        f"<b>Ожидание:</b> <code>{preset['eta']}</code>\n\n"
        "Нажми кнопку ниже, чтобы начать."
    )
    await screen(call.message.chat.id, call.from_user.id, text, kb([[("🚀 Начать", "do_search")], [("⚙️ Изменить режим", f"digits:{length}:{int(with_digits)}")], [("👤 Профиль", "profile"), ("💎 Premium", "premium_menu")], [("◀️ Главное меню", "main")]]))

@dp.callback_query(F.data == "do_search")
async def cb_do_search(call: CallbackQuery) -> None:
    await answer_cb(call)
    user = db.get_user(call.from_user.id)
    if not user or int(user["is_banned"]):
        return
    cfg = SEARCH_CFG.get(call.from_user.id, {"length": 6, "digits": False, "mode": DEFAULT_SEARCH_MODE})
    length = int(cfg["length"])
    with_digits = bool(cfg["digits"])
    mode = normalize_search_mode(cfg.get("mode", DEFAULT_SEARCH_MODE))

    if length == 5 and not is_premium(user):
        await screen(call.message.chat.id, call.from_user.id, "<b>💎 5 букв доступны только с Premium.</b>", premium_kb())
        return

    db.restore_attempts_if_needed(call.from_user.id, DAILY_RESTORE_ATTEMPTS)
    user = db.get_user(call.from_user.id)

    left_cd = SEARCH_COOLDOWN_SECONDS - (ts() - int(user["last_search_at"] or 0))
    if left_cd > 0:
        await screen(call.message.chat.id, call.from_user.id, f"<b>⏳ Не так быстро.</b>\n\nСледующий поиск через <code>{left_cd}</code> сек.", kb([[("🔁 Обновить", "do_search")], [("◀️ Главное меню", "main")]]))
        return

    if int(user["attempts"]) <= 0 and not is_premium(user):
        await screen(call.message.chat.id, call.from_user.id, "<b>Запросы закончились.</b>\n\nМожно пригласить друга или подключить Premium.", kb([[("🎁 Рефералка", "refs")], [("💎 Premium", "premium_menu")], [("◀️ Главное меню", "main")]]))
        return

    if not is_premium(user) and not db.use_attempt(call.from_user.id):
        await screen(call.message.chat.id, call.from_user.id, "<b>Запросы закончились.</b>", back_main_kb())
        return
    if is_premium(user):
        db.update_user(call.from_user.id, last_search_at=ts())

    msg = await screen(call.message.chat.id, call.from_user.id, "<b>⚡ Быстрая проверка.</b>\n\nЗапускаю красивый подбор...")
    username = await search_with_live_status(call.message.chat.id, msg.message_id, length, with_digits, mode)
    user = db.get_user(call.from_user.id)
    if not username:
        text = (
            "<b>Ничего не нашлось.</b>\n\n"
            f"За {int(MODE_PRESETS[mode].get('time_limit', MAX_SEARCH_SECONDS))} сек. ничего не нашлось. Нажми «Искать ещё» — бот сразу сделает новый реролл.\n"
            f"<b>Запросов осталось:</b> <code>{int(user['attempts'])}</code>"
        )
        await screen(call.message.chat.id, call.from_user.id, text, kb([[("🔁 Искать ещё", "do_search")], [("⚙️ Настройки поиска", "search_menu")], [("◀️ Главное меню", "main")]]))
        return

    db.add_found(call.from_user.id, username, length, with_digits)
    checks = ["Telegram Bot API"]
    if WEB_DOUBLE_CHECK:
        checks.append("t.me")
    if FRAGMENT_DOUBLE_CHECK:
        checks.append("Fragment")
    check_label = " + ".join(checks)
    text = (
        "<b>✅ Найден свободный username</b>\n\n"
        f"<b>Telegram:</b> <code>@{esc(username)}</code>\n"
        f"<b>Ссылка Telegram:</b> https://t.me/{esc(username)}\n"
        f"<b>Ссылка Fragment:</b> https://fragment.com/username/{esc(username)}\n\n"
        f"<b>Длина:</b> <code>{length} символов</code>\n"
        f"<b>Формат:</b> <code>{'с цифрами' if with_digits else 'только буквы'}</code>\n"
        f"<b>Проверка:</b> <code>{esc(check_label)}</code>\n\n"
        "<i>Важно: бот только показывает найденный вариант. Он не меняет username и не забирает ник автоматически.</i>\n\n"
        f"<b>Запросов осталось:</b> <code>{int(user['attempts'])}</code>"
    )
    await screen(call.message.chat.id, call.from_user.id, text, result_kb(username))


@dp.callback_query(F.data == "my_names")
async def cb_my_names(call: CallbackQuery) -> None:
    await answer_cb(call)
    rows = []
    with db.connect() as con:
        rows = con.execute("SELECT username, created_at FROM found_usernames WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (call.from_user.id,)).fetchall()
    if not rows:
        text = "<b>📌 Мои ники</b>\n\nПока ничего не найдено."
    else:
        names = "\n".join([f"• <code>@{esc(r['username'])}</code>" for r in rows])
        text = f"<b>📌 Мои последние ники</b>\n\n{names}"
    await screen(call.message.chat.id, call.from_user.id, text, back_main_kb())


@dp.callback_query(F.data == "premium_menu")
async def cb_premium(call: CallbackQuery) -> None:
    await answer_cb(call)
    user = db.get_user(call.from_user.id)
    text = (
        f"<b>💎 {esc(PREMIUM_NAME)}</b>\n\n"
        "Premium открывает 5-символьные варианты, убирает лимит бесплатных запросов и делает подбор удобнее.\n"
        "Тарифы выставлены по нормальной сетке: короткий тест, неделя, две недели, месяц, два месяца, полгода и год.\n\n"
        f"<b>Твой статус:</b> {esc(premium_text(user))}"
    )
    await screen(call.message.chat.id, call.from_user.id, text, premium_kb())


@dp.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: CallbackQuery) -> None:
    await answer_cb(call)
    days = int(call.data.split(":")[1])
    amount = premium_price_for_days(days)
    await bot.send_invoice(
        chat_id=call.message.chat.id,
        title=f"{PREMIUM_NAME} на {days} дней",
        description=f"Доступ к Premium-функциям {APP_NAME} на {days} дней.",
        payload=f"premium:{days}:{amount}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"{PREMIUM_NAME} {days} дней", amount=amount)],
    )


@dp.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery) -> None:
    await q.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: Message) -> None:
    await register_if_needed(message.from_user.id, message.from_user.first_name or "", message.from_user.username or "")
    payload = message.successful_payment.invoice_payload
    days = 14
    if payload.startswith("premium:"):
        parts = payload.split(":")
        if len(parts) >= 2 and parts[1].isdigit():
            days = int(parts[1])
    stars = int(message.successful_payment.total_amount)
    db.set_premium_seconds(message.from_user.id, days * 86400, replace=False)
    db.add_payment(message.from_user.id, stars, days, message.successful_payment.telegram_payment_charge_id or "")
    await clear_user_message(message)
    user = db.get_user(message.from_user.id)
    await screen(message.chat.id, message.from_user.id, f"<b>✅ Premium активирован.</b>\n\n{esc(premium_text(user))}", main_kb(message.from_user.id))


@dp.callback_query(F.data == "admin")
async def cb_admin(call: CallbackQuery) -> None:
    await answer_cb(call)
    if not is_admin(call.from_user.id):
        return
    await screen(call.message.chat.id, call.from_user.id, "<b>⚙️ Админ панель</b>\n\nВыбери нужный раздел.", admin_kb())


@dp.callback_query(F.data == "adm_stats")
async def cb_adm_stats(call: CallbackQuery) -> None:
    await answer_cb(call)
    if not is_admin(call.from_user.id):
        return
    s = db.stats()
    text = (
        "<b>📊 Статистика</b>\n\n"
        f"Пользователей: <code>{s['users']}</code>\n"
        f"Premium: <code>{s['premium']}</code>\n"
        f"Заблокировано: <code>{s['banned']}</code>\n"
        f"Найдено ников: <code>{s['found']}</code>\n"
        f"Оплат: <code>{s['payments']}</code>\n"
        f"Stars: <code>{s['stars']}</code>"
    )
    await screen(call.message.chat.id, call.from_user.id, text, admin_kb())


@dp.callback_query(F.data == "adm_users")
async def cb_adm_users(call: CallbackQuery) -> None:
    await answer_cb(call)
    if not is_admin(call.from_user.id):
        return
    users = db.recent_users(10)
    lines = []
    for u in users:
        name = u["username"] or u["first_name"] or "no_name"
        lines.append(f"• <code>{u['user_id']}</code> — {esc(name)} — {esc(premium_text(u))}")
    text = "<b>👥 Последние пользователи</b>\n\n" + ("\n".join(lines) if lines else "Пусто.")
    await screen(call.message.chat.id, call.from_user.id, text, admin_kb())


@dp.callback_query(F.data == "adm_found")
async def cb_adm_found(call: CallbackQuery) -> None:
    await answer_cb(call)
    if not is_admin(call.from_user.id):
        return
    rows = db.recent_found(12)
    lines = [f"• <code>@{esc(r['username'])}</code> — <code>{r['user_id']}</code>" for r in rows]
    text = "<b>📌 Последние найденные username</b>\n\n" + ("\n".join(lines) if lines else "Пусто.")
    await screen(call.message.chat.id, call.from_user.id, text, admin_kb())


@dp.callback_query(F.data == "adm_premium_help")
async def cb_adm_help(call: CallbackQuery) -> None:
    await answer_cb(call)
    if not is_admin(call.from_user.id):
        return
    text = (
        "<b>💎 Premium-команды</b>\n\n"
        "Выдать навсегда:\n<code>/premium 728805373</code>\n\n"
        "Выдать на 30 дней:\n<code>/premium 728805373 30</code>\n\n"
        "Бан / разбан:\n<code>/ban 728805373</code>\n<code>/unban 728805373</code>"
    )
    await screen(call.message.chat.id, call.from_user.id, text, admin_kb())


async def on_startup() -> None:
    global BOT_USERNAME
    db.init_db()
    me = await bot.get_me()
    BOT_USERNAME = me.username
    for uid in PREMIUM_IDS:
        db.ensure_user(uid, "", "", None, FREE_ATTEMPTS)
        current = db.get_user(uid)
        if not is_premium(current):
            db.set_premium(uid, None)
    print(f"✅ {APP_NAME} запущен: @{BOT_USERNAME}")
    print(f"Proxy: {PROXY_URL or 'не используется'}")


async def main() -> None:
    while True:
        try:
            await on_startup()
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        except TelegramNetworkError as e:
            print("❌ Нет соединения с api.telegram.org:443. Это проблема сети/VPN/фаервола, а не токена и не кода.")
            print(f"Детали: {e}")
            print(f"🔁 Повторная попытка через {POLLING_RETRY_SECONDS} сек.")
            await asyncio.sleep(POLLING_RETRY_SECONDS)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    asyncio.run(main())
