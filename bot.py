import asyncio
import logging
import os
import io
from aiogram import Bot, Dispatcher, types, filters
from aiogram.types import CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile, InlineKeyboardMarkup, \
    InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram import F
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from dotenv import load_dotenv
from datetime import datetime
import matplotlib.pyplot as plt
import re
import pytz
import sqlite3
import requests

conn = sqlite3.connect("database.db")  # Подключаемся к базе (файл database.db)
cursor = conn.cursor()


# Создаём таблицы

cursor.execute("""
CREATE TABLE IF NOT EXISTS time_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    category TEXT,
    date TEXT,
    start_time TEXT,
    end_time TEXT,
    duration INTEGER  -- Длительность в минутах
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS time_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    category TEXT,
    start_time TEXT
)
""")

conn.commit()  # Сохраняем изменения

# Загружаем токен из переменных среды
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')

url = f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo"
print(requests.get(url).json())
# Проверка, что токен получен
if not TOKEN:
    raise ValueError("BOT_TOKEN is not set in environment variables!")

# Настраиваем бота
bot = Bot(token=TOKEN)
dp = Dispatcher()

async def on_startup(bot: Bot):
    await bot.set_webhook(f"https://telegram-chatbot-treker.onrender.com/webhook")

async def main():
    # Отключаем логгирование для aiohttp, чтобы не засорять логи
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('aiohttp').setLevel(logging.WARNING)

    # Создаем aiohttp приложение
    app = web.Application()
    webhook_handler = SimpleRequestHandler(dp, bot=bot)
    webhook_handler.register(app, path="/webhook")

    # Настраиваем вебхук при старте
    await on_startup(bot)

    # Запускаем сервер
    port = int(os.environ.get("PORT", 5000))  # Render передает порт через переменную PORT
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()

    print(f"Бот запущен на порту {port}")
    await asyncio.Event().wait()  # Бесконечное ожидание


CATEGORIES = ["😴 Сон", "🛁 Уход за собой", "💼 Работа", "🏋️‍ Спорт и Здоровье", "👨‍👩‍👧‍👦 Семья и друзья",
              "🚗 Логистика", "🏡 Домашние дела", "🎮 Развлечения", "📚 Личное развитие", "🐌 Прокрастинация"]

# Словарь для перевода дней недели
DAYS_TRANSLATION = {
    "Monday": "Понедельник",
    "Tuesday": "Вторник",
    "Wednesday": "Среда",
    "Thursday": "Четверг",
    "Friday": "Пятница",
    "Saturday": "Суббота",
    "Sunday": "Воскресенье",
}

CATEGORY_MAPPING = {
    "selfcare": "🛁 Уход за собой",
    "work": "💼 Работа",
    "sport": "🏋️‍ Спорт и Здоровье",
    "family": "👨‍👩‍👧‍👦 Семья и друзья",
    "sleep": "😴 Сон",
    "home": "🏡 Домашние дела",
    "learning": "📚 Личное развитие",
    "fun": "🎮 Развлечения",
    "lazy": "🐌 Прокрастинация",
    "logistics": "🚗 Логистика"
}


# Переводит datetime Python в строку UTC ISO 8601
def to_utc_iso(dt):
    dt_utc = dt.astimezone(pytz.utc)  # Приводим к UTC
    return dt_utc.isoformat()  # Преобразуем в ISO формат


# Переводит строку UTC ISO 8601 в datetime UTC
def from_utc_iso(utc_str):
    dt_utc = datetime.fromisoformat(utc_str).replace(tzinfo=pytz.utc)  # Приводим к UTC
    return dt_utc


# Переводит datetime UTC в datetime с локальным часовым поясом
def from_utc_to_tz(dt):
    local_tz = os.getenv("TZ", "Asia/Dubai")  # Получаем локальный часовой пояс из переменной среды
    return dt.astimezone(pytz.timezone(local_tz))  # Переводим в локальный часовой пояс


# Переводит местное время в UTC
def local_time_to_utc(dt):
    local_tz = os.getenv("TZ", "Asia/Dubai")  # Получаем локальный часовой пояс
    local_zone = pytz.timezone(local_tz)
    dt = local_zone.localize(dt)
    # Переводим в UTC
    utc_dt = dt.astimezone(pytz.utc)
    return utc_dt


