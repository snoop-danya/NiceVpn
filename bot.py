# bot.py - ПОЛНОСТЬЮ ПЕРЕРАБОТАННАЯ ВЕРСИЯ С ИСПРАВЛЕНИЯМИ
import subprocess
import sys


def install_dependencies():
    """Принудительная установка зависимостей"""
    try:
        import aiosqlite
        print("✅ aiosqlite already installed")
    except ImportError:
        print("📦 Installing aiosqlite...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "aiosqlite==0.19.0"])

    try:
        import aiohttp
        print("✅ aiohttp already installed")
    except ImportError:
        print("📦 Installing aiohttp...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "aiohttp==3.9.1"])


# Вызовите функцию перед импортом остальных модулей
install_dependencies()

import asyncio
import aiosqlite
import logging
from datetime import datetime
from typing import Optional
import re
import secrets
import json
import html  # Добавьте этот импорт

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup,
    InlineKeyboardButton, CallbackQuery, Message
)
import aiohttp

# =========== НАСТРОЙКИ ===========
BOT_TOKEN = "8668215242:AAEnNgOD-stAG9TkX4wvh_58T0ubkiktKEU"
SITE_URL = "https://niceknifes.ru/NiceVpn"
API_ENDPOINT = f"{SITE_URL}/bot_api.php"

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# =========== СОСТОЯНИЯ ДЛЯ FSM ===========
class RegisterStates(StatesGroup):
    waiting_for_email = State()
    waiting_for_username = State()
    waiting_for_password = State()
    waiting_for_support_message = State()  # Добавьте эту строку


class SupportStates(StatesGroup):
    waiting_for_message = State()


class LoginStates(StatesGroup):
    waiting_for_username = State()
    waiting_for_password = State()


class TopupStates(StatesGroup):
    waiting_for_amount = State()


class BuyVPNStates(StatesGroup):
    waiting_for_tariff = State()
    waiting_for_period = State()

    class SupportStates(StatesGroup):
        waiting_for_message = State()


class AdminStates(StatesGroup):
    waiting_for_payment_id = State()
    waiting_for_user_id = State()
    waiting_for_balance_amount = State()
    waiting_for_user_action = State()  # Это правильное название
    waiting_for_new_username = State()
    waiting_for_new_email = State()
    waiting_for_new_password = State()
    waiting_for_delete_user_id = State()
    waiting_for_tariff_action = State()
    waiting_for_tariff_data = State()
    waiting_for_broadcast_message = State()
    waiting_for_ticket_response = State()
    waiting_for_ticket_id = State()


# =========== КЛАВИАТУРЫ ===========
def get_main_keyboard(user_role: str = "user") -> ReplyKeyboardMarkup:
    """Главная клавиатура"""
    buttons = [
        [KeyboardButton(text="📊 Мой профиль")],
        [KeyboardButton(text="🔑 Моя подписка")],
        [KeyboardButton(text="💳 Пополнить баланс")],
        [KeyboardButton(text="🛒 Купить VPN")],
        [KeyboardButton(text="📜 История платежей")],
        [KeyboardButton(text="📋 История подписок")],
        #[KeyboardButton(text="📞 Поддержка")],  # Измените текст здесь
        [KeyboardButton(text="❓ Помощь")]
    ]

    if user_role == "admin":
        buttons.insert(0, [KeyboardButton(text="👑 Админ панель")])

    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True
    )


def get_admin_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура админ панели"""
    buttons = [
        [KeyboardButton(text="✅ Подтвердить платеж")],
        [KeyboardButton(text="💰 Изменить баланс")],
        [KeyboardButton(text="👤 Управление пользователями")],
        [KeyboardButton(text="📊 Управление тарифами")],
        [KeyboardButton(text="📢 Рассылка")],
        [KeyboardButton(text="💬 Обращения в поддержку")],
        [KeyboardButton(text="📈 Статистика")],
        [KeyboardButton(text="◀️ Назад")]
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True
    )

def is_trial_tariff(tariff: dict) -> bool:
    """Определяет, является ли тариф пробным (цена 0 + слово 'проб'/'trial'/'бесплатн' в названии)"""
    price = float(tariff.get('price_month', 0))
    name = tariff.get('name', '').lower()
    trial_keywords = ['проб', 'trial', 'бесплатн', 'free', 'demo', 'демо']
    return price == 0 and any(kw in name for kw in trial_keywords)

def get_tariffs_keyboard(tariffs: list, used_trial_ids: list = None) -> InlineKeyboardMarkup:
    """Клавиатура выбора тарифа"""
    if used_trial_ids is None:
        used_trial_ids = []
    keyboard = []
    for tariff in tariffs:
        if is_trial_tariff(tariff):
            already_used = int(tariff['id']) in used_trial_ids
            if already_used:
                btn_text = f"🚫 {tariff['name']} — уже использован"
                callback = f"trial_used_{tariff['id']}"
            else:
                btn_text = f"{tariff['name']} — Бесплатно (24ч)"
                callback = f"tariff_{tariff['id']}"
        else:
            price_m = float(tariff.get('price_month', 0))
            price_text = f"{price_m:.0f}₽/мес" if price_m > 0 else "Бесплатно"
            btn_text = f"{tariff['name']} - {price_text}"
            callback = f"tariff_{tariff['id']}"
        keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=callback)])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_periods_keyboard(tariff: dict) -> InlineKeyboardMarkup:
    """Клавиатура выбора периода на основе тарифа"""
    # Для пробного тарифа — только кнопка на 24 часа
    if is_trial_tariff(tariff):
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🎁 Пробный период — 24 часа (бесплатно)",
                callback_data="period_trial"
            )
        ]])

    keyboard = []
    if float(tariff.get('price_month', 0)) > 0:
        keyboard.append([InlineKeyboardButton(
            text=f"1 месяц - {float(tariff['price_month']):.0f} ₽",
            callback_data="period_1_month"
        )])
    elif float(tariff.get('price_month', 0)) == 0:
        keyboard.append([InlineKeyboardButton(
            text="Бесплатно (1 месяц)",
            callback_data="period_1_month"
        )])
    if tariff.get('price_3months') and float(tariff['price_3months']) > 0:
        keyboard.append([InlineKeyboardButton(
            text=f"3 месяца - {float(tariff['price_3months']):.0f} ₽",
            callback_data="period_3_months"
        )])
    if tariff.get('price_6months') and float(tariff['price_6months']) > 0:
        keyboard.append([InlineKeyboardButton(
            text=f"6 месяцев - {float(tariff['price_6months']):.0f} ₽",
            callback_data="period_6_months"
        )])
    if tariff.get('price_year') and float(tariff['price_year']) > 0:
        keyboard.append([InlineKeyboardButton(
            text=f"12 месяцев - {float(tariff['price_year']):.0f} ₽",
            callback_data="period_12_months"
        )])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_admin_tariffs_keyboard(tariffs: list) -> InlineKeyboardMarkup:
    """Клавиатура управления тарифами для админа"""
    keyboard = []
    for tariff in tariffs:
        keyboard.append([
            InlineKeyboardButton(
                text=f"✏️ {tariff['name']}",
                callback_data=f"edit_tariff_{tariff['id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="➕ Создать тариф", callback_data="create_tariff")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# =========== БАЗА ДАННЫХ (SQLite для хранения сессий) ===========
class Database:
    def __init__(self, db_path: str = "bot_sessions.db"):
        self.db_path = db_path

    async def init_db(self):
        """Инициализация базы данных"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    telegram_id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    username TEXT,
                    email TEXT,
                    role TEXT,
                    balance REAL,
                    session_token TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pending_payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    amount REAL,
                    payment_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Новая таблица для обращений в поддержку
            await db.execute("""
                CREATE TABLE IF NOT EXISTS support_tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    username TEXT,
                    user_id INTEGER,
                    message TEXT,
                    status TEXT DEFAULT 'open',
                    admin_response TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()
            await db.execute("""
                            CREATE TABLE IF NOT EXISTS trial_usage (
                                telegram_id INTEGER,
                                tariff_id   INTEGER,
                                used_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                PRIMARY KEY (telegram_id, tariff_id)
                            )
                        """)

    async def save_ticket(self, telegram_id: int, username: str, user_id: int, message: str) -> int:
        """Сохранить обращение в поддержку"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO support_tickets (telegram_id, username, user_id, message, status, created_at) VALUES (?, ?, ?, ?, 'open', CURRENT_TIMESTAMP)",
                (telegram_id, username, user_id, message)
            )
            await db.commit()
            return cursor.lastrowid

    async def get_open_tickets(self) -> list:
        """Получить открытые обращения"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                    "SELECT * FROM support_tickets WHERE status = 'open' ORDER BY created_at DESC"
            ) as cursor:
                return await cursor.fetchall()

    async def get_all_tickets(self) -> list:
        """Получить все обращения"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                    "SELECT * FROM support_tickets ORDER BY created_at DESC LIMIT 50"
            ) as cursor:
                return await cursor.fetchall()

    async def update_ticket_status(self, ticket_id: int, status: str, admin_response: str = None):
        """Обновить статус обращения"""
        async with aiosqlite.connect(self.db_path) as db:
            if admin_response:
                await db.execute(
                    "UPDATE support_tickets SET status = ?, admin_response = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (status, admin_response, ticket_id)
                )
            else:
                await db.execute(
                    "UPDATE support_tickets SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (status, ticket_id)
                )
            await db.commit()

    async def get_ticket(self, ticket_id: int) -> Optional[dict]:
        """Получить обращение по ID"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                    "SELECT * FROM support_tickets WHERE id = ?",
                    (ticket_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        'id': row[0],
                        'telegram_id': row[1],
                        'username': row[2],
                        'user_id': row[3],
                        'message': row[4],
                        'status': row[5],
                        'admin_response': row[6],
                        'created_at': row[7],
                        'updated_at': row[8]
                    }
        return None

    async def has_used_trial(self, telegram_id: int, tariff_id: int) -> bool:
        """Проверить, использовал ли пользователь пробный период"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                    "SELECT 1 FROM trial_usage WHERE telegram_id = ? AND tariff_id = ?",
                    (telegram_id, tariff_id)
            ) as cursor:
                return await cursor.fetchone() is not None

    async def mark_trial_used(self, telegram_id: int, tariff_id: int):
        """Записать использование пробного периода"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO trial_usage (telegram_id, tariff_id, used_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (telegram_id, tariff_id)
            )
            await db.commit()

    async def get_used_trial_ids(self, telegram_id: int) -> list:
        """Получить список ID тарифов, по которым пробный уже брался"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                    "SELECT tariff_id FROM trial_usage WHERE telegram_id = ?",
                    (telegram_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
    async def migrate_db(self):
        """Миграция базы данных - добавляет недостающие колонки"""
        async with aiosqlite.connect(self.db_path) as db:
            # Проверяем наличие колонки payment_id в таблице pending_payments
            cursor = await db.execute("PRAGMA table_info(pending_payments)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]

            if 'payment_id' not in column_names:
                logger.info("Adding payment_id column to pending_payments table")
                await db.execute("ALTER TABLE pending_payments ADD COLUMN payment_id INTEGER")
                await db.commit()
                await db.execute("""
                                CREATE TABLE IF NOT EXISTS trial_usage (
                                    telegram_id INTEGER,
                                    tariff_id   INTEGER,
                                    used_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                    PRIMARY KEY (telegram_id, tariff_id)
                                )
                            """)
                logger.info("Migration completed")

    async def save_session(self, telegram_id: int, user_data: dict):
        """Сохранить сессию пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            session_token = str(user_data.get('id', user_data.get('user_id', 0)))

            await db.execute("""
                INSERT OR REPLACE INTO user_sessions 
                (telegram_id, user_id, username, email, role, balance, session_token, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                telegram_id,
                user_data.get('id', user_data.get('user_id', 0)),
                user_data.get('username', ''),
                user_data.get('email', ''),
                user_data.get('role', 'user'),
                float(user_data.get('balance', 0)),
                session_token
            ))
            await db.commit()

    async def get_session(self, telegram_id: int) -> Optional[dict]:
        """Получить сессию пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                    "SELECT user_id, username, email, role, balance, session_token FROM user_sessions WHERE telegram_id = ?",
                    (telegram_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        'id': row[0],
                        'username': row[1],
                        'email': row[2],
                        'role': row[3],
                        'balance': row[4],
                        'session_token': row[5]
                    }
        return None

    async def update_balance(self, telegram_id: int, new_balance: float):
        """Обновить баланс в сессии"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE user_sessions SET balance = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                (new_balance, telegram_id)
            )
            await db.commit()

    async def delete_session(self, telegram_id: int):
        """Удалить сессию пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM user_sessions WHERE telegram_id = ?", (telegram_id,))
            await db.commit()

    async def save_pending_payment(self, telegram_id: int, amount: float, payment_id: int = None) -> int:
        """Сохранить ожидающий платеж"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO pending_payments (telegram_id, amount, payment_id) VALUES (?, ?, ?)",
                (telegram_id, amount, payment_id)
            )
            await db.commit()
            return cursor.lastrowid

    async def delete_pending_payment(self, payment_id: int):
        """Удалить ожидающий платеж"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM pending_payments WHERE id = ?", (payment_id,))
            await db.commit()


db = Database()


# =========== API ВЗАИМОДЕЙСТВИЕ С САЙТОМ ===========
class SiteAPI:
    @staticmethod
    async def make_request(action: str, data: dict = None, session_token: str = None) -> dict:
        """Выполнить запрос к API сайта"""
        payload = {'action': action}
        if data:
            payload.update(data)
        if session_token:
            payload['session_token'] = session_token

        logger.info(f"Making request to {API_ENDPOINT} with action={action}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(API_ENDPOINT, data=payload, timeout=30) as response:
                    result = await response.json()
                    logger.info(f"Response for {action}: {result.get('success', False)}")
                    return result
        except Exception as e:
            logger.error(f"API request error: {e}")
            return {'success': False, 'message': f'Ошибка связи с сервером: {str(e)}'}

    @staticmethod
    async def register(email: str, username: str, password: str) -> dict:
        """Регистрация пользователя"""
        return await SiteAPI.make_request('register', {
            'email': email,
            'username': username,
            'password': password
        })

    @staticmethod
    async def admin_delete_user(session_token: str, user_id: int) -> dict:
        """Удалить пользователя (админ)"""
        return await SiteAPI.make_request('admin_delete_user', {
            'user_id': user_id
        }, session_token)

    @staticmethod
    async def admin_delete_user(session_token: str, user_id: int) -> dict:
        """Удалить пользователя (админ)"""
        return await SiteAPI.make_request('admin_delete_user', {
            'user_id': user_id
        }, session_token)

    @staticmethod
    async def admin_broadcast(session_token: str, message: str) -> dict:
        """Отправить рассылку (админ)"""
        return await SiteAPI.make_request('admin_broadcast', {
            'message': message
        }, session_token)

    @staticmethod
    async def admin_get_stats(session_token: str) -> dict:
        """Получить статистику (админ)"""
        return await SiteAPI.make_request('admin_get_stats', session_token=session_token)

    @staticmethod
    async def admin_update_user(session_token: str, user_id: int, field: str, value: str) -> dict:
        """Обновить данные пользователя (админ)"""
        return await SiteAPI.make_request('admin_update_user', {
            'user_id': user_id,
            'field': field,
            'value': value
        }, session_token)

    @staticmethod
    async def admin_create_tariff(session_token: str, tariff_data: dict) -> dict:
        """Создать тариф (админ)"""
        return await SiteAPI.make_request('admin_create_tariff', tariff_data, session_token)

    @staticmethod
    async def admin_update_tariff(session_token: str, tariff_id: int, tariff_data: dict) -> dict:
        """Обновить тариф (админ)"""
        data = {'tariff_id': tariff_id}
        data.update(tariff_data)
        return await SiteAPI.make_request('admin_update_tariff', data, session_token)

    @staticmethod
    async def admin_delete_tariff(session_token: str, tariff_id: int) -> dict:
        """Удалить тариф (админ)"""
        return await SiteAPI.make_request('admin_delete_tariff', {
            'tariff_id': tariff_id
        }, session_token)

    @staticmethod
    async def login(username: str, password: str) -> dict:
        """Вход пользователя"""
        return await SiteAPI.make_request('login', {
            'username': username,
            'password': password
        })

    @staticmethod
    async def get_user_data(session_token: str) -> dict:
        """Получить данные пользователя"""
        return await SiteAPI.make_request('get_user_data', session_token=session_token)

    @staticmethod
    async def create_payment(session_token: str, amount: float) -> dict:
        """Создать заявку на пополнение"""
        return await SiteAPI.make_request('create_payment', {
            'amount': amount
        }, session_token)

    @staticmethod
    async def get_tariffs() -> dict:
        """Получить список тарифов"""
        return await SiteAPI.make_request('get_tariffs')

    @staticmethod
    async def generate_key(session_token: str, tariff_id: int, period: str) -> dict:
        """Сгенерировать VPN ключ"""
        return await SiteAPI.make_request('generate_key', {
            'tariff_id': tariff_id,
            'period': period
        }, session_token)

    @staticmethod
    async def admin_complete_payment(session_token: str, payment_id: int) -> dict:
        """Подтвердить платеж (админ)"""
        return await SiteAPI.make_request('admin_complete_payment', {
            'payment_id': payment_id
        }, session_token)

    @staticmethod
    async def admin_get_users(session_token: str) -> dict:
        """Получить список пользователей (админ)"""
        return await SiteAPI.make_request('admin_get_users', session_token=session_token)

    @staticmethod
    async def admin_get_stats(session_token: str) -> dict:
        """Получить статистику (админ)"""
        return await SiteAPI.make_request('admin_get_stats', session_token=session_token)

    @staticmethod
    async def admin_update_balance(session_token: str, user_id: int, amount: float) -> dict:
        """Изменить баланс пользователя (админ)"""
        return await SiteAPI.make_request('admin_update_balance', {
            'user_id': user_id,
            'amount': amount
        }, session_token)

    @staticmethod
    async def admin_update_user(session_token: str, user_id: int, field: str, value: str) -> dict:
        """Обновить данные пользователя (админ)"""
        return await SiteAPI.make_request('admin_update_user', {
            'user_id': user_id,
            'field': field,
            'value': value
        }, session_token)

    @staticmethod
    async def admin_get_pending_payments(session_token: str) -> dict:
        """Получить ожидающие платежи (админ)"""
        return await SiteAPI.make_request('admin_get_pending_payments', session_token=session_token)

    @staticmethod
    async def admin_create_tariff(session_token: str, tariff_data: dict) -> dict:
        """Создать тариф (админ)"""
        return await SiteAPI.make_request('admin_create_tariff', tariff_data, session_token)

    @staticmethod
    async def admin_update_tariff(session_token: str, tariff_id: int, tariff_data: dict) -> dict:
        """Обновить тариф (админ)"""
        data = {'tariff_id': tariff_id}
        data.update(tariff_data)
        return await SiteAPI.make_request('admin_update_tariff', data, session_token)

    @staticmethod
    async def admin_delete_tariff(session_token: str, tariff_id: int) -> dict:
        """Удалить тариф (админ)"""
        return await SiteAPI.make_request('admin_delete_tariff', {
            'tariff_id': tariff_id
        }, session_token)


@dp.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext):
    """Отмена текущей операции"""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("❌ Нет активной операции для отмены.")
        return

    await state.clear()
    await message.answer("✅ Операция отменена.")


# =========== ХЭНДЛЕРЫ ===========
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    await state.clear()

    # Проверяем, есть ли активная сессия
    session = await db.get_session(message.from_user.id)

    if session and session.get('session_token'):
        # Проверяем валидность токена на сервере
        validation_result = await SiteAPI.get_user_data(session['session_token'])

        if validation_result['success']:
            # Сессия валидна, обновляем данные
            balance = validation_result.get('balance', session['balance'])
            role = validation_result.get('role', session['role'])
            await db.update_balance(message.from_user.id, balance)

            await message.answer(
                f"✅ С возвращением, {session['username']}!\n\n"
                f"💰 Ваш баланс: {balance:.2f} ₽\n"
                f"👑 Роль: {'Администратор' if role == 'admin' else 'Пользователь'}",
                reply_markup=get_main_keyboard(role)
            )
        else:
            # Сессия невалидна, удаляем
            await db.delete_session(message.from_user.id)
            await show_auth_menu(message)
    else:
        await show_auth_menu(message)


async def show_auth_menu(message: Message):
    """Показать меню авторизации"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔐 Вход", callback_data="action_login")],
        [InlineKeyboardButton(text="📝 Регистрация", callback_data="action_register")]
    ])
    await message.answer(
        "🌟 Добро пожаловать в NiceVPN Bot!\n\n"
        "Здесь вы можете:\n"
        "• Приобрести VPN ключ\n"
        "• Пополнить баланс\n"
        "• Управлять подпиской\n"
        "• Получить поддержку\n\n"
        "Пожалуйста, войдите или зарегистрируйтесь:",
        reply_markup=keyboard
    )


