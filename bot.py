import os
import sqlite3
import secrets
import asyncio
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise RuntimeError('BOT_TOKEN is not set')

bot = Bot(TOKEN)
dp = Dispatcher()

db = sqlite3.connect('bot.db', check_same_thread=False)
db.row_factory = sqlite3.Row

db.execute('''CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    telegram_name TEXT,
    display_name TEXT,
    pair_code TEXT,
    partner_id INTEGER
)''')

db.execute('''CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    emotion TEXT NOT NULL,
    resource INTEGER NOT NULL,
    needs TEXT NOT NULL,
    intensity INTEGER NOT NULL,
    support TEXT,
    avoid TEXT,
    comment TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    acknowledged INTEGER DEFAULT 0
)''')
db.commit()

EMOTIONS = [
    '🙂 Спокійно', '😊 Добре', '😔 Сумно', '😰 Тривожно', '😤 Роздратовано',
    '😵 Перевантажено', '😶 Відсторонено', '🥺 Вразливо', '🔥 Збуджено'
]

NEEDS = [
    '🫂 Близькості', '💋 Ніжності', '💬 Поговорити', '👂 Щоб мене вислухали',
    '🤝 Підтримки', '🏠 Побути наодинці', '🧘 Менше контакту',
    '🎮 Провести час разом', '🔥 Сексуальної близькості',
    '🛟 Допомоги з чимось конкретним', '❓ Не знаю, але мені щось потрібно'
]

SUPPORT = [
    '🫂 Обійняти', '👂 Просто послухати', '💬 Поговорити', '🤫 Дати тишу',
    '🏠 Дати простір', '❤️ Сказати щось тепле', '🤝 Запропонувати допомогу',
    '🎮 Побути разом без серйозних розмов', '📩 Написати пізніше',
    '❓ Спочатку запитай, що мені потрібно'
]

AVOID = [
    '🚫 Не давати порад', '🚫 Не розпитувати', '🚫 Не торкатися без запиту',
    '🚫 Не жартувати з цього', '🚫 Не намагатися одразу виправити мій стан',
    '🚫 Не залишати мене одну/одного'
]

class CheckinStates(StatesGroup):
    choosing_emotion = State()
    custom_emotion = State()
    choosing_resource = State()
    choosing_needs = State()
    custom_need = State()
    choosing_intensity = State()
    choosing_support = State()
    custom_support = State()
    choosing_avoid = State()
    custom_avoid = State()
    choosing_comment = State()
    entering_comment = State()
    choosing_duration = State()

class SetupStates(StatesGroup):
    entering_name = State()


def ensure_user(user):
    db.execute('INSERT OR IGNORE INTO users (telegram_id, telegram_name, display_name) VALUES (?, ?, ?)',
               (user.id, user.first_name or 'Користувач', user.first_name or 'Користувач'))
    db.execute('UPDATE users SET telegram_name = ? WHERE telegram_id = ?',
               (user.first_name or 'Користувач', user.id))
    db.commit()


def get_display_name(user_id):
    row = db.execute('SELECT display_name, telegram_name FROM users WHERE telegram_id = ?', (user_id,)).fetchone()
    if not row:
        return 'Партнер'
    return row['display_name'] or row['telegram_name'] or 'Партнер'


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💗 Мій check-in', callback_data='checkin')],
        [InlineKeyboardButton(text='👀 Стан партнера', callback_data='partner_status')],
        [InlineKeyboardButton(text='📊 Історія', callback_data='history')],
        [InlineKeyboardButton(text="🔗 Під'єднати партнера", callback_data='pair')],
        [InlineKeyboardButton(text="⚙️ Моє ім'я", callback_data='rename')],
    ])