# Функция для удаления эмодзи из строки.
def remove_emojis(text):
    return re.sub(r'[^\w\s,]', '', text)


# Функция для форматирования процентов. Скрывает проценты < 1%
def autopct_func(pct, allvalues):
    if pct < 1:
        return ''
    else:
        return f'{pct:.0f}%'  # Округляем до целого числа


# Функция для создания главного меню
def get_main_menu(has_active_tracking: bool):
    keyboard = []
    if has_active_tracking:
        keyboard.append([
            KeyboardButton(text="⏺ Начать трекинг"),KeyboardButton(text="⏹ Завершить трекинг")
        ])
    else:
        keyboard.append([
            KeyboardButton(text="⏺ Начать трекинг")
        ])
    keyboard.append([
        KeyboardButton(text="➕ Добавить трекинг"), KeyboardButton(text="✏ Изменить трекинг")
    ])
    keyboard.append([KeyboardButton(text="📊 Статистика")])

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


# Создает меню категорий
def get_category_menu(categories):
    keyboard = []
    # Группируем по две кнопки в ряд
    for i in range(0, len(categories), 2):
        row = categories[i:i + 2]  # Берём 2 элемента
        keyboard.append([KeyboardButton(text=cat) for cat in row])  # Создаём строку

    # Добавляем кнопку "Назад" в отдельную строку
    keyboard.append([KeyboardButton(text="⬅ Назад")])

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


# Создает меню статистики
def get_stats_menu():
    keyboard = [[KeyboardButton(text="📅 Статистика за день"), KeyboardButton(text="📊 Статистика за неделю")],
                [KeyboardButton(text="⬅ Назад")]]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


# Проверяет наличие активного треккинга
def check_active_tracking(user_id):
    cursor.execute("SELECT COUNT(*) FROM time_tracking WHERE user_id = ?", (user_id,))
    count = cursor.fetchone()[0]
    return count > 0


# Получает все треккинги за день
def get_day_trackings(user_id, date):
    cursor.execute("""
        SELECT category, start_time, end_time 
        FROM time_logs
        WHERE user_id = ? 
        AND (
            start_time BETWEEN ? AND ?
            OR end_time BETWEEN ? AND ?
            OR (start_time >= ? AND start_time <= ? AND end_time > ?)
        )
        ORDER BY start_time
    """, (user_id, date + "T00:00:00Z", date + "T23:59:59Z",
          date + "T00:00:00Z", date + "T23:59:59Z",
          date + "T00:00:00Z", date + "T23:59:59Z", date + "T23:59:59Z"))

    trackings = cursor.fetchall()

    # Конвертируем время в локальный часовой пояс
    result = []
    for category, start_time_iso, end_time_iso in trackings:
        start_time = from_utc_to_tz(from_utc_iso(start_time_iso))
        end_time = from_utc_to_tz(from_utc_iso(end_time_iso))

        result.append((category, start_time.strftime("%H:%M"), end_time.strftime("%H:%M")))

    return result


# Проверка наложения трекингов
def check_overlap(user_id, date, new_start_utc, new_end_utc):
    existing_trackings = get_day_trackings(user_id, date)

    new_start = from_utc_to_tz(new_start_utc) if new_start_utc else None
    new_end = from_utc_to_tz(new_end_utc)  if new_end_utc else None

    for category, start_time_str, end_time_str in existing_trackings:
        start_time = datetime.strptime(start_time_str, "%H:%M")
        end_time = datetime.strptime(end_time_str, "%H:%M")

        if not (new_end and new_end <= start_time or new_start and new_start >= end_time):
            return f"⚠ Ошибка! Пересечение с '{category}' ({start_time_str} - {end_time_str})"

    return None  # Нет пересечений


def start_tracking(user_id, category):
    now = to_utc_iso(datetime.now())  # Записываем текущее время в ISO формате
    cursor.execute("INSERT INTO time_tracking (user_id, category, start_time) VALUES (?, ?, ?)",
                   (user_id, category, now))
    conn.commit()