@dp.callback_query(lambda c: c.data == "action_login")
async def action_login(callback: CallbackQuery, state: FSMContext):
    """Начало процесса входа"""
    await callback.message.delete()
    await callback.message.answer(
        "🔐 Вход в аккаунт\n\n"
        "Введите ваш логин (никнейм или email):"
    )
    await state.set_state(LoginStates.waiting_for_username)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "action_register")
async def action_register(callback: CallbackQuery, state: FSMContext):
    """Начало процесса регистрации"""
    await callback.message.delete()
    await callback.message.answer(
        "📝 Регистрация нового аккаунта\n\n"
        "Введите ваш Email:"
    )
    await state.set_state(RegisterStates.waiting_for_email)
    await callback.answer()


# =========== РЕГИСТРАЦИЯ ===========
@dp.message(RegisterStates.waiting_for_email)
async def register_process_email(message: Message, state: FSMContext):
    """Обработка email при регистрации"""
    email = message.text.strip()

    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        await message.answer("❌ Неверный формат email. Попробуйте еще раз:")
        return

    await state.update_data(reg_email=email)
    await message.answer("Введите желаемый никнейм (минимум 3 символа):")
    await state.set_state(RegisterStates.waiting_for_username)


@dp.message(RegisterStates.waiting_for_username)
async def register_process_username(message: Message, state: FSMContext):
    """Обработка username при регистрации"""
    username = message.text.strip()

    if len(username) < 3:
        await message.answer("❌ Никнейм должен содержать минимум 3 символа. Попробуйте еще раз:")
        return

    await state.update_data(reg_username=username)
    await message.answer("Введите пароль (минимум 6 символов):")
    await state.set_state(RegisterStates.waiting_for_password)


@dp.message(RegisterStates.waiting_for_password)
async def register_process_password(message: Message, state: FSMContext):
    """Обработка пароля и завершение регистрации"""
    password = message.text.strip()

    if len(password) < 6:
        await message.answer("❌ Пароль должен содержать минимум 6 символов. Попробуйте еще раз:")
        return

    data = await state.get_data()
    email = data.get('reg_email')
    username = data.get('reg_username')

    result = await SiteAPI.register(email, username, password)

    if result['success']:
        # Автоматический вход после регистрации
        login_result = await SiteAPI.login(username, password)

        if login_result['success']:
            await db.save_session(message.from_user.id, login_result['user'])
            await message.answer(
                f"✅ Регистрация успешна!\n\n"
                f"Добро пожаловать, {username}!\n"
                f"💰 Баланс: {login_result['user']['balance']:.2f} ₽",
                reply_markup=get_main_keyboard('user')
            )
        else:
            await message.answer(
                "✅ Регистрация успешна! Теперь войдите в аккаунт.\n\n"
                "Используйте команду /start для входа."
            )
        await state.clear()
    else:
        await message.answer(
            f"❌ Ошибка регистрации: {result.get('message', 'Неизвестная ошибка')}\n\n"
            f"Попробуйте снова командой /start"
        )
        await state.clear()


# =========== ВХОД ===========
@dp.message(LoginStates.waiting_for_username)
async def login_process_username(message: Message, state: FSMContext):
    """Обработка username при входе"""
    username = message.text.strip()
    await state.update_data(login_username=username)
    await message.answer("Введите пароль:")
    await state.set_state(LoginStates.waiting_for_password)


@dp.message(LoginStates.waiting_for_password)
async def login_process_password(message: Message, state: FSMContext):
    """Обработка пароля и вход в систему"""
    password = message.text.strip()
    data = await state.get_data()
    username = data.get('login_username')

    result = await SiteAPI.login(username, password)

    if result['success']:
        await db.save_session(message.from_user.id, result['user'])
        await message.answer(
            f"✅ Вход выполнен!\n\n"
            f"Добро пожаловать, {result['user']['username']}!\n"
            f"💰 Баланс: {result['user']['balance']:.2f} ₽",
            reply_markup=get_main_keyboard(result['user']['role'])
        )
        await state.clear()
    else:
        await message.answer(
            f"❌ Ошибка входа: {result.get('message', 'Неверный логин или пароль')}\n\n"
            f"Попробуйте снова командой /start"
        )
        await state.clear()


# =========== ОСНОВНЫЕ ФУНКЦИИ ===========
@dp.message(F.text == "📊 Мой профиль")
async def show_profile(message: Message):
    """Показать профиль пользователя"""
    session = await db.get_session(message.from_user.id)

    if not session:
        await message.answer("❌ Вы не авторизованы. Используйте /start для входа.")
        return

    result = await SiteAPI.get_user_data(session['session_token'])

    if result['success']:
        profile_text = (
            f"📊 *Ваш профиль*\n\n"
            f"👤 *Никнейм:* {result.get('username', session['username'])}\n"
            f"📧 *Email:* {result.get('email', session['email'])}\n"
            f"💰 *Баланс:* {result.get('balance', session['balance']):.2f} ₽\n"
            f"👑 *Роль:* {'Администратор' if result.get('role') == 'admin' else 'Пользователь'}"
        )
        await db.update_balance(message.from_user.id, result.get('balance', session['balance']))
    else:
        profile_text = (
            f"📊 *Ваш профиль*\n\n"
            f"👤 *Никнейм:* {session['username']}\n"
            f"📧 *Email:* {session['email']}\n"
            f"💰 *Баланс:* {session['balance']:.2f} ₽\n"
            f"👑 *Роль:* {'Администратор' if session['role'] == 'admin' else 'Пользователь'}"
        )

    await message.answer(profile_text, parse_mode="Markdown")


