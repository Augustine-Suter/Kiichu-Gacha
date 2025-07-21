
# KiichuBot v1.0.0
# DEV: Angryappleseed (angryappleseed on discord)
# Last Updated: Feb 28, 2024
from signal import SIGINT, SIGTERM
import contextlib
from contextlib import asynccontextmanager
import aiosqlite
import asyncio
import json
import logging
import os
import sys

import platform
import random

import discord
from discord.ext import commands, tasks
from discord.ext.commands import Bot, Context

import helpers.exceptions as exceptions
from datetime import datetime
from helpers.colors import colors
from helpers.emotes import emotes


# ------------------INTENTS---------------------#

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


# ----------------------------LOAD CONFIG.JSON--------------------------#

if not os.path.isfile(f"{os.path.realpath(os.path.dirname(__file__))}/config.json"):
    sys.exit("'config.json' was not found")
else:
    with open(f"{os.path.realpath(os.path.dirname(__file__))}/config.json") as file:
        config = json.load(file)




        
#--------------Default Prefix in Config.json--------------------#
default_prefix = config["prefix"]
    

#----------------------------KIICHUBOT-----------------------------#

class KiichuBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log_channel = {} 
        self.active_ban_votes = {}

# -------------------GET SERVER PREFIXES---------------------------#
    
    async def get_custom_prefix(self, message):
        bot_mention = f'<@{self.user.id}> '
        prefixes = [self.default_prefix, bot_mention]

        if message.guild is not None:
            server_id = str(message.guild.id)
            custom_prefix = self.custom_prefixes.get(server_id)
            if custom_prefix:
                prefixes = [custom_prefix]

        return tuple(prefixes)



bot = KiichuBot(command_prefix=KiichuBot.get_custom_prefix, 
                 intents=intents, 
                 help_command=None,
                 case_insensitive=True)



bot.default_prefix = default_prefix
bot.custom_prefixes = {}
bot.config = config


#--------------------TERMINAL LOGGING-----------------------------#

class LoggingFormatter(logging.Formatter):
    black = "\x1b[30m"
    red = "\x1b[31m"
    green = "\x1b[32m"
    yellow = "\x1b[33m"
    blue = "\x1b[34m"
    gray = "\x1b[38m"
    reset = "\x1b[0m"
    bold = "\x1b[1m"

    COLORS = {
        logging.DEBUG: gray + bold,
        logging.INFO: blue + bold,
        logging.WARNING: yellow + bold,
        logging.ERROR: red,
        logging.CRITICAL: red + bold,
    }

    def format(self, record):
        log_color = self.COLORS[record.levelno]
        format = "(black){asctime}(reset) (levelcolor){levelname:<8}(reset) (green){name}(reset) {message}"
        format = format.replace("(black)", self.black + self.bold)
        format = format.replace("(reset)", self.reset)
        format = format.replace("(levelcolor)", log_color)
        format = format.replace("(green)", self.green + self.bold)
        formatter = logging.Formatter(format, "%Y-%m-%d %H:%M:%S", style="{")
        return formatter.format(record)


logger = logging.getLogger("KiichuBot")
logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(LoggingFormatter())

file_handler = logging.FileHandler(filename="discord.log", encoding="utf-8", mode="w")
file_handler_formatter = logging.Formatter(
    "[{asctime}] [{levelname:<8}] {name}: {message}", "%Y-%m-%d %H:%M:%S", style="{"
)
file_handler.setFormatter(file_handler_formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)
bot.logger = logger






#-------------------------------LOAD DATABASE--------------------------#

async def init_db():
    async with aiosqlite.connect(
        f"{os.path.realpath(os.path.dirname(__file__))}/database/database.db"
    ) as db:
        # Enable WAL mode and set busy timeout
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA busy_timeout=5000;")
        
        with open(
            f"{os.path.realpath(os.path.dirname(__file__))}/database/schema.sql"
        ) as file:
            await db.executescript(file.read())
        await db.commit()





#---------------------------ON READY------------------------------#

@bot.event
async def on_ready():
    
    # Initialize the database
    await init_db()
    # Load server prefixes
    await load_prefixes()
    
    statuses = ["with your feelings~", "Palworld!", "Tetrio :D", "League of Legends"]
    selected_status = random.choice(statuses)
    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Game(name=selected_status)
        )
    bot.logger.info(f"Hi hi! It's {bot.user.name}!")
    bot.logger.info(f"My current version is: {config['version']}!")
    bot.logger.info(f"My status is set to: 'Playing {selected_status}'")
    bot.logger.info(f"Curent discord.py API version: {discord.__version__}")
    bot.logger.info(f"Python version: {platform.python_version()}")
    bot.logger.info(f"Running on: {platform.system()} {platform.release()} ({os.name})")
    if config["sync_commands_globally"]:
        bot.logger.info("Syncing commands globally...")
        await bot.tree.sync()
    bot.logger.info(f"#KiichuBot")




#
#-------------------------------EVENTS LISTENERS--------------------------------#
#




#------------------------ON GUILD JOIN-------------------------#
@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
   pass


#------------------------ON GUILD LEAVE-------------------------#
@bot.event
async def on_guild_remove(guild):
    pass


#------------------------ON DISCONNECT-------------------------#
@bot.event
async def on_disconnect():
    pass


