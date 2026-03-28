import asyncio
import logging
import os
from datetime import datetime, date
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineQuery,
    InlineQueryResultArticle, InputTextMessageContent,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import hashlib

from database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db = Database()
scheduler = AsyncIOScheduler()


# ── FSM States ──────────────────────────────────────────────────────────────

class AddGoal(StatesGroup):
    waiting_period = State()
    waiting_text = State()


class ReviewGoal(StatesGroup):
    reviewing = State()


# ── Keyboards ────────────────────────────────────────────────────────────────

def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Цели на месяц", callback_data="view:month"),
         InlineKeyboardButton(text="📆 Цели на год", callback_data="view:year")],
        [InlineKeyboardButton(text="📋 Цели на неделю", callback_data="view:week")],
        [InlineKeyboardButton(text="➕ Добавить цель", callback_data="add_goal")],
        [InlineKeyboardButton(text="🗑 Удалить цель", callback_data="delete_goal")],
    ])


def period_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Неделя", callback_data="period:week"),
         InlineKeyboardButton(text="📅 Месяц", callback_data="period:month"),
         InlineKeyboardButton(text="📆 Год", callback_data="period:year")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back:main")],
    ])


def yes_no_kb(goal_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data=f"review:yes:{goal_id}"),
         InlineKeyboardButton(text="❌ Нет", callback_data=f"review:no:{goal_id}")],
    ])


def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="back:main")]
    ])


# ── Helpers ──────────────────────────────────────────────────────────────────

def format_goals(goals: list, title: str) -> str:
    if not goals:
        return f"{title}\n\n_Целей нет. Добавь через меню!_"
    lines = [title, ""]
    for i, g in enumerate(goals, 1):
        status = "✅" if g["done"] else "🔲"
        lines.append(f"{status} {i}. {g['text']}")
    return "\n".join(lines)


def period_label(period: str) -> str:
    return {"week": "📋 Неделя", "month": "📅 Месяц", "year": "📆 Год"}.get(period, period)


# ── /start ────────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    db.ensure_user(message.from_user.id)
    await message.answer(
        "👋 *Goals Bot*\n\nОтслеживай цели на неделю, месяц и год.\n"
        "В любом чате используй `@имя_бота` чтобы поделиться своими целями.",
        parse_mode="Markdown",
        reply_markup=main_kb()
    )


@dp.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("📌 Главное меню", reply_markup=main_kb())


# ── View Goals ────────────────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("view:"))
async def view_goals(callback: CallbackQuery):
    period = callback.data.split(":")[1]
    uid = callback.from_user.id
    goals = db.get_goals(uid, period)
    titles = {"week": "📋 Цели на неделю", "month": "📅 Цели на месяц", "year": "📆 Цели на год"}
    text = format_goals(goals, titles[period])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_kb())
    await callback.answer()


# ── Add Goal ──────────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "add_goal")
async def add_goal_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddGoal.waiting_period)
    await callback.message.edit_text("Выбери период для цели:", reply_markup=period_kb())
    await callback.answer()


