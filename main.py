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

STATUSES = {
    1: "Технические работы",
    2: "Сервер работает",
    3: "Сервер остановлен",
    4: "Сервер остановлен [открывается по запросу, расписания нету]",
    5: "Неизвестно",
}
STATUS_NAMES = STATUSES.copy()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ==================== ОБЩЕЕ ХРАНИЛИЩЕ В ПАМЯТИ ====================
# Это главная фишка — оба бота работают с ОДНОЙ переменной в памяти
server_data = {s: {"status": 5, "note": ""} for s in SERVERS}
discord_config = {
    "status_channel_id": 0,
    "status_message_id": 0,
    "report_channel_id": 0,
    "report_message_id": 0,
}
reports = []

# ==================== DISCORD БОТ ====================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
ds_bot = discord.Client(intents=intents)

# Ссылка на функцию обновления — будет установлена после создания ботов
update_discord_status_func = None
send_tg_notification_func = None

def build_status_message():
    lines = ["===== СТАТУС СЕРВЕРОВ =====", ""]
    for server in SERVERS:
        data = server_data[server]
        status_text = STATUSES.get(data["status"], "Неизвестно")
        note = data.get("note", "")
        if note:
            lines.append(f"{server}: {status_text}")
            lines.append(f"   📝 {note}")
        else:
            lines.append(f"{server}: {status_text}")
        lines.append("")
    return "```ansi\n" + "\n".join(lines) + "```"

async def update_discord_status(changed_server=None):
    """Обновляет сообщение в Discord"""
    channel_id = discord_config.get("status_channel_id", 0)
    if not channel_id:
        return
    channel = ds_bot.get_channel(channel_id)
    if not channel:
        return

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
        else:
            msg = await channel.send(content)
            discord_config["status_message_id"] = msg.id
    except Exception as e:
        logging.error(f"Ошибка обновления Discord: {e}")

    if changed_server:
        try:
            ping = await channel.send(f"@everyone Статус сервера **{changed_server}** был обновлён!")
            await asyncio.sleep(10)
            await ping.delete()
        except:
            pass

