"""
Staged concurrency / load test for Bot-File-School.

The bot is a Telegram long-polling service: there is no HTTP endpoint to hit,
so load is generated the way the real system receives it - by feeding Update
objects through the REAL dispatcher (same routers, middlewares, FSM storage and
SQLite database the production process uses) from many concurrent tasks.

Every simulated user picks a random action from the project's real feature mix,
with jitter, drop-outs, double clicks and stale ids, so the load is not a single
repeated call.

Run:  python tests/load_test.py            # stages 10..1000
      python tests/load_test.py 10 50      # only the given stages
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import random
import shutil
import statistics
import sys
import time
from collections import Counter
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# reuse the functional-test harness (fake Telegram session + real wiring)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import conftest  # noqa: E402  (sets env vars, must come first)

import models  # noqa: E402
from conftest import (  # noqa: E402
    OWNER_ID,
    callback_update,
    make_callback,
    make_chat,
    make_message,
    make_user,
    message_update,
)

STAGES = [10, 50, 100, 250, 500, 750, 1000]
OPS_PER_USER = 8
ACTION_TIMEOUT = 30.0
pending_tasks: set[asyncio.Task] = set()


# ─── database instrumentation ────────────────────────────────────────────────


class DbStats:
    def __init__(self) -> None:
        self.connections_opened = 0
        self.connections_closed = 0
        self.active_connections = 0
        self.peak_active_connections = 0
        self.locked_errors = 0
        self.query_times: list[float] = []

    def summary(self) -> dict:
        return {
            "connections_opened": self.connections_opened,
            "connections_leaked": self.connections_opened - self.connections_closed,
            "active_connections": self.active_connections,
            "peak_active_connections": self.peak_active_connections,
            "database_locked_errors": self.locked_errors,
            "measure_query_avg_ms": round(
                1000 * statistics.fmean(self.query_times), 3) if self.query_times else 0.0,
            "measure_query_p95_ms": round(
                1000 * percentile(self.query_times, 95), 3) if self.query_times else 0.0,
        }


db_stats = DbStats()


def instrument_database() -> None:
    import database

    real_get_db = database.get_db

    async def counting_get_db():
        conn = await real_get_db()
        db_stats.connections_opened += 1
        db_stats.active_connections += 1
        db_stats.peak_active_connections = max(
            db_stats.peak_active_connections, db_stats.active_connections)

        real_close = conn.close
        closed = False

        async def counting_close():
            nonlocal closed
            if not closed:
                try:
                    return await real_close()
                finally:
                    closed = True
                    db_stats.connections_closed += 1
                    db_stats.active_connections -= 1
            return await real_close()

        conn.close = counting_close
        return conn

    # db_session / db_write_session look up get_db in this module at call time,
    # so patching it here instruments every database access.
    database.get_db = counting_get_db


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round((pct / 100) * len(ordered) + 0.5)) - 1))
    return ordered[k]


# ─── realistic user behaviour ────────────────────────────────────────────────


class World:
    def __init__(self, ids: dict):
        self.__dict__.update(ids)


async def seed() -> World:
    fid = await models.create_field("ریاضی")
    sid = await models.create_subject(fid, "هندسه")
    cid = await models.create_chapter(sid, "فصل ۱")
    note_ids = []
    for i in range(12):
        note_ids.append(
            await models.create_note(
                title=f"جزوه {i}",
                description="توضیح",
                field_id=fid,
                subject_id=sid,
                chapter_id=cid,
                page_start=1,
                page_end=5,
                file_type="document",
                file_id=f"LOADFILE{i}",
                file_unique_id=f"LOADUNIQ{i}",
                file_name=f"n{i}.pdf",
                mime_type="application/pdf",
                file_size=4096,
                submitted_by=1,
                submitted_by_name="Seeder",
                status="approved",
            )
        )
    for d, items in {
        0: ["ریاضی", "فیزیک", "شیمی"],
        1: ["هندسه", "عربی"],
        2: ["زیست", "زمین"],
    }.items():
        for i, content in enumerate(items, start=1):
            await models.set_schedule_cell(None, d, i, content)
    cat = await models.create_task_category("ریاضی")
    await models.create_task(cat, "صفحه ۲۲", "حل تمرینها", created_by=OWNER_ID)
    await models.add_online_class_full(0, "ریاضی", "16:00", "https://meet.test", start_hour=16)
    return World({"field": fid, "subject": sid, "chapter": cid,
                  "notes": note_ids, "cat": cat})


class Metrics:
    def __init__(self) -> None:
        self.total = 0
        self.ok = 0
        self.failed = 0
        self.timeouts = 0
        self.latencies: list[float] = []
        self.errors: Counter = Counter()
        self.actions: Counter = Counter()
        self.cpu_samples: list[float] = []
        self.rss_samples: list[float] = []
        self.updates = 0
        self.updates_ok = 0
        self.updates_failed = 0
        self.update_timeouts = 0
        self.update_latencies: list[float] = []
        self.db_query_latencies: list[float] = []

    def record_ok(self, dt: float, action: str) -> None:
        self.total += 1
        self.ok += 1
        self.latencies.append(dt)
        self.actions[action] += 1

    def record_error(self, exc: BaseException, action: str) -> None:
        self.total += 1
        self.failed += 1
        self.errors[f"{type(exc).__name__}: {str(exc)[:70]}"] += 1
        self.actions[action] += 1

    def record_timeout(self, action: str) -> None:
        self.total += 1
        self.timeouts += 1
        self.errors["TimeoutError: action exceeded the time budget"] += 1

    def record_update_ok(self, elapsed: float) -> None:
        self.updates += 1
        self.updates_ok += 1
        self.update_latencies.append(elapsed)

    def record_update_error(self, elapsed: float) -> None:
        self.updates += 1
        self.updates_failed += 1
        self.update_latencies.append(elapsed)

    def record_update_timeout(self, elapsed: float) -> None:
        self.updates += 1
        self.update_timeouts += 1
        self.update_latencies.append(elapsed)


def instrument_dispatcher(h):
    """Measure each incoming Telegram Update fed through the real dispatcher."""
    original_feed = h.feed
    metrics_ref = {"current": None}

    async def measured_feed(update):
        metrics = metrics_ref["current"]
        started = time.perf_counter()
        try:
            result = await original_feed(update)
        except asyncio.CancelledError:
            if metrics is not None:
                metrics.record_update_timeout(time.perf_counter() - started)
            raise
        except asyncio.TimeoutError:
            if metrics is not None:
                metrics.record_update_timeout(time.perf_counter() - started)
            raise
        except Exception:
            if metrics is not None:
                metrics.record_update_error(time.perf_counter() - started)
            raise
        if metrics is not None:
            metrics.record_update_ok(time.perf_counter() - started)
        return result

    h.feed = measured_feed
    return metrics_ref


class LoadSession(conftest.FakeSession):
    """Fake Telegram transport with deterministic transient failures."""

    def __init__(self) -> None:
        super().__init__()
        self.api_requests = 0
        self.api_failures = 0
        self.api_timeouts = 0

    async def make_request(self, bot, method, timeout=None):
        self.api_requests += 1
        request_index = self.api_requests
        if request_index % 997 == 0:
            self.api_timeouts += 1
            raise asyncio.TimeoutError("synthetic Telegram timeout")
        if request_index % 499 == 0:
            self.api_failures += 1
            raise RuntimeError("synthetic Telegram API failure")
        return await super().make_request(bot, method, timeout)


# ─── scenarios (mirror the real feature mix) ─────────────────────────────────


async def scenario_browse(h, world, user, chat, rng) -> str:
    await h.click(chat, user, "menu_fields")
    await h.click(chat, user, f"user_field:{world.field}")
    await h.click(chat, user, f"user_subject:{world.subject}")
    await h.click(chat, user, f"user_chapter:{world.chapter}")
    await h.click(chat, user, f"user_note:{rng.choice(world.notes)}")
    return "browse"


async def scenario_search(h, world, user, chat, rng) -> str:
    from aiogram.types import InlineQuery, Update

    q = rng.choice(["هندسه", "ریاضی", "جزوه", "", "ناموجود"])
    await h.feed(Update(
        update_id=rng.randrange(10**6, 10**9),
        inline_query=InlineQuery(id="q", from_user=user, query=q,
                                 offset="", chat_type="private"),
    ))
    return "search"


async def scenario_submit_note(h, world, user, chat, rng) -> str:
    await h.click(chat, user, "submit_note_start")
    await h.click(chat, user, f"submit_field:{world.field}")
    await h.click(chat, user, f"submit_subject:{world.subject}")
    await h.click(chat, user, f"submit_no_chapter:{world.subject}")
    await h.send(chat, user, f"جزوه بار {user.id}")
    await h.send(chat, user, "رد")
    await h.send(chat, user, "1-5")
    from aiogram.types import Document

    msg = make_message(
        chat, user, message_id=rng.randrange(1, 10**6),
        document=Document(
            file_id=f"FILE{user.id}", file_unique_id=f"U{user.id}",
            file_name="note.pdf", mime_type="application/pdf", file_size=2048,
        ),
    )
    await h.feed(message_update(msg))
    return "submit_note"


async def scenario_schedule(h, world, user, chat, rng) -> str:
    await h.click(chat, user, "menu_schedule")
    day = rng.randrange(0, 3)
    await h.click(chat, user, f"sched_day:{day}")
    await h.click(chat, user, f"task_done:{day}:1")
    await h.click(chat, user, "menu_tasks")
    return "schedule"


async def scenario_admin(h, world, user, chat, rng) -> str:
    # owner is auto-logged-in; the panel tabs are read-heavy
    tab = rng.choice(["admin_notes", "admin_pending", "admin_stats",
                      "admin_users", "admin_schedule", "tasks_admin_list"])
    await h.click(chat, user, tab)
    if tab == "admin_notes":
        await h.click(chat, user, f"note_view:{rng.choice(world.notes)}")
    return "admin"


async def scenario_group(h, world, user, chat, rng) -> str:
    await h.send(chat, user, rng.choice(["سلام", "ممنون", "/all"]))
    return "group_message"


async def scenario_double_click(h, world, user, chat, rng) -> str:
    """Same button pressed twice concurrently - must not duplicate data."""
    note = rng.choice(world.notes)
    await asyncio.gather(
        h.click(chat, user, f"user_note:{note}"),
        h.click(chat, user, f"user_note:{note}"),
    )
    return "double_click"


async def scenario_stale_id(h, world, user, chat, rng) -> str:
    await h.click(chat, user, f"user_note:{rng.randrange(10**6, 10**7)}")
    await h.click(chat, user, f"user_chapter:{rng.randrange(10**6, 10**7)}")
    return "stale_id"


async def scenario_stop_mid_flow(h, world, user, chat, rng) -> str:
    """User abandons a workflow half way (state must not leak)."""
    await h.click(chat, user, "submit_note_start")
    await h.click(chat, user, f"submit_field:{world.field}")
    return "abandon_flow"


async def scenario_concurrent_shared(h, world, user, chat, rng) -> str:
    """Many users hitting the exact same shared resource at the same moment."""
    await asyncio.gather(
        h.click(chat, user, "menu_schedule"),
        h.click(chat, user, f"task_done:0:{rng.choice([1, 2, 3])}"),
    )
    return "shared_resource"


SCENARIOS = [
    (scenario_browse, 26),
    (scenario_search, 16),
    (scenario_submit_note, 12),
    (scenario_schedule, 14),
    (scenario_admin, 8),
    (scenario_group, 6),
    (scenario_double_click, 6),
    (scenario_stale_id, 4),
    (scenario_stop_mid_flow, 4),
    (scenario_concurrent_shared, 4),
]


async def simulated_user(h, world, metrics, user_index: int, ops: int, seed_val: int):
    rng = random.Random(seed_val)
    is_owner = user_index % 50 == 0  # a few admins among the crowd
    uid = OWNER_ID if is_owner else 500_000 + user_index
    user = make_user(uid, f"load{user_index}", f"Load {user_index}")
    chat = make_chat(600_000 + user_index, "private")
    group = make_chat(-900_000 - (user_index % 5), "supergroup", title="Load Group")

    try:
        await h.send(chat, user, "/start")
        if is_owner:
            await h.click(chat, user, "admin_login")
    except Exception as exc:  # noqa: BLE001
        metrics.record_error(exc, "signup")
        return

    names = [s[0] for s in SCENARIOS]
    weights = [s[1] for s in SCENARIOS]

    for _ in range(ops):
        scenario = rng.choices(names, weights=weights, k=1)[0]
        label = scenario.__name__.replace("scenario_", "")
        target_chat = group if scenario in (scenario_group, scenario_stale_id) else chat
        started = time.perf_counter()
        try:
            await asyncio.wait_for(scenario(h, world, user, target_chat, rng), ACTION_TIMEOUT)
            metrics.record_ok(time.perf_counter() - started, label)
        except asyncio.TimeoutError:
            metrics.record_timeout(label)
        except Exception as exc:  # noqa: BLE001 - this is the measurement
            metrics.record_error(exc, label)
            if "locked" in str(exc).lower():
                db_stats.locked_errors += 1
        # think time: fast and slow users mixed
        if rng.random() < 0.5:
            await asyncio.sleep(rng.uniform(0, 0.01))
        if rng.random() < 0.03:
            break  # user left


async def measure_query_latency(rounds: int = 40) -> None:
    for _ in range(rounds):
        t0 = time.perf_counter()
        await models.get_approved_notes(limit=20)
        await models.search_notes("هندسه", limit=10)
        db_stats.query_times.append(time.perf_counter() - t0)


async def run_stage(h, world, users: int, ops: int, seed_val: int,
                    metrics_ref, session) -> dict:
    import psutil

    proc = psutil.Process()
    metrics = Metrics()

    before = {
        "rss_mb": round(proc.memory_info().rss / 1048576, 1),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "connections_opened": db_stats.connections_opened,
        "connections_closed": db_stats.connections_closed,
        "active_connections": db_stats.active_connections,
        "locked": db_stats.locked_errors,
        "api_requests": session.api_requests,
        "api_failures": session.api_failures,
        "api_timeouts": session.api_timeouts,
    }
    await measure_query_latency()
    baseline = {
        "rss_mb": round(proc.memory_info().rss / 1048576, 1),
        "connections_opened": db_stats.connections_opened,
        "connections_closed": db_stats.connections_closed,
        "active_connections": db_stats.active_connections,
        "locked": db_stats.locked_errors,
    }

    sampling = True

    async def sampler():
        while sampling:
            metrics.cpu_samples.append(psutil.cpu_percent(interval=None))
            metrics.rss_samples.append(proc.memory_info().rss / 1048576)
            await asyncio.sleep(0.2)

    async def db_sampler():
        while sampling:
            started = time.perf_counter()
            await models.get_approved_notes(limit=20)
            await models.search_notes("هندسه", limit=10)
            metrics.db_query_latencies.append(time.perf_counter() - started)
            await asyncio.sleep(0.5)

    sampler_task = asyncio.create_task(sampler())
    db_sampler_task = asyncio.create_task(db_sampler())
    cpu_before = psutil.cpu_percent(interval=None)
    db_stats.peak_active_connections = db_stats.active_connections
    wall_start = time.perf_counter()
    tasks = [
        asyncio.create_task(simulated_user(h, world, metrics, i, ops, seed_val + i))
        for i in range(users)
    ]
    metrics_ref["current"] = metrics
    pending_tasks.update(tasks)
    outcome = await asyncio.gather(*tasks, return_exceptions=True)
    metrics_ref["current"] = None
    for exc in outcome:
        if isinstance(exc, BaseException):
            metrics.record_error(exc, "task_crashed")
    wall = time.perf_counter() - wall_start
    sampling = False
    await sampler_task
    await db_sampler_task
    cpu_after = psutil.cpu_percent(interval=None)

    await measure_query_latency()
    after = {
        "rss_mb": round(proc.memory_info().rss / 1048576, 1),
        "connections_opened": db_stats.connections_opened,
        "connections_closed": db_stats.connections_closed,
        "active_connections": db_stats.active_connections,
        "peak_active_connections": db_stats.peak_active_connections,
        "locked": db_stats.locked_errors,
        "api_requests": session.api_requests,
        "api_failures": session.api_failures,
        "api_timeouts": session.api_timeouts,
    }

    lat = metrics.latencies
    result = {
        "users": users,
        "total": metrics.total,
        "ok": metrics.ok,
        "failed": metrics.failed,
        "timeouts": metrics.timeouts,
        "error_rate_pct": round(100 * (metrics.failed + metrics.timeouts) / max(metrics.total, 1), 2),
        "action_rps": round(metrics.total / wall, 1) if wall else 0.0,
        "updates": metrics.updates,
        "updates_ok": metrics.updates_ok,
        "updates_failed": metrics.updates_failed,
        "update_timeouts": metrics.update_timeouts,
        "update_error_rate_pct": round(
            100 * (metrics.updates_failed + metrics.update_timeouts)
            / max(metrics.updates, 1), 2),
        "update_rps": round(metrics.updates / wall, 1) if wall else 0.0,
        "update_avg_ms": round(
            1000 * statistics.fmean(metrics.update_latencies), 2)
            if metrics.update_latencies else 0.0,
        "update_median_ms": round(
            1000 * statistics.median(metrics.update_latencies), 2)
            if metrics.update_latencies else 0.0,
        "update_p95_ms": round(1000 * percentile(metrics.update_latencies, 95), 2),
        "update_p99_ms": round(1000 * percentile(metrics.update_latencies, 99), 2),
        "update_max_ms": round(1000 * max(metrics.update_latencies), 2)
            if metrics.update_latencies else 0.0,
        "db_query_avg_ms": round(
            1000 * statistics.fmean(metrics.db_query_latencies), 2)
            if metrics.db_query_latencies else 0.0,
        "db_query_p95_ms": round(
            1000 * percentile(metrics.db_query_latencies, 95), 2),
        "db_query_p99_ms": round(
            1000 * percentile(metrics.db_query_latencies, 99), 2),
        "db_query_max_ms": round(
            1000 * max(metrics.db_query_latencies), 2)
            if metrics.db_query_latencies else 0.0,
        "wall_s": round(wall, 2),
        "avg_ms": round(1000 * statistics.fmean(lat), 2) if lat else 0.0,
        "median_ms": round(1000 * statistics.median(lat), 2) if lat else 0.0,
        "p95_ms": round(1000 * percentile(lat, 95), 2),
        "p99_ms": round(1000 * percentile(lat, 99), 2),
        "max_ms": round(1000 * max(lat), 2) if lat else 0.0,
        "cpu_before": cpu_before,
        "cpu_during_avg": round(statistics.fmean(metrics.cpu_samples), 1) if metrics.cpu_samples else 0,
        "cpu_during_max": round(max(metrics.cpu_samples), 1) if metrics.cpu_samples else 0,
        "cpu_after": cpu_after,
        "rss_before_mb": baseline["rss_mb"],
        "rss_during_max_mb": round(max(metrics.rss_samples), 1) if metrics.rss_samples else 0,
        "rss_after_mb": after["rss_mb"],
        "connections_opened": after["connections_opened"] - before["connections_opened"],
        "connections_leaked": (after["connections_opened"] - after["connections_closed"])
                              - (baseline["connections_opened"] - baseline["connections_closed"]),
        "peak_db_connections": after["peak_active_connections"],
        "active_db_connections_after": after["active_connections"],
        "locked_errors": after["locked"] - before["locked"],
        "api_requests": after["api_requests"] - before["api_requests"],
        "api_failures": after["api_failures"] - before["api_failures"],
        "api_timeouts": after["api_timeouts"] - before["api_timeouts"],
        "api_success": (
            after["api_requests"] - before["api_requests"]
            - (after["api_failures"] - before["api_failures"])
            - (after["api_timeouts"] - before["api_timeouts"])
        ),
        "errors": metrics.errors.most_common(5),
        "actions": dict(metrics.actions.most_common()),
    }
    return result


def fmt_table(rows: list[dict]) -> str:
    head = (
        f"{'users':>6} | {'actions':>7} | {'updates':>7} | {'upd/s':>7} | "
        f"{'p95upd':>8} | {'p99upd':>8} | {'DB p95':>8} | "
        f"{'err%':>6} | {'cpu%':>5} | "
        f"{'rssMB':>7} | {'DB peak':>7} | {'locked':>6} | {'API err':>7} | {'API to':>6}"
    )
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append(
            f"{r['users']:>6} | {r['total']:>7} | {r['updates']:>7} | "
            f"{r['update_rps']:>7} | {r['update_p95_ms']:>8} | "
            f"{r['update_p99_ms']:>8} | {r['db_query_p95_ms']:>8} | "
            f"{r['update_error_rate_pct']:>6} | "
            f"{r['cpu_during_avg']:>5} | {r['rss_during_max_mb']:>7} | "
            f"{r['peak_db_connections']:>7} | {r['locked_errors']:>6} | "
            f"{r['api_failures']:>7} | {r['api_timeouts']:>6}"
        )
    return "\n".join(lines)


async def main(stages: list[int]) -> None:
    from database import init_database

    instrument_database()
    await init_database()

    # boot the production wiring through the shared harness
    # reuse the session-scoped fixture body manually (pytest fixtures are not
    # available in a plain script)
    import main as main_mod
    from aiogram import Bot, Dispatcher
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    bot = Bot(token=conftest.TEST_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    session = LoadSession()
    await bot.session.close()
    bot.session = session

    main_mod.Bot = lambda **kw: bot  # type: ignore[assignment]
    main_mod.start_scheduler = lambda: None  # type: ignore[assignment]
    main_mod.start_nudge_scheduler = lambda b: None  # type: ignore[assignment]
    main_mod.start_class_notifier = lambda b: None  # type: ignore[assignment]

    async def _no_polling(self, *a, **k):
        return None

    Dispatcher.start_polling = _no_polling  # type: ignore[method-assign]
    await main_mod.main()
    await main_mod.on_startup(bot)

    h = conftest.Harness(bot, main_mod.dp, session)
    metrics_ref = instrument_dispatcher(h)

    from aiogram.methods import GetMe
    session.api_requests = 498
    initial_requests = session.api_requests
    initial_failures = session.api_failures
    initial_timeouts = session.api_timeouts
    injected_failures = 0
    for _ in range(499):
        try:
            await session.make_request(bot, GetMe())
        except (RuntimeError, asyncio.TimeoutError):
            injected_failures += 1
    assert injected_failures == 2
    assert session.api_requests - initial_requests == 499
    assert session.api_failures - initial_failures == 1
    assert session.api_timeouts - initial_timeouts == 1

    world = await seed()

    print(f"Bot-File-School load test - {os.cpu_count()} CPUs, Python {sys.version.split()[0]}")
    print(f"action timeout {ACTION_TIMEOUT}s, {OPS_PER_USER} actions per user\n")

    rows = []
    for i, users in enumerate(stages):
        # fresh DB per stage so stages do not inherit each other's data volume
        await conftest._wipe_db()
        world = await seed()
        row = await run_stage(
            h, world, users, OPS_PER_USER, seed_val=1000 + i * 7919,
            metrics_ref=metrics_ref, session=session)
        rows.append(row)
        print(f"stage {users:>4} users done: {row['total']} actions, "
              f"{row['updates']} dispatcher updates, "
              f"{row['update_rps']} updates/s, "
              f"update errors {row['update_error_rate_pct']}%")
        if row["errors"]:
            for err, n in row["errors"]:
                print(f"      error x{n}: {err}")

    print()
    print(fmt_table(rows))
    print()
    print("detailed rows:")
    for r in rows:
        print(
            f"  users={r['users']:>4} wall={r['wall_s']:>6}s ok={r['ok']:>6} "
            f"failed={r['failed']:>4} timeouts={r['timeouts']:>3} "
            f"updates={r['updates']:>6} update_ok={r['updates_ok']:>6} "
            f"update_failed={r['updates_failed']:>4} update_timeouts={r['update_timeouts']:>3} "
            f"upd/s={r['update_rps']:>7} update_avg={r['update_avg_ms']:>7}ms "
            f"update_median={r['update_median_ms']:>7}ms "
            f"update_p95={r['update_p95_ms']:>7}ms update_p99={r['update_p99_ms']:>7}ms "
            f"update_max={r['update_max_ms']:>7}ms db_query_avg={r['db_query_avg_ms']:>7}ms "
            f"db_query_p95={r['db_query_p95_ms']:>7}ms "
            f"median_action={r['median_ms']:>7}ms cpu_after={r['cpu_after']:>5} "
            f"rss_before={r['rss_before_mb']:>6}MB rss_after={r['rss_after_mb']:>6}MB "
            f"DB_peak={r['peak_db_connections']:>4} DB_active={r['active_db_connections_after']:>3} "
            f"conn_leaked={r['connections_leaked']:>3} locked={r['locked_errors']:>3} "
            f"api_calls={r['api_requests']} api_failures={r['api_failures']} "
            f"api_timeouts={r['api_timeouts']}"
        )
        print(f"      actions: {r['actions']}")

    # global DB micro-benchmark summary
    print()
    print("DB micro-benchmark (20-note page + keyword search):", db_stats.summary())

    # integrity check after the whole run
    total_notes = await models.count_notes()
    pending = len(await models.get_pending_notes(limit=100000))
    print(f"integrity: notes in DB={total_notes}, pending={pending}, "
          f"leaked connections={db_stats.connections_opened - db_stats.connections_closed}")
    assert db_stats.connections_opened == db_stats.connections_closed, "connection leak!"

    await session.close()
    shutil.rmtree(conftest._TMP_ROOT, ignore_errors=True)
    tasks = pending_tasks
    for t in tasks:
        if not t.done():
            t.cancel()


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:]] or STAGES
    asyncio.run(main(args))
