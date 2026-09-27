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
TOKEN_DISCORD = os.getenv("DISCORD_TOKEN")
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN")
ADMIN_TG_ID = int(os.getenv("ADMIN_TG_ID", "0"))
DS_PREFIX = "!"

SERVERS = ["The bruh Land", "Пивные дали", "Движуха"]

ESC = "\x1b"
ANSI_STATUS = {
    1: f"{ESC}[2;33mТехнические работы{ESC}[0m",
    2: f"{ESC}[2;36mСервер работает{ESC}[0m",
    3: f"{ESC}[2;31mСервер остановлен{ESC}[0m",
    4: f"{ESC}[2;31mСервер остановлен [открывается по запросу, расписания нету]{ESC}[0m",
    5: f"{ESC}[2;34mНеизвестно{ESC}[0m",
}
STATUS_NAMES = {1: "Технические работы", 2: "Сервер работает", 3: "Сервер остановлен", 4: "Остановлен [по запросу]", 5: "Неизвестно"}

CONFIG_FILE = "config.json"
STATUS_FILE = "statuses.json"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ==================== ХРАНИЛИЩЕ ====================
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f: return json.load(f)
        except: return default
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)

discord_config = load_json(CONFIG_FILE, {"status_channel_id": 0, "status_message_id": 0, "report_channel_id": 0, "report_message_id": 0})
server_data = load_json(STATUS_FILE, {s: {"status": 5, "note": ""} for s in SERVERS})
for s in SERVERS:
    if s not in server_data: server_data[s] = {"status": 5, "note": ""}
save_json(CONFIG_FILE, discord_config)
save_json(STATUS_FILE, server_data)

update_discord_func = None
send_tg_alert_func = None

# ==================== DISCORD БОТ ====================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
ds_bot = discord.Client(intents=intents)

def build_status_message():
    lines = ["```ansi", f"{ESC}[2;37m===== СТАТУС СЕРВЕРОВ ====={ESC}[0m", ""]
    for server in SERVERS:
        data = server_data[server]
        status_text = ANSI_STATUS.get(data["status"], ANSI_STATUS[5])
        note = data.get("note", "")
        lines.append(f"{ESC}[1;37m{server}:{ESC}[0m {status_text}")
        if note:
            lines.append(f"   {ESC}[2;37m📝 {note}{ESC}[0m")
        lines.append("")
    lines.append("```")
    return "\n".join(lines)

async def update_discord_status(changed_server=None):
    channel_id = discord_config.get("status_channel_id", 0)
    if not channel_id: return
    channel = ds_bot.get_channel(channel_id)
    if not channel: return

    content = build_status_message()
    msg_id = discord_config.get("status_message_id", 0)
    
    try:
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(content=content)
            except discord.NotFound:
                msg = await channel.send(content)
                discord_config["status_message_id"] = msg.id
                save_json(CONFIG_FILE, discord_config)
        else:
            msg = await channel.send(content)
            discord_config["status_message_id"] = msg.id
            save_json(CONFIG_FILE, discord_config)
    except Exception as e:
        logging.error(f"Ошибка обновления Discord: {e}")

    if changed_server:
        try:
            ping = await channel.send(f"@everyone Статус сервера **{changed_server}** был обновлён!")
            await asyncio.sleep(10)
            await ping.delete()
        except: pass

@ds_bot.event
async def on_ready():
    global update_discord_func
    logging.info(f"✅ Discord бот запущен: {ds_bot.user}")
    logging.info(f"📊 Конфиг: {discord_config}")
    update_discord_func = update_discord_status
    if discord_config.get("status_channel_id"):
        await update_discord_status()