async def send_tg_alert(user, guild, time):
    """Отправляет уведомление в Telegram о жалобе"""
    try:
        await tg_bot.send_message(
            ADMIN_TG_ID,
            f"🚨 <b>Жалоба на подключение!</b>\n\n"
            f"Пользователь: <b>{user}</b>\n"
            f"Сервер: <b>{guild}</b>\n"
            f"Время: {time}",
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Ошибка отправки в TG: {e}")

@ds_bot.event
async def on_ready():
    global update_discord_status_func
    logging.info(f"✅ Discord бот запущен: {ds_bot.user}")
    update_discord_status_func = update_discord_status
    if discord_config.get("status_channel_id"):
        await update_discord_status()

@ds_bot.event
async def on_message(message: discord.Message):
    if message.author == ds_bot.user:
        return

    # Канал жалоб
    report_channel_id = discord_config.get("report_channel_id", 0)
    if message.channel.id == report_channel_id and report_channel_id != 0:
        if message.id == discord_config.get("report_message_id"):
            return
        
        content = message.content.strip()
        try:
            await message.delete()
        except:
            pass

        if content == ".repcon":
            notify = await message.channel.send("✅ Информация была успешно отправлена хосту. Ожидайте проверки.")
            
            # ПРЯМОЕ уведомление в Telegram
            if send_tg_notification_func:
                await send_tg_notification_func(
                    str(message.author),
                    message.guild.name,
                    datetime.now().strftime("%d.%m.%Y %H:%M:%S")
                )
            
            await asyncio.sleep(10)
            try:
                await notify.delete()
            except:
                pass
        else:
            warn = await message.channel.send(f"⚠️ {message.author.mention}, здесь только команды. Используйте `.repcon`")
            await asyncio.sleep(5)
            try:
                await warn.delete()
            except:
                pass
        return

    # Команды админа
    if message.content.startswith(DS_PREFIX) and message.author.guild_permissions.administrator:
        cmd = message.content[len(DS_PREFIX):].strip().lower()
        
        if cmd == "help":
            await message.channel.send(
                f"**Команды:**\n"
                f"`{DS_PREFIX}setstatuschannel` - канал статусов\n"
                f"`{DS_PREFIX}setrepconchannel` - канал жалоб"
            )
        elif cmd == "setstatuschannel":
            discord_config["status_channel_id"] = message.channel.id
            msg = await message.channel.send(build_status_message())
            discord_config["status_message_id"] = msg.id
            await message.channel.send("✅ Канал статусов установлен!")
        elif cmd == "setrepconchannel":
            discord_config["report_channel_id"] = message.channel.id
            text = "Если вы испытываете проблемы с подключением к серверу, напишите команду `.repcon` в этот чат **ТОЛЬКО В ЭТОТ ЧАТ**"
            msg = await message.channel.send(text)
            discord_config["report_message_id"] = msg.id
            await message.channel.send("✅ Канал жалоб установлен!")

# ==================== TELEGRAM БОТ ====================
tg_bot = Bot(token=TOKEN_TELEGRAM)
dp = Dispatcher(storage=MemoryStorage())

class NoteStates(StatesGroup):
    waiting_note = State()

async def build_main_menu():
    buttons = []
    for server in SERVERS:
        data = server_data[server]
        status_name = STATUS_NAMES.get(data["status"], "Неизвестно")
        buttons.append([InlineKeyboardButton(
            text=f"{server} [{status_name}]",
            callback_data=f"srv:{server}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def build_server_menu(server: str):
    data = server_data[server]
    buttons = []
    for code, name in STATUS_NAMES.items():
        mark = "✅ " if code == data["status"] else ""
        buttons.append([InlineKeyboardButton(
            text=f"{mark}{name}",
            callback_data=f"set:{server}:{code}"
        )])
    buttons.append([InlineKeyboardButton(
        text="📝 Изменить заметку" if data.get("note") else " Добавить заметку",
        callback_data=f"note:{server}"
    )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back:main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(CommandStart())
async def start_handler(message: Message):
    if message.from_user.id != ADMIN_TG_ID:
        await message.answer(f"⛔ Доступ запрещён.\nТвой ID: `{message.from_user.id}`\nНужен: `{ADMIN_TG_ID}`")
        return
    await message.answer(
        "👋 <b>Панель управления</b>\nВыберите сервер:",
        reply_markup=await build_main_menu(),
        parse_mode="HTML"
    )

@dp.callback_query()
async def callback_handler(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_TG_ID:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    data = callback.data

    if data == "back:main":
        await state.clear()
        await callback.message.edit_text(
            "👋 <b>Панель управления</b>\nВыберите сервер:",
            reply_markup=await build_main_menu(),
            parse_mode="HTML"
        )
    elif data.startswith("srv:"):
        server = data[4:]
        d = server_data[server]
        await callback.message.edit_text(
            f"🖥 <b>{server}</b>\nСтатус: <b>{STATUS_NAMES[d['status']]}</b>\nЗаметка: <i>{d.get('note') or '—'}</i>",
            reply_markup=await build_server_menu(server),
            parse_mode="HTML"
        )
    elif data.startswith("set:"):
        _, server, code = data.split(":")
        code = int(code)
        
        # МЕНЯЕМ СТАТУС В ОБЩЕЙ ПАМЯТИ
        server_data[server]["status"] = code
        logging.info(f"✅ Telegram изменил статус: {server} -> {code}")
        
        # ПРЯМОЕ обновление Discord
        if update_discord_status_func:
            await update_discord_status_func(changed_server=server)
            logging.info(f"✅ Discord обновлён для: {server}")
        
        d = server_data[server]
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
    
    # МЕНЯЕМ ЗАМЕТКУ В ОБЩЕЙ ПАМЯТИ
    server_data[server]["note"] = note
    logging.info(f"✅ Telegram изменил заметку: {server} -> '{note}'")
    
    # ПРЯМОЕ обновление Discord
    if update_discord_status_func:
        await update_discord_status_func()
        logging.info(f"✅ Discord обновлён (заметка) для: {server}")
    
    await state.clear()
    await message.answer(
        f"✅ Заметка для {server} обновлена.",
        reply_markup=await build_server_menu(server),
        parse_mode="HTML"
    )

# ==================== ЗАПУСК ====================
async def main():
    global send_tg_notification_func
    
    logging.info("=" * 50)
    logging.info("ЗАПУСК ОБОИХ БОТОВ С ПРЯМОЙ СВЯЗЬЮ")
    logging.info("=" * 50)
    
    # Устанавливаем прямую ссылку на функцию уведомлений
    send_tg_notification_func = send_tg_alert
    
    await asyncio.gather(
        ds_bot.start(TOKEN_DISCORD),
        dp.start_polling(tg_bot)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен.")
