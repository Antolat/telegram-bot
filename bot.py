import logging
import asyncio
import json
import tempfile
import os
import calendar
import uuid

from datetime import datetime, timedelta, date

import dateparser
import speech_recognition as sr
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Замените на ваш токен
API_TOKEN = 7504092318:AAEiytgbg-iCpVDVGCv9wN0Z-uSv1WdzMC8

# Инициализация бота, диспетчера и планировщика
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
scheduler = AsyncIOScheduler()
recognizer = sr.Recognizer()

# -----------------------
# ХРАНЕНИЕ ДАННЫХ
# -----------------------

def load_user_settings():
    try:
        with open("user_settings.json", "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_user_settings(settings):
    try:
        with open("user_settings.json", "w") as f:
            json.dump(settings, f)
    except Exception as e:
        logging.error(f"Ошибка при сохранении настроек: {e}")

user_settings = load_user_settings()

def load_events():
    try:
        with open("events.json", "r") as f:
            return json.load(f).get("events", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_events(events):
    try:
        with open("events.json", "w") as f:
            json.dump({"events": events}, f)
    except Exception as e:
        logging.error(f"Ошибка при сохранении событий: {e}")

events = load_events()

# -----------------------
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# -----------------------

def event_occurs_on(event, target_date: date) -> bool:
    try:
        event_date = datetime.fromisoformat(event["date"]).date()
    except Exception:
        return False
    recurrence = event.get("recurrence", "none")
    if recurrence == "none":
        return event_date == target_date
    elif recurrence == "daily":
        return event_date <= target_date
    elif recurrence == "weekly":
        return event_date <= target_date and event_date.weekday() == target_date.weekday()
    elif recurrence == "monthly":
        return event_date <= target_date and event_date.day == target_date.day
    elif recurrence == "yearly":
        return event_date <= target_date and event_date.month == target_date.month and event_date.day == target_date.day
    return False

def generate_calendar(year: int, month: int):
    inline_kb = InlineKeyboardMarkup(row_width=7)
    month_year = f"{calendar.month_name[month]} {year}"
    inline_kb.add(InlineKeyboardButton(month_year, callback_data="ignore"))
    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    inline_kb.add(*[InlineKeyboardButton(day, callback_data="ignore") for day in week_days])
    month_cal = calendar.monthcalendar(year, month)
    for week in month_cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="ignore"))
            else:
                day_str = f"{year}-{month:02d}-{day:02d}"
                row.append(InlineKeyboardButton(str(day), callback_data=f"day:{day_str}"))
        inline_kb.add(*row)
    prev_month = month - 1
    prev_year = year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1
    inline_kb.add(
        InlineKeyboardButton("<<", callback_data=f"calendar:{prev_year}-{prev_month:02d}"),
        InlineKeyboardButton(">>", callback_data=f"calendar:{next_year}-{next_month:02d}")
    )
    return inline_kb

# -----------------------
# ГЛОБАЛЬНЫЕ Состояния
# -----------------------

# Для пошагового создания события
# Ключ – user_id, значение – словарь с ключами: step, date, title, category, recurrence, reminder, description
event_creation_state = {}
# Для редактирования события
event_edit_state = {}
# Для поиска событий
search_state = {}
# Для просмотра дня/недели (простой флаг хранения)
if not hasattr(dp, 'day_view_state'):
    dp.day_view_state = {}
if not hasattr(dp, 'week_view_state'):
    dp.week_view_state = {}

# -----------------------
# ОСНОВНОЕ МЕНЮ
# -----------------------

main_kb = ReplyKeyboardMarkup(resize_keyboard=True)
main_kb.add(KeyboardButton("📅 Месяц"))
main_kb.add(KeyboardButton("📅 День"), KeyboardButton("📅 Неделя"))
main_kb.add(KeyboardButton("📁 Архив"))
main_kb.add(KeyboardButton("➕ Добавить событие"))
main_kb.add(KeyboardButton("🔍 Поиск событий"))
main_kb.add(KeyboardButton("📊 Отчет"))
main_kb.add(KeyboardButton("⚙ Настройки"))
main_kb.add(KeyboardButton("🔄 Синхронизация"))

