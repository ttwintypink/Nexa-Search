import asyncio

import aiohttp
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

import bot as legacy_bot
from core.pipeline import (
    PipelineContext,
    PipelineResult,
    PipelineTimeouts,
    RetryPolicy,
    UsernameAvailabilityPipeline,
)


def build_pipeline_context(username: str, mode: str = "strict") -> PipelineContext:
    normalized_mode = legacy_bot.normalize_search_mode(mode)
    preset = legacy_bot.MODE_PRESETS[normalized_mode]
    return PipelineContext(
        username_raw=username,
        strict=bool(preset["strict"]),
        mode=normalized_mode,
        timeouts=PipelineTimeouts(
            fragment_seconds=float(
                legacy_bot.os.getenv("PIPELINE_FRAGMENT_TIMEOUT_SECONDS", "4.0")
            ),
            telegram_seconds=float(
                legacy_bot.os.getenv("PIPELINE_TELEGRAM_TIMEOUT_SECONDS", "4.0")
            ),
        ),
        retry_policy=RetryPolicy(
            attempts=max(
                1,
                int(legacy_bot.os.getenv("PIPELINE_RETRY_ATTEMPTS", "1")),
            ),
            delay_seconds=max(
                0.0,
                float(legacy_bot.os.getenv("PIPELINE_RETRY_DELAY_SECONDS", "0.0")),
            ),
        ),
    )


async def run_username_pipeline(
    username: str,
    session: aiohttp.ClientSession | None = None,
    mode: str = "strict",
) -> PipelineResult:
    context = build_pipeline_context(username, mode=mode)
    if session is not None:
        pipeline = UsernameAvailabilityPipeline(
            bot=legacy_bot.bot,
            http_session=session,
        )
        return await pipeline.run(context)

    timeout = aiohttp.ClientTimeout(
        total=max(
            context.timeouts.fragment_seconds + context.timeouts.telegram_seconds,
            4.0,
        )
    )
    async with aiohttp.ClientSession(timeout=timeout) as owned_session:
        pipeline = UsernameAvailabilityPipeline(
            bot=legacy_bot.bot,
            http_session=owned_session,
        )
        return await pipeline.run(context)


def render_diag_report(result: PipelineResult) -> str:
    username = result.normalized_username or legacy_bot.clean_check_username(
        result.username_raw
    )
    lines = [
        "<b>diag</b>",
        f"user: <code>@{legacy_bot.esc(username)}</code>",
        f"decision: <code>{legacy_bot.esc(result.decision.value)}</code>",
        f"reason: <code>{legacy_bot.esc(result.reason)}</code>",
        "",
    ]
    for stage in result.stages:
        status = "-" if stage.http_status is None else str(stage.http_status)
        lines.extend(
            [
                f"<b>{legacy_bot.esc(stage.stage_name)}</b>",
                f"result: <code>{legacy_bot.esc(stage.outcome.value)}</code>",
                f"http_status: <code>{legacy_bot.esc(status)}</code>",
                f"latency_ms: <code>{stage.latency_ms}</code>",
                f"reason: <code>{legacy_bot.esc(stage.reason)}</code>",
                "",
            ]
        )
    return "\n".join(lines).strip()


async def final_verify_username(
    username: str,
    session: aiohttp.ClientSession,
    mode: str = "turbo",
) -> tuple[bool, str]:
    username = legacy_bot.clean_check_username(username)
    if legacy_bot.is_unsettable_profile_username(username):
        return False, "invalid_or_unsettable"
    result = await run_username_pipeline(username, session=session, mode=mode)
    return result.is_candidate, result.reason


async def check_username_available(username: str) -> tuple[bool, str]:
    username = legacy_bot.clean_check_username(username)
    if legacy_bot.is_unsettable_profile_username(username):
        return False, "invalid_or_unsettable"
    result = await run_username_pipeline(username, mode="strict")
    return result.is_candidate, result.reason


async def quick_check_candidate(
    username: str,
    session: aiohttp.ClientSession,
    mode: str,
) -> tuple[bool, str]:
    username = legacy_bot.clean_check_username(username)
    if legacy_bot.is_unsettable_profile_username(username):
        return False, "invalid_or_unsettable"
    result = await run_username_pipeline(username, session=session, mode=mode)
    return result.is_candidate, result.reason


def install_monkeypatches() -> None:
    legacy_bot.WEB_DOUBLE_CHECK = False
    legacy_bot.FRAGMENT_DOUBLE_CHECK = True
    legacy_bot.final_verify_username = final_verify_username
    legacy_bot.check_username_available = check_username_available
    legacy_bot.quick_check_candidate = quick_check_candidate


@legacy_bot.dp.message(Command("diag"))
async def diag_cmd(message: Message, command: CommandObject) -> None:
    await legacy_bot.register_if_needed(
        message.from_user.id,
        message.from_user.first_name or "",
        message.from_user.username or "",
    )
    await legacy_bot.clear_user_message(message)
    if not legacy_bot.is_admin(message.from_user.id):
        await legacy_bot.screen(
            message.chat.id,
            message.from_user.id,
            "<b>РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ РїСЂР°РІ.</b>",
            legacy_bot.back_main_kb(),
        )
        return
    username = legacy_bot.clean_check_username(command.args or "")
    if not username:
        await legacy_bot.screen(
            message.chat.id,
            message.from_user.id,
            "<b>usage:</b> <code>/diag username</code>",
            legacy_bot.admin_kb(),
        )
        return
    result = await run_username_pipeline(username, mode="strict")
    await legacy_bot.screen(
        message.chat.id,
        message.from_user.id,
        render_diag_report(result),
        legacy_bot.admin_kb(),
    )


async def main() -> None:
    install_monkeypatches()
    print("[bootstrap] read-only pipeline enabled")
    await legacy_bot.main()


if __name__ == "__main__":
    asyncio.run(main())
