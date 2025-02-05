import logging
import asyncio
import speech_recognition as sr
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from googleapiclient.discovery import build
from PIL import Image, ImageDraw, ImageFont
import requests
import datetime
import json

API_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
scheduler = AsyncIOScheduler()
recognizer = sr.Recognizer()

# Загрузка или создание настроек пользователя
def load_user_settings():
    try:
        with open("user_settings.json", "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}

def save_user_settings(settings):
    try:
        with open("user_settings.json", "w") as file:
            json.dump(settings, file)
    except Exception as e:
        logging.error(f"Ошибка при сохранении настроек: {e}")

user_settings = load_user_settings()

# Кнопки управления
main_kb = ReplyKeyboardMarkup(resize_keyboard=True)
main_kb.add(KeyboardButton("📅 Показать календарь"))
main_kb.add(KeyboardButton("➕ Добавить событие"))
main_kb.add(KeyboardButton("⚙ Настройки"))

settings_kb = ReplyKeyboardMarkup(resize_keyboard=True)
settings_kb.add(KeyboardButton("🕒 Настроить расписание уведомлений"))
settings_kb.add(KeyboardButton("⬅ Назад"))

schedule_kb = ReplyKeyboardMarkup(resize_keyboard=True)
schedule_kb.add(KeyboardButton("📌 Одинаковое время для всех дней"))
schedule_kb.add(KeyboardButton("📆 Разное время для каждого дня"))
schedule_kb.add(KeyboardButton("❌ Отключить расписание"))
schedule_kb.add(KeyboardButton("⬅ Назад"))

# Функции для работы с расписанием
def send_daily_schedule(user_id):
    try:
        asyncio.create_task(bot.send_message(user_id, "Ваше расписание на сегодня: ..."))
    except Exception as e:
        logging.error(f"Ошибка отправки расписания: {e}")

def send_evening_report(user_id):
    try:
        asyncio.create_task(bot.send_message(user_id, "Ваш вечерний отчет: ..."))
    except Exception as e:
        logging.error(f"Ошибка отправки вечернего отчета: {e}")

# Подтверждение после голосового сообщения
async def confirm_event(user_id, text):
    confirm_kb = InlineKeyboardMarkup()
    confirm_kb.add(InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm:{text}"))
    confirm_kb.add(InlineKeyboardButton("❌ Отменить", callback_data="cancel"))
    await bot.send_message(user_id, f"Распознанный текст: {text}\nПодтвердить?", reply_markup=confirm_kb)

@dp.callback_query_handler(lambda call: call.data.startswith("confirm:"))
async def confirmed_event(call: types.CallbackQuery):
    text = call.data.split(":", 1)[1]
    await bot.send_message(call.from_user.id, f"Событие добавлено: {text}")
    # Здесь можно добавить логику сохранения события в календарь

@dp.callback_query_handler(lambda call: call.data == "cancel")
async def canceled_event(call: types.CallbackQuery):
    await bot.send_message(call.from_user.id, "Добавление события отменено.")

# Обработчик голосовых сообщений
@dp.message_handler(content_types=types.ContentType.VOICE)
async def handle_voice(message: types.Message):
    try:
        file = await message.voice.get_file()
        file_path = file.file_path
        await bot.download_file(file_path, "voice.ogg")
        with sr.AudioFile("voice.ogg") as source:
            audio = recognizer.record(source)
        text = recognizer.recognize_google(audio, language="ru-RU")
        await confirm_event(message.from_user.id, text)
    except sr.UnknownValueError:
        await message.answer("Не удалось распознать речь. Попробуйте ещё раз.")
    except sr.RequestError as e:
        logging.error(f"Ошибка запроса к сервису распознавания речи: {e}")
        await message.answer("Ошибка сервиса распознавания речи. Попробуйте позже.")
    except Exception as e:
        logging.error(f"Ошибка обработки голосового сообщения: {e}")
        await message.answer("Произошла ошибка при обработке голосового сообщения.")

# Запуск бота
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scheduler.start()
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
