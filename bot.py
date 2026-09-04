import os
import sqlite3
import secrets
import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

bot = Bot(TOKEN)
dp = Dispatcher()

db = sqlite3.connect("bot.db", check_same_thread=False)

db.execute("""
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    name TEXT,
    pair_code TEXT,
    partner_id INTEGER
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS needs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    need TEXT,
    intensity INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

db.commit()


NEEDS = [
    "🫂 Хочу близькості",
    "💋 Хочу ніжності",
    "💬 Хочу поговорити",
    "👂 Хочу, щоб мене вислухали",
    "🤝 Потрібна підтримка",
    "🏠 Хочу побути наодинці",
    "🧘 Потрібно менше контакту",
    "🎮 Хочу провести час разом",
    "🔥 Хочу сексуальної близькості",
    "🆘 Мені зараз важко",
]


def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💗 Мої потреби",
                    callback_data="needs",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👀 Стан партнера",
                    callback_data="partner",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔗 Під'єднати партнера",
                    callback_data="pair",
                )
            ],
        ]
    )


def needs_menu():
    buttons = []

    for index, need in enumerate(NEEDS):
        buttons.append(
            [
                InlineKeyboardButton(
                    text=need,
                    callback_data=f"need:{index}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="home",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def intensity_menu(need_index):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=str(number),
                    callback_data=f"intensity:{need_index}:{number}",
                )
                for number in range(1, 6)
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="needs",
                )
            ],
        ]
    )


def ensure_user(event):
    user = event.from_user

    db.execute(
        """
        INSERT OR IGNORE INTO users (telegram_id, name)
        VALUES (?, ?)
        """,
        (
            user.id,
            user.first_name or "Користувач",
        ),
    )

    db.commit()


@dp.message(CommandStart())
async def start(message: Message):
    ensure_user(message)

    await message.answer(
        "Привіт 💗\n\n"
        "Цей бот допоможе вам із партнером "
        "ділитися своїми актуальними потребами.\n\n"
        "Що хочеш зробити?",
        reply_markup=main_menu(),
    )


@dp.callback_query(F.data == "home")
async def home(callback: CallbackQuery):
    await callback.message.edit_text(
        "Що хочеш зробити?",
        reply_markup=main_menu(),
    )

    await callback.answer()


@dp.callback_query(F.data == "needs")
async def show_needs(callback: CallbackQuery):
    ensure_user(callback)

    await callback.message.edit_text(
        "💗 Що тобі зараз потрібно?",
        reply_markup=needs_menu(),
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("need:"))
async def choose_need(callback: CallbackQuery):
    index = int(callback.data.split(":")[1])

    await callback.message.edit_text(
        f"{NEEDS[index]}\n\n"
        "Наскільки сильно тобі цього хочеться зараз?\n\n"
        "1 — трохи\n"
        "5 — дуже сильно",
        reply_markup=intensity_menu(index),
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("intensity:"))
async def save_need(callback: CallbackQuery):
    _, index, intensity = callback.data.split(":")

    index = int(index)
    intensity = int(intensity)

    need = NEEDS[index]
    user_id = callback.from_user.id

    ensure_user(callback)

    db.execute(
        """
        INSERT INTO needs (telegram_id, need, intensity)
        VALUES (?, ?, ?)
        """,
        (
            user_id,
            need,
            intensity,
        ),
    )

    db.commit()

    result = db.execute(
        """
        SELECT partner_id
        FROM users
        WHERE telegram_id = ?
        """,
        (user_id,),
    ).fetchone()

    scale = "●" * intensity + "○" * (5 - intensity)

    await callback.message.edit_text(
        "Збережено 💗\n\n"
        f"{need}\n"
        f"Важливість: {scale}",
        reply_markup=main_menu(),
    )

    if result and result[0]:
        partner_id = result[0]

        try:
            name = callback.from_user.first_name or "Партнер"

            await bot.send_message(
                partner_id,
                "💗 Оновлення від партнера\n\n"
                f"{name} зараз відчуває потребу:\n\n"
                f"{need}\n"
                f"Важливість: {scale}",
            )

        except Exception:
            pass

    await callback.answer("Потребу збережено 💗")


@dp.callback_query(F.data == "pair")
async def pair(callback: CallbackQuery):
    ensure_user(callback)

    user_id = callback.from_user.id

    result = db.execute(
        """
        SELECT pair_code, partner_id
        FROM users
        WHERE telegram_id = ?
        """,
        (user_id,),
    ).fetchone()

    if result and result[1]:
        await callback.message.edit_text(
            "💗 Партнер уже під'єднаний.",
            reply_markup=main_menu(),
        )

        await callback.answer()
        return

    code = result[0] if result else None

    if not code:
        code = secrets.token_hex(3).upper()

        db.execute(
            """
            UPDATE users
            SET pair_code = ?
            WHERE telegram_id = ?
            """,
            (
                code,
                user_id,
            ),
        )

        db.commit()

    await callback.message.edit_text(
        "🔗 Під'єднання партнера\n\n"
        "Надішли партнеру цей код:\n\n"
        f"<code>{code}</code>\n\n"
        "Партнеру потрібно:\n"
        "1. Відкрити цього бота.\n"
        "2. Натиснути Start.\n"
        "3. Надіслати цей код повідомленням.",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )

    await callback.answer()


@dp.message(F.text.regexp(r"^[A-Fa-f0-9]{6}$"))
async def connect_partner(message: Message):
    ensure_user(message)

    code = message.text.strip().upper()
    user_id = message.from_user.id

    result = db.execute(
        """
        SELECT telegram_id
        FROM users
        WHERE pair_code = ?
        AND telegram_id != ?
        """,
        (
            code,
            user_id,
        ),
    ).fetchone()

    if not result:
        await message.answer(
            "Не знайшла такого коду 😕\n"
            "Перевір його та спробуй ще раз."
        )
        return

    partner_id = result[0]

    db.execute(
        """
        UPDATE users
        SET partner_id = ?
        WHERE telegram_id = ?
        """,
        (
            partner_id,
            user_id,
        ),
    )

    db.execute(
        """
        UPDATE users
        SET partner_id = ?
        WHERE telegram_id = ?
        """,
        (
            user_id,
            partner_id,
        ),
    )

    db.commit()

    await message.answer(
        "Готово! 💗\n\n"
        "Ви тепер під'єднані.",
        reply_markup=main_menu(),
    )

    try:
        name = message.from_user.first_name or "Партнер"

        await bot.send_message(
            partner_id,
            f"💗 {name} під'єднався/під'єдналася до вашої пари!",
            reply_markup=main_menu(),
        )

    except Exception:
        pass


@dp.callback_query(F.data == "partner")
async def partner_status(callback: CallbackQuery):
    ensure_user(callback)

    user_id = callback.from_user.id

    result = db.execute(
        """
        SELECT partner_id
        FROM users
        WHERE telegram_id = ?
        """,
        (user_id,),
    ).fetchone()

    if not result or not result[0]:
        await callback.message.edit_text(
            "Спочатку потрібно під'єднати партнера 🔗",
            reply_markup=main_menu(),
        )

        await callback.answer()
        return

    partner_id = result[0]

    partner = db.execute(
        """
        SELECT name
        FROM users
        WHERE telegram_id = ?
        """,
        (partner_id,),
    ).fetchone()

    latest = db.execute(
        """
        SELECT need, intensity
        FROM needs
        WHERE telegram_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (partner_id,),
    ).fetchone()

    partner_name = partner[0] if partner else "Партнер"

    if not latest:
        text = (
            f"👀 {partner_name} поки що "
            "не додавав/ла жодної потреби."
        )

    else:
        need, intensity = latest
        scale = "●" * intensity + "○" * (5 - intensity)

        text = (
            f"👀 Зараз у {partner_name}:\n\n"
            f"{need}\n"
            f"Важливість: {scale}"
        )

    await callback.message.edit_text(
        text,
        reply_markup=main_menu(),
    )

    await callback.answer()


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
