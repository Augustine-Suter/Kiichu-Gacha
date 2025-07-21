
#------------------ THROWN EXCEPTIONS----------------------------#

from discord.ext import commands
from helpers.emotes import emotes


class UserBlacklisted(commands.CheckFailure):
    def __init__(self, message=f"You are blacklisted from using this bot! {emotes['ded']}"):
        self.message = message
        super().__init__(self.message)

class UserNotOwner(commands.CheckFailure):
    def __init__(self, message=f"You do not have permission to use this command! {emotes['ded']}"):
        self.message = message
        super().__init__(self.message)

class UserNotTrusted(commands.CheckFailure):
    def __init__(self, message=f"You do not have permission to use this command! {emotes['ded']}"):
        self.message = message
        super().__init__(self.message)

class UserNotModerator(commands.CheckFailure):
    def __init__(self, message=f"You do not have permission to use this command! {emotes['ded']}"):
        self.message = message
        super().__init__(self.message)