import asyncio
import logging
import os
import io
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile
from aiogram.filters import Command
from dotenv import load_dotenv
from datetime import datetime
import sqlite3
import matplotlib.pyplot as plt
import re

conn = sqlite3.connect("database.db")  # Подключаемся к базе (файл database.db)
cursor = conn.cursor()

# Создаём таблицы

cursor.execute("""
CREATE TABLE IF NOT EXISTS time_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    category TEXT,
    date TEXT,
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
TOKEN = os.getenv('BOT_TOKEN')

# Настраиваем бота
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Кнопки для быстрого выбора категории
keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛁 Уход за собой"), KeyboardButton(text="💼 Работа")],
        [KeyboardButton(text="🏋️‍ Спорт и Здоровье"), KeyboardButton(text="👨‍👩‍👧‍👦 Семья и друзья")],
        [KeyboardButton(text="😴 Сон"), KeyboardButton(text="🏡 Домашние дела")],
        [KeyboardButton(text="📚 Личное развитие"), KeyboardButton(text="🎮 Развлечения")],
        [KeyboardButton(text="🐌 Прокрастинация"), KeyboardButton(text="🚗 Логистика")],
    ],
    resize_keyboard=True
)

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

# Обработчик команды /start
@dp.message(Command("start"))
async def start_command(message: types.Message):
    await message.answer("Выберите категорию:", reply_markup=keyboard)


def start_tracking(user_id, category):
    now = datetime.now().isoformat()  # Записываем текущее время в ISO формате
    cursor.execute("INSERT INTO time_tracking (user_id, category, start_time) VALUES (?, ?, ?)",
                   (user_id, category, now))
    conn.commit()


def stop_tracking(user_id):
    cursor.execute("SELECT category, start_time FROM time_tracking WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                   (user_id,))
    row = cursor.fetchone()  # Берём последнюю запись

    if row:
        category, start_time = row
        start_time = datetime.fromisoformat(start_time)
        duration = datetime.now() - start_time
        minutes = round(duration.total_seconds() / 60)

        # **Сохраняем в таблицу статистики**
        date = datetime.now().strftime("%Y-%m-%d")  # Дата в формате YYYY-MM-DD
        cursor.execute("INSERT INTO time_logs (user_id, category, date, duration) VALUES (?, ?, ?, ?)",
                       (user_id, category, date, minutes))
        conn.commit()

        # Удаляем запись из `time_tracking`, чтобы активность считалась завершённой
        cursor.execute("DELETE FROM time_tracking WHERE user_id = ?", (user_id,))
        conn.commit()

        return category, minutes
    return None, None


# статистика за день по категориям
def get_daily_stats(user_id):
    date = datetime.now().strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT category, SUM(duration) FROM time_logs 
        WHERE user_id = ? AND date = ? 
        GROUP BY category
    """, (user_id, date))

    rows = cursor.fetchall()

    # Считаем время без трекинга
    total_tracked = sum(duration for _, duration in rows)
    untracked_minutes = 1440 - total_tracked  # 1440 минут = 24 часа

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
    print(rows)
    for date, category, duration in rows:
        weekday = datetime.strptime(date, "%Y-%m-%d").strftime("%A")
        weekday_ru = DAYS_TRANSLATION[weekday]  # Переводим на русский
        if weekday_ru not in stats_by_day:
            stats_by_day[weekday_ru] = {}
        stats_by_day[weekday_ru][category] = duration

    # Добавляем "Без трекинга" на каждый день
    for weekday in stats_by_day.keys():
        total_tracked = sum(stats_by_day[weekday].values())
        untracked_minutes = 1440 - total_tracked
        stats_by_day[weekday]["🕰 Без трекинга"] = untracked_minutes

    return stats_by_day


# Функция для удаления эмодзи из строки.
def remove_emojis(text):
    return re.sub(r'[^\w\s,]', '', text)


# Функция для форматирования процентов. Скрывает проценты < 1%
def autopct_func(pct, allvalues):
    if pct < 1:
        return ''
    else:
        return f'{pct:.0f}%'  # Округляем до целого числа


# Обработчик нажатия на кнопку
@dp.message(lambda message: message.text in CATEGORIES)
async def track_time(message: types.Message):
    user_id = message.from_user.id # Получаем ID пользователя
    category = message.text

    # Проверяем, была ли активность
    old_category, minutes = stop_tracking(user_id)

    if old_category:
        await message.answer(f"⏳ Ты потратил {minutes} мин на {old_category}.")

    # Запускаем новую активность
    if old_category != category:
        start_tracking(user_id, category)
        await message.answer(f"✅ Начат трекинг: {category}")


# Обработчик получения статистики
@dp.message(Command("stats_day"))
async def send_daily_stats(message: types.Message):
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
    wedges, texts, autotexts = ax.pie(durations, autopct=lambda pct: autopct_func(pct, durations), startangle=90, colors=plt.cm.Paired.colors)
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


@dp.message(Command("stats_week"))
async def send_weekly_stats(message: types.Message):
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

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

print(f"TOKEN: {TOKEN}")

if __name__ == "__main__":
    asyncio.run(main())