#---------------------ON COMMAND COMPLETION--------------------#
@bot.event
async def on_command_completion(context: Context) -> None:
    full_command_name = context.command.qualified_name
    split = full_command_name.split(" ")
    executed_command = str(split[0])
    if context.guild is not None:
        bot.logger.info(
            f"Executed {executed_command} command in {context.guild.name} (ID: {context.guild.id}) by {context.author} (ID: {context.author.id})"
        )
    else:
        bot.logger.info(
            f"Executed {executed_command} command by {context.author} (ID: {context.author.id}) in DMs"
        )





# ---------------------------------ERROR HANDLING----------------------------------------#

@bot.event
async def on_command_error(context: commands.Context, error) -> None:
    #-------------------COMMAND ON COOLDOWN------------------------#
    if isinstance(error, commands.CommandOnCooldown):
        # Calculate when the command will be available again
        now = datetime.now().timestamp()
        retry_time = int(now + error.retry_after)
        
        embed = discord.Embed(
            description=(
                f"**Please slow down!** {emotes['ded']}\n"
                f"You can use this again in a couple seconds!"
            ),
            color=colors["red"]
        )
        
        # Send and delete after cooldown duration + 1 second buffer
        msg = await context.send(embed=embed)
        await msg.delete(delay=error.retry_after + 1)


    #-------------------USER IS BLACKLISTED------------------------#
    elif isinstance(error, exceptions.UserBlacklisted):
        embed = discord.Embed(
            description=f"You are blacklisted from using the bot! {emotes['ded']}", color=colors["red"]
        )
        await context.send(embed=embed)
        if context.guild:
            bot.logger.warning(
                f"Blacklisted user {context.author} (ID: {context.author.id}) tried to execute a command in the guild {context.guild.name} (ID: {context.guild.id})."
            )
        else:
            bot.logger.warning(
                f"Blacklisted user {context.author} (ID: {context.author.id}) tried to execute a command in the bot's DMs."
            )

    #-------------------USER IS NOT AN OWNER------------------------#
    elif isinstance(error, exceptions.UserNotOwner):
        embed = discord.Embed(
            description=f"You are not the owner of KiichuBot! {emotes['ded']}", color=colors["red"]
        )
        await context.send(embed=embed)
        if context.guild:
            bot.logger.warning(
                f"{context.author} (ID: {context.author.id}) tried to execute an owner only command in the guild {context.guild.name} (ID: {context.guild.id})."
            )
        else:
            bot.logger.warning(
                f"{context.author} (ID: {context.author.id}) tried to execute an owner only command in the bot's DMs."
            )


    #-------------------USER IS NOT TRUSTED------------------------#
    elif isinstance(error, exceptions.UserNotTrusted):
        embed = discord.Embed(
            description=f"You are not a Trusted User of KiichuBot! {emotes['ded']}", color=colors["red"]
        )
        await context.send(embed=embed)
        if context.guild:
            bot.logger.warning(
                f"{context.author} (ID: {context.author.id}) tried to execute a trusted-user only command in the guild {context.guild.name} (ID: {context.guild.id})."
            )
        else:
            bot.logger.warning(
                f"{context.author} (ID: {context.author.id}) tried to execute a trusted-user only command in the bot's DMs."
            )


    #-------------------USER IS NOT MODERATORr------------------------#
    elif isinstance(error, exceptions.UserNotModerator):
        embed = discord.Embed(
            description=f"You are not a Moderator! {emotes['ded']}", color=colors["red"]
        )
        await context.send(embed=embed)
        if context.guild:
            bot.logger.warning(
                f"{context.author} (ID: {context.author.id}) tried to execute a moderator only command in the guild {context.guild.name} (ID: {context.guild.id})."
            )
        else:
            bot.logger.warning(
                f"{context.author} (ID: {context.author.id}) tried to execute amoderator only command in the bot's DMs."
            )


    #--------------------USER LACKS PERMISSIONS------------------#
    elif isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            description="You are missing the permission(s) `" + ", ".join(error.missing_permissions) + f"` to execute this command! {emotes['ded']}",
            color=colors["red"],
        )
        await context.send(embed=embed)

    #---------------------BOT LACKS PERMISSIONS------------------#
    elif isinstance(error, commands.BotMissingPermissions):
        embed = discord.Embed(
            description="I am missing the permission(s) `" + ", ".join(error.missing_permissions) + f"` to fully perform this command! {emotes['ded']}",
            color=colors["red"],
        )
        await context.send(embed=embed)

    #-------------------MISSING ARGUMENT------------------#
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title=f"Error! {emotes['ded']}",
            description=str(error).capitalize(),
            color=colors["red"],
        )
        await context.send(embed=embed)
    else:
        raise error




#
#-------------------------------------------------------------------------------------------
#

#-----------------------------LOAD COGS-------------------------------------#
async def load_cogs() -> None:
    for file in os.listdir(f"{os.path.realpath(os.path.dirname(__file__))}/cogs"):
        if file.endswith(".py"):
            extension = file[:-3]
            try:
                await bot.load_extension(f"cogs.{extension}")
                bot.logger.info(f"Loaded extension: '{extension}'")
            except Exception as e:
                exception = f"{type(e).__name__}: {e}"
                bot.logger.error(f"Failed to load extension: {extension}\n{exception}")



#-----------------------------LOAD PREFIXES--------------------------------#
async def load_prefixes() -> None:
    async with aiosqlite.connect(
        f"{os.path.realpath(os.path.dirname(__file__))}/database/database.db"
    ) as db:
        async with db.execute("SELECT * FROM prefixes") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                bot.custom_prefixes[row[0]] = row[1]



# RUN THE BOT
asyncio.run(init_db())
asyncio.run(load_cogs())
bot.run(config["token"])