def list_keyboard(items, prefix, custom=True):
    rows = [[InlineKeyboardButton(text=item, callback_data=f'{prefix}:{i}')] for i, item in enumerate(items)]
    if custom:
        rows.append([InlineKeyboardButton(text='✏️ Інше', callback_data=f'{prefix}:custom')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='home')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def resource_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(i), callback_data=f'resource:{i}') for i in range(1, 6)],
        [InlineKeyboardButton(text='❌ Скасувати', callback_data='cancel')]
    ])


def needs_keyboard(selected):
    rows = []
    for i, item in enumerate(NEEDS):
        mark = '✅ ' if item in selected else ''
        rows.append([InlineKeyboardButton(text=mark + item, callback_data=f'need_toggle:{i}')])
    rows += [
        [InlineKeyboardButton(text='✏️ Своя потреба', callback_data='need_custom')],
        [InlineKeyboardButton(text='➡️ Далі', callback_data='needs_done')],
        [InlineKeyboardButton(text='❌ Скасувати', callback_data='cancel')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def intensity_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(i), callback_data=f'intensity:{i}') for i in range(1, 6)]
    ])


def support_keyboard():
    rows = [[InlineKeyboardButton(text=item, callback_data=f'support:{i}')] for i, item in enumerate(SUPPORT)]
    rows += [
        [InlineKeyboardButton(text='✏️ Свій варіант', callback_data='support:custom')],
        [InlineKeyboardButton(text='⏭ Пропустити', callback_data='support:skip')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def avoid_keyboard():
    rows = [[InlineKeyboardButton(text=item, callback_data=f'avoid:{i}')] for i, item in enumerate(AVOID)]
    rows += [
        [InlineKeyboardButton(text='✏️ Свій варіант', callback_data='avoid:custom')],
        [InlineKeyboardButton(text='⏭ Пропустити', callback_data='avoid:skip')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def comment_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✏️ Написати коментар', callback_data='comment:write')],
        [InlineKeyboardButton(text='⏭ Пропустити', callback_data='comment:skip')]
    ])


def duration_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='30 хв', callback_data='duration:30m'), InlineKeyboardButton(text='1 год', callback_data='duration:1h')],
        [InlineKeyboardButton(text='3 год', callback_data='duration:3h'), InlineKeyboardButton(text='До кінця дня', callback_data='duration:evening')],
        [InlineKeyboardButton(text='До завтра', callback_data='duration:tomorrow')],
        [InlineKeyboardButton(text='Поки не зміню', callback_data='duration:manual')]
    ])


def reaction_keyboard(checkin_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='❤️ Я почув/ла', callback_data=f'ack:{checkin_id}')],
        [InlineKeyboardButton(text='🤝 Можу допомогти', callback_data=f'help:{checkin_id}')]
    ])


def format_checkin(row, owner_name):
    needs = [x for x in (row['needs'] or '').split('||') if x]
    needs_text = '\n'.join(f'• {n}' for n in needs) if needs else '—'
    resource = '●' * row['resource'] + '○' * (5 - row['resource'])
    intensity = '●' * row['intensity'] + '○' * (5 - row['intensity'])
    parts = [
        f'💗 Check-in від {owner_name}', '', row['emotion'], f'🔋 Ресурс: {resource}', '',
        'Потреби:', needs_text, f'Важливість: {intensity}'
    ]
    if row['support']:
        parts += ['', f"✅ Зараз допоможе: {row['support']}"]
    if row['avoid']:
        parts += ['', f"🚫 Краще не робити: {row['avoid']}"]
    if row['comment']:
        parts += ['', f"💬 {row['comment']}"]
    if row['expires_at']:
        try:
            exp = datetime.fromisoformat(row['expires_at']).astimezone()
            parts += ['', f"⏳ Актуально до: {exp.strftime('%d.%m %H:%M')}"]
        except Exception:
            pass
    else:
        parts += ['', '⏳ Актуально: поки не зміню']
    return '\n'.join(parts)


@dp.message(CommandStart())
async def start(message: Message):
    ensure_user(message.from_user)
    await message.answer(f"Привіт, {get_display_name(message.from_user.id)} 💗\n\nЩо хочеш зробити?", reply_markup=main_menu())


