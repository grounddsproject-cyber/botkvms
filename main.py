import discord
import asyncio
import json
import os
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.session.aiohttp import AiohttpSession

# ==================== НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ====================
# Хостинг сам подставит эти значения из настроек проекта
TOKEN_DISCORD = os.getenv("DISCORD_TOKEN", "YOUR_DISCORD_TOKEN")
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN")
ADMIN_TG_ID = int(os.getenv("ADMIN_TG_ID", "123456789"))

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
            with open(path, "r", encoding="utf-8") as f: return json.load(f)
        except: return default
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)

config = load_json(CONFIG_FILE, {"status_channel_id": 0, "status_message_id": 0, "report_channel_id": 0, "report_message_id": 0})
statuses = load_json(STATUS_FILE, {s: {"status": 5, "note": ""} for s in SERVERS})
for s in SERVERS:
    if s not in statuses: statuses[s] = {"status": 5, "note": ""}
save_json(STATUS_FILE, statuses)

last_statuses_snapshot = json.dumps(statuses, sort_keys=True)

# ==================== DISCORD ЧАСТЬ ====================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
ds_bot = discord.Client(intents=intents)

def build_status_message():
    global statuses
    statuses = load_json(STATUS_FILE, statuses)
    lines = ["[2;37m===== СТАТУС СЕРВЕРОВ =====[0m", ""]
    for server in SERVERS:
        data = statuses.get(server, {"status": 5, "note": ""})
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
    channel_id = config.get("status_channel_id", 0)
    if not channel_id: return
    channel = ds_bot.get_channel(channel_id)
    if not channel: return

    msg_id = config.get("status_message_id", 0)
    try:
        if msg_id:
            msg = await channel.fetch_message(msg_id)
            await msg.edit(content=build_status_message())
        else:
            msg = await channel.send(build_status_message())
            config["status_message_id"] = msg.id
            save_json(CONFIG_FILE, config)
    except Exception:
        msg = await channel.send(build_status_message())
        config["status_message_id"] = msg.id
        save_json(CONFIG_FILE, config)

    if changed_server:
        try:
            ping = await channel.send(f"@everyone Статус сервера **{changed_server}** был обновлён!")
            await asyncio.sleep(10)
            await ping.delete()
        except: pass

async def check_status_changes():
    global last_statuses_snapshot
    while True:
        await asyncio.sleep(3)
        try:
            current = load_json(STATUS_FILE, statuses)
            current_snap = json.dumps(current, sort_keys=True)
            if current_snap != last_statuses_snapshot:
                changed = next((s for s in SERVERS if statuses.get(s) != current.get(s)), None)
                statuses.clear()
                statuses.update(current)
                last_statuses_snapshot = current_snap
                await update_status_message(changed)
                logging.info(f"Статус обновлен: {changed}")
        except Exception as e:
            logging.error(f"Ошибка проверки статусов: {e}")

@ds_bot.event
async def on_ready():
    logging.info(f"Discord бот запущен: {ds_bot.user}")
    if config.get("status_channel_id"): await update_status_message()
    ds_bot.loop.create_task(check_status_changes())

@ds_bot.event
async def on_message(message: discord.Message):
    if message.author == ds_bot.user: return

    # Канал жалоб
    if message.channel.id == config.get("report_channel_id", 0) and config.get("report_channel_id", 0) != 0:
        if message.id == config.get("report_message_id"): return
        content = message.content.strip()
        try: await message.delete()
        except: pass

        if content == ".repcon":
            notify = await message.channel.send("✅ Информация была успешно отправлена хосту. Ожидайте проверки.")
            reports = load_json(REPORTS_FILE, [])
            reports.append({"user": str(message.author), "user_id": message.author.id, "guild": message.guild.name, "time": datetime.now().strftime("%d.%m.%Y %H:%M:%S")})
            save_json(REPORTS_FILE, reports)
            await asyncio.sleep(10)
            try: await notify.delete()
            except: pass
        else:
            warn = await message.channel.send(f"⚠️ {message.author.mention}, здесь принимаются **только команды**. Используйте `.repcon`")
            await asyncio.sleep(5)
            try: await warn.delete()
            except: pass
        return

    # Команды админа
    if message.content.startswith(DS_PREFIX) and message.author.guild_permissions.administrator:
        cmd = message.content[len(DS_PREFIX):].strip().lower()
        if cmd == "help":
            await message.channel.send(f"**Команды:**\n`{DS_PREFIX}setstatuschannel` - канал статусов\n`{DS_PREFIX}setrepconchannel` - канал жалоб")
        elif cmd == "setstatuschannel":
            config["status_channel_id"] = message.channel.id
            save_json(CONFIG_FILE, config)
            msg = await message.channel.send(build_status_message())
            config["status_message_id"] = msg.id
            save_json(CONFIG_FILE, config)
            await message.channel.send("✅ Канал статусов установлен!")
        elif cmd == "setrepconchannel":
            config["report_channel_id"] = message.channel.id
            text = "Если вы испытываете проблемы с подключением к серверу, напишите команду `.repcon` в этот чат **ТОЛЬКО В ЭТОТ ЧАТ**"
            msg = await message.channel.send(text)
            config["report_message_id"] = msg.id
            save_json(CONFIG_FILE, config)
            await message.channel.send("✅ Канал жалоб установлен!")

