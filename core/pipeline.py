from __future__ import annotations

import asyncio
import html
import re
import time
from dataclasses import dataclass, field, replace
from enum import Enum

import aiohttp
from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{4,31}$")
BAD_RESERVED_PARTS = ("telegram", "support", "admin", "helpdesk")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 NexaSearchReadOnlyPipeline/1.0"
)


class StageOutcome(str, Enum):
    PASS = "pass"
    SKIP = "skip"
    ERROR = "error"


class PipelineDecision(str, Enum):
    CANDIDATE = "candidate"
    SKIP = "skip"
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 1
    delay_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class PipelineTimeouts:
    fragment_seconds: float = 4.0
    telegram_seconds: float = 4.0


@dataclass(frozen=True, slots=True)
class PipelineContext:
    username_raw: str
    strict: bool
    mode: str
    timeouts: PipelineTimeouts
    retry_policy: RetryPolicy = RetryPolicy()


@dataclass(frozen=True, slots=True)
class StageResult:
    stage_name: str
    outcome: StageOutcome
    reason: str
    http_status: int | None
    latency_ms: int


@dataclass(frozen=True, slots=True)
class PipelineResult:
    username_raw: str
    normalized_username: str | None
    decision: PipelineDecision
    reason: str
    stages: tuple[StageResult, ...] = field(default_factory=tuple)

    @property
    def is_candidate(self) -> bool:
        return self.decision is PipelineDecision.CANDIDATE


@dataclass(frozen=True, slots=True)
class PipelineState:
    context: PipelineContext
    normalized_username: str | None = None
    stages: tuple[StageResult, ...] = field(default_factory=tuple)
    halted: bool = False
    decision: PipelineDecision | None = None
    decision_reason: str | None = None

    def add_stage(
        self,
        result: StageResult,
        *,
        normalized_username: str | None = None,
        halted: bool | None = None,
    ) -> PipelineState:
        return replace(
            self,
            normalized_username=(
                self.normalized_username
                if normalized_username is None
                else normalized_username
            ),
            stages=self.stages + (result,),
            halted=self.halted if halted is None else halted,
        )


class UsernameHandler:
    stage_name = "UsernameHandler"
    always_run = False

    def __init__(self, next_handler: UsernameHandler | None = None) -> None:
        self._next = next_handler

    def set_next(self, handler: UsernameHandler) -> UsernameHandler:
        self._next = handler
        return handler

    async def handle(self, state: PipelineState) -> PipelineState:
        if state.halted and not self.always_run:
            if self._next is None:
                return state
            return await self._next.handle(state)
        print(
            f"[task:processing] username={state.context.username_raw} "
            f"stage={self.stage_name}"
        )
        next_state = await self.process(state)
        if self._next is None:
            return next_state
        return await self._next.handle(next_state)

    async def process(self, state: PipelineState) -> PipelineState:
        raise NotImplementedError


class NormalizeUsernameHandler(UsernameHandler):
    stage_name = "NormalizeUsernameHandler"

    async def process(self, state: PipelineState) -> PipelineState:
        started_at = time.perf_counter()
        normalized = (state.context.username_raw or "").strip().lstrip("@").lower()
        reason = "normalized"
        outcome = StageOutcome.PASS
        halted = False

        if not USERNAME_RE.fullmatch(normalized):
            reason = "invalid_format"
            outcome = StageOutcome.SKIP
            halted = True
        elif any(part in normalized for part in BAD_RESERVED_PARTS):
            reason = "reserved_substring"
            outcome = StageOutcome.SKIP
            halted = True
        elif "__" in normalized or normalized.endswith("_"):
            reason = "invalid_underscore_pattern"
            outcome = StageOutcome.SKIP
            halted = True
        else:
            compact = normalized.replace("_", "")
            if len(set(compact)) <= 2 or re.search(r"(.)\1\1", compact):
                reason = "too_repetitive"
                outcome = StageOutcome.SKIP
                halted = True

        latency_ms = int((time.perf_counter() - started_at) * 1000)
        stage = StageResult(
            stage_name=self.stage_name,
            outcome=outcome,
            reason=reason,
            http_status=None,
            latency_ms=latency_ms,
        )
        return state.add_stage(
            stage,
            normalized_username=normalized,
            halted=halted,
        )