@ds_bot.event
async def on_message(message: discord.Message):
    if message.author == ds_bot.user: return

    # Логируем ВСЕ сообщения для диагностики
    logging.info(f" Сообщение от {message.author} в канале {message.channel.id}: '{message.content}'")

    # --- КАНАЛ ЖАЛОБ (.repcon) ---
    report_channel_id = discord_config.get("report_channel_id", 0)
    logging.info(f"🔍 report_channel_id={report_channel_id}, текущий канал={message.channel.id}")
    
    if message.channel.id == report_channel_id and report_channel_id != 0:
        logging.info(f"✅ Сообщение в канале жалоб! ID сообщения: {message.id}, report_message_id: {discord_config.get('report_message_id')}")
        
        if message.id == discord_config.get("report_message_id"):
            logging.info("⚠️ Это сообщение бота, игнорируем")
            return
        
        content = message.content.strip()
        logging.info(f"📝 Содержание: '{content}'")
        
        # Пытаемся удалить сообщение пользователя
        try:
            await message.delete()
            logging.info("✅ Сообщение удалено")
        except discord.Forbidden:
            logging.error("❌ У бота нет прав 'Управлять сообщениями'! Дайте это право в настройках сервера.")
            await message.channel.send("⚠️ Ошибка: у бота нет прав удалять сообщения. Обратитесь к администратору.")
            return
        except Exception as e:
            logging.error(f"❌ Ошибка удаления: {e}")

        if content == ".repcon":
            logging.info(f"🚨🚨 ПОЛУЧЕНА КОМАНДА .repcon ОТ {message.author}! 🚨🚨")
            notify = await message.channel.send("✅ Информация была успешно отправлена хосту. Ожидайте проверки.")
            
            # Прямое уведомление в Telegram
            if send_tg_alert_func:
                logging.info("📱 Отправляем уведомление в Telegram...")
                await send_tg_alert_func(str(message.author), message.guild.name, datetime.now().strftime("%d.%m.%Y %H:%M:%S"))
                logging.info("✅ Уведомление отправлено в Telegram")
            else:
                logging.error("❌ send_tg_alert_func не установлен!")
            
            await asyncio.sleep(10)
            try: await notify.delete()
            except: pass
        else:
            logging.info(f"⚠️ Не команда .repcon, отправляем предупреждение")
            warn = await message.channel.send(f"⚠️ {message.author.mention}, здесь принимаются **только команды**. Используйте `.repcon`")
            await asyncio.sleep(5)
            try: await warn.delete()
            except: pass
        return

    # --- КОМАНДЫ АДМИНА ---
    if message.content.startswith(DS_PREFIX) and message.author.guild_permissions.administrator:
        cmd = message.content[len(DS_PREFIX):].strip().lower()
        logging.info(f" Команда админа: {cmd}")
        
        if cmd == "help":
            await message.channel.send(f"**Команды:**\n`{DS_PREFIX}setstatuschannel` - канал статусов\n`{DS_PREFIX}setrepconchannel` - канал жалоб")
        
        elif cmd == "setstatuschannel":
            discord_config["status_channel_id"] = message.channel.id
            discord_config["status_message_id"] = 0
            save_json(CONFIG_FILE, discord_config)
            await update_discord_status()
            await message.channel.send("✅ Канал статусов установлен!")
            logging.info(f"✅ Установлен канал статусов: {message.channel.id}")
        
        elif cmd == "setrepconchannel":
            discord_config["report_channel_id"] = message.channel.id
            save_json(CONFIG_FILE, discord_config)
            text = "Если вы испытываете проблемы с подключением к серверу, напишите команду `.repcon` в этот чат **ТОЛЬКО В ЭТОТ ЧАТ**"
            msg = await message.channel.send(text)
            discord_config["report_message_id"] = msg.id
            save_json(CONFIG_FILE, discord_config)
            await message.channel.send("✅ Канал жалоб установлен! (Не забудьте дать боту право 'Управлять сообщениями')")
            logging.info(f"✅ Установлен канал жалоб: {message.channel.id}, ID сообщения: {msg.id}")

# ==================== TELEGRAM БОТ ====================
tg_bot = Bot(token=TOKEN_TELEGRAM)
dp = Dispatcher(storage=MemoryStorage())

class NoteStates(StatesGroup):
    waiting_note = State()

