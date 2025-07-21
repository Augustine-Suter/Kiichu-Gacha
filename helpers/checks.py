
#-------------------PERMISSION CHECKS-----------------------------#

import json
import os
from typing import Callable, TypeVar

from discord.ext import commands

from helpers.exceptions import *
from helpers import database

T = TypeVar("T")


def is_owner() -> Callable[[T], T]:
    async def predicate(context: commands.Context) -> bool:
        with open(
            f"{os.path.realpath(os.path.dirname(__file__))}/../config.json"
        ) as file:
            data = json.load(file)
        if context.author.id not in data["owners"]:
            raise UserNotOwner
        return True

    return commands.check(predicate)


def not_blacklisted() -> Callable[[T], T]:
    async def predicate(context: commands.Context) -> bool:
        if await database.is_blacklisted(context.author.id):
            raise UserBlacklisted
        return True

    return commands.check(predicate)


def is_trusted() -> Callable[[T], T]:
    async def predicate(context: commands.Context) -> bool:
        with open(
            f"{os.path.realpath(os.path.dirname(__file__))}/../config.json"
        ) as file:
            data = json.load(file)
        if context.author.id not in data["trustedUsers"]:
            raise UserNotTrusted
        return True

    return commands.check(predicate)


def is_moderator() -> Callable[[T], T]:
    async def predicate(context: commands.Context) -> bool:
        with open(f"{os.path.realpath(os.path.dirname(__file__))}/../config.json") as file:
            data = json.load(file)
        mod_roles = data.get("modRoles", [])
        if not any(role.id in mod_roles for role in context.author.roles):
            raise UserNotModerator
        
        return True

    return commands.check(predicate)