@dp.callback_query(AddGoal.waiting_period, F.data.startswith("period:"))
async def add_goal_period(callback: CallbackQuery, state: FSMContext):
    period = callback.data.split(":")[1]
    await state.update_data(period=period)
    await state.set_state(AddGoal.waiting_text)
    label = period_label(period)
    await callback.message.edit_text(
        f"✏️ Напиши цель для периода *{label}*:\n\n_(отправь текстом)_",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(AddGoal.waiting_text)
async def add_goal_text(message: Message, state: FSMContext):
    data = await state.get_data()
    period = data["period"]
    goal_text = message.text.strip()
    if len(goal_text) > 300:
        await message.answer("❗ Цель слишком длинная (макс 300 символов). Сократи.")
        return
    db.add_goal(message.from_user.id, period, goal_text)
    await state.clear()
    label = period_label(period)
    await message.answer(
        f"✅ Цель добавлена в *{label}*:\n_{goal_text}_",
        parse_mode="Markdown",
        reply_markup=main_kb()
    )


# ── Delete Goal ───────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "delete_goal")
async def delete_goal_menu(callback: CallbackQuery):
    uid = callback.from_user.id
    buttons = []
    for period, label in [("week", "📋 Неделя"), ("month", "📅 Месяц"), ("year", "📆 Год")]:
        goals = db.get_goals(uid, period)
        for g in goals:
            buttons.append([InlineKeyboardButton(
                text=f"{label} | {g['text'][:40]}",
                callback_data=f"del:{g['id']}"
            )])
    if not buttons:
        await callback.answer("Нет целей для удаления", show_alert=True)
        return
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back:main")])
    await callback.message.edit_text(
        "🗑 Выбери цель для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("del:"))
async def delete_goal_confirm(callback: CallbackQuery):
    goal_id = int(callback.data.split(":")[1])
    db.delete_goal(callback.from_user.id, goal_id)
    await callback.answer("✅ Цель удалена")
    await callback.message.edit_text("✅ Цель удалена", reply_markup=main_kb())


# ── Back ──────────────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "back:main")
async def back_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("📌 Главное меню", reply_markup=main_kb())
    await callback.answer()


# ── Review (да/нет по целям) ──────────────────────────────────────────────────

async def send_review(uid: int, period: str, label: str):
    goals = db.get_active_goals(uid, period)
    if not goals:
        return
    goal = goals[0]
    try:
        await bot.send_message(
            uid,
            f"🔔 *Ежемесячный отчёт* — {label}\n\nЦель: _{goal['text']}_\n\nУдалось?",
            parse_mode="Markdown",
            reply_markup=yes_no_kb(goal["id"])
        )
    except Exception as e:
        logger.warning(f"Cannot send review to {uid}: {e}")


@dp.callback_query(F.data.startswith("review:"))
async def handle_review(callback: CallbackQuery):
    _, result, goal_id = callback.data.split(":")
    goal_id = int(goal_id)
    uid = callback.from_user.id
    done = result == "yes"

    db.mark_goal(goal_id, done)

    if done:
        msg = "✅ Отлично! Цель выполнена и отмечена."
    else:
        # перенести на следующий период
        goal = db.get_goal_by_id(goal_id)
        if goal:
            db.add_goal(uid, goal["period"], goal["text"])
        msg = "❌ Цель не выполнена — перенесена на следующий период."

    await callback.message.edit_text(msg, reply_markup=main_kb())
    await callback.answer()

    # следующая цель для ревью
    goals = db.get_active_goals(uid, "month")
    if goals:
        goal = goals[0]
        await callback.message.answer(
            f"Следующая цель: _{goal['text']}_\n\nУдалось?",
            parse_mode="Markdown",
            reply_markup=yes_no_kb(goal["id"])
        )


# ── Inline Mode ───────────────────────────────────────────────────────────────

@dp.inline_query()
async def inline_goals(inline_query: InlineQuery):
    uid = inline_query.from_user.id
    query = inline_query.query.strip().lower()
    results = []

    periods = []
    if query in ("", "все", "all"):
        periods = ["week", "month", "year"]
    elif query in ("неделя", "week", "н"):
        periods = ["week"]
    elif query in ("месяц", "month", "м"):
        periods = ["month"]
    elif query in ("год", "year", "г"):
        periods = ["year"]
    else:
        periods = ["week", "month", "year"]

    titles = {"week": "📋 Цели на неделю", "month": "📅 Цели на месяц", "year": "📆 Цели на год"}

    for period in periods:
        goals = db.get_goals(uid, period)
        text = format_goals(goals, titles[period])
        uid_hash = hashlib.md5(f"{uid}{period}".encode()).hexdigest()[:8]
        results.append(
            InlineQueryResultArticle(
                id=uid_hash,
                title=titles[period],
                description=f"{len(goals)} целей" if goals else "Нет целей",
                input_message_content=InputTextMessageContent(
                    message_text=text,
                    parse_mode="Markdown"
                )
            )
        )

    await inline_query.answer(results, cache_time=10, is_personal=True)


# ── Scheduler Jobs ────────────────────────────────────────────────────────────

async def monthly_review_job():
    """1-го числа каждого месяца — опрос по месячным целям"""
    users = db.get_all_users()
    for uid in users:
        await send_review(uid, "month", "Месяц")


async def quarterly_review_job():
    """Раз в квартал (1 января, апреля, июля, октября) — опрос по годовым целям"""
    today = date.today()
    if today.month in (1, 4, 7, 10) and today.day == 1:
        users = db.get_all_users()
        for uid in users:
            await send_review(uid, "year", "Год (квартальный чек)")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    db.init()

    # Ежемесячно 1-го числа в 10:00
    scheduler.add_job(monthly_review_job, "cron", day=1, hour=10, minute=0)
    # Ежедневно проверяем — квартал?
    scheduler.add_job(quarterly_review_job, "cron", hour=10, minute=5)
    scheduler.start()

    logger.info("Bot started")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