@dp.callback_query(F.data == 'home')
async def home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text('Що хочеш зробити?', reply_markup=main_menu())
    await callback.answer()


@dp.callback_query(F.data == 'cancel')
async def cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text('Check-in скасовано.', reply_markup=main_menu())
    await callback.answer()


@dp.callback_query(F.data == 'rename')
async def rename(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SetupStates.entering_name)
    await callback.message.edit_text("Напиши ім'я або нік, який бот має показувати партнеру:")
    await callback.answer()


@dp.message(SetupStates.entering_name)
async def save_name(message: Message, state: FSMContext):
    name = (message.text or '').strip()
    if not name:
        await message.answer("Напиши ім'я текстом.")
        return
    db.execute('UPDATE users SET display_name = ? WHERE telegram_id = ?', (name[:50], message.from_user.id))
    db.commit()
    await state.clear()
    await message.answer(f'Готово, {name} 💗', reply_markup=main_menu())


@dp.callback_query(F.data == 'checkin')
async def checkin_start(callback: CallbackQuery, state: FSMContext):
    ensure_user(callback.from_user)
    await state.clear()
    await state.set_state(CheckinStates.choosing_emotion)
    await callback.message.edit_text('Як ти зараз почуваєшся?', reply_markup=list_keyboard(EMOTIONS, 'emotion', True))
    await callback.answer()


@dp.callback_query(CheckinStates.choosing_emotion, F.data.startswith('emotion:'))
async def choose_emotion(callback: CallbackQuery, state: FSMContext):
    value = callback.data.split(':', 1)[1]
    if value == 'custom':
        await state.set_state(CheckinStates.custom_emotion)
        await callback.message.edit_text('Напиши свій стан або емоцію:')
        await callback.answer()
        return
    await state.update_data(emotion=EMOTIONS[int(value)])
    await state.set_state(CheckinStates.choosing_resource)
    await callback.message.edit_text('🔋 Скільки в тебе зараз ресурсу?\n\n1 — майже немає сил\n5 — багато сил', reply_markup=resource_keyboard())
    await callback.answer()


@dp.message(CheckinStates.custom_emotion)
async def custom_emotion(message: Message, state: FSMContext):
    text = (message.text or '').strip()
    await state.update_data(emotion=f'✏️ {text[:80]}')
    await state.set_state(CheckinStates.choosing_resource)
    await message.answer('🔋 Скільки в тебе зараз ресурсу?', reply_markup=resource_keyboard())


@dp.callback_query(CheckinStates.choosing_resource, F.data.startswith('resource:'))
async def choose_resource(callback: CallbackQuery, state: FSMContext):
    await state.update_data(resource=int(callback.data.split(':')[1]), needs=[])
    await state.set_state(CheckinStates.choosing_needs)
    await callback.message.edit_text('💗 Чого ти зараз потребуєш?\n\nМожна вибрати до 3 варіантів.', reply_markup=needs_keyboard([]))
    await callback.answer()


@dp.callback_query(CheckinStates.choosing_needs, F.data.startswith('need_toggle:'))
async def toggle_need(callback: CallbackQuery, state: FSMContext):
    item = NEEDS[int(callback.data.split(':')[1])]
    data = await state.get_data()
    selected = data.get('needs', [])
    if item in selected:
        selected.remove(item)
    elif len(selected) < 3:
        selected.append(item)
    else:
        await callback.answer('Можна вибрати максимум 3 потреби.', show_alert=True)
        return
    await state.update_data(needs=selected)
    await callback.message.edit_reply_markup(reply_markup=needs_keyboard(selected))
    await callback.answer()


