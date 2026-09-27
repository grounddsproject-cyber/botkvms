import discord
import asyncio
import os
import logging
import asyncpg
from datetime import datetime

# ==================== НАСТРОЙКИ ====================
TOKEN_DISCORD = os.getenv("DISCORD_TOKEN", "YOUR_DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@db.xxx.supabase.co:5432/postgres")

DS_PREFIX = "!"
SERVERS = ["The bruh Land", "Пивные дали", "Движуха"]

STATUSES = {
    1: "[2;33mТехнические работы[0m",
    2: "[2;36mСервер работает[0m",
    3: "[2;31mСервер остановлен[0m",
    4: "[2;31mСервер остановлен [открывается по запросу, расписания нету][0m",
    5: "[2;34mНеизвестно[0m",
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ==================== БАЗА ДАННЫХ ====================
db_pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    logging.info("Подключение к БД установлено")

async def get_config(key):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM config WHERE key = $1", key)
        return int(row["value"]) if row else 0

async def set_config(key, value):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE config SET value = $1 WHERE key = $2", str(value), key)

async def get_all_servers():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT name, status, note FROM servers ORDER BY id")
        return [(r["name"], r["status"], r["note"]) for r in rows]

async def build_status_message():
    servers = await get_all_servers()
    lines = ["[2;37m===== СТАТУС СЕРВЕРОВ =====[0m", ""]
    for name, status, note in servers:
        status_text = STATUSES.get(status, STATUSES[5])
        if note:
            lines.append(f"[1;37m{name}:[0m {status_text}")
            lines.append(f"   [2;37m📝 {note}[0m")
        else:
            lines.append(f"[1;37m{name}:[0m {status_text}")
        lines.append("")
    return "```ansi\n" + "\n".join(lines) + "```"

# ==================== DISCORD BOT ====================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
ds_bot = discord.Client(intents=intents)

async def update_status_message(changed_server=None):
    channel_id = await get_config("status_channel_id")
    if not channel_id:
        return
    channel = ds_bot.get_channel(channel_id)
    if not channel:
        return

    msg_id = await get_config("status_message_id")
    content = await build_status_message()

    try:
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(content=content)
            except discord.NotFound:
                msg = await channel.send(content)
                await set_config("status_message_id", msg.id)
        else:
            msg = await channel.send(content)
            await set_config("status_message_id", msg.id)
    except Exception as e:
        logging.error(f"Ошибка обновления сообщения: {e}")
        msg = await channel.send(content)
        await set_config("status_message_id", msg.id)

    if changed_server:
        try:
            ping = await channel.send(f"@everyone Статус сервера **{changed_server}** был обновлён!")
            await asyncio.sleep(10)
            await ping.delete()
        except:
            pass

async def check_status_changes():
    """Проверяет изменения в БД каждые 3 секунды"""
    last_snapshot = None
    await asyncio.sleep(2)  # Даём время на инициализацию
    
    while True:
        try:
            servers = await get_all_servers()
            snapshot = str(servers)
            
            if last_snapshot is not None and snapshot != last_snapshot:
                # Нашли изменённый сервер
                last_dict = {name: (s, n) for name, s, n in (last_snapshot if isinstance(last_snapshot, list) else eval(last_snapshot.replace("'", '"')))}
                changed = None
                for name, status, note in servers:
                    if last_dict.get(name) != (status, note):
                        changed = name
                        break
                
                await update_status_message(changed)
                logging.info(f"Статус обновлен: {changed}")
            
            last_snapshot = snapshot
        except Exception as e:
            logging.error(f"Ошибка проверки изменений: {e}")
        
        await asyncio.sleep(3)

async def ensure_report_message(channel: discord.TextChannel):
    text = "Если вы испытываете проблемы с подключением к серверу, напишите команду `.repcon` в этот чат **ТОЛЬКО В ЭТОТ ЧАТ**"
    msg_id = await get_config("report_message_id")
    if msg_id:
        try:
            msg = await channel.fetch_message(msg_id)
            await msg.edit(content=text)
            return
        except discord.NotFound:
            pass
    msg = await channel.send(text)
    await set_config("report_channel_id", channel.id)
    await set_config("report_message_id", msg.id)

@ds_bot.event
async def on_ready():
    logging.info(f"Discord бот запущен: {ds_bot.user}")
    await init_db()
    ds_bot.loop.create_task(check_status_changes())

@ds_bot.event
async def on_message(message: discord.Message):
    if message.author == ds_bot.user:
        return

    # Канал жалоб
    report_channel_id = await get_config("report_channel_id")
    if message.channel.id == report_channel_id and report_channel_id != 0:
        report_msg_id = await get_config("report_message_id")
        if message.id == report_msg_id:
            return
        
        content = message.content.strip()
        try:
            await message.delete()
        except:
            pass

        if content == ".repcon":
            notify = await message.channel.send("✅ Информация была успешно отправлена хосту. Ожидайте проверки.")
            
            # Записываем жалобу в БД
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO reports (user_name, user_id, guild_name) VALUES ($1, $2, $3)",
                    str(message.author), message.author.id, message.guild.name
                )
            
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
        
        if cmd == "help":
            await message.channel.send(
                f"**Команды:**\n"
                f"`{DS_PREFIX}setstatuschannel` - канал статусов\n"
                f"`{DS_PREFIX}setrepconchannel` - канал жалоб"
            )
        elif cmd == "setstatuschannel":
            await set_config("status_channel_id", message.channel.id)
            msg = await message.channel.send(await build_status_message())
            await set_config("status_message_id", msg.id)
            await message.channel.send("✅ Канал статусов установлен!")
        elif cmd == "setrepconchannel":
            await ensure_report_message(message.channel)
            await message.channel.send("✅ Канал жалоб установлен!")

if __name__ == "__main__":
    try:
        ds_bot.run(TOKEN_DISCORD)
    except KeyboardInterrupt:
        logging.info("Discord бот остановлен.")