@dp.message(F.text == "🔑 Моя подписка")
async def show_subscription(message: Message):
    """Показать информацию о подписке"""
    session = await db.get_session(message.from_user.id)

    if not session:
        await message.answer("❌ Вы не авторизованы. Используйте /start для входа.")
        return

    result = await SiteAPI.get_user_data(session['session_token'])

    if result['success'] and result.get('subscription'):
        sub = result['subscription']

        sub_text = (
            f"🔑 *Ваша подписка*\n\n"
            f"📡 *Тариф:* {sub.get('tariff_name', 'Неизвестно')}\n"
            f"🔐 *Ключ:* `{sub.get('vpn_key', 'Нет ключа')}`\n"
            f"⏰ *Действует до:* {sub.get('expires_at', 'Неизвестно')}\n"
        )

        if sub.get('vpn_key'):
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 Скопировать ключ", callback_data=f"copy_key_{sub['vpn_key']}")]
            ])
            await message.answer(sub_text, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await message.answer(sub_text, parse_mode="Markdown")
    else:
        await message.answer(
            "🔑 *Нет активной подписки*\n\n"
            "У вас нет активной VPN подписки. Приобретите тариф в разделе 🛒 Купить VPN",
            parse_mode="Markdown"
        )


@dp.callback_query(lambda c: c.data.startswith("copy_key_"))
async def copy_key(callback: CallbackQuery):
    """Скопировать VPN ключ"""
    key = callback.data.replace("copy_key_", "")
    await callback.answer(f"Ключ скопирован: {key}", show_alert=True)


@dp.message(F.text == "💳 Пополнить баланс")
async def topup_balance(message: Message, state: FSMContext):
    """Пополнение баланса - ПЕРЕРАБОТАННАЯ ВЕРСИЯ"""
    session = await db.get_session(message.from_user.id)

    if not session:
        await message.answer("❌ Вы не авторизованы. Используйте /start для входа.")
        return

    # Проверяем сессию на сервере
    validation = await SiteAPI.get_user_data(session['session_token'])
    if not validation['success']:
        await db.delete_session(message.from_user.id)
        await message.answer("❌ Сессия истекла. Используйте /start для входа.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="100 ₽", callback_data="topup_100"),
         InlineKeyboardButton(text="200 ₽", callback_data="topup_200")],
        [InlineKeyboardButton(text="500 ₽", callback_data="topup_500"),
         InlineKeyboardButton(text="1000 ₽", callback_data="topup_1000")],
        [InlineKeyboardButton(text="2000 ₽", callback_data="topup_2000"),
         InlineKeyboardButton(text="5000 ₽", callback_data="topup_5000")],
        [InlineKeyboardButton(text="Другая сумма", callback_data="topup_custom")]
    ])

    await message.answer(
        "💳 *Пополнение баланса*\n\n"
        "Выберите сумму пополнения (мин. 100 ₽):\n\n"
        "📝 *Реквизиты для перевода:*\n"
        "🏦 Сбербанк\n"
        "💳 СБП Сбербанк: `79038889093`\n"
        "👤 Получатель: Гаджикурбанов Курбан Ярметович\n\n"
        "После перевода нажмите кнопку с суммой, чтобы создать заявку.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    await state.set_state(TopupStates.waiting_for_amount)


@dp.callback_query(lambda c: c.data.startswith("topup_"))
async def process_topup_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора суммы пополнения"""
    session = await db.get_session(callback.from_user.id)

    if not session:
        await callback.answer("❌ Вы не авторизованы", show_alert=True)
        await callback.message.answer("Используйте /start для входа")
        return

    data = callback.data
    if data == "topup_custom":
        await callback.message.edit_text(
            "💳 Введите сумму пополнения (от 100 до 50000 ₽):",
            reply_markup=None
        )
        await state.set_state(TopupStates.waiting_for_amount)
    else:
        amount = int(data.split("_")[1])
        await create_payment_request(callback.message, amount, state, callback.from_user.id)

    await callback.answer()


@dp.message(TopupStates.waiting_for_amount)
async def process_custom_topup(message: Message, state: FSMContext):
    """Обработка пользовательской суммы пополнения"""
    session = await db.get_session(message.from_user.id)

    if not session:
        await message.answer("❌ Вы не авторизованы. Используйте /start для входа.")
        await state.clear()
        return

    try:
        amount = float(message.text.strip())
        if amount < 100:
            await message.answer("❌ Минимальная сумма пополнения 100 ₽. Попробуйте снова:")
            return
        if amount > 50000:
            await message.answer("❌ Максимальная сумма пополнения 50000 ₽. Попробуйте снова:")
            return
        await create_payment_request(message, amount, state, message.from_user.id)
    except ValueError:
        await message.answer("❌ Введите корректное число. Попробуйте снова:")


async def create_payment_request(message: Message, amount: float, state: FSMContext, telegram_id: int):
    """Создать заявку на пополнение - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    session = await db.get_session(telegram_id)

    if not session:
        await message.answer("❌ Вы не авторизованы. Используйте /start для входа.")
        await state.clear()
        return

    logger.info(f"Creating payment for user {session['username']} (ID: {session['id']}) with amount {amount}")
    logger.info(f"Session token: {session['session_token']}")

    # Создаем платеж через API
    result = await SiteAPI.create_payment(session['session_token'], amount)

    if result['success']:
        payment_id = result.get('payment_id')

        # Сохраняем заявку локально
        await db.save_pending_payment(telegram_id, amount, payment_id)

        await message.answer(
            f"✅ *Заявка на пополнение создана!*\n\n"
            f"💰 Сумма: {amount:.2f} ₽\n"
            f"🆔 Номер заявки: {payment_id}\n\n"
            f"⏳ Ожидайте подтверждения администратора.\n"
            f"Баланс пополнится автоматически после проверки.\n\n"
            f"💳 *Реквизиты для оплаты:*\n"
            f"СБП Сбербанк: `79038889093`\n"
            f"Получатель: Гаджикурбанов Курбан Ярметович\n\n"
            f"❗ После перевода отправьте администратору @Betkansky1 номер заявки: {payment_id}",
            parse_mode="Markdown"
        )
    else:
        error_msg = result.get('message', 'Не удалось создать заявку')
        logger.error(f"Payment creation failed: {error_msg}")
        await message.answer(f"❌ Ошибка: {error_msg}")

    await state.clear()


@dp.message(F.text == "🛒 Купить VPN")
async def buy_vpn(message: Message, state: FSMContext):
    """Купить VPN (начало процесса)"""
    session = await db.get_session(message.from_user.id)

    if not session:
        await message.answer("❌ Вы не авторизованы. Используйте /start для входа.")
        return

    # Проверяем сессию
    validation = await SiteAPI.get_user_data(session['session_token'])
    if not validation['success']:
        await db.delete_session(message.from_user.id)
        await message.answer("❌ Сессия истекла. Используйте /start для входа.")
        return

    result = await SiteAPI.get_tariffs()

    if result['success'] and result.get('tariffs'):
        # Фильтруем активные тарифы
        active_tariffs = [t for t in result['tariffs'] if t.get('is_active') == '1']

        if active_tariffs:
            used_trial_ids = await db.get_used_trial_ids(message.from_user.id)
            await state.update_data(buyer_telegram_id=message.from_user.id)
            await message.answer(
                "🛒 *Выберите тариф*\n\n"
                "Нажмите на интересующий вас тариф для продолжения:",
                parse_mode="Markdown",
                reply_markup=get_tariffs_keyboard(active_tariffs, used_trial_ids)
            )
            await state.set_state(BuyVPNStates.waiting_for_tariff)
        else:
            await message.answer("❌ Нет активных тарифов. Обратитесь к администратору.")
    else:
        await message.answer("❌ Не удалось загрузить список тарифов. Попробуйте позже.")

@dp.callback_query(BuyVPNStates.waiting_for_tariff, lambda c: c.data.startswith("trial_used_"))
async def trial_already_used(callback: CallbackQuery, state: FSMContext):
    await callback.answer(
        "🚫 Вы уже использовали пробный период этого тарифа.\n"
        "Пробный период доступен только один раз.",
        show_alert=True
    )
@dp.callback_query(BuyVPNStates.waiting_for_tariff, lambda c: c.data.startswith("tariff_"))
async def process_tariff_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора тарифа"""
    tariff_id = int(callback.data.split("_")[1])
    await state.update_data(selected_tariff_id=tariff_id)

    # Получаем полную информацию о тарифе
    result = await SiteAPI.get_tariffs()
    tariff = None
    for t in result.get('tariffs', []):
        if int(t['id']) == tariff_id:
            tariff = t
            break

    if tariff:
        # Проверка пробного тарифа
        if is_trial_tariff(tariff):
            data = await state.get_data()
            tg_id = data.get('buyer_telegram_id', callback.from_user.id)
            if await db.has_used_trial(tg_id, tariff_id):
                await callback.answer(
                    "🚫 Вы уже использовали пробный период этого тарифа!",
                    show_alert=True
                )
                return
        await state.update_data(selected_tariff_id=tariff_id, selected_tariff=tariff)

        description = tariff.get('description', 'Нет описания')
        if tariff.get('features'):
            try:
                features = json.loads(tariff['features']) if isinstance(tariff['features'], str) else tariff['features']
                description += "\n\n📌 *Особенности:*\n• " + "\n• ".join(features)
            except:
                pass

        await callback.message.edit_text(
            f"📡 *Тариф: {tariff['name']}*\n\n"
            f"{description}\n\n"
            "Выберите период подписки:",
            parse_mode="Markdown",
            reply_markup=get_periods_keyboard(tariff)
        )
        await state.set_state(BuyVPNStates.waiting_for_period)
    else:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        await callback.message.edit_text("❌ Тариф не найден. Попробуйте снова.")
        await state.clear()

    await callback.answer()


@dp.callback_query(BuyVPNStates.waiting_for_period, lambda c: c.data.startswith("period_"))
async def process_period_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора периода и генерация ключа"""
    raw_period = callback.data.split("_", 1)[1]  # "trial", "1_month", "3_months" и т.д.

    data = await state.get_data()
    tariff_id = data.get('selected_tariff_id')
    telegram_id = data.get('buyer_telegram_id', callback.from_user.id)

    session = await db.get_session(callback.from_user.id)
    if not session:
        await callback.answer("❌ Не авторизован", show_alert=True)
        await state.clear()
        return

    # Определяем period для API
    if raw_period == "trial":
        # Финальная проверка — вдруг успел нажать дважды
        if await db.has_used_trial(telegram_id, tariff_id):
            await callback.answer("🚫 Вы уже использовали пробный период!", show_alert=True)
            await state.clear()
            return
        api_period = "trial"
    else:
        period_map = {
            "1": "1_month", "3": "3_months", "6": "6_months", "12": "12_months",
            "1_month": "1_month", "3_months": "3_months",
            "6_months": "6_months", "12_months": "12_months",
        }
        api_period = period_map.get(raw_period, raw_period)

    result = await SiteAPI.generate_key(session['session_token'], tariff_id, api_period)

    if result['success']:
        # Если пробный — записываем использование
        if raw_period == "trial":
            await db.mark_trial_used(telegram_id, tariff_id)

        if 'balance' in result:
            await db.update_balance(callback.from_user.id, result['balance'])

        key = result.get('key', 'Нет ключа')
        tariff_name = result.get('tariff_name', 'Неизвестно')
        period_text = "Пробный период — 24 часа" if raw_period == "trial" else result.get('period', 'Неизвестно')
        price = result.get('price', 0)
        balance = result.get('balance', 0)
        expires_at = result.get('expires_at', 'Неизвестно')
        trial_note = "\n\n⚠️ <b>Пробный период использован. Повторно недоступен.</b>" if raw_period == "trial" else ""

        key_text = (
            f"✅ <b>VPN ключ успешно создан!</b>\n\n"
            f"📡 <b>Тариф:</b> {tariff_name}\n"
            f"📅 <b>Период:</b> {period_text}\n"
            f"💰 <b>Списано:</b> {price:.2f} ₽\n"
            f"💳 <b>Ваш баланс:</b> {balance:.2f} ₽\n\n"
            f"🔐 <b>Ваш ключ:</b>\n"
            f"<code>{key}</code>\n\n"
            f"⏰ <b>Действителен до:</b> {expires_at}"
            f"{trial_note}\n\n"
            f"⚠️ Сохраните ключ в надежном месте!"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Скопировать ключ", callback_data=f"copy_key_{key}")]
        ])
        await callback.message.edit_text(key_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        error_msg = result.get('message', 'Не удалось создать ключ')
        await callback.message.edit_text(
            f"❌ <b>Ошибка:</b> {error_msg}\n\n"
            f"Возможные причины:\n"
            f"• Недостаточно средств на балансе\n"
            f"• Пробный период уже был использован\n"
            f"• Технические проблемы",
            parse_mode="HTML"
        )

    await state.clear()
    await callback.answer()

@dp.message(F.text == "📜 История платежей")
async def show_payments(message: Message):
    """Показать историю платежей"""
    session = await db.get_session(message.from_user.id)

    if not session:
        await message.answer("❌ Вы не авторизованы. Используйте /start для входа.")
        return

    result = await SiteAPI.get_user_data(session['session_token'])

    if result['success'] and result.get('payments'):
        payments_text = "📜 *История платежей*\n\n"
        for payment in result['payments'][:10]:
            status_icon = "✅" if payment.get('status') == 'completed' else "⏳"
            amount = float(payment.get('amount', 0))
            date = payment.get('created_at', '')[:10]
            payments_text += f"{status_icon} {amount:.2f} ₽ - {date}\n"

        await message.answer(payments_text, parse_mode="Markdown")
    else:
        await message.answer("📜 У вас пока нет истории платежей.")


@dp.message(F.text == "📋 История подписок")
async def show_subscriptions_history(message: Message):
    """Показать историю подписок"""
    session = await db.get_session(message.from_user.id)

    if not session:
        await message.answer("❌ Вы не авторизованы. Используйте /start для входа.")
        return

    result = await SiteAPI.get_user_data(session['session_token'])

    if result['success'] and result.get('all_subscriptions'):
        subs_text = "📋 *История подписок*\n\n"
        for sub in result['all_subscriptions'][:10]:
            status_icon = "🟢" if sub.get('is_active') else "🔴"
            date = sub.get('created_at', '')[:10]
            price = float(sub.get('price', 0))
            subs_text += f"{status_icon} {sub.get('tariff_name', 'Неизвестно')} - {price:.2f} ₽ ({date})\n"

        await message.answer(subs_text, parse_mode="Markdown")
    else:
        await message.answer("📋 У вас пока нет истории подписок.")


@dp.message(F.text == "❓ Помощь")
async def show_help(message: Message):
    """Показать справку"""
    help_text = (
        "❓ *Помощь по боту*\n\n"
        "📌 *Доступные команды:*\n"
        "/start - Главное меню\n\n"
        "📌 *Как купить VPN:*\n"
        "1. Пополните баланс через раздел 💳 Пополнить баланс\n"
        "2. Перейдите в раздел 🛒 Купить VPN\n"
        "3. Выберите тариф и период\n"
        "4. Получите ваш VPN ключ\n\n"
        "📌 *Как использовать ключ:*\n"
        "Используйте полученный ключ в приложении HAPP или STRAISAND\n\n"
        "📌 *Связь с администратором:*\n"
        "Нажмите кнопку ниже для связи с администратором"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Связаться с администратором", callback_data="contact_support")]
    ])

    await message.answer(help_text, parse_mode="Markdown", reply_markup=keyboard)