class FragmentCheckHandler(UsernameHandler):
    stage_name = "FragmentCheckHandler"

    def __init__(
        self,
        http_session: aiohttp.ClientSession,
        next_handler: UsernameHandler | None = None,
    ) -> None:
        super().__init__(next_handler)
        self._http_session = http_session

    async def process(self, state: PipelineState) -> PipelineState:
        username = state.normalized_username or ""
        url = f"https://fragment.com/username/{username}"
        started_at = time.perf_counter()
        attempts = max(1, state.context.retry_policy.attempts)
        last_status: int | None = None
        last_reason = "fragment_unverified"

        for attempt in range(1, attempts + 1):
            try:
                timeout = aiohttp.ClientTimeout(
                    total=state.context.timeouts.fragment_seconds
                )
                async with self._http_session.get(
                    url,
                    allow_redirects=True,
                    timeout=timeout,
                    headers={
                        "User-Agent": DEFAULT_USER_AGENT,
                        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
                    },
                ) as response:
                    last_status = response.status
                    text = await response.text(errors="ignore")
                    final_url = str(response.url).lower()
                    low = re.sub(r"\s+", " ", html.unescape(text)).lower()
                    exact_markers = (
                        f"/username/{username}",
                        f"@{username}",
                        f"{username}.t.me",
                        f">{username}<",
                        f"username/{username}",
                    )
                    belongs_to_username = (
                        any(marker in low for marker in exact_markers)
                        or f"/username/{username}" in final_url
                    )
                    not_found_markers = (
                        "not found",
                        "page not found",
                        "username not found",
                        "no results found",
                        "nothing found",
                    )
                    busy_markers = (
                        "for sale",
                        "on sale",
                        "listed for sale",
                        "sale price",
                        "buy now",
                        "make an offer",
                        "available for purchase",
                        "minimum bid",
                        "place bid",
                        "highest bid",
                        "current bid",
                        "bid history",
                        "auction",
                        "auction ends",
                        "sold for",
                        "sold",
                        "taken",
                        "unavailable",
                        "owned by",
                        "owner",
                        "ownership history",
                        "collectible username",
                        "telegram username",
                        "ton web 3.0 address",
                    )
                    if response.status in {404, 410}:
                        return state.add_stage(
                            StageResult(
                                stage_name=self.stage_name,
                                outcome=StageOutcome.PASS,
                                reason="fragment_not_listed",
                                http_status=response.status,
                                latency_ms=int(
                                    (time.perf_counter() - started_at) * 1000
                                ),
                            )
                        )
                    if not belongs_to_username and any(
                        marker in low for marker in not_found_markers
                    ):
                        return state.add_stage(
                            StageResult(
                                stage_name=self.stage_name,
                                outcome=StageOutcome.PASS,
                                reason="fragment_not_listed",
                                http_status=response.status,
                                latency_ms=int(
                                    (time.perf_counter() - started_at) * 1000
                                ),
                            )
                        )
                    if belongs_to_username and any(
                        marker in low for marker in busy_markers
                    ):
                        return state.add_stage(
                            StageResult(
                                stage_name=self.stage_name,
                                outcome=StageOutcome.SKIP,
                                reason="fragment_collectible_or_occupied",
                                http_status=response.status,
                                latency_ms=int(
                                    (time.perf_counter() - started_at) * 1000
                                ),
                            ),
                            halted=True,
                        )
                    if belongs_to_username:
                        return state.add_stage(
                            StageResult(
                                stage_name=self.stage_name,
                                outcome=StageOutcome.SKIP,
                                reason="fragment_page_exists",
                                http_status=response.status,
                                latency_ms=int(
                                    (time.perf_counter() - started_at) * 1000
                                ),
                            ),
                            halted=True,
                        )
                    last_reason = "fragment_ambiguous_response"
            except asyncio.TimeoutError:
                last_reason = "fragment_timeout"
            except aiohttp.ClientError:
                last_reason = "fragment_client_error"
            except Exception:
                last_reason = "fragment_unexpected_error"

            if attempt < attempts and state.context.retry_policy.delay_seconds > 0:
                await asyncio.sleep(state.context.retry_policy.delay_seconds)

        return state.add_stage(
            StageResult(
                stage_name=self.stage_name,
                outcome=StageOutcome.ERROR,
                reason=last_reason,
                http_status=last_status,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
            ),
            halted=True,
        )


