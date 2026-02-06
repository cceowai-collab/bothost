import asyncio
import json
import os
import random
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
TOKEN = "8574369883:AAF-F7eusMG5u00S9mYnEMwvWnbSJI3sty4"
ADMIN_ID = 123456789  # Ваш ID для админки

# Константы игры
WAR_PREPARATION_TIME = 300  # 5 минут на подготовку к войне (в секундах)

# Хранилище данных
GAMES_FILE = "games_data.json"


# Классы данных
@dataclass
class Country:
    """Класс страны"""
    name: str
    emoji: str
    base_income: float  # Пассивный доход в секунду
    army_cost: int = 1000  # Стоимость улучшения армии
    city_cost: int = 5000  # Стоимость улучшения города


# Данные стран
COUNTRIES = {
    "russia": Country("Россия", "🇷🇺", 10.0),
    "ukraine": Country("Украина", "🇺🇦", 8.0),
    "turkey": Country("Турция", "🇹🇷", 7.0),
    "sweden": Country("Швеция", "🇸🇪", 6.0),
    "finland": Country("Финляндия", "🇫🇮", 5.0),
    "spain": Country("Испания", "🇪🇸", 9.0),
}


@dataclass
class Player:
    """Класс игрока"""
    user_id: int
    username: str
    country: str
    money: float = 1000.0
    army_level: int = 1
    city_level: int = 1
    last_income: datetime = field(default_factory=datetime.now)
    wins: int = 0
    losses: int = 0
    is_online: bool = True
    has_dm_notifications: bool = True  # Флаг для уведомлений в ЛС


@dataclass
class Game:
    """Класс игры"""
    chat_id: int
    creator_id: int
    players: Dict[int, Player] = field(default_factory=dict)
    war_active: bool = False
    war_preparation: bool = False  # Флаг подготовки к войне
    war_participants: List[int] = field(default_factory=list)
    war_start_time: Optional[datetime] = None
    war_preparation_end: Optional[datetime] = None  # Время окончания подготовки
    last_war: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)


# Состояния FSM
class GameStates(StatesGroup):
    waiting_for_country = State()
    waiting_for_war_target = State()


# Глобальные переменные
games: Dict[int, Game] = {}
bot: Optional[Bot] = None