# =========== АДМИНСКИЕ ХЭНДЛЕРЫ ===========
# =========== АДМИНСКИЕ ХЭНДЛЕРЫ (ПОЛНАЯ ВЕРСИЯ) ===========

@dp.message(F.text == "👑 Админ панель")
async def admin_panel(message: Message):
    """Админ панель"""
    session = await db.get_session(message.from_user.id)

    if not session or session['role'] != 'admin':
        await message.answer("❌ Доступ запрещен. У вас нет прав администратора.")
        return

    await message.answer(
        "👑 *Административная панель*\n\n"
        "Выберите действие:",
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard()
    )



@dp.message(F.text == "✅ Подтвердить платеж")
async def admin_confirm_payment(message: Message, state: FSMContext):
    """Подтверждение платежа (админ)"""
    session = await db.get_session(message.from_user.id)

    if not session or session['role'] != 'admin':
        await message.answer("❌ Доступ запрещен.")
        return

    # Получаем список ожидающих платежей через API
    result = await SiteAPI.admin_get_pending_payments(session['session_token'])

    if result['success'] and result.get('payments'):
        payments_text = "📋 *Ожидающие платежи:*\n\n"
        for payment in result['payments']:
            payments_text += (
                f"🆔 ID: {payment['id']} | "
                f"👤 {payment['username']} | "
                f"💰 {float(payment['amount']):.2f} ₽ | "
                f"📅 {payment['created_at'][:10]}\n"
            )
        await message.answer(payments_text, parse_mode="Markdown")
    else:
        await message.answer("📋 Нет ожидающих платежей.")

    await message.answer(
        "✅ *Подтверждение платежа*\n\n"
        "Введите ID заявки на пополнение:"
    )
    await state.set_state(AdminStates.waiting_for_payment_id)


@dp.message(AdminStates.waiting_for_payment_id)
async def process_payment_confirmation(message: Message, state: FSMContext):
    """Обработка подтверждения платежа с получением данных из БД"""
    try:
        payment_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите корректный ID заявки:")
        return

    session = await db.get_session(message.from_user.id)

    # Сначала получаем информацию о платеже из локальной БД
    payment_info = None
    async with aiosqlite.connect(db.db_path) as conn:
        async with conn.execute(
                "SELECT telegram_id, amount FROM pending_payments WHERE payment_id = ? OR id = ?",
                (payment_id, payment_id)
        ) as cursor:
            payment_info = await cursor.fetchone()

    # Подтверждаем платеж через API
    result = await SiteAPI.admin_complete_payment(session['session_token'], payment_id)

    if result['success']:
        # Если получили сумму из API или из локальной БД
        payment_amount = result.get('amount', payment_info[1] if payment_info else 0)
        user_id = result.get('user_id', 0)
        new_balance = result.get('new_balance', 0)

        # Находим telegram_id пользователя
        user_telegram_id = payment_info[0] if payment_info else None

        if not user_telegram_id and user_id:
            async with aiosqlite.connect(db.db_path) as conn:
                async with conn.execute(
                        "SELECT telegram_id, username FROM user_sessions WHERE user_id = ?",
                        (user_id,)
                ) as cursor:
                    user_data = await cursor.fetchone()
                    if user_data:
                        user_telegram_id = user_data[0]
                        username = user_data[1]

        # Отправляем уведомление пользователю
        if user_telegram_id:
            try:
                await bot.send_message(
                    user_telegram_id,
                    f"✅ *Пополнение баланса подтверждено!*\n\n"
                    f"💰 Сумма: {payment_amount:.2f} ₽\n"
                    f"💳 Ваш новый баланс: {new_balance:.2f} ₽\n\n"
                    f"Спасибо за пополнение! Можете приобрести VPN тариф в разделе 🛒 Купить VPN",
                    parse_mode="Markdown"
                )
                await message.answer(
                    f"✅ Платеж #{payment_id} подтвержден!\n"
                    f"💰 Сумма: {payment_amount:.2f} ₽\n"
                    f"📨 Уведомление отправлено пользователю"
                )

                # Удаляем из pending_payments
                await db.delete_pending_payment(payment_id)

            except Exception as e:
                await message.answer(
                    f"✅ Платеж #{payment_id} подтвержден!\n"
                    f"💰 Сумма: {payment_amount:.2f} ₽\n"
                    f"⚠️ Не удалось отправить уведомление: {e}"
                )
        else:
            await message.answer(
                f"✅ Платеж #{payment_id} подтвержден!\n"
                f"💰 Сумма: {payment_amount:.2f} ₽\n"
                f"⚠️ Не удалось найти пользователя для уведомления"
            )
    else:
        await message.answer(f"❌ {result.get('message', 'Ошибка подтверждения')}")

    await state.clear()


@dp.message(F.text == "💰 Изменить баланс")
async def admin_change_balance(message: Message, state: FSMContext):
    """Изменение баланса пользователя (админ)"""
    session = await db.get_session(message.from_user.id)

    if not session or session['role'] != 'admin':
        await message.answer("❌ Доступ запрещен.")
        return

    await message.answer(
        "💰 *Изменение баланса*\n\n"
        "Введите ID пользователя:"
    )
    await state.set_state(AdminStates.waiting_for_user_id)


@dp.message(AdminStates.waiting_for_user_id)
async def process_balance_user_id(message: Message, state: FSMContext):
    """Обработка ID пользователя для изменения баланса"""
    try:
        user_id = int(message.text.strip())
        await state.update_data(target_user_id=user_id)
        await message.answer(
            "Введите сумму для изменения баланса:\n"
            "• Положительное число - начисление\n"
            "• Отрицательное число - списание\n\n"
            "Пример: 100 или -50"
        )
        await state.set_state(AdminStates.waiting_for_balance_amount)
    except ValueError:
        await message.answer("❌ Введите корректный ID пользователя:")