@dp.callback_query(CheckinStates.choosing_needs, F.data == 'need_custom')
async def need_custom(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if len(data.get('needs', [])) >= 3:
        await callback.answer('Уже вибрано 3 потреби.', show_alert=True)
        return
    await state.set_state(CheckinStates.custom_need)
    await callback.message.edit_text('Напиши свою потребу:')
    await callback.answer()


@dp.message(CheckinStates.custom_need)
async def save_custom_need(message: Message, state: FSMContext):
    data = await state.get_data()
    selected = data.get('needs', [])
    selected.append(f"✏️ {(message.text or '').strip()[:100]}")
    await state.update_data(needs=selected)
    await state.set_state(CheckinStates.choosing_needs)
    await message.answer('Додано. Можеш вибрати ще або перейти далі.', reply_markup=needs_keyboard(selected))


@dp.callback_query(CheckinStates.choosing_needs, F.data == 'needs_done')
async def needs_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get('needs'):
        await callback.answer('Вибери хоча б одну потребу.', show_alert=True)
        return
    await state.set_state(CheckinStates.choosing_intensity)
    await callback.message.edit_text('Наскільки важливі ці потреби зараз?\n\n1 — легке бажання\n5 — дуже сильна потреба', reply_markup=intensity_keyboard())
    await callback.answer()


@dp.callback_query(CheckinStates.choosing_intensity, F.data.startswith('intensity:'))
async def choose_intensity(callback: CallbackQuery, state: FSMContext):
    await state.update_data(intensity=int(callback.data.split(':')[1]))
    await state.set_state(CheckinStates.choosing_support)
    await callback.message.edit_text('✅ Що партнер може зробити, щоб тобі стало трохи краще?', reply_markup=support_keyboard())
    await callback.answer()


@dp.callback_query(CheckinStates.choosing_support, F.data.startswith('support:'))
async def choose_support(callback: CallbackQuery, state: FSMContext):
    value = callback.data.split(':', 1)[1]
    if value == 'custom':
        await state.set_state(CheckinStates.custom_support)
        await callback.message.edit_text('Напиши, що саме зараз допоможе:')
        await callback.answer()
        return
    await state.update_data(support=None if value == 'skip' else SUPPORT[int(value)])
    await state.set_state(CheckinStates.choosing_avoid)
    await callback.message.edit_text('🚫 Чого партнеру зараз краще НЕ робити?', reply_markup=avoid_keyboard())
    await callback.answer()


@dp.message(CheckinStates.custom_support)
async def save_custom_support(message: Message, state: FSMContext):
    await state.update_data(support=f"✏️ {(message.text or '').strip()[:120]}")
    await state.set_state(CheckinStates.choosing_avoid)
    await message.answer('🚫 Чого партнеру зараз краще НЕ робити?', reply_markup=avoid_keyboard())


@dp.callback_query(CheckinStates.choosing_avoid, F.data.startswith('avoid:'))
async def choose_avoid(callback: CallbackQuery, state: FSMContext):
    value = callback.data.split(':', 1)[1]
    if value == 'custom':
        await state.set_state(CheckinStates.custom_avoid)
        await callback.message.edit_text('Напиши, чого зараз краще не робити:')
        await callback.answer()
        return
    await state.update_data(avoid=None if value == 'skip' else AVOID[int(value)])
    await state.set_state(CheckinStates.choosing_comment)
    await callback.message.edit_text('💬 Хочеш щось додати своїми словами?', reply_markup=comment_keyboard())
    await callback.answer()


@dp.message(CheckinStates.custom_avoid)
async def save_custom_avoid(message: Message, state: FSMContext):
    await state.update_data(avoid=f"✏️ {(message.text or '').strip()[:120]}")
    await state.set_state(CheckinStates.choosing_comment)
    await message.answer('💬 Хочеш щось додати своїми словами?', reply_markup=comment_keyboard())


@dp.callback_query(CheckinStates.choosing_comment, F.data.startswith('comment:'))
async def choose_comment(callback: CallbackQuery, state: FSMContext):
    if callback.data.endswith('write'):
        await state.set_state(CheckinStates.entering_comment)
        await callback.message.edit_text('Напиши коментар:')
        await callback.answer()
        return
    await state.update_data(comment=None)
    await state.set_state(CheckinStates.choosing_duration)
    await callback.message.edit_text('⏳ Як довго цей стан актуальний?', reply_markup=duration_keyboard())
    await callback.answer()


@dp.message(CheckinStates.entering_comment)
async def save_comment(message: Message, state: FSMContext):
    await state.update_data(comment=(message.text or '').strip()[:500])
    await state.set_state(CheckinStates.choosing_duration)
    await message.answer('⏳ Як довго цей стан актуальний?', reply_markup=duration_keyboard())


@dp.callback_query(CheckinStates.choosing_duration, F.data.startswith('duration:'))
async def finish_checkin(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(':')[1]
    data = await state.get_data()
    now = datetime.now(timezone.utc)
    expires_at = None
    if key == '30m': expires_at = now + timedelta(minutes=30)
    elif key == '1h': expires_at = now + timedelta(hours=1)
    elif key == '3h': expires_at = now + timedelta(hours=3)
    elif key == 'tomorrow': expires_at = now + timedelta(days=1)
    elif key == 'evening':
        local_now = datetime.now().astimezone()
        expires_at = local_now.replace(hour=23, minute=59, second=0, microsecond=0).astimezone(timezone.utc)

    cur = db.execute('''INSERT INTO checkins
        (telegram_id, emotion, resource, needs, intensity, support, avoid, comment, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (callback.from_user.id, data['emotion'], data['resource'], '||'.join(data['needs']), data['intensity'],
         data.get('support'), data.get('avoid'), data.get('comment'), expires_at.isoformat() if expires_at else None, now.isoformat()))
    db.commit()
    row = db.execute('SELECT * FROM checkins WHERE id = ?', (cur.lastrowid,)).fetchone()
    text = format_checkin(row, get_display_name(callback.from_user.id))
    await callback.message.edit_text('Готово 💗\n\n' + text, reply_markup=main_menu())

    partner = db.execute('SELECT partner_id FROM users WHERE telegram_id = ?', (callback.from_user.id,)).fetchone()
    if partner and partner['partner_id']:
        try:
            await bot.send_message(partner['partner_id'], text, reply_markup=reaction_keyboard(row['id']))
        except Exception:
            pass
    await state.clear()
    await callback.answer('Check-in збережено')


@dp.callback_query(F.data == 'pair')
async def pair_menu(callback: CallbackQuery):
    ensure_user(callback.from_user)
    row = db.execute('SELECT pair_code, partner_id FROM users WHERE telegram_id = ?', (callback.from_user.id,)).fetchone()
    if row and row['partner_id']:
        await callback.message.edit_text(f"💗 Ти вже під'єднана/ий до {get_display_name(row['partner_id'])}.", reply_markup=main_menu())
        await callback.answer(); return
    code = row['pair_code'] if row else None
    if not code:
        code = secrets.token_hex(3).upper()
        db.execute('UPDATE users SET pair_code = ? WHERE telegram_id = ?', (code, callback.from_user.id))
        db.commit()
    await callback.message.edit_text(
        f"🔗 Надішли партнеру цей код:\n\n<code>{code}</code>\n\nПартнер має відкрити бота, натиснути Start і надіслати код одним повідомленням.",
        parse_mode='HTML', reply_markup=main_menu())
    await callback.answer()


@dp.message(F.text.regexp(r'^[A-Fa-f0-9]{6}$'))
async def connect_partner(message: Message):
    ensure_user(message.from_user)
    code = message.text.strip().upper()
    row = db.execute('SELECT telegram_id FROM users WHERE pair_code = ? AND telegram_id != ?', (code, message.from_user.id)).fetchone()
    if not row:
        await message.answer('Не знайшла такого коду 😕 Перевір його й спробуй ще раз.')
        return
    partner_id = row['telegram_id']
    db.execute('UPDATE users SET partner_id = ? WHERE telegram_id = ?', (partner_id, message.from_user.id))
    db.execute('UPDATE users SET partner_id = ? WHERE telegram_id = ?', (message.from_user.id, partner_id))
    db.commit()
    await message.answer(f"Готово 💗 Ти під'єднана/ий до {get_display_name(partner_id)}.", reply_markup=main_menu())
    try:
        await bot.send_message(partner_id, f"💗 {get_display_name(message.from_user.id)} під'єднався/під'єдналася до вашої пари.", reply_markup=main_menu())
    except Exception:
        pass


@dp.callback_query(F.data == 'partner_status')
async def partner_status(callback: CallbackQuery):
    row = db.execute('SELECT partner_id FROM users WHERE telegram_id = ?', (callback.from_user.id,)).fetchone()
    if not row or not row['partner_id']:
        await callback.message.edit_text("Спочатку потрібно під'єднати партнера 🔗", reply_markup=main_menu())
        await callback.answer(); return
    partner_id = row['partner_id']
    checkins = db.execute('SELECT * FROM checkins WHERE telegram_id = ? ORDER BY id DESC', (partner_id,)).fetchall()
    active = None
    now = datetime.now(timezone.utc)
    for c in checkins:
        if not c['expires_at'] or datetime.fromisoformat(c['expires_at']) > now:
            active = c; break
    if not active:
        await callback.message.edit_text(f"👀 У {get_display_name(partner_id)} зараз немає активного check-in.", reply_markup=main_menu())
    else:
        await callback.message.edit_text(format_checkin(active, get_display_name(partner_id)), reply_markup=reaction_keyboard(active['id']))
    await callback.answer()


@dp.callback_query(F.data.startswith('ack:'))
async def ack(callback: CallbackQuery):
    cid = int(callback.data.split(':')[1])
    row = db.execute('SELECT * FROM checkins WHERE id = ?', (cid,)).fetchone()
    if not row:
        await callback.answer('Check-in не знайдено.', show_alert=True); return
    db.execute('UPDATE checkins SET acknowledged = 1 WHERE id = ?', (cid,)); db.commit()
    try:
        await bot.send_message(row['telegram_id'], f"❤️ {get_display_name(callback.from_user.id)} побачив/ла твій check-in.")
    except Exception:
        pass
    await callback.answer('Відправлено ❤️', show_alert=True)


@dp.callback_query(F.data.startswith('help:'))
async def help_offer(callback: CallbackQuery):
    cid = int(callback.data.split(':')[1])
    row = db.execute('SELECT * FROM checkins WHERE id = ?', (cid,)).fetchone()
    if not row:
        await callback.answer('Check-in не знайдено.', show_alert=True); return
    try:
        await bot.send_message(row['telegram_id'], f"🤝 {get_display_name(callback.from_user.id)} написав/ла: «Можу допомогти».")
    except Exception:
        pass
    await callback.answer('Відправлено 🤝', show_alert=True)


@dp.callback_query(F.data == 'history')
async def history(callback: CallbackQuery):
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    rows = db.execute('''SELECT emotion, resource, needs, created_at FROM checkins
                         WHERE telegram_id = ? AND created_at >= ? ORDER BY id DESC LIMIT 10''',
                      (callback.from_user.id, since)).fetchall()
    if not rows:
        text = "📊 За останні 7 днів check-in'ів ще немає."
    else:
        lines = ["📊 Твої останні check-in'и за 7 днів:\n"]
        for row in rows:
            dt = datetime.fromisoformat(row['created_at']).astimezone().strftime('%d.%m %H:%M')
            need = (row['needs'] or '').split('||')[0]
            lines.append(f"{dt} — {row['emotion']} · 🔋 {row['resource']}/5 · {need}")
        text = '\n'.join(lines)
    await callback.message.edit_text(text, reply_markup=main_menu())
    await callback.answer()


async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
