from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from enum import Enum

import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter

USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{4,31}$")
RESERVED_PARTS = ("telegram", "support", "admin", "helpdesk", "security")

class CheckVerdict(str, Enum):
    OK = "ok"
    SKIP = "skip"
    RETRY = "retry"

@dataclass(slots=True)
class CheckResult:
    verdict: CheckVerdict
    reason: str
    source: str

def normalize_username(username: str) -> str:
    return (username or "").strip().lstrip("@").lower()

def local_username_check(username: str, *, with_digits: bool = True) -> CheckResult:
    u = normalize_username(username)
    if not USERNAME_RE.fullmatch(u):
        return CheckResult(CheckVerdict.SKIP, "bad_format", "local")
    if not with_digits and not u.isalpha():
        return CheckResult(CheckVerdict.SKIP, "digits_disabled", "local")
    if "__" in u or u.endswith("_"):
        return CheckResult(CheckVerdict.SKIP, "bad_underscore", "local")
    if any(part in u for part in RESERVED_PARTS):
        return CheckResult(CheckVerdict.SKIP, "reserved_part", "local")
    clean = u.replace("_", "")
    if len(set(clean)) <= 2 or re.search(r"(.)\1\1", clean):
        return CheckResult(CheckVerdict.SKIP, "too_repetitive", "local")
    return CheckResult(CheckVerdict.OK, "format_ok", "local")

async def fragment_username_check(session: aiohttp.ClientSession, username: str, *, strict: bool = True, timeout_seconds: float = 6.0) -> CheckResult:
    u = normalize_username(username)
    url = f"https://fragment.com/username/{u}"
    headers = {"User-Agent": "Mozilla/5.0 NexaSearchSafeChecker/1.0", "Accept": "text/html,application/xhtml+xml"}
    try:
        async with session.get(url, headers=headers, timeout=timeout_seconds, allow_redirects=True) as resp:
            text = (await resp.text(errors="ignore")).lower()
            if resp.status == 404:
                return CheckResult(CheckVerdict.OK, "fragment_404", "fragment")
            markers = ("fragment", "username", "auction", "available", "for sale", "sold", "owner", "ton", "collectible", "status")
            if resp.status == 200 and any(m in text for m in markers):
                if u in text or "username" in text or "auction" in text or "available" in text:
                    return CheckResult(CheckVerdict.SKIP, "fragment_card_exists", "fragment")
            if 200 <= resp.status < 500:
                return CheckResult(CheckVerdict.OK, f"fragment_no_card_http_{resp.status}", "fragment")
            return CheckResult(CheckVerdict.SKIP if strict else CheckVerdict.RETRY, f"fragment_http_{resp.status}", "fragment")
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return CheckResult(CheckVerdict.SKIP if strict else CheckVerdict.RETRY, "fragment_network_error", "fragment")

async def telegram_bot_api_check(bot: Bot, username: str, *, strict: bool = True) -> CheckResult:
    u = normalize_username(username)
    try:
        await bot.get_chat(f"@{u}")
        return CheckResult(CheckVerdict.SKIP, "telegram_chat_exists", "telegram_bot_api")
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "chat not found" in msg or "username not found" in msg:
            return CheckResult(CheckVerdict.OK, "telegram_not_found", "telegram_bot_api")
        if "wrong username" in msg or "username_invalid" in msg or "invalid username" in msg:
            return CheckResult(CheckVerdict.SKIP, "telegram_invalid_username", "telegram_bot_api")
        return CheckResult(CheckVerdict.SKIP if strict else CheckVerdict.RETRY, "telegram_bad_request", "telegram_bot_api")
    except TelegramRetryAfter:
        return CheckResult(CheckVerdict.RETRY, "telegram_retry_after", "telegram_bot_api")
    except (TelegramNetworkError, TelegramForbiddenError):
        return CheckResult(CheckVerdict.SKIP if strict else CheckVerdict.RETRY, "telegram_network_or_forbidden", "telegram_bot_api")

async def tme_web_check(session: aiohttp.ClientSession, username: str, *, strict: bool = True, timeout_seconds: float = 6.0) -> CheckResult:
    u = normalize_username(username)
    url = f"https://t.me/{u}"
    headers = {"User-Agent": "Mozilla/5.0 NexaSearchSafeChecker/1.0", "Accept": "text/html,application/xhtml+xml"}
    try:
        async with session.get(url, headers=headers, timeout=timeout_seconds, allow_redirects=True) as resp:
            text = (await resp.text(errors="ignore")).lower()
            occupied = ("tgme_page_title", "tgme_page_extra", "tgme_page_description", "view in telegram", "open in telegram")
            free = ("username not found", "not found")
            if resp.status == 200 and any(m in text for m in occupied):
                return CheckResult(CheckVerdict.SKIP, "tme_profile_exists", "tme")
            if resp.status == 404 or any(m in text for m in free):
                return CheckResult(CheckVerdict.OK, "tme_not_found", "tme")
            return CheckResult(CheckVerdict.SKIP if strict else CheckVerdict.RETRY, f"tme_unknown_http_{resp.status}", "tme")
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return CheckResult(CheckVerdict.SKIP if strict else CheckVerdict.RETRY, "tme_network_error", "tme")

async def safe_username_check(bot: Bot, session: aiohttp.ClientSession, username: str, *, with_digits: bool = True, strict: bool = True, use_tme: bool = False) -> CheckResult:
    u = normalize_username(username)
    local = local_username_check(u, with_digits=with_digits)
    if local.verdict != CheckVerdict.OK:
        return local
    fragment = await fragment_username_check(session, u, strict=strict)
    if fragment.verdict != CheckVerdict.OK:
        return fragment
    tg = await telegram_bot_api_check(bot, u, strict=strict)
    if tg.verdict != CheckVerdict.OK:
        return tg
    if use_tme:
        tme = await tme_web_check(session, u, strict=strict)
        if tme.verdict != CheckVerdict.OK:
            return tme
    return CheckResult(CheckVerdict.OK, "safe_to_show", "final")