@dp.message(AdminStates.waiting_for_balance_amount)
async def process_balance_amount(message: Message, state: FSMContext):
    """Обработка суммы для изменения баланса"""
    try:
        amount = float(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите корректную сумму:")
        return

    data = await state.get_data()
    user_id = data.get('target_user_id')
    session = await db.get_session(message.from_user.id)

    result = await SiteAPI.admin_update_balance(session['session_token'], user_id, amount)

    if result['success']:
        await message.answer(
            f"✅ {result.get('message', 'Баланс изменен')}\n💰 Новый баланс: {result.get('new_balance', 0):.2f} ₽")
    else:
        await message.answer(f"❌ {result.get('message', 'Ошибка изменения баланса')}")

    await state.clear()


@dp.message(F.text == "👤 Управление пользователями")
async def admin_manage_users(message: Message, state: FSMContext):
    """Управление пользователями (админ)"""
    session = await db.get_session(message.from_user.id)

    if not session or session['role'] != 'admin':
        await message.answer("❌ Доступ запрещен.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать пользователя", callback_data="admin_edit_user")],
        [InlineKeyboardButton(text="🗑 Удалить пользователя", callback_data="admin_delete_user")],
        [InlineKeyboardButton(text="📋 Список пользователей", callback_data="admin_list_users")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
    ])

    await message.answer(
        "👤 *Управление пользователями*\n\n"
        "Выберите действие:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


@dp.callback_query(lambda c: c.data == "admin_list_users")
async def admin_list_users_callback(callback: CallbackQuery):
    """Список пользователей (админ) - callback версия"""
    session = await db.get_session(callback.from_user.id)

    if not session or session['role'] != 'admin':
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return

    result = await SiteAPI.admin_get_users(session['session_token'])

    if result['success'] and result.get('users'):
        users_text = "👥 *Список пользователей:*\n\n"
        for user in result['users'][:20]:
            users_text += (
                f"🆔 `{user['id']}` | "
                f"👤 {user['username']} | "
                f"💰 {float(user['balance']):.2f} ₽\n"
            )

        if len(result['users']) > 20:
            users_text += f"\n... и еще {len(result['users']) - 20} пользователей"

        await callback.message.edit_text(users_text, parse_mode="Markdown")
    else:
        await callback.message.edit_text("❌ Не удалось загрузить список пользователей.")

    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_edit_user")
async def admin_edit_user_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования пользователя"""
    await callback.message.edit_text(
        "✏️ *Редактирование пользователя*\n\n"
        "Введите ID пользователя для редактирования:"
    )
    await state.set_state(AdminStates.waiting_for_user_id)
    await callback.answer()


@dp.message(AdminStates.waiting_for_user_id)
async def process_edit_user_id(message: Message, state: FSMContext):
    """Обработка ID пользователя для редактирования"""
    try:
        user_id = int(message.text.strip())
        await state.update_data(edit_user_id=user_id)

        # Получаем данные пользователя
        session = await db.get_session(message.from_user.id)
        result = await SiteAPI.admin_get_users(session['session_token'])

        user_data = None
        if result['success']:
            for user in result['users']:
                if user['id'] == user_id:
                    user_data = user
                    break

        if user_data:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Изменить никнейм", callback_data="edit_field_username")],
                [InlineKeyboardButton(text="✏️ Изменить email", callback_data="edit_field_email")],
                [InlineKeyboardButton(text="✏️ Изменить пароль", callback_data="edit_field_password")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_manage_users")]
            ])

            await message.answer(
                f"👤 *Пользователь ID: {user_id}*\n"
                f"📝 Никнейм: {user_data['username']}\n"
                f"📧 Email: {user_data['email']}\n"
                f"💰 Баланс: {float(user_data['balance']):.2f} ₽\n\n"
                "Выберите поле для редактирования:",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            await state.set_state(AdminStates.waiting_for_user_action)
        else:
            await message.answer("❌ Пользователь не найден")
            await state.clear()

    except ValueError:
        await message.answer("❌ Введите корректный ID пользователя:")


@dp.callback_query(lambda c: c.data.startswith("edit_field_"))
async def process_edit_field(callback: CallbackQuery, state: FSMContext):
    """Выбор поля для редактирования"""
    field = callback.data.replace("edit_field_", "")
    await state.update_data(edit_field=field)

    field_names = {
        'username': 'никнейм',
        'email': 'email',
        'password': 'пароль'
    }

    await callback.message.edit_text(
        f"Введите новый {field_names.get(field, field)}:"
    )

    if field == 'username':
        await state.set_state(AdminStates.waiting_for_new_username)
    elif field == 'email':
        await state.set_state(AdminStates.waiting_for_new_email)
    elif field == 'password':
        await state.set_state(AdminStates.waiting_for_new_password)

    await callback.answer()


@dp.message(AdminStates.waiting_for_new_username)
async def update_username(message: Message, state: FSMContext):
    """Обновление никнейма"""
    new_username = message.text.strip()

    if len(new_username) < 3:
        await message.answer("❌ Никнейм должен содержать минимум 3 символа. Попробуйте снова:")
        return

    data = await state.get_data()
    user_id = data.get('edit_user_id')
    session = await db.get_session(message.from_user.id)

    result = await SiteAPI.admin_update_user(session['session_token'], user_id, 'username', new_username)

    if result['success']:
        await message.answer(f"✅ Никнейм пользователя изменен на '{new_username}'")
    else:
        await message.answer(f"❌ {result.get('message', 'Ошибка изменения никнейма')}")

    await state.clear()
    await admin_manage_users(message, state)

    @dp.message(F.text == "📞 Поддержка")
    async def support_button(message: Message, state: FSMContext):
        """Кнопка связи с поддержкой"""
        print(f"DEBUG: support_button called by {message.from_user.id}")  # Отладка

        session = await db.get_session(message.from_user.id)

        if not session:
            await message.answer("❌ Вы не авторизованы. Используйте /start для входа.")
            return

        await message.answer(
            "📞 *Связь с администратором*\n\n"
            "Опишите вашу проблему или вопрос. Администратор ответит вам в ближайшее время.\n\n"
            "Для отмены отправьте /cancel",
            parse_mode="Markdown"
        )
        await state.set_state(SupportStates.waiting_for_message)

        @dp.message()
        async def debug_all_messages(message: Message):
            """Отладка - показывает все сообщения"""
            print(f"DEBUG: Получено сообщение: '{message.text}' от {message.from_user.id}")
            # Не отвечаем, чтобы не мешать другим обработчикам

        @dp.message(SupportStates.waiting_for_message)
        async def process_support_message(message: Message, state: FSMContext):
            """Обработка сообщения в поддержку"""
            if message.text == "/cancel":
                await state.clear()
                await message.answer("❌ Обращение отменено.")
                return

            session = await db.get_session(message.from_user.id)

            if not session:
                await message.answer("❌ Вы не авторизованы. Используйте /start для входа.")
                await state.clear()
                return

            # Сохраняем обращение в базу данных
            ticket_id = await db.save_ticket(
                message.from_user.id,
                session['username'],
                session['id'],
                message.text
            )

            # Отправляем подтверждение пользователю
            await message.answer(
                f"✅ *Обращение #{ticket_id} отправлено!*\n\n"
                f"Администратор свяжется с вами в ближайшее время.\n"
                f"Вы можете отслеживать статус обращения.\n\n"
                f"Для отмены используйте /cancel",
                parse_mode="Markdown"
            )

            # Уведомляем всех администраторов
            async with aiosqlite.connect(db.db_path) as conn:
                async with conn.execute(
                        "SELECT telegram_id, username FROM user_sessions WHERE role = 'admin'") as cursor:
                    admins = await cursor.fetchall()

                    for admin in admins:
                        try:
                            admin_id = admin[0]
                            admin_name = admin[1]

                            await bot.send_message(
                                admin_id,
                                f"🆕 *Новое обращение в поддержку!*\n\n"
                                f"🆔 ID: {ticket_id}\n"
                                f"👤 Пользователь: {session['username']}\n"
                                f"🆔 User ID: {session['id']}\n"
                                f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                                f"📝 Сообщение:\n"
                                f"<code>{message.text[:500]}</code>\n\n"
                                f"Для ответа перейдите в раздел 👑 Админ панель → 💬 Обращения в поддержку",
                                parse_mode="HTML"
                            )
                        except Exception as e:
                            logger.error(f"Failed to notify admin {admin_id}: {e}")

            await state.clear()


@dp.message(AdminStates.waiting_for_new_email)
async def update_email(message: Message, state: FSMContext):
    """Обновление email"""
    new_email = message.text.strip()

    import re
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', new_email):
        await message.answer("❌ Неверный формат email. Попробуйте снова:")
        return

    data = await state.get_data()
    user_id = data.get('edit_user_id')
    session = await db.get_session(message.from_user.id)

    result = await SiteAPI.admin_update_user(session['session_token'], user_id, 'email', new_email)

    if result['success']:
        await message.answer(f"✅ Email пользователя изменен на '{new_email}'")
    else:
        await message.answer(f"❌ {result.get('message', 'Ошибка изменения email')}")

    await state.clear()
    await admin_manage_users(message, state)


@dp.message(AdminStates.waiting_for_new_password)
async def update_password(message: Message, state: FSMContext):
    """Обновление пароля"""
    new_password = message.text.strip()

    if len(new_password) < 6:
        await message.answer("❌ Пароль должен содержать минимум 6 символов. Попробуйте снова:")
        return

    data = await state.get_data()
    user_id = data.get('edit_user_id')
    session = await db.get_session(message.from_user.id)

    result = await SiteAPI.admin_update_user(session['session_token'], user_id, 'password', new_password)

    if result['success']:
        await message.answer(f"✅ Пароль пользователя изменен")
    else:
        await message.answer(f"❌ {result.get('message', 'Ошибка изменения пароля')}")

    await state.clear()
    await admin_manage_users(message, state)


@dp.callback_query(lambda c: c.data == "admin_delete_user")
async def admin_delete_user_start(callback: CallbackQuery, state: FSMContext):
    """Начало удаления пользователя"""
    await callback.message.edit_text(
        "🗑 *Удаление пользователя*\n\n"
        "⚠️ ВНИМАНИЕ! Это действие необратимо.\n\n"
        "Введите ID пользователя для удаления:"
    )
    await state.set_state(AdminStates.waiting_for_delete_user_id)
    await callback.answer()


@dp.message(AdminStates.waiting_for_delete_user_id)
async def process_delete_user(message: Message, state: FSMContext):
    """Обработка удаления пользователя"""
    try:
        user_id = int(message.text.strip())

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_{user_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_manage_users")]
        ])

        await message.answer(
            f"⚠️ *Подтверждение удаления*\n\n"
            f"Вы действительно хотите удалить пользователя с ID: {user_id}?\n\n"
            f"Это действие нельзя отменить!",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    except ValueError:
        await message.answer("❌ Введите корректный ID пользователя:")


@dp.callback_query(lambda c: c.data.startswith("confirm_delete_"))
async def confirm_delete_user(callback: CallbackQuery, state: FSMContext):
    """Подтверждение удаления пользователя"""
    user_id = int(callback.data.replace("confirm_delete_", ""))
    session = await db.get_session(callback.from_user.id)

    result = await SiteAPI.admin_delete_user(session['session_token'], user_id)

    if result['success']:
        await callback.message.edit_text(f"✅ Пользователь с ID {user_id} удален")
    else:
        await callback.message.edit_text(f"❌ {result.get('message', 'Ошибка удаления пользователя')}")

    await callback.answer()
    await admin_manage_users(callback.message, state)


@dp.message(F.text == "📊 Управление тарифами")
async def admin_manage_tariffs(message: Message, state: FSMContext):
    """Управление тарифами (админ)"""
    session = await db.get_session(message.from_user.id)

    if not session or session['role'] != 'admin':
        await message.answer("❌ Доступ запрещен.")
        return

    result = await SiteAPI.get_tariffs()

    if result['success'] and result.get('tariffs'):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for tariff in result['tariffs']:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"📝 {tariff['name']} - {float(tariff['price_month']):.0f}₽/мес",
                    callback_data=f"tariff_edit_{tariff['id']}"
                )
            ])
        keyboard.inline_keyboard.append(
            [InlineKeyboardButton(text="➕ Создать новый тариф", callback_data="tariff_create")])
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])

        await message.answer(
            "📊 *Управление тарифами*\n\n"
            "Выберите тариф для редактирования или создайте новый:",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        await state.set_state(AdminStates.waiting_for_tariff_action)
    else:
        await message.answer("❌ Не удалось загрузить список тарифов.")


@dp.callback_query(lambda c: c.data == "tariff_create")
async def tariff_create(callback: CallbackQuery, state: FSMContext):
    """Создание нового тарифа"""
    await state.update_data(creating_tariff=True, tariff_step=1, tariff_data={})
    await callback.message.edit_text(
        "➕ *Создание нового тарифа*\n\n"
        "Шаг 1/4: Введите название тарифа:"
    )
    await state.set_state(AdminStates.waiting_for_tariff_data)
    await callback.answer()


@dp.message(AdminStates.waiting_for_tariff_data)
async def process_tariff_creation(message: Message, state: FSMContext):
    """Обработка создания тарифа"""
    data = await state.get_data()
    step = data.get('tariff_step', 1)
    tariff_data = data.get('tariff_data', {})

    if step == 1:
        tariff_data['name'] = message.text.strip()
        await state.update_data(tariff_data=tariff_data, tariff_step=2)
        await message.answer(
            "Шаг 2/4: Введите описание тарифа:"
        )

    elif step == 2:
        tariff_data['description'] = message.text.strip()
        await state.update_data(tariff_data=tariff_data, tariff_step=3)
        await message.answer(
            "Шаг 3/4: Введите цены в формате:\n"
            "месяц,3месяца,6месяцев,год\n\n"
            "Пример: 199,499,899,1599\n"
            "(для бесплатного тарифа введите 0,0,0,0)"
        )

    elif step == 3:
        try:
            prices = message.text.strip().split(',')
            if len(prices) != 4:
                await message.answer("❌ Введите 4 числа через запятую:")
                return

            tariff_data['price_month'] = float(prices[0].strip())
            tariff_data['price_3months'] = float(prices[1].strip())
            tariff_data['price_6months'] = float(prices[2].strip())
            tariff_data['price_year'] = float(prices[3].strip())
            await state.update_data(tariff_data=tariff_data, tariff_step=4)
            await message.answer(
                "Шаг 4/4: Введите особенности тарифа (каждая с новой строки):\n"
                "Пример:\n"
                "Скорость до 1 Гбит/с\n"
                "10 устройств\n"
                "Безлимитный трафик"
            )
        except ValueError:
            await message.answer("❌ Введите корректные числа:")

    elif step == 4:
        features = message.text.strip().split('\n')
        tariff_data['features'] = json.dumps(features)
        tariff_data['is_active'] = 1

        session = await db.get_session(message.from_user.id)
        result = await SiteAPI.admin_create_tariff(session['session_token'], tariff_data)

        if result['success']:
            await message.answer(f"✅ Тариф '{tariff_data['name']}' успешно создан!")
        else:
            await message.answer(f"❌ {result.get('message', 'Ошибка создания тарифа')}")

        await state.clear()
        await admin_manage_tariffs(message, state)


@dp.message(F.text == "📢 Рассылка")
async def admin_broadcast(message: Message, state: FSMContext):
    """Рассылка сообщений (админ)"""
    session = await db.get_session(message.from_user.id)

    if not session or session['role'] != 'admin':
        await message.answer("❌ Доступ запрещен.")
        return

    await message.answer(
        "📢 *Рассылка сообщений*\n\n"
        "Введите текст сообщения для рассылки всем пользователям:\n\n"
        "⚠️ ВНИМАНИЕ: Сообщение будет отправлено ВСЕМ пользователям бота!",
        parse_mode="Markdown"
    )
    await state.set_state(AdminStates.waiting_for_broadcast_message)


@dp.message(AdminStates.waiting_for_broadcast_message)
async def process_broadcast(message: Message, state: FSMContext):
    """Обработка рассылки"""
    broadcast_text = message.text.strip()

    await message.answer(
        f"📢 *Подтверждение рассылки*\n\n"
        f"Текст сообщения:\n"
        f"\"{broadcast_text[:200]}{'...' if len(broadcast_text) > 200 else ''}\"\n\n"
        f"Отправить всем пользователям?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отправить", callback_data="confirm_broadcast")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_broadcast")]
        ])
    )
    await state.update_data(broadcast_text=broadcast_text)


@dp.callback_query(lambda c: c.data == "confirm_broadcast")
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext):
    """Подтверждение рассылки"""
    data = await state.get_data()
    broadcast_text = data.get('broadcast_text')

    # Получаем всех пользователей из локальной БД
    async with aiosqlite.connect(db.db_path) as conn:
        async with conn.execute("SELECT telegram_id FROM user_sessions") as cursor:
            users = await cursor.fetchall()

    success_count = 0
    fail_count = 0

    await callback.message.edit_text("📢 Начинаю рассылку...")

    for user in users:
        try:
            await bot.send_message(user[0], f"📢 *АДМИНИСТРАТОР:*\n\n{broadcast_text}", parse_mode="Markdown")
            success_count += 1
            await asyncio.sleep(0.05)  # Небольшая задержка
        except:
            fail_count += 1

    await callback.message.edit_text(
        f"✅ *Рассылка завершена!*\n\n"
        f"📨 Отправлено: {success_count}\n"
        f"❌ Не доставлено: {fail_count}"
    )
    await state.clear()
    await callback.answer()


@dp.callback_query(lambda c: c.data == "cancel_broadcast")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    """Отмена рассылки"""
    await callback.message.edit_text("❌ Рассылка отменена")
    await state.clear()
    await callback.answer()


@dp.message(F.text == "💬 Обращения в поддержку")
async def admin_support_tickets(message: Message, state: FSMContext):
    """Обращения в поддержку (админ)"""
    session = await db.get_session(message.from_user.id)

    if not session or session['role'] != 'admin':
        await message.answer("❌ Доступ запрещен.")
        return

    open_tickets = await db.get_open_tickets()

    if open_tickets:
        tickets_text = "💬 *Открытые обращения:*\n\n"
        for ticket in open_tickets:
            tickets_text += (
                f"🆔 #{ticket[0]} | 👤 {ticket[2]} | "
                f"📅 {ticket[7][:16]}\n"
                f"📝 {ticket[4][:50]}...\n\n"
            )
        await message.answer(tickets_text, parse_mode="Markdown")

        await message.answer(
            "Введите ID обращения для ответа (или /skip для пропуска):"
        )
        await state.set_state(AdminStates.waiting_for_ticket_id)
    else:
        await message.answer("💬 Нет открытых обращений.")


@dp.message(AdminStates.waiting_for_ticket_id)
async def process_ticket_id(message: Message, state: FSMContext):
    """Обработка ID обращения"""
    if message.text == "/skip":
        await state.clear()
        await message.answer("Операция отменена")
        return

    try:
        ticket_id = int(message.text.strip())
        ticket = await db.get_ticket(ticket_id)

        if ticket:
            await state.update_data(current_ticket_id=ticket_id)
            await message.answer(
                f"💬 *Обращение #{ticket_id}*\n\n"
                f"👤 Пользователь: {ticket['username']}\n"
                f"🆔 ID: {ticket['user_id']}\n"
                f"📅 Дата: {ticket['created_at'][:16]}\n\n"
                f"📝 Сообщение:\n{ticket['message']}\n\n"
                f"Введите ваш ответ:"
            )
            await state.set_state(AdminStates.waiting_for_ticket_response)
        else:
            await message.answer("❌ Обращение не найдено. Введите корректный ID:")

    except ValueError:
        await message.answer("❌ Введите корректный ID обращения:")


@dp.message(AdminStates.waiting_for_ticket_response)
async def process_ticket_response(message: Message, state: FSMContext):
    """Обработка ответа на обращение (HTML версия)"""
    data = await state.get_data()
    ticket_id = data.get('current_ticket_id')
    response_text = message.text.strip()

    ticket = await db.get_ticket(ticket_id)

    if ticket:
        # Экранируем специальные символы для HTML
        import html
        safe_response = html.escape(response_text)

        # Отправляем ответ пользователю в HTML формате
        try:
            await bot.send_message(
                ticket['telegram_id'],
                f"<b>💬 Ответ от администратора</b>\n\nПо вашему обращению #{ticket_id}:\n\n{safe_response}\n\nЕсли вопрос решен, нажмите /close_ticket",
                parse_mode="HTML"
            )

            # Обновляем статус обращения
            await db.update_ticket_status(ticket_id, 'answered', response_text)

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Решено", callback_data=f"ticket_resolved_{ticket_id}")],
                [InlineKeyboardButton(text="❌ Закрыть", callback_data=f"ticket_close_{ticket_id}")]
            ])

            await message.answer(
                f"✅ Ответ отправлен пользователю!\n\nДождитесь подтверждения от пользователя или закройте обращение вручную.",
                reply_markup=keyboard
            )
        except Exception as e:
            await message.answer(f"❌ Ошибка при отправке: {str(e)}")

    await state.clear()

    @dp.message(Command("close_ticket"))
    async def close_ticket_command(message: Message, state: FSMContext):
        """Команда для закрытия обращения пользователем"""
        session = await db.get_session(message.from_user.id)

        if not session:
            await message.answer("❌ Вы не авторизованы.")
            return

        # Ищем открытое обращение пользователя
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                    "SELECT id FROM support_tickets WHERE telegram_id = ? AND status IN ('open', 'answered') ORDER BY id DESC LIMIT 1",
                    (message.from_user.id,)
            ) as cursor:
                ticket = await cursor.fetchone()

                if ticket:
                    ticket_id = ticket[0]
                    await conn.execute(
                        "UPDATE support_tickets SET status = 'closed' WHERE id = ?",
                        (ticket_id,)
                    )
                    await conn.commit()
                    await message.answer(f"✅ Обращение #{ticket_id} закрыто. Спасибо за обращение!")
                else:
                    await message.answer("❌ У вас нет открытых обращений.")

@dp.callback_query(lambda c: c.data.startswith("ticket_resolved_"))
async def ticket_resolved(callback: CallbackQuery):
    """Пользователь отметил обращение как решенное"""
    ticket_id = int(callback.data.replace("ticket_resolved_", ""))
    await db.update_ticket_status(ticket_id, 'resolved')
    await callback.message.edit_text("✅ Обращение отмечено как решенное. Спасибо!")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("ticket_close_"))
async def ticket_close(callback: CallbackQuery):
    """Закрытие обращения администратором"""
    ticket_id = int(callback.data.replace("ticket_close_", ""))
    await db.update_ticket_status(ticket_id, 'closed')
    await callback.message.edit_text("❌ Обращение закрыто администратором.")
    await callback.answer()


# =========== ПОЛЬЗОВАТЕЛЬСКАЯ ПОДДЕРЖКА ===========

@dp.message(F.text == "❓ Помощь")
async def show_help(message: Message):
    """Показать справку"""
    help_text = (
        "❓ *Помощь по боту*\n\n"
        "📌 *Доступные команды:*\n"
        "/start - Главное меню\n\n"
        "📌 *Как купить VPN:*\n"
        "1. Пополните баланс через раздел 💳 Пополнить баланс\n"
        "2. Перейдите в раздел 🛒 Купить VPN\n"
        "3. Выберите тариф и период\n"
        "4. Получите ваш VPN ключ\n\n"
        "📌 *Как использовать ключ:*\n"
        "Используйте полученный ключ в приложении WireGuard или OpenVPN\n\n"
        "📌 *Связь с администратором:*\n"
        "Отправьте /support ваше сообщение для связи с администратором"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Связаться с администратором", callback_data="contact_support")]
    ])

    await message.answer(help_text, parse_mode="Markdown", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data == "contact_support")
async def contact_support(callback: CallbackQuery, state: FSMContext):
    """Начало обращения в поддержку"""
    await callback.message.answer(
        "📞 *Связь с администратором*\n\n"
        "Опишите вашу проблему или вопрос. Администратор ответит вам в ближайшее время.\n\n"
        "Для отмены отправьте /cancel",
        parse_mode="Markdown"
    )
    await state.set_state("waiting_for_support_message")
    await callback.answer()


@dp.message(Command("support"))
async def support_command(message: Message, state: FSMContext):
    """Команда для обращения в поддержку"""
    print(f"✅ Support command from {message.from_user.id}")

    session = await db.get_session(message.from_user.id)

    if not session:
        await message.answer("❌ Вы не авторизованы. Используйте /start для входа.")
        return

    await message.answer(
        "📞 *Связь с администратором*\n\n"
        "Опишите вашу проблему или вопрос. Администратор ответит вам в ближайшее время.\n\n"
        "Для отмены отправьте /cancel",
        parse_mode="Markdown"
    )
    await state.set_state(SupportStates.waiting_for_message)


@dp.message(StateFilter("waiting_for_support_message"))
async def process_support_message(message: Message, state: FSMContext):
    """Обработка сообщения в поддержку"""
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Обращение отменено.")
        return

    session = await db.get_session(message.from_user.id)

    if not session:
        await message.answer("❌ Вы не авторизованы. Используйте /start для входа.")
        await state.clear()
        return

    # Сохраняем обращение
    ticket_id = await db.save_ticket(
        message.from_user.id,
        session['username'],
        session['id'],
        message.text
    )

    # Уведомляем администратора
    admin_session = await db.get_session_by_role('admin')

    await message.answer(
        f"✅ *Обращение #{ticket_id} отправлено!*\n\n"
        f"Администратор свяжется с вами в ближайшее время.\n"
        f"Вы можете отслеживать статус обращения по ID: {ticket_id}",
        parse_mode="Markdown"
    )

    # Отправляем уведомление админу (если есть активная сессия админа)
    async with aiosqlite.connect(db.db_path) as conn:
        async with conn.execute("SELECT telegram_id FROM user_sessions WHERE role = 'admin'") as cursor:
            admins = await cursor.fetchall()
            for admin in admins:
                try:
                    await bot.send_message(
                        admin[0],
                        f"🆕 *Новое обращение в поддержку!*\n\n"
                        f"🆔 ID: {ticket_id}\n"
                        f"👤 Пользователь: {session['username']}\n"
                        f"🆔 User ID: {session['id']}\n"
                        f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                        f"📝 Сообщение:\n{message.text[:200]}...\n\n"
                        f"Для ответа перейдите в раздел 💬 Обращения в поддержку",
                        parse_mode="Markdown"
                    )
                except:
                    pass

    await state.clear()


# Добавьте метод в Database для поиска админов
async def get_session_by_role(self, role: str) -> Optional[dict]:
    """Получить сессию админа"""
    async with aiosqlite.connect(self.db_path) as db:
        async with db.execute(
                "SELECT telegram_id, user_id, username, email, role, balance, session_token FROM user_sessions WHERE role = ? LIMIT 1",
                (role,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    'id': row[1],
                    'username': row[2],
                    'email': row[3],
                    'role': row[4],
                    'balance': row[5],
                    'session_token': row[6],
                    'telegram_id': row[0]
                }
    return None


# Добавьте метод в класс Database
Database.get_session_by_role = get_session_by_role


@dp.callback_query(lambda c: c.data == "admin_back")
async def admin_back_callback(callback: CallbackQuery):
    """Возврат в админ панель"""
    await admin_panel(callback.message)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_manage_users")
async def admin_manage_users_callback(callback: CallbackQuery, state: FSMContext):
    """Возврат к управлению пользователями"""
    await admin_manage_users(callback.message, state)
    await callback.answer()


@dp.message(F.text == "📋 Просмотр платежей")
async def admin_view_payments(message: Message):
    """Просмотр всех платежей (админ) - простая версия"""
    session = await db.get_session(message.from_user.id)

    if not session or session['role'] != 'admin':
        await message.answer("❌ Доступ запрещен.")
        return

    # Получаем платежи из локальной базы
    async with aiosqlite.connect(db.db_path) as conn:
        async with conn.execute(
                "SELECT id, telegram_id, amount, created_at FROM pending_payments ORDER BY id DESC LIMIT 20") as cursor:
            payments = await cursor.fetchall()

            if payments:
                payments_text = "📋 *Последние заявки на пополнение:*\n\n"
                for payment in payments:
                    payments_text += f"🆔 ID: {payment[0]} | 👤 TG: {payment[1]} | 💰 {payment[2]:.2f} ₽ | 📅 {payment[3][:10]}\n"
                await message.answer(payments_text, parse_mode="Markdown")
            else:
                await message.answer("📋 Нет заявок на пополнение.")


@dp.message(AdminStates.waiting_for_payment_id)
async def process_payment_confirmation(message: Message, state: FSMContext):
    """Обработка подтверждения платежа с уведомлением пользователя"""
    try:
        payment_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите корректный ID заявки:")
        return

    session = await db.get_session(message.from_user.id)
    result = await SiteAPI.admin_complete_payment(session['session_token'], payment_id)

    if result['success']:
        # Получаем информацию о платеже
        payment_amount = result.get('amount', 0)
        user_id = result.get('user_id', 0)
        new_balance = result.get('new_balance', 0)

        # Находим telegram_id пользователя по user_id
        user_telegram_id = None
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                    "SELECT telegram_id, username FROM user_sessions WHERE user_id = ?",
                    (user_id,)
            ) as cursor:
                user_data = await cursor.fetchone()
                if user_data:
                    user_telegram_id = user_data[0]
                    username = user_data[1]

        # Отправляем уведомление пользователю
        if user_telegram_id:
            try:
                await bot.send_message(
                    user_telegram_id,
                    f"✅ *Пополнение баланса подтверждено!*\n\n"
                    f"💰 Сумма: {payment_amount:.2f} ₽\n"
                    f"💳 Ваш новый баланс: {new_balance:.2f} ₽\n\n"
                    f"Спасибо за пополнение! Можете приобрести VPN тариф в разделе 🛒 Купить VPN",
                    parse_mode="Markdown"
                )
                await message.answer(
                    f"✅ Платеж подтвержден!\n"
                    f"💰 Сумма: {payment_amount:.2f} ₽\n"
                    f"👤 Пользователь: {username}\n"
                    f"📨 Уведомление отправлено пользователю"
                )
            except Exception as e:
                await message.answer(
                    f"✅ Платеж подтвержден!\n"
                    f"💰 Сумма: {payment_amount:.2f} ₽\n"
                    f"👤 Пользователь: {username}\n"
                    f"⚠️ Не удалось отправить уведомление пользователю: {e}"
                )
        else:
            await message.answer(
                f"✅ Платеж подтвержден!\n"
                f"💰 Сумма: {payment_amount:.2f} ₽\n"
                f"⚠️ Пользователь не найден в базе сессий"
            )
    else:
        await message.answer(f"❌ {result.get('message', 'Ошибка подтверждения')}")

    await state.clear()


@dp.message(F.text == "💰 Изменить баланс")
async def admin_change_balance(message: Message, state: FSMContext):
    """Изменение баланса пользователя (админ)"""
    session = await db.get_session(message.from_user.id)

    if not session or session['role'] != 'admin':
        await message.answer("❌ Доступ запрещен.")
        return

    await message.answer(
        "💰 *Изменение баланса*\n\n"
        "Введите ID пользователя:"
    )
    await state.set_state(AdminStates.waiting_for_user_id)


@dp.message(AdminStates.waiting_for_user_id)
async def process_balance_user_id(message: Message, state: FSMContext):
    """Обработка ID пользователя для изменения баланса"""
    try:
        user_id = int(message.text.strip())
        await state.update_data(target_user_id=user_id)
        await message.answer(
            "Введите сумму для изменения баланса:\n"
            "• Положительное число - начисление\n"
            "• Отрицательное число - списание\n\n"
            "Пример: 100 или -50"
        )
        await state.set_state(AdminStates.waiting_for_balance_amount)
    except ValueError:
        await message.answer("❌ Введите корректный ID пользователя:")


@dp.message(AdminStates.waiting_for_balance_amount)
async def process_balance_amount(message: Message, state: FSMContext):
    """Обработка суммы для изменения баланса"""
    try:
        amount = float(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите корректную сумму:")
        return

    data = await state.get_data()
    user_id = data.get('target_user_id')
    session = await db.get_session(message.from_user.id)

    result = await SiteAPI.admin_update_balance(session['session_token'], user_id, amount)

    if result['success']:
        await message.answer(
            f"✅ {result.get('message', 'Баланс изменен')}\n💰 Новый баланс: {result.get('new_balance', 0):.2f} ₽")
    else:
        await message.answer(f"❌ {result.get('message', 'Ошибка изменения баланса')}")

    await state.clear()


@dp.message(F.text == "👤 Редактировать пользователя")
async def admin_edit_user(message: Message, state: FSMContext):
    """Редактирование пользователя (админ)"""
    session = await db.get_session(message.from_user.id)

    if not session or session['role'] != 'admin':
        await message.answer("❌ Доступ запрещен.")
        return

    await message.answer(
        "👤 *Редактирование пользователя*\n\n"
        "Введите ID пользователя для редактирования:"
    )
    await state.set_state(AdminStates.waiting_for_user_id)


@dp.message(AdminStates.waiting_for_user_id)
async def process_edit_user_id(message: Message, state: FSMContext):
    """Обработка ID пользователя для редактирования"""
    try:
        user_id = int(message.text.strip())
        await state.update_data(edit_user_id=user_id)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить никнейм", callback_data="edit_username")],
            [InlineKeyboardButton(text="✏️ Изменить email", callback_data="edit_email")],
            [InlineKeyboardButton(text="✏️ Изменить пароль", callback_data="edit_password")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
        ])

        await message.answer(
            f"👤 *Редактирование пользователя ID: {user_id}*\n\n"
            "Выберите, что хотите изменить:",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        await state.set_state(AdminStates.waiting_for_user_edit_action)
    except ValueError:
        await message.answer("❌ Введите корректный ID пользователя:")


@dp.callback_query(AdminStates.waiting_for_user_action, lambda c: c.data.startswith("edit_"))
async def process_edit_action(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора действия для редактирования"""
    action = callback.data.replace("edit_", "")
    await state.update_data(edit_action=action)

    if action == "username":
        await callback.message.edit_text(
            "Введите новый никнейм (минимум 3 символа):"
        )
        await state.set_state(AdminStates.waiting_for_new_username)
    elif action == "email":
        await callback.message.edit_text(
            "Введите новый email:"
        )
        await state.set_state(AdminStates.waiting_for_new_email)
    elif action == "password":
        await callback.message.edit_text(
            "Введите новый пароль (минимум 6 символов):"
        )
        await state.set_state(AdminStates.waiting_for_new_password)

    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("edit_field_"))
