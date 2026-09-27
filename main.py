import discord
import asyncio
import json
import os
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ==================== НАСТРОЙКИ ====================
tg_bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))
dp = Dispatcher(storage=MemoryStorage())

TOKEN_DISCORD = os.getenv("DISCORD_TOKEN")
ADMIN_TG_ID = int(os.getenv("ADMIN_TG_ID", "0"))
DS_PREFIX = "!"
SERVERS = ["The bruh Land", "Пивные дали", "Движуха"]

STATUSES = {
    1: "[2;33mТехнические работы[0m",
    2: "[2;36mСервер работает[0m",
    3: "[2;31mСервер остановлен[0m",
    4: "[2;31mСервер остановлен [открывается по запросу, расписания нету][0m",
    5: "[2;34mНеизвестно[0m",
}
STATUS_NAMES = {1: "Технические работы", 2: "Сервер работает", 3: "Сервер остановлен", 4: "Остановлен [по запросу]", 5: "Неизвестно"}

CONFIG_FILE = "config.json"
STATUS_FILE = "statuses.json"
REPORTS_FILE = "reports.json"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return default
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# Инициализация файлов
config = load_json(CONFIG_FILE, {"status_channel_id": 0, "status_message_id": 0, "report_channel_id": 0, "report_message_id": 0})
save_json(CONFIG_FILE, config)

statuses = load_json(STATUS_FILE, {s: {"status": 5, "note": ""} for s in SERVERS})
for s in SERVERS:
    if s not in statuses:
        statuses[s] = {"status": 5, "note": ""}
save_json(STATUS_FILE, statuses)

save_json(REPORTS_FILE, [])

logging.info(f"Файлы инициализированы: {CONFIG_FILE}, {STATUS_FILE}, {REPORTS_FILE}")

# ==================== DISCORD ЧАСТЬ ====================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
ds_bot = discord.Client(intents=intents)

def build_status_message():
    """Читает файл статусов и строит сообщение"""
    current_statuses = load_json(STATUS_FILE, statuses)
    lines = ["[2;37m===== СТАТУС СЕРВЕРОВ =====[0m", ""]
    for server in SERVERS:
        data = current_statuses.get(server, {"status": 5, "note": ""})
        status_text = STATUSES.get(data["status"], STATUSES[5])
        note = data.get("note", "")
        if note:
            lines.append(f"[1;37m{server}:[0m {status_text}")
            lines.append(f"   [2;37m📝 {note}[0m")
        else:
            lines.append(f"[1;37m{server}:[0m {status_text}")
        lines.append("")
    return "```ansi\n" + "\n".join(lines) + "```"

async def update_status_message(changed_server=None):
    """Обновляет сообщение в Discord"""
    channel_id = config.get("status_channel_id", 0)
    if not channel_id:
        logging.warning("status_channel_id не установлен")
        return
    channel = ds_bot.get_channel(channel_id)
    if not channel:
        logging.warning(f"Канал {channel_id} не найден")
        return

    content = build_status_message()
    msg_id = config.get("status_message_id", 0)
    
    try:
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(content=content)
                logging.info(f"Сообщение статусов обновлено (ID: {msg_id})")
            except discord.NotFound:
                logging.warning(f"Сообщение {msg_id} не найдено, создаю новое")
                msg = await channel.send(content)
                config["status_message_id"] = msg.id
                save_json(CONFIG_FILE, config)
        else:
            msg = await channel.send(content)
            config["status_message_id"] = msg.id
            save_json(CONFIG_FILE, config)
            logging.info(f"Создано новое сообщение статусов (ID: {msg.id})")
    except Exception as e:
        logging.error(f"Ошибка обновления сообщения: {e}")

    if changed_server:
        try:
            ping = await channel.send(f"@everyone Статус сервера **{changed_server}** был обновлён!")
            logging.info(f"Отправлен пинг для сервера: {changed_server}")
            await asyncio.sleep(10)
            await ping.delete()
        except Exception as e:
            logging.error(f"Ошибка отправки пинга: {e}")

async def check_status_changes():
    """Проверяет изменения в файле статусов каждые 3 секунды"""
    logging.info("Запущена проверка изменений статусов")
    last_snapshot = ""
    
    while True:
        await asyncio.sleep(3)
        try:
            current_statuses = load_json(STATUS_FILE, {})
            current_snap = json.dumps(current_statuses, sort_keys=True)
            
            if last_snapshot and current_snap != last_snapshot:
                logging.info("Обнаружены изменения в statuses.json!")
                
                # Находим изменённый сервер
                last_data = json.loads(last_snapshot) if last_snapshot else {}
                changed_server = None
                for server in SERVERS:
                    old = last_data.get(server, {})
                    new = current_statuses.get(server, {})
                    if old != new:
                        changed_server = server
                        break
                
                logging.info(f"Изменён сервер: {changed_server}")
                await update_status_message(changed_server)
            
            last_snapshot = current_snap
        except Exception as e:
            logging.error(f"Ошибка в check_status_changes: {e}")