class TelegramBotApiCheckHandler(UsernameHandler):
    stage_name = "TelegramBotApiCheckHandler"

    def __init__(
        self,
        bot: Bot,
        next_handler: UsernameHandler | None = None,
    ) -> None:
        super().__init__(next_handler)
        self._bot = bot

    async def process(self, state: PipelineState) -> PipelineState:
        username = state.normalized_username or ""
        started_at = time.perf_counter()
        attempts = max(1, state.context.retry_policy.attempts)
        last_reason = "telegram_unverified"

        for attempt in range(1, attempts + 1):
            try:
                await asyncio.wait_for(
                    self._bot.get_chat(f"@{username}"),
                    timeout=state.context.timeouts.telegram_seconds,
                )
                return state.add_stage(
                    StageResult(
                        stage_name=self.stage_name,
                        outcome=StageOutcome.SKIP,
                        reason="telegram_chat_exists",
                        http_status=200,
                        latency_ms=int(
                            (time.perf_counter() - started_at) * 1000
                        ),
                    ),
                    halted=True,
                )
            except TelegramBadRequest as exc:
                message = str(exc).lower()
                if "chat not found" in message or "username not found" in message:
                    return state.add_stage(
                        StageResult(
                            stage_name=self.stage_name,
                            outcome=StageOutcome.PASS,
                            reason="telegram_not_found",
                            http_status=400,
                            latency_ms=int(
                                (time.perf_counter() - started_at) * 1000
                            ),
                        )
                    )
                if (
                    "username_invalid" in message
                    or "invalid username" in message
                    or "wrong username" in message
                    or "forbidden" in message
                    or "not enough rights" in message
                ):
                    return state.add_stage(
                        StageResult(
                            stage_name=self.stage_name,
                            outcome=StageOutcome.SKIP,
                            reason="telegram_invalid_or_forbidden",
                            http_status=400,
                            latency_ms=int(
                                (time.perf_counter() - started_at) * 1000
                            ),
                        ),
                        halted=True,
                    )
                last_reason = "telegram_bad_request"
            except TelegramRetryAfter as exc:
                last_reason = "telegram_retry_after"
                if attempt < attempts:
                    retry_delay = max(
                        state.context.retry_policy.delay_seconds,
                        float(exc.retry_after),
                    )
                    await asyncio.sleep(retry_delay)
                    continue
            except TelegramForbiddenError:
                return state.add_stage(
                    StageResult(
                        stage_name=self.stage_name,
                        outcome=StageOutcome.SKIP,
                        reason="telegram_forbidden",
                        http_status=403,
                        latency_ms=int((time.perf_counter() - started_at) * 1000),
                    ),
                    halted=True,
                )
            except TelegramNetworkError:
                last_reason = "telegram_network_error"
            except asyncio.TimeoutError:
                last_reason = "telegram_timeout"
            except Exception:
                last_reason = "telegram_unexpected_error"

            if attempt < attempts and state.context.retry_policy.delay_seconds > 0:
                await asyncio.sleep(state.context.retry_policy.delay_seconds)

        return state.add_stage(
            StageResult(
                stage_name=self.stage_name,
                outcome=StageOutcome.ERROR,
                reason=last_reason,
                http_status=None,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
            ),
            halted=True,
        )


class ResultDecisionHandler(UsernameHandler):
    stage_name = "ResultDecisionHandler"
    always_run = True

    async def process(self, state: PipelineState) -> PipelineState:
        decision = PipelineDecision.CANDIDATE
        reason = "candidate_after_read_only_checks"
        outcome = StageOutcome.PASS

        for stage in state.stages:
            if stage.outcome is StageOutcome.ERROR:
                decision = PipelineDecision.UNVERIFIED
                reason = stage.reason
                outcome = StageOutcome.ERROR
                break
            if stage.outcome is StageOutcome.SKIP:
                decision = PipelineDecision.SKIP
                reason = stage.reason
                outcome = StageOutcome.SKIP
                break

        final_stage = StageResult(
            stage_name=self.stage_name,
            outcome=outcome,
            reason=reason,
            http_status=None,
            latency_ms=0,
        )
        return replace(
            state.add_stage(final_stage),
            decision=decision,
            decision_reason=reason,
            halted=True,
        )


class UsernameAvailabilityPipeline:
    def __init__(
        self,
        bot: Bot,
        http_session: aiohttp.ClientSession,
    ) -> None:
        self._entrypoint = NormalizeUsernameHandler()
        fragment = self._entrypoint.set_next(FragmentCheckHandler(http_session))
        telegram = fragment.set_next(TelegramBotApiCheckHandler(bot))
        telegram.set_next(ResultDecisionHandler())

    async def run(self, context: PipelineContext) -> PipelineResult:
        print(
            f"[task:init] username={context.username_raw} "
            f"mode={context.mode} strict={context.strict}"
        )
        initial_state = PipelineState(context=context)
        try:
            final_state = await self._entrypoint.handle(initial_state)
            result = PipelineResult(
                username_raw=context.username_raw,
                normalized_username=final_state.normalized_username,
                decision=final_state.decision or PipelineDecision.UNVERIFIED,
                reason=final_state.decision_reason or "pipeline_unverified",
                stages=final_state.stages,
            )
        except Exception:
            stage = StageResult(
                stage_name=self.__class__.__name__,
                outcome=StageOutcome.ERROR,
                reason="pipeline_unexpected_error",
                http_status=None,
                latency_ms=0,
            )
            result = PipelineResult(
                username_raw=context.username_raw,
                normalized_username=None,
                decision=PipelineDecision.UNVERIFIED,
                reason="pipeline_unexpected_error",
                stages=(stage,),
            )

        if result.decision is PipelineDecision.UNVERIFIED:
            print(
                f"[task:error] username={result.normalized_username or context.username_raw} "
                f"decision={result.decision.value} reason={result.reason}"
            )
        else:
            print(
                f"[task:success] username={result.normalized_username or context.username_raw} "
                f"decision={result.decision.value} reason={result.reason}"
            )
        return result