# Функции для работы с данными
def save_data():
    """Сохранить данные игр в файл"""
    try:
        data = {}
        for chat_id, game in games.items():
            game_data = {
                "chat_id": game.chat_id,
                "creator_id": game.creator_id,
                "war_active": game.war_active,
                "war_preparation": game.war_preparation,
                "war_participants": game.war_participants,
                "war_start_time": game.war_start_time.isoformat() if game.war_start_time else None,
                "war_preparation_end": game.war_preparation_end.isoformat() if game.war_preparation_end else None,
                "last_war": game.last_war.isoformat() if game.last_war else None,
                "created_at": game.created_at.isoformat(),
                "players": {}
            }
            for user_id, player in game.players.items():
                game_data["players"][str(user_id)] = {
                    "user_id": player.user_id,
                    "username": player.username,
                    "country": player.country,
                    "money": player.money,
                    "army_level": player.army_level,
                    "city_level": player.city_level,
                    "last_income": player.last_income.isoformat(),
                    "wins": player.wins,
                    "losses": player.losses,
                    "is_online": player.is_online,
                    "has_dm_notifications": player.has_dm_notifications
                }
            data[str(chat_id)] = game_data

        with open(GAMES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("Данные сохранены успешно")
    except Exception as e:
        logger.error(f"Ошибка сохранения данных: {e}")


def load_data():
    """Загрузить данные игр из файла"""
    global games
    if not os.path.exists(GAMES_FILE):
        logger.info("Файл данных не найден, будет создан новый")
        return

    try:
        with open(GAMES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        games = {}
        for chat_id_str, game_data in data.items():
            chat_id = int(chat_id_str)
            game = Game(
                chat_id=chat_id,
                creator_id=game_data["creator_id"],
                war_active=game_data["war_active"],
                war_preparation=game_data.get("war_preparation", False),
                war_participants=game_data["war_participants"],
                created_at=datetime.fromisoformat(game_data["created_at"])
            )

            if game_data["war_start_time"]:
                game.war_start_time = datetime.fromisoformat(game_data["war_start_time"])
            if game_data.get("war_preparation_end"):
                game.war_preparation_end = datetime.fromisoformat(game_data["war_preparation_end"])
            if game_data["last_war"]:
                game.last_war = datetime.fromisoformat(game_data["last_war"])

            for user_id_str, player_data in game_data["players"].items():
                player = Player(
                    user_id=player_data["user_id"],
                    username=player_data["username"],
                    country=player_data["country"],
                    money=player_data["money"],
                    army_level=player_data["army_level"],
                    city_level=player_data["city_level"],
                    last_income=datetime.fromisoformat(player_data["last_income"]),
                    wins=player_data["wins"],
                    losses=player_data["losses"],
                    is_online=player_data.get("is_online", True)
                )
                player.has_dm_notifications = player_data.get("has_dm_notifications", True)
                game.players[int(user_id_str)] = player

            games[chat_id] = game

        logger.info(f"Загружено {len(games)} игр")
    except Exception as e:
        logger.error(f"Ошибка загрузки данных: {e}")


async def update_income():
    """Фоновая задача для обновления пассивного дохода"""
    while True:
        try:
            await asyncio.sleep(1)
            current_time = datetime.now()

            for game in games.values():
                if game.war_active:
                    continue

                for player in game.players.values():
                    if not player.is_online:
                        continue

                    time_diff = (current_time - player.last_income).total_seconds()
                    if time_diff > 0:
                        country = COUNTRIES[player.country]
                        income = country.base_income * player.city_level * time_diff
                        player.money += income
                        player.last_income = current_time

            # Автосохранение каждые 60 секунд
            if int(current_time.timestamp()) % 60 == 0:
                save_data()

        except Exception as e:
            logger.error(f"Ошибка в update_income: {e}")
            await asyncio.sleep(5)


# Функции для создания клавиатур
def get_game_keyboard(player_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для игрока"""
    keyboard = [
        [
            InlineKeyboardButton(text="💰 Статистика", callback_data=f"stats_{player_id}"),
            InlineKeyboardButton(text="⚔️ Улучшить армию", callback_data=f"upgrade_army_{player_id}")
        ],
        [
            InlineKeyboardButton(text="🏙️ Улучшить город", callback_data=f"upgrade_city_{player_id}"),
            InlineKeyboardButton(text="🌍 Топ игроков", callback_data=f"top_{player_id}")
        ],
        [
            InlineKeyboardButton(text="⚔️ Начать войну", callback_data=f"start_war_{player_id}")
        ],
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data=f"refresh_{player_id}"),
            InlineKeyboardButton(text="🔔 Настройки", callback_data=f"settings_{player_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_countries_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора страны"""
    keyboard = []
    for country_id, country in COUNTRIES.items():
        keyboard.append([InlineKeyboardButton(
            text=f"{country.emoji} {country.name} ({country.base_income}/сек)",
            callback_data=f"country_{country_id}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_war_targets_keyboard(game: Game, attacker_id: int) -> InlineKeyboardMarkup:
    """Клавиатура выбора цели для войны"""
    keyboard = []
    for player_id, player in game.players.items():
        if player_id != attacker_id:
            country = COUNTRIES[player.country]
            keyboard.append([InlineKeyboardButton(
                text=f"{player.username} {country.emoji} (⚔{player.army_level} 💰{int(player.money)})",
                callback_data=f"wartarget_{player_id}"
            )])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_settings_keyboard(player_id: int, has_notifications: bool) -> InlineKeyboardMarkup:
    """Клавиатура настроек"""
    notification_status = "🔔 Вкл" if has_notifications else "🔕 Выкл"
    keyboard = [
        [
            InlineKeyboardButton(
                text=f"Уведомления в ЛС: {notification_status}",
                callback_data=f"toggle_notifications_{player_id}"
            )
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data=f"refresh_{player_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# Вспомогательные функции
async def is_user_in_game(chat_id: int, user_id: int) -> bool:
    """Проверка, находится ли пользователь в игре"""
    return chat_id in games and user_id in games[chat_id].players


async def check_callback_owner(callback: CallbackQuery) -> bool:
    """Проверка, что callback принадлежит пользователю"""
    try:
        data = callback.data.split('_')
        if len(data) < 2:
            return False
        callback_user_id = int(data[-1])
        return callback_user_id == callback.from_user.id
    except (ValueError, IndexError):
        return False


async def show_player_menu(message_or_callback, user_id: Optional[int] = None, is_callback: bool = False):
    """Показать меню игрока"""
    if user_id is None:
        if is_callback:
            user_id = message_or_callback.from_user.id
        else:
            user_id = message_or_callback.from_user.id

    if is_callback:
        chat_id = message_or_callback.message.chat.id
        message_obj = message_or_callback.message
    else:
        chat_id = message_or_callback.chat.id
        message_obj = message_or_callback

    if not await is_user_in_game(chat_id, user_id):
        if is_callback:
            await message_or_callback.answer("❌ Вы не в игре! Используйте /join чтобы присоединиться.")
        else:
            await message_or_callback.answer("❌ Вы не в игре! Используйте /join чтобы присоединиться.")
        return

    game = games[chat_id]
    player = game.players[user_id]
    country = COUNTRIES[player.country]

    # Расчет стоимости улучшений
    income_per_sec = country.base_income * player.city_level
    army_upgrade_cost = country.army_cost * player.army_level
    city_upgrade_cost = country.city_cost * player.city_level

    # Формирование текста
    text = (
        f"🎮 **Управление страной**\n\n"
        f"🌍 **Страна:** {country.emoji} {country.name}\n"
        f"👤 **Игрок:** {player.username}\n"
        f"💰 **Казна:** {int(player.money)} монет\n"
        f"⚔️ **Уровень армии:** {player.army_level}\n"
        f"🏙️ **Уровень города:** {player.city_level}\n"
        f"📈 **Пассивный доход:** {income_per_sec:.1f} монет/сек\n"
        f"🏆 **Статистика:** {player.wins} побед / {player.losses} поражений\n\n"
        f"**Улучшения:**\n"
        f"⚔️ Улучшить армию - {army_upgrade_cost} монет\n"
        f"🏙️ Улучшить город - {city_upgrade_cost} монет"
    )

    if game.war_active:
        text += "\n\n⚔️ **Сейчас идет война!**"
    elif game.war_preparation:
        if user_id in game.war_participants:
            time_left = int((game.war_preparation_end - datetime.now()).total_seconds())
            if time_left > 0:
                text += f"\n\n🛡️ **Подготовка к войне!**\n⏳ До начала: {time_left} сек\nУлучшайте армию!"

    if is_callback:
        await message_obj.edit_text(text, reply_markup=get_game_keyboard(user_id))
    else:
        await message_obj.answer(text, reply_markup=get_game_keyboard(user_id))


async def send_dm_notification(user_id: int, message: str):
    """Отправить уведомление в личные сообщения"""
    try:
        await bot.send_message(user_id, message)
        logger.info(f"Уведомление отправлено пользователю {user_id}")
        return True
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")
        return False


# Обработчики команд
async def cmd_start(message: Message):
    """Обработка команды /start"""
    if message.chat.type == "private":
        await message.answer(
            "🎮 **Добро пожаловать в Control Europe!**\n\n"
            "⚠️ Игра доступна только в групповых чатах!\n\n"
            "Добавьте меня в группу и используйте команду /join чтобы присоединиться к игре."
        )
    else:
        await message.answer(
            "🎮 **Control Europe - стратегическая игра**\n\n"
            "**Доступные команды:**\n"
            "/join - Присоединиться к игре\n"
            "/players - Список игроков\n"
            "/help - Помощь по игре"
        )


async def cmd_join(message: Message, state: FSMContext):
    """Обработка команды /join"""
    if message.chat.type == "private":
        await message.answer("❌ Игра доступна только в групповых чатах!")
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    # Если игра не создана в этом чате, создаем ее автоматически
    if chat_id not in games:
        games[chat_id] = Game(
            chat_id=chat_id,
            creator_id=user_id
        )
        save_data()

    game = games[chat_id]

    # Проверка на активную войну или подготовку
    if game.war_active or game.war_preparation:
        await message.answer("⚔️ Сейчас идет война или подготовка к ней! Подождите окончания.")
        return

    # Проверка, участвует ли уже пользователь
    if await is_user_in_game(chat_id, user_id):
        await message.answer("✅ Вы уже в игре!")
        await show_player_menu(message)
        return

    # Сохранение состояния и показ выбора страны
    await state.set_state(GameStates.waiting_for_country)
    await state.update_data(chat_id=chat_id, user_id=user_id)

    await message.answer(
        "🌍 **Выберите страну:**\n\n"
        "Каждая страна имеет свой базовый доход в секунду.\n"
        "Страну нельзя будет изменить позже!\n\n"
        "🔔 **Уведомления:**\n"
        "По умолчанию включены уведомления в ЛС о войнах.",
        reply_markup=get_countries_keyboard()
    )


async def cmd_players(message: Message):
    """Показать список игроков"""
    if message.chat.type == "private":
        await message.answer("❌ Игра доступна только в групповых чатах!")
        return

    chat_id = message.chat.id

    if chat_id not in games:
        await message.answer("❌ Игра еще не создана в этом чате!")
        return

    game = games[chat_id]

    if not game.players:
        await message.answer("👥 В игре пока нет игроков. Используйте /join чтобы присоединиться!")
        return

    text = "👥 **Список игроков:**\n\n"
    for i, (player_id, player) in enumerate(game.players.items(), 1):
        country = COUNTRIES[player.country]
        text += f"{i}. {country.emoji} **{player.username}** - 💰{int(player.money)} (⚔{player.army_level} 🏙{player.city_level})\n"

    text += f"\nВсего игроков: {len(game.players)}"
    await message.answer(text)


async def cmd_help(message: Message):
    """Помощь по игре"""
    help_text = (
        "🎮 **Помощь по Control Europe**\n\n"
        "**Основные принципы:**\n"
        "• Вы управляете страной и развиваете ее экономику\n"
        "• Пассивный доход зависит от страны и уровня города\n"
        "• Улучшайте армию для победы в войнах\n"
        "• Улучшайте город для увеличения дохода\n\n"
        "**Войны:**\n"
        "• Можно объявить войну другому игроку\n"
        "• Перед войной есть 5 минут на подготовку\n"
        "• Во время подготовки можно улучшать армию\n"
        "• Победитель получает 15% казны проигравшего\n\n"
        "**Команды:**\n"
        "/join - Присоединиться к игре\n"
        "/players - Список игроков\n"
        "/help - Эта справка\n\n"
        "**Уведомления:**\n"
        "Уведомления о войнах приходят в ЛС. Можно отключить в настройках."
    )
    await message.answer(help_text)


# Обработчики callback-запросов
async def callback_country_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора страны"""
    data = await state.get_data()
    chat_id = data.get('chat_id')
    user_id = data.get('user_id')

    if not chat_id or chat_id not in games:
        await callback.message.edit_text("❌ Ошибка! Игра не найдена.")
        await state.clear()
        return

    if callback.from_user.id != user_id:
        await callback.answer("❌ Это не ваша кнопка!")
        return

    country_id = callback.data.split('_')[1]

    if country_id not in COUNTRIES:
        await callback.message.edit_text("❌ Неверная страна!")
        await state.clear()
        return

    game = games[chat_id]

    # Проверка, не выбрана ли страна другим игроком
    for player in game.players.values():
        if player.country == country_id:
            await callback.message.edit_text("❌ Эта страна уже занята другим игроком!")
            await state.clear()
            return

    # Создание игрока
    player = Player(
        user_id=user_id,
        username=callback.from_user.username or callback.from_user.first_name,
        country=country_id
    )

    game.players[user_id] = player
    await state.clear()

    country = COUNTRIES[country_id]
    await callback.message.edit_text(
        f"✅ **Вы успешно присоединились к игре!**\n\n"
        f"🌍 **Страна:** {country.emoji} {country.name}\n"
        f"💰 **Стартовый капитал:** 1000 монет\n"
        f"⚔️ **Уровень армии:** 1\n"
        f"🏙️ **Уровень города:** 1\n"
        f"📈 **Пассивный доход:** {country.base_income} монет/сек\n\n"
        f"Используйте кнопки ниже для управления своей страной."
    )

    await show_player_menu(callback, is_callback=True)


async def callback_stats(callback: CallbackQuery):
    """Обработка просмотра статистики"""
    if not await check_callback_owner(callback):
        await callback.answer("❌ Это не ваша кнопка!")
        return

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    if not await is_user_in_game(chat_id, user_id):
        await callback.answer("❌ Вы не в игре!")
        return

    game = games[chat_id]
    player = game.players[user_id]
    country = COUNTRIES[player.country]

    # Расчет статистики
    income_per_sec = country.base_income * player.city_level
    army_upgrade_cost = country.army_cost * player.army_level
    city_upgrade_cost = country.city_cost * player.city_level
    total_income = player.money - 1000

    notification_status = "✅ Включены" if player.has_dm_notifications else "❌ Выключены"

    text = (
        f"📊 **Детальная статистика**\n\n"
        f"👤 **Игрок:** {player.username}\n"
        f"🌍 **Страна:** {country.emoji} {country.name}\n"
        f"📅 **В игре с:** {player.last_income.strftime('%d.%m.%Y %H:%M')}\n"
        f"🔔 **Уведомления в ЛС:** {notification_status}\n\n"
        f"💰 **Финансы:**\n"
        f"• Текущий баланс: {int(player.money)} монет\n"
        f"• Пассивный доход: {income_per_sec:.1f} монет/сек\n"
        f"• Всего заработано: ≈{int(total_income)} монет\n\n"
        f"⚔️ **Военная мощь:**\n"
        f"• Уровень армии: {player.army_level}\n"
        f"• След. улучшение: {army_upgrade_cost} монет\n"
        f"• Сила атаки: {player.army_level * (1 + 0.1 * player.city_level):.1f}\n\n"
        f"🏙️ **Экономика:**\n"
        f"• Уровень города: {player.city_level}\n"
        f"• След. улучшение: {city_upgrade_cost} монет\n"
        f"• Множитель дохода: {player.city_level}x\n\n"
        f"🏆 **Боевая статистика:**\n"
        f"• Побед: {player.wins}\n"
        f"• Поражений: {player.losses}\n"
    )

    if player.wins + player.losses > 0:
        win_rate = player.wins / (player.wins + player.losses) * 100
        text += f"• Соотношение: {win_rate:.1f}%\n"
    else:
        text += "• Соотношение: 0%\n"

    text += f"\n🔄 Измените настройки уведомлений через меню 'Настройки'"

    await callback.message.edit_text(text)
    await callback.answer()


async def callback_upgrade_army(callback: CallbackQuery):
    """Обработка улучшения армии"""
    if not await check_callback_owner(callback):
        await callback.answer("❌ Это не ваша кнопка!")
        return

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    if not await is_user_in_game(chat_id, user_id):
        await callback.answer("❌ Вы не в игре!")
        return

    game = games[chat_id]

    # Проверка на активную войну (но можно во время подготовки)
    if game.war_active:
        await callback.answer("⚔️ Во время войны нельзя улучшать армию!")
        return

    player = game.players[user_id]
    country = COUNTRIES[player.country]

    upgrade_cost = country.army_cost * player.army_level

    if player.money >= upgrade_cost:
        player.money -= upgrade_cost
        player.army_level += 1
        save_data()

        await callback.answer(f"✅ Армия улучшена до уровня {player.army_level}!")
        await show_player_menu(callback, is_callback=True)
    else:
        await callback.answer(f"❌ Недостаточно средств! Нужно {upgrade_cost} монет.")


async def callback_upgrade_city(callback: CallbackQuery):
    """Обработка улучшения города"""
    if not await check_callback_owner(callback):
        await callback.answer("❌ Это не ваша кнопка!")
        return

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    if not await is_user_in_game(chat_id, user_id):
        await callback.answer("❌ Вы не в игре!")
        return

    game = games[chat_id]

    # Проверка на активную войну или подготовку
    if game.war_active or game.war_preparation:
        await callback.answer("⚔️ Во время войны или подготовки нельзя улучшать город!")
        return

    player = game.players[user_id]
    country = COUNTRIES[player.country]

    upgrade_cost = country.city_cost * player.city_level

    if player.money >= upgrade_cost:
        player.money -= upgrade_cost
        player.city_level += 1
        save_data()

        await callback.answer(f"✅ Город улучшен до уровня {player.city_level}!")
        await show_player_menu(callback, is_callback=True)
    else:
        await callback.answer(f"❌ Недостаточно средств! Нужно {upgrade_cost} монет.")


async def callback_top(callback: CallbackQuery):
    """Обработка топа игроков"""
    if not await check_callback_owner(callback):
        await callback.answer("❌ Это не ваша кнопка!")
        return

    chat_id = callback.message.chat.id

    if chat_id not in games:
        await callback.answer("❌ Игра не найдена!")
        return

    game = games[chat_id]

    if not game.players:
        await callback.message.edit_text("📊 В игре пока нет игроков!")
        await callback.answer()
        return

    # Сортировка игроков по деньгам
    sorted_players = sorted(
        game.players.values(),
        key=lambda p: p.money,
        reverse=True
    )

    text = "🏆 **Топ игроков** 🏆\n\n"
    medals = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]

    for i, player in enumerate(sorted_players[:10], 1):
        country = COUNTRIES[player.country]
        medal = medals[i - 1] if i <= 10 else f"{i}."
        power = player.army_level * (1 + 0.1 * player.city_level)
        text += f"{medal} {country.emoji} **{player.username}**\n"
        text += f"   💰 {int(player.money)} | ⚔️ {player.army_level} | 🏙️ {player.city_level} | 📈 {power:.1f}\n\n"

    text += f"Всего игроков: {len(game.players)}"
    await callback.message.edit_text(text)
    await callback.answer()


async def callback_settings(callback: CallbackQuery):
    """Обработка открытия настроек"""
    if not await check_callback_owner(callback):
        await callback.answer("❌ Это не ваша кнопка!")
        return

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    if not await is_user_in_game(chat_id, user_id):
        await callback.answer("❌ Вы не в игре!")
        return

    player = games[chat_id].players[user_id]

    text = (
        f"⚙️ **Настройки игры**\n\n"
        f"Здесь вы можете настроить параметры уведомлений.\n\n"
        f"🔔 **Уведомления в личные сообщения:**\n"
        f"• Уведомления о начале войны с вашим участием\n"
        f"• Результаты ваших войн\n\n"
        f"Текущий статус: {'✅ **Включены**' if player.has_dm_notifications else '❌ **Выключены**'}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_settings_keyboard(user_id, player.has_dm_notifications)
    )
    await callback.answer()


async def callback_toggle_notifications(callback: CallbackQuery):
    """Обработка переключения уведомлений"""
    if not await check_callback_owner(callback):
        await callback.answer("❌ Это не ваша кнопка!")
        return

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    if not await is_user_in_game(chat_id, user_id):
        await callback.answer("❌ Вы не в игре!")
        return

    player = games[chat_id].players[user_id]
    player.has_dm_notifications = not player.has_dm_notifications
    save_data()

    status = "включены" if player.has_dm_notifications else "выключены"
    await callback.answer(f"🔔 Уведомления {status}!")

    # Обновляем сообщение настроек
    text = (
        f"⚙️ **Настройки игры**\n\n"
        f"Здесь вы можете настроить параметры уведомлений.\n\n"
        f"🔔 **Уведомления в личные сообщения:**\n"
        f"• Уведомления о начале войны с вашим участием\n"
        f"• Результаты ваших войн\n\n"
        f"Текущий статус: {'✅ **Включены**' if player.has_dm_notifications else '❌ **Выключены**'}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_settings_keyboard(user_id, player.has_dm_notifications)
    )


async def callback_start_war(callback: CallbackQuery, state: FSMContext):
    """Обработка начала войны"""
    if not await check_callback_owner(callback):
        await callback.answer("❌ Это не ваша кнопка!")
        return

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    if not await is_user_in_game(chat_id, user_id):
        await callback.answer("❌ Вы не в игре!")
        return

    game = games[chat_id]

    # Проверка на активную войну или подготовку
    if game.war_active or game.war_preparation:
        await callback.answer("⚔️ Война уже идет или готовится!")
        return

    # Проверка кулдауна (минимум 3 минуты между войнами)
    if game.last_war and (datetime.now() - game.last_war).total_seconds() < 180:
        remaining = 180 - (datetime.now() - game.last_war).total_seconds()
        await callback.answer(f"⏳ До следующей войны: {int(remaining)} сек")
        return

    # Проверка, что есть другие игроки
    if len(game.players) < 2:
        await callback.answer("❌ Недостаточно игроков для войны!")
        return

    # Сохранение состояния и показ выбора цели
    await state.set_state(GameStates.waiting_for_war_target)
    await state.update_data(chat_id=chat_id, attacker_id=user_id)

    await callback.message.edit_text(
        "🎯 **Выберите противника для войны:**\n\n"
        "Война начнется через 5 минут (время на подготовку).\n"
        "Во время подготовки можно улучшать армию!\n"
        "Победитель получает 15% казны проигравшего!\n\n"
        "🔔 **Уведомления:**\n"
        "Участники получат сообщение в ЛС.",
        reply_markup=get_war_targets_keyboard(game, user_id)
    )
    await callback.answer()


async def callback_war_target(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора цели для войны"""
    data = await state.get_data()
    chat_id = data.get('chat_id')
    attacker_id = data.get('attacker_id')

    if not chat_id or not attacker_id:
        await callback.message.edit_text("❌ Ошибка!")
        await state.clear()
        return

    if callback.from_user.id != attacker_id:
        await callback.answer("❌ Это не ваша кнопка!")
        return

    target_id = int(callback.data.split('_')[1])

    if target_id == attacker_id:
        await callback.answer("❌ Нельзя воевать с самим собой!")
        return

    game = games[chat_id]

    # Проверка, что игроки существуют
    if attacker_id not in game.players or target_id not in game.players:
        await callback.message.edit_text("❌ Игрок не найден!")
        await state.clear()
        return

    # Проверка на активную войну или подготовку
    if game.war_active or game.war_preparation:
        await callback.message.edit_text("⚔️ Война уже идет или готовится!")
        await state.clear()
        return

    # Начало подготовки к войне
    game.war_preparation = True
    game.war_participants = [attacker_id, target_id]
    game.war_preparation_end = datetime.now() + timedelta(seconds=WAR_PREPARATION_TIME)

    attacker = game.players[attacker_id]
    target = game.players[target_id]

    attacker_country = COUNTRIES[attacker.country]
    target_country = COUNTRIES[target.country]

    # Сообщение в чат для всех
    war_announcement = (
        f"⚔️ **ОБЪЯВЛЕНА ВОЙНА!** ⚔️\n\n"
        f"**Атакующий:** {attacker_country.emoji} {attacker.username}\n"
        f"**Защитник:** {target_country.emoji} {target.username}\n\n"
        f"⚔️ **Силы сторон:**\n"
        f"• {attacker.username}: армия {attacker.army_level}, город {attacker.city_level}\n"
        f"• {target.username}: армия {target.army_level}, город {target.city_level}\n\n"
        f"🛡️ **Время на подготовку:** {WAR_PREPARATION_TIME // 60} минут\n"
        f"⏳ **Война начнется:** через {WAR_PREPARATION_TIME} секунд\n\n"
        f"Участники могут улучшать армию во время подготовки!"
    )

    await callback.message.edit_text(war_announcement)

    # Отправляем уведомления в ЛС только участникам
    attacker_message = (
        f"🎯 **Вы объявили войну!**\n\n"
        f"Вы атакуете {target_country.emoji} {target.username}\n"
        f"🛡️ **Время на подготовку:** {WAR_PREPARATION_TIME // 60} минут\n"
        f"⚔️ **Сила противника:** армия {target.army_level}, город {target.city_level}\n\n"
        f"Улучшайте армию во время подготовки!\n"
        f"Война начнется автоматически через {WAR_PREPARATION_TIME} секунд."
    )

    target_message = (
        f"⚠️ **Вам объявили войну!**\n\n"
        f"{attacker_country.emoji} {attacker.username} атакует вашу страну!\n"
        f"🛡️ **Время на подготовку:** {WAR_PREPARATION_TIME // 60} минут\n"
        f"⚔️ **Сила противника:** армия {attacker.army_level}, город {attacker.city_level}\n\n"
        f"Срочно улучшайте армию для защиты!\n"
        f"Война начнется автоматически через {WAR_PREPARATION_TIME} секунд."
    )

    if attacker.has_dm_notifications:
        await send_dm_notification(attacker.user_id, attacker_message)

    if target.has_dm_notifications:
        await send_dm_notification(target.user_id, target_message)

    # Запуск таймера подготовки к войне
    asyncio.create_task(war_preparation_countdown(chat_id))

    await state.clear()


async def war_preparation_countdown(chat_id: int):
    """Таймер подготовки к войне"""
    try:
        await asyncio.sleep(WAR_PREPARATION_TIME)  # Ждем время подготовки

        if chat_id not in games:
            return

        game = games[chat_id]

        if not game.war_preparation or len(game.war_participants) != 2:
            game.war_preparation = False
            game.war_participants = []
            game.war_preparation_end = None
            return

        # Начало войны
        game.war_preparation = False
        game.war_active = True
        game.war_start_time = datetime.now()

        attacker_id = game.war_participants[0]
        target_id = game.war_participants[1]

        attacker = game.players[attacker_id]
        target = game.players[target_id]

        attacker_country = COUNTRIES[attacker.country]
        target_country = COUNTRIES[target.country]

        # Сообщение в чат для всех о начале войны
        war_start_message = (
            f"⚔️ **ВОЙНА НАЧАЛАСЬ!** ⚔️\n\n"
            f"**Атакующий:** {attacker_country.emoji} {attacker.username}\n"
            f"**Защитник:** {target_country.emoji} {target.username}\n\n"
            f"⚔️ **Текущие силы:**\n"
            f"• {attacker.username}: армия {attacker.army_level}\n"
            f"• {target.username}: армия {target.army_level}\n\n"
            f"⏳ **Бой продлится 60 секунд...**"
        )

        await bot.send_message(chat_id, war_start_message)

        # Отправляем уведомления в ЛС только участникам
        war_start_dm = (
            f"⚔️ **ВОЙНА НАЧАЛАСЬ!**\n\n"
            f"Бой между {attacker.username} и {target.username} начался!\n"
            f"⏳ **Длительность:** 60 секунд\n"
            f"💰 **Награда:** 15% казны проигравшего\n\n"
            f"Удачи в бою!"
        )

        if attacker.has_dm_notifications:
            await send_dm_notification(attacker.user_id, war_start_dm)

        if target.has_dm_notifications:
            await send_dm_notification(target.user_id, war_start_dm)

        # Запуск таймера войны
        asyncio.create_task(war_countdown(chat_id))

    except Exception as e:
        logger.error(f"Ошибка в war_preparation_countdown: {e}")
        if chat_id in games:
            games[chat_id].war_preparation = False
            games[chat_id].war_participants = []


async def war_countdown(chat_id: int):
    """Таймер войны"""
    try:
        await asyncio.sleep(60)  # Война длится 60 секунд

        if chat_id not in games:
            return

        game = games[chat_id]

        if not game.war_active or len(game.war_participants) != 2:
            game.war_active = False
            game.war_participants = []
            game.war_start_time = None
            return

        # Определение победителя
        attacker_id = game.war_participants[0]
        target_id = game.war_participants[1]

        attacker = game.players[attacker_id]
        target = game.players[target_id]

        attacker_power = attacker.army_level * (1 + 0.1 * attacker.city_level)
        target_power = target.army_level * (1 + 0.1 * target.city_level)

        # Добавление случайности (10%)
        attacker_power *= random.uniform(0.95, 1.05)
        target_power *= random.uniform(0.95, 1.05)

        # Проверка на боевой дух (шанс 5% на победу слабого)
        if random.random() < 0.05:
            if attacker_power < target_power:
                attacker_power, target_power = target_power, attacker_power

        if attacker_power > target_power:
            winner = attacker
            loser = target
            winner.wins += 1
            loser.losses += 1

            # Награда победителю (15% денег проигравшего)
            loot = loser.money * 0.15
            if loot < 100:
                loot = 100  # Минимальная награда

            winner.money += loot
            loser.money -= loot

            result_message = (
                f"🎉 **ВОЙНА ОКОНЧЕНА!** 🎉\n\n"
                f"🏆 **ПОБЕДИТЕЛЬ:** {COUNTRIES[winner.country].emoji} {winner.username}\n"
                f"💀 **ПРОИГРАВШИЙ:** {COUNTRIES[loser.country].emoji} {loser.username}\n\n"
                f"⚔️ **Сила атаки:**\n"
                f"• {attacker.username}: {attacker_power:.1f}\n"
                f"• {target.username}: {target_power:.1f}\n\n"
                f"💰 **Добыча:** {int(loot)} монет\n"
                f"🏆 **Статистика обновлена:**\n"
                f"• {winner.username}: {winner.wins}/{winner.losses}\n"
                f"• {loser.username}: {loser.wins}/{loser.losses}"
            )
        else:
            winner = target
            loser = attacker
            winner.wins += 1
            loser.losses += 1

            loot = loser.money * 0.15
            if loot < 100:
                loot = 100

            winner.money += loot
            loser.money -= loot

            result_message = (
                f"🎉 **ВОЙНА ОКОНЧЕНА!** 🎉\n\n"
                f"🏆 **ПОБЕДИТЕЛЬ:** {COUNTRIES[winner.country].emoji} {winner.username}\n"
                f"💀 **ПРОИГРАВШИЙ:** {COUNTRIES[loser.country].emoji} {loser.username}\n\n"
                f"⚔️ **Сила атаки:**\n"
                f"• {attacker.username}: {attacker_power:.1f}\n"
                f"• {target.username}: {target_power:.1f}\n\n"
                f"💰 **Добыча:** {int(loot)} монет\n"
                f"🏆 **Статистика обновлена:**\n"
                f"• {winner.username}: {winner.wins}/{winner.losses}\n"
                f"• {loser.username}: {loser.wins}/{loser.losses}"
            )

        # Сброс состояния войны
        game.war_active = False
        game.war_participants = []
        game.war_start_time = None
        game.war_preparation_end = None
        game.last_war = datetime.now()

        # Отправка результата в чат
        await bot.send_message(chat_id, result_message)

        # Отправка уведомлений в ЛС только участникам
        winner_message = (
            f"🎉 **ВЫ ПОБЕДИЛИ В ВОЙНЕ!**\n\n"
            f"Вы победили {COUNTRIES[loser.country].emoji} {loser.username}\n"
            f"💰 **Добыча:** {int(loot)} монет\n"
            f"🏆 **Ваша статистика:** {winner.wins}/{winner.losses}\n\n"
            f"Поздравляем с победой!"
        )

        loser_message = (
            f"😔 **ВЫ ПРОИГРАЛИ В ВОЙНЕ**\n\n"
            f"Вы проиграли {COUNTRIES[winner.country].emoji} {winner.username}\n"
            f"💰 **Потеряно:** {int(loot)} монет\n"
            f"🏆 **Ваша статистика:** {loser.wins}/{loser.losses}\n\n"
            f"Не отчаивайтесь! Улучшайте армию и попробуйте снова!"
        )

        if winner.has_dm_notifications:
            await send_dm_notification(winner.user_id, winner_message)

        if loser.has_dm_notifications:
            await send_dm_notification(loser.user_id, loser_message)

        # Сохранение данных
        save_data()

    except Exception as e:
        logger.error(f"Ошибка в war_countdown: {e}")
        if chat_id in games:
            games[chat_id].war_active = False
            games[chat_id].war_participants = []


async def callback_refresh(callback: CallbackQuery):
    """Обработка обновления"""
    if not await check_callback_owner(callback):
        await callback.answer("❌ Это не ваша кнопка!")
        return

    await show_player_menu(callback, is_callback=True)
    await callback.answer("🔄 Обновлено!")


# Основная функция
async def main():
    """Основная функция запуска бота"""
    global bot

    # Загрузка данных
    load_data()

    # Инициализация бота
    bot = Bot(token=TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Регистрация обработчиков команд
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_join, Command("join"))
    dp.message.register(cmd_players, Command("players"))
    dp.message.register(cmd_help, Command("help"))

    # Регистрация обработчиков callback-запросов
    dp.callback_query.register(callback_country_selection, F.data.startswith("country_"))
    dp.callback_query.register(callback_stats, F.data.startswith("stats_"))
    dp.callback_query.register(callback_upgrade_army, F.data.startswith("upgrade_army_"))
    dp.callback_query.register(callback_upgrade_city, F.data.startswith("upgrade_city_"))
    dp.callback_query.register(callback_top, F.data.startswith("top_"))
    dp.callback_query.register(callback_settings, F.data.startswith("settings_"))
    dp.callback_query.register(callback_toggle_notifications, F.data.startswith("toggle_notifications_"))
    dp.callback_query.register(callback_start_war, F.data.startswith("start_war_"))
    dp.callback_query.register(callback_war_target, F.data.startswith("wartarget_"))
    dp.callback_query.register(callback_refresh, F.data.startswith("refresh_"))

    # Запуск фоновой задачи для обновления дохода
    asyncio.create_task(update_income())

    # Запуск бота
    logger.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