async def ensure_report_message(channel: discord.TextChannel):
    """Создаёт сообщение в канале жалоб"""
    text = "Если вы испытываете проблемы с подключением к серверу, напишите команду `.repcon` в этот чат **ТОЛЬКО В ЭТОТ ЧАТ**"
    msg_id = config.get("report_message_id", 0)
    
    if msg_id:
        try:
            msg = await channel.fetch_message(msg_id)
            await msg.edit(content=text)
            return
        except discord.NotFound:
            pass
    
    msg = await channel.send(text)
    config["report_channel_id"] = channel.id
    config["report_message_id"] = msg.id
    save_json(CONFIG_FILE, config)
    logging.info(f"Создано сообщение в канале жалоб (ID: {msg.id})")

@ds_bot.event
async def on_ready():
    logging.info(f"✅ Discord бот запущен: {ds_bot.user}")
    if config.get("status_channel_id"):
        await update_status_message()
    ds_bot.loop.create_task(check_status_changes())

@ds_bot.event
async def on_message(message: discord.Message):
    if message.author == ds_bot.user:
        return

    # Канал жалоб
    report_channel_id = config.get("report_channel_id", 0)
    if message.channel.id == report_channel_id and report_channel_id != 0:
        if message.id == config.get("report_message_id"):
            return
        
        content = message.content.strip()
        logging.info(f"Получено сообщение в канале жалоб: '{content}' от {message.author}")
        
        try:
            await message.delete()
        except:
            pass

        if content == ".repcon":
            logging.info(f"Получена команда .repcon от {message.author}")
            notify = await message.channel.send("✅ Информация была успешно отправлена хосту. Ожидайте проверки.")
            
            # Записываем жалобу в файл
            reports = load_json(REPORTS_FILE, [])
            reports.append({
                "user": str(message.author),
                "user_id": message.author.id,
                "guild": message.guild.name,
                "time": datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            })
            save_json(REPORTS_FILE, reports)
            logging.info(f"Жалоба записана в {REPORTS_FILE}")
            
            await asyncio.sleep(10)
            try:
                await notify.delete()
            except:
                pass
        else:
            warn = await message.channel.send(f"⚠️ {message.author.mention}, здесь принимаются **только команды**. Используйте `.repcon`")
            await asyncio.sleep(5)
            try:
                await warn.delete()
            except:
                pass
        return

    # Команды админа
    if message.content.startswith(DS_PREFIX) and message.author.guild_permissions.administrator:
        cmd = message.content[len(DS_PREFIX):].strip().lower()
        logging.info(f"Команда админа: {cmd}")
        
        if cmd == "help":
            await message.channel.send(
                f"**Команды:**\n"
                f"`{DS_PREFIX}setstatuschannel` - канал статусов\n"
                f"`{DS_PREFIX}setrepconchannel` - канал жалоб"
            )
        elif cmd == "setstatuschannel":
            config["status_channel_id"] = message.channel.id
            save_json(CONFIG_FILE, config)
            msg = await message.channel.send(build_status_message())
            config["status_message_id"] = msg.id
            save_json(CONFIG_FILE, config)
            await message.channel.send("✅ Канал статусов установлен!")
            logging.info(f"Установлен канал статусов: {message.channel.id}")
        elif cmd == "setrepconchannel":
            await ensure_report_message(message.channel)
            await message.channel.send("✅ Канал жалоб установлен!")
            logging.info(f"Установлен канал жалоб: {message.channel.id}")

# ==================== TELEGRAM ЧАСТЬ ====================
class NoteStates(StatesGroup):
    waiting_note = State()