def stop_tracking(user_id):
    cursor.execute("SELECT category, start_time FROM time_tracking WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                   (user_id,))
    row = cursor.fetchone()  # Берём последнюю запись

    if row:
        category, start_time = row
        start = start_time
        start_time = from_utc_iso(start_time)
        now = datetime.now().astimezone(pytz.utc)
        end = to_utc_iso(now)
        duration = now - start_time
        minutes = round(duration.total_seconds() / 60)

        # **Сохраняем в таблицу статистики**
        date = datetime.now().strftime("%Y-%m-%d")  # Дата в формате YYYY-MM-DD
        cursor.execute(
            "INSERT INTO time_logs (user_id, category, date, start_time, end_time, duration) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, category, date, start, end, minutes))
        conn.commit()

        # Удаляем запись из `time_tracking`, чтобы активность считалась завершённой
        cursor.execute("DELETE FROM time_tracking WHERE user_id = ?", (user_id,))
        conn.commit()

        return category, minutes
    return None, None


# статистика за день по категориям
def get_daily_stats(user_id):
    date = datetime.now().strftime("%Y-%m-%d")
    local_tz = pytz.timezone(os.getenv("TZ", "Asia/Dubai"))
    midnight_local = datetime.now(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = midnight_local.astimezone(pytz.utc)
    now_utc = datetime.now(pytz.utc)
    total_for_now = int((now_utc - midnight_utc).total_seconds()//60)
    cursor.execute("""
        SELECT category, SUM(duration) FROM time_logs 
        WHERE user_id = ? AND date = ? 
        GROUP BY category
    """, (user_id, date))

    rows = cursor.fetchall()
    cursor.execute("""
            SELECT category, start_time, end_time, duration FROM time_logs 
            WHERE user_id = ? AND date = ? ORDER BY end_time LIMIT 1
        """, (user_id, date))

    category_sleep, start_time_sleep, end_time_sleep, duration_sleep = cursor.fetchone()
    sleep_before_midnight = 0

    start_time_sleep = from_utc_iso(start_time_sleep)
    end_time_sleep = from_utc_iso(end_time_sleep)

    if category_sleep == "😴 Сон":
        if start_time_sleep < midnight_utc < end_time_sleep:
            sleep_before_midnight = (midnight_utc-start_time_sleep).total_seconds() / 60  # Время сна после 00:00
            sleep_before_midnight = max(0, round(sleep_before_midnight))

    total_tracked = sum(duration for _, duration in rows)

    # Вычисляем "без трекинга" до текущего момента
    untracked_minutes = total_for_now - total_tracked + sleep_before_midnight

    # Добавляем "Без трекинга"
    rows.append(("🕰 Без трекинга", untracked_minutes))
    return rows


# статистика за неделю по категориям
def get_weekly_stats(user_id):
    cursor.execute("""
        SELECT date, category, SUM(duration) FROM time_logs 
        WHERE user_id = ? AND date >= date('now', '-6 days')
        GROUP BY date, category
        ORDER BY date
    """, (user_id,))

    rows = cursor.fetchall()

    # Группируем по дням недели
    stats_by_day = {}
    for date, category, duration in rows:
        weekday = datetime.strptime(date, "%Y-%m-%d").strftime("%A")
        weekday_ru = DAYS_TRANSLATION[weekday]  # Переводим на русский
        if weekday_ru not in stats_by_day:
            stats_by_day[weekday_ru] = {}
        stats_by_day[weekday_ru][category] = duration

    # Добавляем "Без трекинга" на каждый день
    for weekday in stats_by_day.keys():
        total_tracked = sum(stats_by_day[weekday].values())
        today = DAYS_TRANSLATION[datetime.now().strftime("%A")]

        if weekday != today:
            untracked_minutes = max(1440 - total_tracked, 0)
        else:
            now = from_utc_to_tz(datetime.now().astimezone(pytz.utc))
            untracked_minutes = now.hour * 60 + now.minute
            untracked_minutes = max(untracked_minutes-total_tracked, 0)
        stats_by_day[weekday]["🕰 Без трекинга"] = untracked_minutes

    return stats_by_day


# Обработчик команды /start
@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_id = message.from_user.id
    has_active_tracking = check_active_tracking(user_id)
    await message.answer("Выберите действие:", reply_markup=get_main_menu(has_active_tracking))


# Обработчик нажатия на кнопку ⏺ Начать трекинг
@dp.message(lambda message: message.text == "⏺ Начать трекинг")
async def start_tracking_menu(message: types.Message):
    await message.answer("Выберите категорию:", reply_markup=get_category_menu(CATEGORIES))


# Обработчик нажатия на кнопку ⬅ Назад
@dp.message(lambda message: message.text == "⬅ Назад")
async def back_to_menu(message: types.Message):
    user_id = message.from_user.id
    has_active_tracking = check_active_tracking(user_id)
    await message.answer("Главное меню:", reply_markup=get_main_menu(has_active_tracking))


# Обработчик нажатия на кнопку ⏹ Завершить трекинг
@dp.message(lambda message: message.text == "⏹ Завершить трекинг")
async def stop_tracking_handler(message: types.Message):
    user_id = message.from_user.id
    category, minutes = stop_tracking(user_id)
    if category:
        await message.answer(f"⏳ Ты потратил {minutes} мин на {category}.", parse_mode="Markdown")
    else:
        await message.answer("Нет активного трекинга.")
    has_active_tracking = check_active_tracking(user_id)
    await message.answer("Главное меню:", reply_markup=get_main_menu(has_active_tracking))


# Обработчик нажатия на кнопку 📊 Статистика
@dp.message(lambda message: message.text == "📊 Статистика")
async def show_stats_menu(message: types.Message):
    await message.answer("Выберите нужную статистику:", reply_markup=get_stats_menu())


# Обработчик нажатия на кнопку категории
@dp.message(lambda message: message.text in CATEGORIES)
async def track_time(message: types.Message):
    user_id = message.from_user.id  # Получаем ID пользователя
    category = message.text

    # Проверяем, была ли активность
    old_category, minutes = stop_tracking(user_id)

    if old_category:
        await message.answer(f"⏳ Ты потратил {minutes} мин на {old_category}.")

    # Запускаем новую активность
    start_tracking(user_id, category)
    await message.answer(f"✅ Начат трекинг: {category}")
    has_active_tracking = check_active_tracking(user_id)
    await message.answer("Главное меню:", reply_markup=get_main_menu(has_active_tracking))


# Добавляет не отмеченный трек в прошлом
@dp.message(lambda message: message.text == "➕ Добавить трекинг")
async def add_past_tracking(message: types.Message):
    user_id = message.from_user.id
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛁 Уход за собой", callback_data=f"track_selfcare_{user_id}"),
         InlineKeyboardButton(text="💼 Работа", callback_data=f"track_work_{user_id}")],
        [InlineKeyboardButton(text="🏋️‍ Спорт и Здоровье", callback_data=f"track_sport_{user_id}"),
         InlineKeyboardButton(text="👨‍👩‍👧‍👦 Семья и друзья", callback_data=f"track_family_{user_id}")],
        [InlineKeyboardButton(text="😴 Сон", callback_data=f"track_sleep_{user_id}"),
         InlineKeyboardButton(text="🏡 Домашние дела", callback_data=f"track_home_{user_id}")],
        [InlineKeyboardButton(text="📚 Личное развитие", callback_data=f"track_learning_{user_id}"),
         InlineKeyboardButton(text="🎮 Развлечения", callback_data=f"track_fun_{user_id}")],
        [InlineKeyboardButton(text="🐌 Прокрастинация", callback_data=f"track_lazy_{user_id}"),
         InlineKeyboardButton(text="🚗 Логистика", callback_data=f"track_logistics_{user_id}")],
    ])
    await message.answer("Выбери категорию: ", reply_markup=keyboard)


# Колбэк выбора категории для добавления старого трека
@dp.callback_query(F.data.startswith("track_"))
async def add_past_tracking_by_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split("_")[1]
    try:
        category = CATEGORY_MAPPING.get(category)
        user_id = callback.data.split("_")[2]
        await callback.message.answer("Введи время и дату начала в формате DD.MM HH:MM:")
        await state.update_data(category=category, user_id=user_id)
        await state.set_state("waiting_for_new_tracking_start_time")
    except ValueError:
        await callback.message.answer("Ошибка категории. Попробуй снова")


# Обработка времени старта трекинга в прощшлом
@dp.message(StateFilter("waiting_for_new_tracking_start_time"))
async def process_new_tracking_start_time(message: types.Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        date, hours = message.text.split()
        hour, minute = map(int, hours.split(":"))
        day, month = map(int, date.split("."))
        now_utc = datetime.now().astimezone(pytz.utc)
        start_time = datetime(now_utc.year, month, day, hour, minute)
        date = datetime(now_utc.year, month, day).strftime("%Y-%m-%d")
        start_time_utc = local_time_to_utc(start_time)
        conflict = check_overlap(user_id, date, start_time_utc, None)
        if start_time_utc > now_utc:
            await message.answer("Ошибка: Время не может быть позже настоящего момента! Попробуйте еще раз.")
            return
        elif conflict:
            return conflict
        else:
            await message.answer("Введи время и дату окончания в формате DD.MM HH:MM:")
            await state.update_data(start_time=start_time_utc)
            await state.set_state("waiting_for_new_tracking_end_time")
    except ValueError:
        await message.answer("Неверный формат! Попробуй еще раз (пример: 7.02 14:30).")


# Обработка времени окончания трекинга в прошлом
@dp.message(StateFilter("waiting_for_new_tracking_end_time"))
async def process_new_tracking_end_time(message: types.Message, state: FSMContext):
    try:
        date, hours = message.text.split()
        hour, minute = map(int, hours.split(":"))
        day, month = map(int, date.split("."))
        data = await state.get_data()
        category = data["category"]
        user_id = data["user_id"]
        start_time = data["start_time"]
        now = datetime.now().astimezone(pytz.utc)
        end_time = local_time_to_utc(datetime(now.year, month, day, hour, minute))
        date = end_time.strftime("%Y-%m-%d")
        conflict = check_overlap(user_id, date, start_time, end_time)
        if end_time > now or start_time > end_time:
            await message.answer(
                "Ошибка: Время не может быть позже настоящего момента и раньше времени старта! Попробуйте еще раз.")
            return
        elif conflict:
            return conflict
        else:
            start_time_str = from_utc_to_tz(start_time).strftime("%d.%m.%Y %H:%M")
            end_time_str = from_utc_to_tz(end_time).strftime("%d.%m.%Y %H:%M")
            start_time_iso = start_time.isoformat()
            end_time_iso = end_time.isoformat()
            duration = round((end_time - start_time).total_seconds() / 60)
            cursor.execute(
                "INSERT INTO time_logs (user_id, category, date, start_time, end_time, duration) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, category, date, start_time_iso, end_time_iso, duration),
            )
            conn.commit()
            await message.answer(
                f"Новый треккинг категории *{category}* успешно добавлен! 🎉\n"
                f"📌 Время начала: {start_time_str}\n"
                f"📌 Время окончания: {end_time_str}",
                parse_mode="Markdown"
            )
            await state.clear()
            has_active_tracking = check_active_tracking(user_id)
            await message.answer("Главное меню:", reply_markup=get_main_menu(has_active_tracking))
    except ValueError:
        await message.answer("Неверный формат! Попробуй еще раз (пример: 7.02 14:30).")


# Меняет время старта / окончания последней деятельности
@dp.message(lambda message: message.text == "✏ Изменить трекинг")
async def edit_last_tracking(message: types.Message):
    user_id = message.from_user.id
    # Получаем последний трекинг пользователя
    cursor.execute(
        "SELECT id, category, start_time, end_time, date FROM time_logs WHERE user_id = ? ORDER BY start_time DESC LIMIT 1",
        (user_id,))
    last_tracking = cursor.fetchone()

    if not last_tracking:
        await message.answer("У тебя пока нет записей для редактирования.")
        return

    tracking_id, category, start_time, end_time, date = last_tracking
    # Создаем кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить начало", callback_data=f"edit_start_{tracking_id}_{date}_{end_time}")],
        [InlineKeyboardButton(text="Изменить окончание", callback_data=f"edit_end_{tracking_id}_{date}_{start_time}")]
    ])
    start_time_text = from_utc_to_tz(from_utc_iso(start_time)).strftime("%d.%m.%Y %H:%M")
    end_time_text = from_utc_to_tz(from_utc_iso(end_time)).strftime("%d.%m.%Y %H:%M")
    await message.answer(
        f"Твой последний трекинг:\n"
        f"📌 Категория: {category}\n"
        f"🕒 Начало: {start_time_text}\n"
        f"⏳ Окончание: {end_time_text}\n"
        f"Что ты хочешь изменить?",
        reply_markup=keyboard
    )