@dp.message_handler(commands=["start"])
async def start_handler(message: types.Message):
    welcome_text = (
        "Привет!\n\n"
        "Я — минималистичный календарь-бот, созданный для удобного планирования ваших дел. "
        "Вы можете добавлять события голосом или текстом, просматривать их по дням, неделям и месяцам, "
        "а также получать своевременные напоминания. Выберите действие ниже, чтобы начать!"
    )
    await message.answer(welcome_text, reply_markup=main_kb)

# -----------------------
# ПРОСМОТР КАЛЕНДАРЯ
# -----------------------

@dp.message_handler(lambda message: message.text == "📅 Месяц")
async def month_calendar_handler(message: types.Message):
    today = datetime.today()
    inline_kb = generate_calendar(today.year, today.month)
    await message.answer("Выберите дату:", reply_markup=inline_kb)

@dp.callback_query_handler(lambda call: call.data.startswith("calendar:"))
async def calendar_navigation(call: types.CallbackQuery):
    _, ym = call.data.split(":", 1)
    year, month = map(int, ym.split("-"))
    inline_kb = generate_calendar(year, month)
    await call.message.edit_reply_markup(reply_markup=inline_kb)

@dp.callback_query_handler(lambda call: call.data.startswith("day:"))
async def day_selection(call: types.CallbackQuery):
    _, date_str = call.data.split(":", 1)
    selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    user_id = call.from_user.id
    user_events = [ev for ev in events if ev["user_id"] == user_id and event_occurs_on(ev, selected_date)]
    text = f"События на {selected_date.isoformat()}:\n"
    if not user_events:
        text += "Нет событий."
    else:
        for ev in user_events:
            text += f"\nID: {ev['id']}\nНазвание: {ev['title']}\nДата: {ev['date']}\n"
            if ev.get("category"):
                text += f"Категория: {ev['category']}\n"
            if ev.get("recurrence", "none") != "none":
                text += f"Повторение: {ev['recurrence']}\n"
    inline_kb = InlineKeyboardMarkup()
    inline_kb.add(InlineKeyboardButton("➕ Добавить событие", callback_data=f"add:{date_str}"))
    if user_events:
        for ev in user_events:
            inline_kb.add(InlineKeyboardButton(f"✏️ Изменить {ev['title']}", callback_data=f"edit:{ev['id']}"))
            inline_kb.add(InlineKeyboardButton(f"🗑 Удалить {ev['title']}", callback_data=f"delete:{ev['id']}"))
    await call.message.edit_text(text, reply_markup=inline_kb)

# Просмотр событий на выбранный день (текстовая команда "📅 День")
@dp.message_handler(lambda message: message.text == "📅 День")
async def start_day_view(message: types.Message):
    dp.day_view_state[message.from_user.id] = True
    await message.answer("Введите дату для просмотра (например, 'сегодня', 'завтра', или '2025-02-05'):")

@dp.message_handler(lambda message: message.from_user.id in dp.day_view_state)
async def day_view_input(message: types.Message):
    user_id = message.from_user.id
    parsed_date = dateparser.parse(message.text, languages=['ru'])
    if not parsed_date:
        await message.answer("Не удалось распознать дату. Попробуйте снова:")
        return
    target_date = parsed_date.date()
    user_events = [ev for ev in events if ev["user_id"] == user_id and event_occurs_on(ev, target_date)]
    text = f"События на {target_date.isoformat()}:\n"
    if not user_events:
        text += "Нет событий."
    else:
        for ev in user_events:
            text += f"\nID: {ev['id']}\nНазвание: {ev['title']}\nДата: {ev['date']}\n"
    await message.answer(text)
    dp.day_view_state.pop(user_id, None)

# Просмотр событий за неделю (текстовая команда "📅 Неделя")
@dp.message_handler(lambda message: message.text == "📅 Неделя")
async def week_view_handler(message: types.Message):
    dp.week_view_state[message.from_user.id] = True
    await message.answer("Введите дату для определения недели (например, 'сегодня', 'завтра', или '2025-02-05'):")