async def build_main_menu():
    current_statuses = load_json(STATUS_FILE, statuses)
    buttons = []
    for server in SERVERS:
        data = current_statuses.get(server, {"status": 5})
        status_name = STATUS_NAMES.get(data["status"], "Неизвестно")
        buttons.append([InlineKeyboardButton(
            text=f"{server} [{status_name}]",
            callback_data=f"srv:{server}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def build_server_menu(server: str):
    current_statuses = load_json(STATUS_FILE, statuses)
    data = current_statuses.get(server, {"status": 5, "note": ""})
    buttons = []
    for code, name in STATUS_NAMES.items():
        mark = "✅ " if code == data["status"] else ""
        buttons.append([InlineKeyboardButton(
            text=f"{mark}{name}",
            callback_data=f"set:{server}:{code}"
        )])
    buttons.append([InlineKeyboardButton(
        text="📝 Изменить заметку" if data.get("note") else "📝 Добавить заметку",
        callback_data=f"note:{server}"
    )])
    buttons.append([InlineKeyboardButton(text="️ Назад", callback_data="back:main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def check_reports():
    """Проверяет новые жалобы каждые 5 секунд"""
    logging.info("Запущена проверка жалоб")
    last_count = len(load_json(REPORTS_FILE, []))
    
    while True:
        await asyncio.sleep(5)
        try:
            reports = load_json(REPORTS_FILE, [])
            if len(reports) > last_count:
                logging.info(f"Обнаружено {len(reports) - last_count} новых жалоб")
                for r in reports[last_count:]:
                    await tg_bot.send_message(
                        ADMIN_TG_ID,
                        f"🚨 <b>Жалоба на подключение!</b>\n\n"
                        f"Пользователь: <b>{r['user']}</b>\n"
                        f"Сервер: <b>{r['guild']}</b>\n"
                        f"Время: {r['time']}",
                        parse_mode="HTML"
                    )
                    logging.info(f"Отправлена жалоба от {r['user']}")
                last_count = len(reports)
        except Exception as e:
            logging.error(f"Ошибка в check_reports: {e}")

@dp.message(CommandStart())
async def start_handler(message: Message):
    logging.info(f"Получена команда /start от {message.from_user.id}")
    if message.from_user.id != ADMIN_TG_ID:
        await message.answer(
            f"⛔ Доступ запрещён.\n"
            f"Бот видит твой ID: `{message.from_user.id}`\n"
            f"В настройках указан: `{ADMIN_TG_ID}`"
        )
        return
    await message.answer(
        "👋 <b>Панель управления</b>\nВыберите сервер:",
        reply_markup=await build_main_menu(),
        parse_mode="HTML"
    )

@dp.callback_query()
async def callback_handler(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_TG_ID:
        await callback.answer(" Доступ запрещён", show_alert=True)
        return
    data = callback.data
    logging.info(f"Callback: {data}")

    if data == "back:main":
        await state.clear()
        await callback.message.edit_text(
            "👋 <b>Панель управления</b>\nВыберите сервер:",
            reply_markup=await build_main_menu(),
            parse_mode="HTML"
        )
    elif data.startswith("srv:"):
        server = data[4:]
        current_statuses = load_json(STATUS_FILE, statuses)
        d = current_statuses.get(server, {"status": 5, "note": ""})
        await callback.message.edit_text(
            f"🖥 <b>{server}</b>\nСтатус: <b>{STATUS_NAMES[d['status']]}</b>\nЗаметка: <i>{d.get('note') or '—'}</i>",
            reply_markup=await build_server_menu(server),
            parse_mode="HTML"
        )
    elif data.startswith("set:"):
        _, server, code = data.split(":")
        code = int(code)
        logging.info(f"Установка статуса: {server} -> {code}")
        
        current_statuses = load_json(STATUS_FILE, statuses)
        current_statuses[server]["status"] = code
        save_json(STATUS_FILE, current_statuses)
        logging.info(f"Статус сохранён в файл: {server} = {code}")
        
        d = current_statuses.get(server, {"status": 5, "note": ""})
        await callback.message.edit_text(
            f"🖥 <b>{server}</b>\nСтатус: <b>{STATUS_NAMES[code]}</b>\nЗаметка: <i>{d.get('note') or '—'}</i>",
            reply_markup=await build_server_menu(server),
            parse_mode="HTML"
        )
        await callback.answer("✅ Статус обновлён")
    elif data.startswith("note:"):
        await state.update_data(server=data[5:])
        await state.set_state(NoteStates.waiting_note)
        await callback.message.edit_text("📝 Введите новую заметку (или `-` для удаления):")

@dp.message(NoteStates.waiting_note)
async def note_handler(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_TG_ID:
        return
    data = await state.get_data()
    server = data.get("server")
    if not server:
        return
    
    text = message.text.strip()
    note = "" if text == "-" else text
    logging.info(f"Установка заметки: {server} -> '{note}'")
    
    current_statuses = load_json(STATUS_FILE, statuses)
    current_statuses[server]["note"] = note
    save_json(STATUS_FILE, current_statuses)
    logging.info(f"Заметка сохранена в файл: {server} = '{note}'")
    
    await state.clear()
    await message.answer(
        f"✅ Заметка для {server} обновлена.",
        reply_markup=await build_server_menu(server),
        parse_mode="HTML"
    )

# ==================== ЗАПУСК ====================
async def main():
    logging.info("=" * 50)
    logging.info("ЗАПУСК ОБОИХ БОТОВ")
    logging.info("=" * 50)
    logging.info(f"Discord токен: {'✅' if TOKEN_DISCORD else ''}")
    logging.info(f"Telegram токен: {'✅' if os.getenv('TELEGRAM_TOKEN') else '❌'}")
    logging.info(f"Admin TG ID: {ADMIN_TG_ID}")
    logging.info(f"Файл статусов: {STATUS_FILE}")
    logging.info(f"Файл жалоб: {REPORTS_FILE}")
    
    asyncio.create_task(check_status_changes())
    asyncio.create_task(check_reports())
    
    await asyncio.gather(
        ds_bot.start(TOKEN_DISCORD),
        dp.start_polling(tg_bot)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен.")