# Колбэки изменения старта и окончания прошлого трекинга
@dp.callback_query(F.data.startswith("edit_start_"))
async def edit_start_time(callback: CallbackQuery, state: FSMContext):
    tracking_id = callback.data.split("_")[2]
    date = callback.data.split("_")[3]
    end_time = callback.data.split("_")[4]
    await callback.message.answer("Введи новое время начала в формате HH:MM:")
    await state.update_data(tracking_id=tracking_id, date=date, end_time=end_time)
    await state.set_state("waiting_for_new_start_time")


@dp.callback_query(F.data.startswith("edit_end_"))
async def edit_end_time(callback: CallbackQuery, state: FSMContext):
    tracking_id = callback.data.split("_")[2]
    date = callback.data.split("_")[3]
    start_time = callback.data.split("_")[4]
    await callback.message.answer("Введи новое время окончания в формате HH:MM:")
    await state.update_data(tracking_id=tracking_id, date=date, start_time=start_time)
    await state.set_state("waiting_for_new_end_time")


# Ожидание нового времени старта и окончания прошлого трекинга
@dp.message(StateFilter("waiting_for_new_start_time"))
async def process_new_start_time(message: types.Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        new_hour, new_minute = map(int, message.text.split(":"))
        data = await state.get_data()
        tracking_id = data["tracking_id"]
        date = data["date"]
        end_time = from_utc_iso(data["end_time"])
        new_start_time = datetime.strptime(date, "%Y-%m-%d").replace(hour=new_hour, minute=new_minute)
        new_start_time = local_time_to_utc(new_start_time)
        conflict = check_overlap(user_id, date, new_start_time, None)
        if end_time < new_start_time:
            await message.answer("Ошибка: Время финиша не может быть раньше старта! Попробуйте еще раз.")
        elif conflict:
            return conflict
        else:
            new_time_iso = new_start_time.isoformat()
            duration = end_time - new_start_time
            minutes = round(duration.total_seconds() / 60)
            cursor.execute("UPDATE time_logs SET start_time = ?, duration = ? WHERE id = ?",
                           (new_time_iso, minutes, tracking_id))
            conn.commit()

            new_time_str = from_utc_to_tz(new_start_time).strftime("%d.%m.%Y %H:%M")
            await message.answer(f"✅ Время начала изменено на {new_time_str}.")
            await state.clear()
            user_id = message.from_user.id
            has_active_tracking = check_active_tracking(user_id)
            await message.answer("Главное меню:", reply_markup=get_main_menu(has_active_tracking))
    except ValueError:
        await message.answer("Неверный формат! Попробуй еще раз (пример: 14:30).")


@dp.message(StateFilter("waiting_for_new_end_time"))
async def process_new_end_time(message: types.Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        new_hour, new_minute = map(int, message.text.split(":"))
        data = await state.get_data()
        tracking_id = data["tracking_id"]
        date = data["date"]
        start_time = from_utc_iso(data["start_time"])
        new_end_time = datetime.strptime(date, "%Y-%m-%d").replace(hour=new_hour, minute=new_minute)
        new_end_time = local_time_to_utc(new_end_time)
        conflict = check_overlap(user_id, date, None, new_end_time)
        if new_end_time < start_time:
            await message.answer("Ошибка: Время финиша не может быть раньше старта! Попробуйте еще раз.")
        elif conflict:
            return conflict
        else:
            new_time_iso = new_end_time.isoformat()
            duration = new_end_time - start_time
            minutes = round(duration.total_seconds() / 60)
            cursor.execute("UPDATE time_logs SET end_time = ?, duration = ? WHERE id = ?",
                           (new_time_iso, minutes, tracking_id))
            conn.commit()
            new_time_str = from_utc_to_tz(new_end_time).strftime("%d.%m.%Y %H:%M")
            await message.answer(f"✅ Время окончания изменено на {new_time_str}.")
            await state.clear()
            user_id = message.from_user.id
            has_active_tracking = check_active_tracking(user_id)
            await message.answer("Главное меню:", reply_markup=get_main_menu(has_active_tracking))

    except ValueError:
        await message.answer("Неверный формат! Попробуй еще раз (пример: 15:45).")


# Обработчик нажатия на кнопку 📅 Статистика за день
@dp.message(lambda message: message.text == "📅 Статистика за день")
async def show_stats_day(message: types.Message):
    user_id = message.from_user.id

    # Получаем статистику
    daily_stats = get_daily_stats(user_id)
    categories = []
    durations = []

    for row in daily_stats:
        categories.append(remove_emojis(row[0]))
        durations.append(row[1])

    # Проверяем, что есть данные для графика
    if not categories or not durations:
        await message.answer("Нет данных для построения графика.")
        return

    # Создаем график
    fig, ax = plt.subplots(figsize=(8, 8))
    wedges, texts, autotexts = ax.pie(durations, autopct=lambda pct: autopct_func(pct, durations), startangle=90,
                                      colors=plt.cm.Paired.colors)
    # Добавляем легенду внизу графика
    ax.legend(wedges, categories, title="Категории", loc="lower center", fontsize=10, bbox_to_anchor=(0.5, -0.3),
              ncol=3)
    # Равные оси для круга
    ax.axis('equal')
    ax.set_title('Распределение времени по категориям за день')

    # Сохраняем график в буфер
    buf = io.BytesIO()
    try:
        plt.savefig(buf, format='png', bbox_inches='tight')
        buf.seek(0)  # Перемещаем курсор к началу буфера
    except Exception as e:
        await message.answer(f"Ошибка при создании графика: {e}")
        return

    # Создаем InputFile из буфера
    image = BufferedInputFile(buf.getvalue(), filename="daily_stats.png")
    # Отправляем изображение в Telegram
    try:
        await message.answer_photo(photo=image)
    except Exception as e:
        await message.answer(f"Ошибка при отправке изображения: {e}")
    finally:
        plt.close()  # Закрываем график, чтобы не занимать память

    # Форматируем вывод
    daily_text = "\n".join([f"📌 {cat}: {mins // 60} ч {mins % 60} мин" for cat, mins in daily_stats]) or "Нет данных"

    text = (f"📊 *Статистика за сегодня:*\n{daily_text}")

    await message.answer(text, parse_mode="Markdown")
    has_active_tracking = check_active_tracking(user_id)
    await message.answer("Главное меню:", reply_markup=get_main_menu(has_active_tracking))


# Обработчик нажатия на кнопку 📊 Статистика за неделю
@dp.message(lambda message: message.text == "📊 Статистика за неделю")
async def show_stats_week(message: types.Message):
    user_id = message.from_user.id
    # Получаем статистику
    weekly_stats = get_weekly_stats(user_id)

    # Форматируем вывод
    text = "📊 *Статистика за неделю:*\n"
    for weekday, stats in weekly_stats.items():
        day_text = f"\n📅 *{weekday}:*\n" + "\n".join(
            [f"📌 {cat}: {mins // 60} ч {mins % 60} мин" for cat, mins in stats.items()]
        )
        text += day_text
    await message.answer(text, parse_mode="Markdown")
    has_active_tracking = check_active_tracking(user_id)
    await message.answer("Главное меню:", reply_markup=get_main_menu(has_active_tracking))


# async def main():
#     logging.basicConfig(level=logging.INFO)
#     await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