# ==================== TELEGRAM ЧАСТЬ ====================
class NoteStates(StatesGroup):
    waiting_note = State()

# ВАЖНО: Если на хостинге всё равно будет ошибка подключения к Telegram, 
# раскомментируй строки ниже и вставь свой прокси (можно взять бесплатный на proxy6.net)
# proxy_url = "http://login:password@ip:port" 
# session = AiohttpSession(proxy=proxy_url)
# tg_bot = Bot(token=TOKEN_TELEGRAM, session=session)

tg_bot = Bot(token=TOKEN_TELEGRAM)
dp = Dispatcher(storage=MemoryStorage())

async def build_main_menu():
    buttons = [[InlineKeyboardButton(text=f"{s} [{STATUS_NAMES[statuses[s]['status']]}]", callback_data=f"srv:{s}")] for s in SERVERS]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def build_server_menu(server: str):
    data = statuses.get(server, {"status": 5, "note": ""})
    buttons = [[InlineKeyboardButton(text=f"{'✅ ' if c == data['status'] else ''}{n}", callback_data=f"set:{server}:{c}")] for c, n in STATUS_NAMES.items()]
    buttons.append([InlineKeyboardButton(text="📝 Изменить заметку" if data.get("note") else "📝 Добавить заметку", callback_data=f"note:{server}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back:main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def check_reports():
    last_count = len(load_json(REPORTS_FILE, []))
    while True:
        await asyncio.sleep(5)
        try:
            reports = load_json(REPORTS_FILE, [])
            if len(reports) > last_count:
                for r in reports[last_count:]:
                    await tg_bot.send_message(ADMIN_TG_ID, f"🚨 **Жалоба на подключение!**\nПользователь: **{r['user']}**\nСервер: **{r['guild']}**\nВремя: {r['time']}", parse_mode="Markdown")
                last_count = len(reports)
        except Exception as e:
            logging.error(f"Ошибка проверки жалоб: {e}")

@dp.message(CommandStart())
async def start_handler(message: Message):
    if message.from_user.id != ADMIN_TG_ID: return await message.answer("⛔ Доступ запрещён.")
    await message.answer("👋 <b>Панель управления</b>\nВыберите сервер:", reply_markup=await build_main_menu(), parse_mode="HTML")

@dp.callback_query()
async def callback_handler(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_TG_ID: return await callback.answer("⛔ Доступ запрещён", show_alert=True)
    data = callback.data

    if data == "back:main":
        await state.clear()
        await callback.message.edit_text("👋 <b>Панель управления</b>\nВыберите сервер:", reply_markup=await build_main_menu(), parse_mode="HTML")
    elif data.startswith("srv:"):
        server = data[4:]
        d = statuses.get(server, {"status": 5, "note": ""})
        await callback.message.edit_text(f"🖥 <b>{server}</b>\nСтатус: <b>{STATUS_NAMES[d['status']]}</b>\nЗаметка: <i>{d.get('note') or '—'}</i>", reply_markup=await build_server_menu(server), parse_mode="HTML")
    elif data.startswith("set:"):
        _, server, code = data.split(":")
        statuses[server]["status"] = int(code)
        save_json(STATUS_FILE, statuses)
        d = statuses.get(server, {"status": 5, "note": ""})
        await callback.message.edit_text(f"🖥 <b>{server}</b>\nСтатус: <b>{STATUS_NAMES[int(code)]}</b>\nЗаметка: <i>{d.get('note') or '—'}</i>", reply_markup=await build_server_menu(server), parse_mode="HTML")
        await callback.answer("✅ Статус обновлён")
    elif data.startswith("note:"):
        await state.update_data(server=data[5:])
        await state.set_state(NoteStates.waiting_note)
        await callback.message.edit_text("📝 Введите новую заметку (или `-` для удаления):")

@dp.message(NoteStates.waiting_note)
async def note_handler(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_TG_ID: return
    data = await state.get_data()
    server = data.get("server")
    if not server: return
    statuses[server]["note"] = "" if message.text.strip() == "-" else message.text.strip()
    save_json(STATUS_FILE, statuses)
    await state.clear()
    await message.answer(f"✅ Заметка для {server} обновлена.", reply_markup=await build_server_menu(server), parse_mode="HTML")

# ==================== ЗАПУСК ОБОИХ БОТОВ ====================
async def main():
    asyncio.create_task(check_reports())
    # Запускаем Discord и Telegram параллельно в одном процессе
    await asyncio.gather(
        ds_bot.start(TOKEN_DISCORD),
        dp.start_polling(tg_bot)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен.")