@dp.message_handler(lambda message: message.from_user.id in dp.week_view_state)
async def week_view_input(message: types.Message):
    user_id = message.from_user.id
    parsed_date = dateparser.parse(message.text, languages=['ru'])
    if not parsed_date:
        await message.answer("Не удалось распознать дату. Попробуйте снова:")
        return
    target_date = parsed_date.date()
    start_of_week = target_date - timedelta(days=target_date.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    text = f"События с {start_of_week.isoformat()} по {end_of_week.isoformat()}:\n"
    found = False
    current_day = start_of_week
    while current_day <= end_of_week:
        day_events = [ev for ev in events if ev["user_id"] == user_id and event_occurs_on(ev, current_day)]
        if day_events:
            text += f"\nДата: {current_day.isoformat()}\n"
            for ev in day_events:
                text += f"ID: {ev['id']} Название: {ev['title']}\n"
            found = True
        current_day += timedelta(days=1)
    if not found:
        text += "\nНет событий."
    await message.answer(text)
    dp.week_view_state.pop(user_id, None)

# Просмотр архивных событий (события старше 30 дней)
@dp.message_handler(lambda message: message.text == "📁 Архив")
async def archive_view_handler(message: types.Message):
    user_id = message.from_user.id
    threshold = date.today() - timedelta(days=30)
    archived_events = [ev for ev in events if ev["user_id"] == user_id and datetime.fromisoformat(ev["date"]).date() < threshold]
    text = "Архив событий (старше 30 дней):\n"
    if not archived_events:
        text += "Нет архивных событий."
    else:
        for ev in archived_events:
            text += f"\nID: {ev['id']} Название: {ev['title']} Дата: {ev['date']}\n"
    await message.answer(text)

# -----------------------
# СОЗДАНИЕ СОБЫТИЯ (Пошагово)
# -----------------------

# Если событие добавляется через кнопку календаря – дата уже известна
@dp.callback_query_handler(lambda call: call.data.startswith("add:"))
async def add_event_callback(call: types.CallbackQuery):
    _, date_str = call.data.split(":", 1)
    user_id = call.from_user.id
    event_creation_state[user_id] = {"step": "title", "date": date_str}
    await call.message.answer("Введите название события:")

# Запуск пошагового создания события через главное меню
@dp.message_handler(lambda message: message.text == "➕ Добавить событие")
async def start_event_creation(message: types.Message):
    user_id = message.from_user.id
    event_creation_state[user_id] = {"step": "date"}
    await message.answer("Введите дату и время события (например, 'завтра в 15:00'):")

# Пошаговая обработка ввода для создания события
@dp.message_handler(lambda message: message.from_user.id in event_creation_state)
async def event_creation_handler(message: types.Message):
    user_id = message.from_user.id
    state = event_creation_state[user_id]
    step = state.get("step")
    if step == "date":
        parsed_date = dateparser.parse(message.text, languages=['ru'])
        if not parsed_date:
            await message.answer("Не удалось распознать дату. Пожалуйста, введите дату ещё раз:")
            return
        state["date"] = parsed_date.isoformat()
        state["step"] = "title"
        await message.answer(f"Дата установлена: {parsed_date}. Теперь введите название события:")
    elif step == "title":
        state["title"] = message.text.strip()
        state["step"] = "category"
        await message.answer("Введите категорию события (или оставьте пустым):")
    elif step == "category":
        state["category"] = message.text.strip()
        state["step"] = "recurrence"
        await message.answer("Введите повторение события (none, daily, weekly, monthly, yearly). Если нет – введите 'none':")
    elif step == "recurrence":
        recurrence = message.text.strip().lower()
        if recurrence not in ["none", "daily", "weekly", "monthly", "yearly"]:
            await message.answer("Неверный формат повторения. Введите одно из: none, daily, weekly, monthly, yearly:")
            return
        state["recurrence"] = recurrence
        state["step"] = "reminder"
        await message.answer("Введите напоминание (в минутах до события, опционально – введите 0 или оставьте пустым, если не нужно):")
    elif step == "reminder":
        text = message.text.strip()
        if text == "" or text == "0":
            state["reminder"] = None
        else:
            try:
                state["reminder"] = int(text)
            except ValueError:
                await message.answer("Неверный формат напоминания. Введите число минут или 0:")
                return
        state["step"] = "description"
        await message.answer("Введите описание события (опционально):")
    elif step == "description":
        state["description"] = message.text.strip()
        # Выводим сводку и просим подтвердить
        summary = (
            f"Проверьте данные события:\nДата: {state['date']}\nНазвание: {state['title']}\n"
            f"Категория: {state.get('category','')}\nПовторение: {state.get('recurrence','none')}\n"
            f"Напоминание: {state.get('reminder','')}\nОписание: {state.get('description','')}\n"
        )
        inline_kb = InlineKeyboardMarkup()
        inline_kb.add(
            InlineKeyboardButton("✅ Подтвердить", callback_data="event_confirm:yes"),
            InlineKeyboardButton("❌ Отменить", callback_data="event_confirm:no")
        )
        state["step"] = "confirm"
        await message.answer(summary, reply_markup=inline_kb)
    elif step == "voice_modification":
        # Если пользователь после голосового ввода решил изменить дату и название,
        # ожидается формат: "дата|название"
        parts = message.text.split("|")
        if len(parts) != 2:
            await message.answer("Введите данные в формате 'дата|название':")
            return
        parsed_date = dateparser.parse(parts[0].strip(), languages=['ru'])
        if not parsed_date:
            await message.answer("Не удалось распознать дату. Попробуйте снова:")
            return
        state["date"] = parsed_date.isoformat()
        state["title"] = parts[1].strip()
        state["step"] = "confirm_voice"
        summary = f"Обновлено: Дата: {state['date']}, Название: {state['title']}\nНажмите Подтвердить, чтобы продолжить, или Отменить."
        inline_kb = InlineKeyboardMarkup()
        inline_kb.add(
            InlineKeyboardButton("✅ Подтвердить", callback_data="voice_event_confirm:yes"),
            InlineKeyboardButton("❌ Отменить", callback_data="voice_event_confirm:no")
        )
        await message.answer(summary, reply_markup=inline_kb)

# Подтверждение создания события (текстовый вариант)
@dp.callback_query_handler(lambda call: call.data.startswith("event_confirm:"))
async def event_confirm_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    response = call.data.split(":", 1)[1]
    if response == "yes":
        state = event_creation_state.get(user_id)
        if state:
            new_event = {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "title": state["title"],
                "category": state.get("category", ""),
                "date": state["date"],
                "recurrence": state.get("recurrence", "none"),
                "reminder": state.get("reminder", None),
                "description": state.get("description", "")
            }
            events.append(new_event)
            save_events(events)
            await call.message.answer("Событие успешно добавлено!")
        else:
            await call.message.answer("Нет данных для подтверждения.")
    else:
        await call.message.answer("Создание события отменено.")
    if user_id in event_creation_state:
        event_creation_state.pop(user_id)
    await call.answer()

# -----------------------
# ГОЛОСОВОЕ СОЗДАНИЕ СОБЫТИЯ
# -----------------------

@dp.message_handler(content_types=types.ContentType.VOICE)
async def handle_voice(message: types.Message):
    user_id = message.from_user.id
    try:
        file = await message.voice.get_file()
        with tempfile.NamedTemporaryFile(delete=False, prefix="voice_", suffix=".ogg") as tmp:
            temp_filename = tmp.name
        await bot.download_file(file.file_path, temp_filename)
        def recognize():
            with sr.AudioFile(temp_filename) as source:
                audio = recognizer.record(source)
            return recognizer.recognize_google(audio, language="ru-RU")
        try:
            text = await asyncio.to_thread(recognize)
            parsed_date = dateparser.parse(text, languages=['ru'])
            state = {}
            if parsed_date:
                state["date"] = parsed_date.isoformat()
                state["title"] = text  # Используем полный текст как название
                state["step"] = "confirm_voice"
                summary = (
                    f"Распознано:\nДата: {state['date']}\nНазвание: {state['title']}\n\n"
                    "Если хотите изменить дату и название, отправьте данные в формате 'дата|название'.\n"
                    "Или нажмите Подтвердить."
                )
                inline_kb = InlineKeyboardMarkup()
                inline_kb.add(
                    InlineKeyboardButton("✅ Подтвердить", callback_data="voice_event_confirm:yes"),
                    InlineKeyboardButton("❌ Отменить", callback_data="voice_event_confirm:no")
                )
                event_creation_state[user_id] = state
                await message.answer(summary, reply_markup=inline_kb)
            else:
                state["step"] = "date"
                state["title"] = text
                event_creation_state[user_id] = state
                await message.answer(f"Распознан текст: {text}\nНе удалось распознать дату. Введите дату и время в естественном формате:")
        except sr.UnknownValueError:
            await message.answer("Не удалось распознать речь. Попробуйте ещё раз.")
        except sr.RequestError as e:
            logging.error(f"Ошибка запроса к сервису распознавания речи: {e}")
            await message.answer("Ошибка сервиса распознавания речи. Попробуйте позже.")
        finally:
            os.remove(temp_filename)
    except Exception as e:
        logging.error(f"Ошибка обработки голосового сообщения: {e}")
        await message.answer("Произошла ошибка при обработке голосового сообщения.")

# Подтверждение голосового ввода
@dp.callback_query_handler(lambda call: call.data.startswith("voice_event_confirm:"))
async def voice_event_confirm_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    response = call.data.split(":", 1)[1]
    if response == "yes":
        state = event_creation_state.get(user_id)
        if state:
            # Если голосовое событие подтверждено, переходим к вводу категории
            state["step"] = "category"
            await call.message.answer("Введите категорию события (или оставьте пустым):")
        else:
            await call.message.answer("Нет данных для подтверждения.")
    else:
        await call.message.answer("Создание события отменено.")
        if user_id in event_creation_state:
            event_creation_state.pop(user_id)
    await call.answer()

# -----------------------
# РЕДАКТИРОВАНИЕ И УДАЛЕНИЕ СОБЫТИЙ
# -----------------------

@dp.callback_query_handler(lambda call: call.data.startswith("edit:"))
async def edit_event_callback(call: types.CallbackQuery):
    event_id = call.data.split(":", 1)[1]
    user_id = call.from_user.id
    event = next((ev for ev in events if ev["id"] == event_id and ev["user_id"] == user_id), None)
    if not event:
        await call.message.answer("Событие не найдено.")
        return
    event_edit_state[user_id] = event_id
    await call.message.answer(
        f"Отредактируйте событие. Текущие данные:\n"
        f"Название: {event['title']}\n"
        f"Категория: {event.get('category', '')}\n"
        f"Повторение: {event.get('recurrence', 'none')}\n"
        f"Напоминание: {event.get('reminder', '')}\n"
        f"Описание: {event.get('description', '')}\n\n"
        "Введите данные в формате:\nНазвание | Категория | Повторение | Напоминание | Описание"
    )

@dp.message_handler(lambda message: message.from_user.id in event_edit_state)
async def edit_event_handler(message: types.Message):
    user_id = message.from_user.id
    event_id = event_edit_state.get(user_id)
    event = next((ev for ev in events if ev["id"] == event_id and ev["user_id"] == user_id), None)
    if not event:
        await message.answer("Событие не найдено.")
        event_edit_state.pop(user_id, None)
        return
    try:
        parts = [part.strip() for part in message.text.split("|")]
        event["title"] = parts[0]
        event["category"] = parts[1] if len(parts) > 1 else ""
        event["recurrence"] = parts[2].lower() if len(parts) > 2 else "none"
        event["reminder"] = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
        event["description"] = parts[4] if len(parts) > 4 else ""
        save_events(events)
        await message.answer("Событие обновлено.")
    except Exception as e:
        logging.error(f"Ошибка редактирования события: {e}")
        await message.answer("Ошибка при редактировании события. Проверьте формат.")
    finally:
        event_edit_state.pop(user_id, None)

@dp.callback_query_handler(lambda call: call.data.startswith("delete:"))
async def delete_event_callback(call: types.CallbackQuery):
    event_id = call.data.split(":", 1)[1]
    user_id = call.from_user.id
    global events
    before_count = len(events)
    events = [ev for ev in events if not (ev["id"] == event_id and ev["user_id"] == user_id)]
    if len(events) < before_count:
        save_events(events)
        await call.message.answer("Событие удалено.")
    else:
        await call.message.answer("Событие не найдено.")

# -----------------------
# ПОИСК СОБЫТИЙ
# -----------------------

@dp.message_handler(lambda message: message.text == "🔍 Поиск событий")
async def search_event_prompt(message: types.Message):
    await message.answer("Введите ключевое слово для поиска событий:")
    search_state[message.from_user.id] = True

@dp.message_handler(lambda message: search_state.get(message.from_user.id, False))
async def search_event_handler(message: types.Message):
    user_id = message.from_user.id
    keyword = message.text.lower()
    matching_events = [
        ev for ev in events
        if ev["user_id"] == user_id and (keyword in ev["title"].lower() or keyword in ev.get("description", "").lower())
    ]
    if not matching_events:
        await message.answer("События не найдены.")
    else:
        text = "Найденные события:\n"
        for ev in matching_events:
            text += f"ID: {ev['id']}\nНазвание: {ev['title']}\nДата: {ev['date']}\n\n"
        await message.answer(text)
    search_state.pop(user_id, None)

# -----------------------
# ОТЧЁТ ЗА МЕСЯЦ
# -----------------------

@dp.message_handler(lambda message: message.text == "📊 Отчет")
async def report_handler(message: types.Message):
    user_id = message.from_user.id
    today = datetime.today()
    current_year = today.year
    current_month = today.month
    report_events = []
    for ev in events:
        if ev["user_id"] == user_id:
            try:
                event_date = datetime.fromisoformat(ev["date"]).date()
            except Exception:
                continue
            if event_date.year == current_year and event_date.month == current_month:
                report_events.append(ev)
            else:
                days_in_month = [date(current_year, current_month, d) for d in range(1, calendar.monthrange(current_year, current_month)[1] + 1)]
                if any(event_occurs_on(ev, d) for d in days_in_month):
                    report_events.append(ev)
    total_events = len(report_events)
    categories = {}
    for ev in report_events:
        cat = ev.get("category", "Без категории")
        categories[cat] = categories.get(cat, 0) + 1
    text = f"Отчет за {calendar.month_name[current_month]} {current_year}:\n"
    text += f"Всего событий: {total_events}\n"
    for cat, count in categories.items():
        text += f"{cat}: {count}\n"
    await message.answer(text)

# -----------------------
# СИНХРОНИЗАЦИЯ (заглушка) и НАСТРОЙКИ
# -----------------------

@dp.message_handler(lambda message: message.text == "🔄 Синхронизация")
async def sync_handler(message: types.Message):
    await message.answer("Интеграция с Google Calendar пока не реализована.")

@dp.message_handler(lambda message: message.text == "⚙ Настройки")
async def settings_handler(message: types.Message):
    await message.answer("Настройки пока не реализованы.")

# -----------------------
# НАПОМИНАНИЯ И ОЧИСТКА ВРЕМЕННЫХ ФАЙЛОВ
# -----------------------

async def check_reminders():
    now = datetime.now()
    for ev in events:
        if ev.get("reminder") is not None:
            try:
                event_dt = datetime.fromisoformat(ev["date"])
            except Exception:
                continue
            reminder_minutes = ev["reminder"]
            reminder_time = event_dt - timedelta(minutes=reminder_minutes)
            if reminder_time <= now < reminder_time + timedelta(minutes=1):
                try:
                    await bot.send_message(ev["user_id"], f"Напоминание: Скоро событие '{ev['title']}'")
                except Exception as e:
                    logging.error(f"Ошибка отправки напоминания: {e}")

scheduler.add_job(check_reminders, "interval", minutes=1)

def cleanup_temp_files():
    temp_dir = tempfile.gettempdir()
    now = datetime.now()
    for filename in os.listdir(temp_dir):
        if filename.startswith("voice_") and filename.endswith(".ogg"):
            file_path = os.path.join(temp_dir, filename)
            try:
                file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                if now - file_mtime > timedelta(hours=24):
                    os.remove(file_path)
                    logging.info(f"Удалён временный файл: {file_path}")
            except Exception as e:
                logging.error(f"Ошибка удаления файла {file_path}: {e}")

scheduler.add_job(cleanup_temp_files, "interval", hours=24)

# -----------------------
# ЗАПУСК БОТА
# -----------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scheduler.start()
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