async def build_main_menu():
    buttons = [[InlineKeyboardButton(text=f"{s} [{STATUS_NAMES[server_data[s]['status']]}]", callback_data=f"srv:{s}")] for s in SERVERS]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def build_server_menu(server: str):
    data = server_data[server]
    buttons = [[InlineKeyboardButton(text=f"{'✅ ' if c == data['status'] else ''}{n}", callback_data=f"set:{server}:{c}")] for c, n in STATUS_NAMES.items()]
    buttons.append([InlineKeyboardButton(text=" Изменить заметку" if data.get("note") else "📝 Добавить заметку", callback_data=f"note:{server}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back:main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def send_tg_alert(user, guild, time):
    try:
        logging.info(f"📤 Отправка в Telegram: ADMIN_TG_ID={ADMIN_TG_ID}")
        await tg_bot.send_message(
            ADMIN_TG_ID,
            f" <b>Жалоба на подключение!</b>\n\nПользователь: <b>{user}</b>\nСервер: <b>{guild}</b>\nВремя: {time}",
            parse_mode="HTML"
        )
        logging.info("✅ Сообщение отправлено в Telegram")
    except Exception as e:
        logging.error(f"❌ Ошибка отправки в Telegram: {e}")

@dp.message(CommandStart())
async def start_handler(message: Message):
    if message.from_user.id != ADMIN_TG_ID:
        await message.answer(f" Доступ запрещён.\nТвой ID: `{message.from_user.id}`\nНужен: `{ADMIN_TG_ID}`")
        return
    await message.answer("👋 <b>Панель управления</b>\nВыберите сервер:", reply_markup=await build_main_menu(), parse_mode="HTML")

@dp.callback_query()
async def callback_handler(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_TG_ID:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    data = callback.data

    if data == "back:main":
        await state.clear()
        await callback.message.edit_text(" <b>Панель управления</b>\nВыберите сервер:", reply_markup=await build_main_menu(), parse_mode="HTML")
    elif data.startswith("srv:"):
        server = data[4:]
        d = server_data[server]
        await callback.message.edit_text(f"🖥 <b>{server}</b>\nСтатус: <b>{STATUS_NAMES[d['status']]}</b>\nЗаметка: <i>{d.get('note') or '—'}</i>", reply_markup=await build_server_menu(server), parse_mode="HTML")
    elif data.startswith("set:"):
        _, server, code = data.split(":")
        code = int(code)
        server_data[server]["status"] = code
        save_json(STATUS_FILE, server_data)
        logging.info(f"✅ Telegram изменил статус: {server} -> {code}")
        
        if update_discord_func:
            await update_discord_func(changed_server=server)
        
        d = server_data[server]
        await callback.message.edit_text(f"🖥 <b>{server}</b>\nСтатус: <b>{STATUS_NAMES[code]}</b>\nЗаметка: <i>{d.get('note') or '—'}</i>", reply_markup=await build_server_menu(server), parse_mode="HTML")
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
    
    text = message.text.strip()
    server_data[server]["note"] = "" if text == "-" else text
    save_json(STATUS_FILE, server_data)
    logging.info(f"✅ Telegram изменил заметку: {server}")
    
    if update_discord_func:
        await update_discord_func()
    
    await state.clear()
    await message.answer(f"✅ Заметка для {server} обновлена.", reply_markup=await build_server_menu(server), parse_mode="HTML")

# ==================== ЗАПУСК ====================
async def main():
    global send_tg_alert_func
    logging.info("=" * 50)
    logging.info("ЗАПУСК ОБОИХ БОТОВ")
    logging.info("=" * 50)
    logging.info(f"Discord токен: {'✅' if TOKEN_DISCORD else '❌'}")
    logging.info(f"Telegram токен: {'✅' if TOKEN_TELEGRAM else '❌'}")
    logging.info(f"ADMIN_TG_ID: {ADMIN_TG_ID}")
    logging.info(f"Конфиг: {discord_config}")
    
    send_tg_alert_func = send_tg_alert
    
    await asyncio.gather(
        ds_bot.start(TOKEN_DISCORD),
        dp.start_polling(tg_bot)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен.")