async def process_edit_field_callback(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора поля для редактирования (callback версия)"""
    field = callback.data.replace("edit_field_", "")
    await state.update_data(edit_field=field)

    field_names = {
        'username': 'никнейм',
        'email': 'email',
        'password': 'пароль'
    }

    await callback.message.edit_text(
        f"Введите новый {field_names.get(field, field)}:"
    )

    if field == 'username':
        await state.set_state(AdminStates.waiting_for_new_username)
    elif field == 'email':
        await state.set_state(AdminStates.waiting_for_new_email)
    elif field == 'password':
        await state.set_state(AdminStates.waiting_for_new_password)

    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_manage_users")
async def admin_manage_users_callback(callback: CallbackQuery):
    """Возврат к управлению пользователями"""
    session = await db.get_session(callback.from_user.id)

    if not session or session['role'] != 'admin':
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать пользователя", callback_data="admin_edit_user")],
        [InlineKeyboardButton(text="🗑 Удалить пользователя", callback_data="admin_delete_user")],
        [InlineKeyboardButton(text="📋 Список пользователей", callback_data="admin_list_users")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
    ])

    await callback.message.edit_text(
        "👤 *Управление пользователями*\n\n"
        "Выберите действие:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.message(AdminStates.waiting_for_new_username)
async def process_new_username(message: Message, state: FSMContext):
    """Установка нового никнейма"""
    new_username = message.text.strip()

    if len(new_username) < 3:
        await message.answer("❌ Никнейм должен содержать минимум 3 символа. Попробуйте снова:")
        return

    data = await state.get_data()
    user_id = data.get('edit_user_id')
    session = await db.get_session(message.from_user.id)

    result = await SiteAPI.admin_update_user(session['session_token'], user_id, 'username', new_username)

    if result['success']:
        await message.answer(f"✅ Никнейм пользователя изменен на '{new_username}'")
    else:
        await message.answer(f"❌ {result.get('message', 'Ошибка изменения никнейма')}")

    await state.clear()


@dp.message(AdminStates.waiting_for_new_email)
async def process_new_email(message: Message, state: FSMContext):
    """Установка нового email"""
    new_email = message.text.strip()

    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', new_email):
        await message.answer("❌ Неверный формат email. Попробуйте снова:")
        return

    data = await state.get_data()
    user_id = data.get('edit_user_id')
    session = await db.get_session(message.from_user.id)

    result = await SiteAPI.admin_update_user(session['session_token'], user_id, 'email', new_email)

    if result['success']:
        await message.answer(f"✅ Email пользователя изменен на '{new_email}'")
    else:
        await message.answer(f"❌ {result.get('message', 'Ошибка изменения email')}")

    await state.clear()


@dp.message(AdminStates.waiting_for_new_password)
async def process_new_password(message: Message, state: FSMContext):
    """Установка нового пароля"""
    new_password = message.text.strip()

    if len(new_password) < 6:
        await message.answer("❌ Пароль должен содержать минимум 6 символов. Попробуйте снова:")
        return

    data = await state.get_data()
    user_id = data.get('edit_user_id')
    session = await db.get_session(message.from_user.id)

    result = await SiteAPI.admin_update_user(session['session_token'], user_id, 'password', new_password)

    if result['success']:
        await message.answer(f"✅ Пароль пользователя изменен")
    else:
        await message.answer(f"❌ {result.get('message', 'Ошибка изменения пароля')}")

    await state.clear()


@dp.message(F.text == "📊 Управление тарифами")
async def admin_manage_tariffs(message: Message, state: FSMContext):
    """Управление тарифами (админ)"""
    session = await db.get_session(message.from_user.id)

    if not session or session['role'] != 'admin':
        await message.answer("❌ Доступ запрещен.")
        return

    result = await SiteAPI.get_tariffs()

    if result['success'] and result.get('tariffs'):
        await message.answer(
            "📊 *Управление тарифами*\n\n"
            "Выберите тариф для редактирования или создайте новый:",
            parse_mode="Markdown",
            reply_markup=get_admin_tariffs_keyboard(result['tariffs'])
        )
        await state.set_state(AdminStates.waiting_for_tariff_action)
    else:
        await message.answer("❌ Не удалось загрузить список тарифов.")


@dp.callback_query(AdminStates.waiting_for_tariff_action, lambda c: c.data.startswith("edit_tariff_"))
async def process_edit_tariff(callback: CallbackQuery, state: FSMContext):
    """Редактирование тарифа"""
    tariff_id = int(callback.data.split("_")[2])
    await state.update_data(editing_tariff_id=tariff_id)

    # Получаем данные тарифа
    result = await SiteAPI.get_tariffs()
    tariff = None
    for t in result.get('tariffs', []):
        if int(t['id']) == tariff_id:
            tariff = t
            break

    if tariff:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Название", callback_data="tariff_field_name")],
            [InlineKeyboardButton(text="✏️ Описание", callback_data="tariff_field_description")],
            [InlineKeyboardButton(text="💰 Цены", callback_data="tariff_field_prices")],
            [InlineKeyboardButton(text="✨ Особенности", callback_data="tariff_field_features")],
            [InlineKeyboardButton(text="🔘 Активность", callback_data="tariff_field_active")],
            [InlineKeyboardButton(text="❌ Удалить тариф", callback_data="tariff_delete")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="tariff_back")]
        ])

        await callback.message.edit_text(
            f"📡 *Редактирование тарифа: {tariff['name']}*\n\n"
            f"ID: {tariff['id']}\n"
            f"Название: {tariff.get('name', '-')}\n"
            f"Описание: {tariff.get('description', '-')[:50]}...\n"
            f"Цены: месяц={tariff.get('price_month', 0)}₽, 3мес={tariff.get('price_3months', 0)}₽, 6мес={tariff.get('price_6months', 0)}₽, год={tariff.get('price_year', 0)}₽\n"
            f"Активен: {'Да' if tariff.get('is_active') == '1' else 'Нет'}\n\n"
            "Выберите поле для редактирования:",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    else:
        await callback.answer("Тариф не найден", show_alert=True)


@dp.callback_query(lambda c: c.data == "create_tariff")
async def process_create_tariff(callback: CallbackQuery, state: FSMContext):
    """Создание нового тарифа"""
    await state.update_data(creating_tariff=True)
    await callback.message.edit_text(
        "➕ *Создание нового тарифа*\n\n"
        "Введите название тарифа:"
    )
    await state.set_state(AdminStates.waiting_for_tariff_data)


@dp.message(AdminStates.waiting_for_tariff_data)
async def process_tariff_creation(message: Message, state: FSMContext):
    """Сбор данных для создания тарифа"""
    data = await state.get_data()

    if not data.get('tariff_data'):
        # Первый шаг - название
        await state.update_data(tariff_data={'name': message.text.strip()})
        await message.answer("Введите описание тарифа:")
    elif len(data.get('tariff_data', {})) == 1:
        # Второй шаг - описание
        tariff_data = data.get('tariff_data', {})
        tariff_data['description'] = message.text.strip()
        await state.update_data(tariff_data=tariff_data)
        await message.answer(
            "Введите цены в формате:\n"
            "месяц,3месяца,6месяцев,год\n\n"
            "Пример: 100,250,450,800\n"
            "(для бесплатного тарифа введите 0)"
        )
    elif len(data.get('tariff_data', {})) == 2:
        # Третий шаг - цены
        try:
            prices = message.text.strip().split(',')
            if len(prices) != 4:
                await message.answer("❌ Введите 4 числа через запятую (месяц,3мес,6мес,год):")
                return

            tariff_data = data.get('tariff_data', {})
            tariff_data['price_month'] = float(prices[0].strip())
            tariff_data['price_3months'] = float(prices[1].strip())
            tariff_data['price_6months'] = float(prices[2].strip())
            tariff_data['price_year'] = float(prices[3].strip())
            await state.update_data(tariff_data=tariff_data)
            await message.answer(
                "Введите особенности тарифа (каждая особенность с новой строки):\n"
                "Пример:\n"
                "Скорость до 1 Гбит/с\n"
                "10 устройств\n"
                "Безлимитный трафик"
            )
        except ValueError:
            await message.answer("❌ Введите корректные числа:")
    elif len(data.get('tariff_data', {})) == 3:
        # Четвертый шаг - особенности
        features = message.text.strip().split('\n')
        tariff_data = data.get('tariff_data', {})
        tariff_data['features'] = json.dumps(features)
        tariff_data['is_active'] = '1'

        session = await db.get_session(message.from_user.id)
        result = await SiteAPI.admin_create_tariff(session['session_token'], tariff_data)

        if result['success']:
            await message.answer(f"✅ Тариф '{tariff_data['name']}' успешно создан!")
        else:
            await message.answer(f"❌ {result.get('message', 'Ошибка создания тарифа')}")

        await state.clear()


@dp.callback_query(lambda c: c.data == "tariff_back")
async def tariff_back(callback: CallbackQuery, state: FSMContext):
    """Возврат к списку тарифов"""
    await admin_manage_tariffs(callback.message, state)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_back")
async def admin_back_callback(callback: CallbackQuery, state: FSMContext):
    """Возврат в админ панель"""
    await admin_panel(callback.message)
    await callback.answer()


@dp.message(F.text == "👥 Список пользователей")
async def admin_list_users(message: Message):
    """Список пользователей (админ)"""
    session = await db.get_session(message.from_user.id)

    if not session or session['role'] != 'admin':
        await message.answer("❌ Доступ запрещен.")
        return

    result = await SiteAPI.admin_get_users(session['session_token'])

    if result['success'] and result.get('users'):
        users_text = "👥 *Список пользователей:*\n\n"
        for user in result['users'][:20]:
            users_text += (
                f"🆔 {user.get('id')} | "
                f"👤 {user.get('username')} | "
                f"💰 {float(user.get('balance', 0)):.2f} ₽\n"
            )

        if len(result['users']) > 20:
            users_text += f"\n... и еще {len(result['users']) - 20} пользователей"

        await message.answer(users_text, parse_mode="Markdown")
    else:
        # Показываем пользователей из локальной базы
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute("SELECT user_id, username, balance FROM user_sessions") as cursor:
                local_users = await cursor.fetchall()
                if local_users:
                    users_text = "👥 *Пользователи (из кэша):*\n\n"
                    for user in local_users[:20]:
                        users_text += f"🆔 {user[0]} | 👤 {user[1]} | 💰 {user[2]:.2f} ₽\n"
                    await message.answer(users_text, parse_mode="Markdown")
                else:
                    await message.answer("❌ Не удалось загрузить список пользователей.")


@dp.message(F.text == "📈 Статистика")
async def admin_stats(message: Message):
    """Статистика (админ)"""
    session = await db.get_session(message.from_user.id)

    if not session or session['role'] != 'admin':
        await message.answer("❌ Доступ запрещен.")
        return

    result = await SiteAPI.admin_get_stats(session['session_token'])

    if result['success']:
        stats = result.get('stats', {})
        stats_text = (
            f"📊 *Статистика системы*\n\n"
            f"👥 Всего пользователей: {stats.get('total_users', 'Н/Д')}\n"
            f"🔑 Активных подписок: {stats.get('active_subscriptions', 'Н/Д')}\n"
            f"💰 Общая сумма платежей: {stats.get('total_payments', 0):.2f} ₽\n"
            f"⏳ Ожидающих платежей: {stats.get('pending_payments', 0)}"
        )
        await message.answer(stats_text, parse_mode="Markdown")
    else:
        await message.answer(
            "📊 *Статистика*\n\n"
            "Функция статистики временно недоступна.\n"
            "Проверьте настройки API на сервере.",
            parse_mode="Markdown"
        )


@dp.message(F.text == "◀️ Назад")
async def admin_back(message: Message):
    """Возврат в главное меню"""
    session = await db.get_session(message.from_user.id)

    if session:
        await message.answer(
            "Возврат в главное меню",
            reply_markup=get_main_keyboard(session['role'])
        )
    else:
        await cmd_start(message, None)


@dp.callback_query(lambda c: c.data.startswith("tariff_field_"))
async def process_tariff_field_edit(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора поля для редактирования тарифа"""
    field = callback.data.replace("tariff_field_", "")
    await state.update_data(editing_tariff_field=field)

    field_names = {
        'name': 'название',
        'description': 'описание',
        'prices': 'цены',
        'features': 'особенности',
        'active': 'активность'
    }

    await callback.message.edit_text(
        f"Введите новое значение для поля '{field_names.get(field, field)}':"
    )
    await state.set_state(AdminStates.waiting_for_tariff_data)


@dp.callback_query(lambda c: c.data == "tariff_delete")
async def process_tariff_delete(callback: CallbackQuery, state: FSMContext):
    """Удаление тарифа"""
    data = await state.get_data()
    tariff_id = data.get('editing_tariff_id')

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data="confirm_delete"),
         InlineKeyboardButton(text="❌ Нет, отмена", callback_data="tariff_back")]
    ])

    await callback.message.edit_text(
        f"⚠️ *Внимание!*\n\nВы действительно хотите удалить тариф ID: {tariff_id}?\n\nЭто действие нельзя отменить.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


@dp.callback_query(lambda c: c.data == "confirm_delete")
async def process_confirm_delete(callback: CallbackQuery, state: FSMContext):
    """Подтверждение удаления тарифа"""
    data = await state.get_data()
    tariff_id = data.get('editing_tariff_id')
    session = await db.get_session(callback.from_user.id)

    result = await SiteAPI.admin_delete_tariff(session['session_token'], tariff_id)

    if result['success']:
        await callback.message.edit_text("✅ Тариф успешно удален!")
        await admin_manage_tariffs(callback.message, state)
    else:
        await callback.message.edit_text(f"❌ {result.get('message', 'Ошибка удаления тарифа')}")

    await callback.answer()


@dp.callback_query(lambda c: c.data == "tariff_field_active")
async def process_tariff_active_toggle(callback: CallbackQuery, state: FSMContext):
    """Переключение активности тарифа"""
    data = await state.get_data()
    tariff_id = data.get('editing_tariff_id')

    # Получаем текущий тариф
    result = await SiteAPI.get_tariffs()
    tariff = None
    for t in result.get('tariffs', []):
        if int(t['id']) == tariff_id:
            tariff = t
            break

    if tariff:
        new_status = '0' if tariff.get('is_active') == '1' else '1'
        tariff_data = {'is_active': new_status}

        session = await db.get_session(callback.from_user.id)
        update_result = await SiteAPI.admin_update_tariff(session['session_token'], tariff_id, tariff_data)

        if update_result['success']:
            await callback.answer(f"Тариф {'активирован' if new_status == '1' else 'деактивирован'}", show_alert=True)
            await process_edit_tariff(callback, state)
        else:
            await callback.answer("Ошибка изменения статуса", show_alert=True)
    else:
        await callback.answer("Тариф не найден", show_alert=True)


@dp.message(AdminStates.waiting_for_tariff_data)
async def process_tariff_data_input(message: Message, state: FSMContext):
    """Обработка ввода данных при создании/редактировании тарифа"""
    data = await state.get_data()

    # Проверяем, это создание или редактирование
    if data.get('creating_tariff'):
        # Логика создания тарифа (как в основном коде)
        if not data.get('tariff_data'):
            # Первый шаг - название
            await state.update_data(tariff_data={'name': message.text.strip()})
            await message.answer("Введите описание тарифа:")
        elif len(data.get('tariff_data', {})) == 1:
            # Второй шаг - описание
            tariff_data = data.get('tariff_data', {})
            tariff_data['description'] = message.text.strip()
            await state.update_data(tariff_data=tariff_data)
            await message.answer(
                "Введите цены в формате:\n"
                "месяц,3месяца,6месяцев,год\n\n"
                "Пример: 100,250,450,800\n"
                "(для бесплатного тарифа введите 0)"
            )
        elif len(data.get('tariff_data', {})) == 2:
            # Третий шаг - цены
            try:
                prices = message.text.strip().split(',')
                if len(prices) != 4:
                    await message.answer("❌ Введите 4 числа через запятую (месяц,3мес,6мес,год):")
                    return

                tariff_data = data.get('tariff_data', {})
                tariff_data['price_month'] = float(prices[0].strip())
                tariff_data['price_3months'] = float(prices[1].strip())
                tariff_data['price_6months'] = float(prices[2].strip())
                tariff_data['price_year'] = float(prices[3].strip())
                await state.update_data(tariff_data=tariff_data)
                await message.answer(
                    "Введите особенности тарифа (каждая особенность с новой строки):\n"
                    "Пример:\n"
                    "Скорость до 1 Гбит/с\n"
                    "10 устройств\n"
                    "Безлимитный трафик"
                )
            except ValueError:
                await message.answer("❌ Введите корректные числа:")
        elif len(data.get('tariff_data', {})) == 3:
            # Четвертый шаг - особенности
            features = message.text.strip().split('\n')
            tariff_data = data.get('tariff_data', {})
            tariff_data['features'] = json.dumps(features)
            tariff_data['is_active'] = '1'

            session = await db.get_session(message.from_user.id)
            result = await SiteAPI.admin_create_tariff(session['session_token'], tariff_data)

            if result['success']:
                await message.answer(f"✅ Тариф '{tariff_data['name']}' успешно создан!")
            else:
                await message.answer(f"❌ {result.get('message', 'Ошибка создания тарифа')}")

            await state.clear()

    elif data.get('editing_tariff_id'):
        # Редактирование тарифа
        field = data.get('editing_tariff_field')
        tariff_id = data.get('editing_tariff_id')
        new_value = message.text.strip()

        tariff_updates = {}

        if field == 'name':
            tariff_updates['name'] = new_value
        elif field == 'description':
            tariff_updates['description'] = new_value
        elif field == 'prices':
            try:
                prices = new_value.split(',')
                if len(prices) != 4:
                    await message.answer("❌ Введите 4 числа через запятую (месяц,3мес,6мес,год):")
                    return
                tariff_updates['price_month'] = float(prices[0].strip())
                tariff_updates['price_3months'] = float(prices[1].strip())
                tariff_updates['price_6months'] = float(prices[2].strip())
                tariff_updates['price_year'] = float(prices[3].strip())
            except ValueError:
                await message.answer("❌ Введите корректные числа:")
                return
        elif field == 'features':
            features = new_value.split('\n')
            tariff_updates['features'] = json.dumps(features)

        session = await db.get_session(message.from_user.id)
        result = await SiteAPI.admin_update_tariff(session['session_token'], tariff_id, tariff_updates)

        if result['success']:
            await message.answer("✅ Тариф успешно обновлен!")
            # Возвращаемся к редактированию тарифа
            await process_edit_tariff(message, state)
        else:
            await message.answer(f"❌ {result.get('message', 'Ошибка обновления тарифа')}")

        await state.clear()

        # поддержка
        # =========== ПОДДЕРЖКА ПОЛЬЗОВАТЕЛЕЙ (ПОЛНАЯ ВЕРСИЯ) ===========

        class SupportStates(StatesGroup):
            waiting_for_message = State()

        @dp.message(F.text.in_(["📞 Связаться с поддержкой", "📞 Поддержка", "Поддержка"]))
        async def support_button(message: Message, state: FSMContext):
            """Кнопка связи с поддержкой"""
            print(f"✅ Support button pressed by {message.from_user.id}")

            session = await db.get_session(message.from_user.id)

            if not session:
                await message.answer("❌ Вы не авторизованы. Используйте /start для входа.")
                return

            await message.answer(
                "📞 *Связь с администратором*\n\n"
                "Опишите вашу проблему или вопрос. Администратор ответит вам в ближайшее время.\n\n"
                "Для отмены отправьте /cancel",
                parse_mode="Markdown"
            )
            await state.set_state(SupportStates.waiting_for_message)

        @dp.message(SupportStates.waiting_for_message)
        async def process_support_message(message: Message, state: FSMContext):
            """Обработка сообщения в поддержку"""
            print(f"📝 Processing support message from {message.from_user.id}: {message.text[:50]}")

            if message.text == "/cancel":
                await state.clear()
                await message.answer("❌ Обращение отменено.")
                return

            session = await db.get_session(message.from_user.id)

            if not session:
                await message.answer("❌ Вы не авторизованы. Используйте /start для входа.")
                await state.clear()
                return

            # Сохраняем обращение
            try:
                async with aiosqlite.connect(db.db_path) as conn:
                    cursor = await conn.execute(
                        "INSERT INTO support_tickets (telegram_id, username, user_id, message, status, created_at) VALUES (?, ?, ?, ?, 'open', datetime('now'))",
                        (message.from_user.id, session['username'], session['id'], message.text)
                    )
                    await conn.commit()
                    ticket_id = cursor.lastrowid

                await message.answer(
                    f"✅ *Обращение #{ticket_id} отправлено!*\n\n"
                    f"Администратор свяжется с вами в ближайшее время.\n\n"
                    f"Для отмены используйте /cancel",
                    parse_mode="Markdown"
                )

                # Уведомляем администраторов
                async with aiosqlite.connect(db.db_path) as conn:
                    async with conn.execute("SELECT telegram_id FROM user_sessions WHERE role = 'admin'") as cursor:
                        admins = await cursor.fetchall()

                        for admin in admins:
                            try:
                                await bot.send_message(
                                    admin[0],
                                    f"🆕 *Новое обращение!*\n\n"
                                    f"🆔 ID: {ticket_id}\n"
                                    f"👤 Пользователь: {session['username']}\n"
                                    f"📝 Сообщение: {message.text[:300]}\n\n"
                                    f"Ответьте через админ-панель: 👑 Админ панель → 💬 Обращения в поддержку",
                                    parse_mode="Markdown"
                                )
                                print(f"✅ Admin {admin[0]} notified")
                            except Exception as e:
                                print(f"❌ Failed to notify admin {admin[0]}: {e}")

            except Exception as e:
                print(f"❌ Error saving ticket: {e}")
                await message.answer("❌ Произошла ошибка при отправке обращения. Попробуйте позже.")

            await state.clear()

        @dp.message(Command("cancel"))
        async def cancel_handler(message: Message, state: FSMContext):
            """Отмена текущей операции"""
            current_state = await state.get_state()
            if current_state is None:
                await message.answer("❌ Нет активной операции для отмены.")
                return

            await state.clear()
            await message.answer("✅ Операция отменена.")


# =========== ЗАПУСК БОТА ===========
async def main():
    """Запуск бота"""
    await db.init_db()
    await db.migrate_db()  # Добавляем миграцию

    await bot.delete_webhook(drop_pending_updates=True)

    print("🤖 Бот запущен!")
    print(f"📡 Сервер: {SITE_URL}")
    print("✅ Все функции активированы")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
