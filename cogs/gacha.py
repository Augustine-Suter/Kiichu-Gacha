import aiosqlite
from aiosqlite import connect
import contextlib
from contextlib import contextmanager 
import os
import asyncio
import random
from datetime import datetime, timedelta, timezone
import hashlib
from datetime import timezone, timedelta
from discord.ext.commands import BucketType
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import Button, View, Select

from helpers.colors import colors
from helpers.emotes import emotes

DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database', 'database.db')

# Card Drop ratess
LIMITED_CARD_RATE = 0 # 0 for now, until we decide to add it to the game
LIMITED_CARD_FALLBACK = True
HOLO_DROP_RATE = 0.2
SIGNED_DROP_RATE = 0.2
GOLDEN_SIGNED_CHANCE = 0.1

# Recycling Values
RECYCLE_STANDARD = 15
RECYCLE_HOLO =  30
RECYCLE_SIGNED = 30
RECYCLE_GOLDEN_SIGNED = 100
RECYCLE_HOLO_SIGNED = 80
RECYCLE_HOLO_GOLDEN_SIGNED = 500

# Stardust earned from dailies
DAILY_STARDUST_AMOUNT = 100
DAILY_COOLDOWN = timedelta(seconds=10)

# Channels where you can gain stardust
STARDUST_CHANNELS = [1333255961057562788,1338661794343817328]
# Channels where you can use commands
COMMAND_CHANNELS = [1333562210089435146] 

# Stardust earned per eligible message
MESSAGE_INTERVAL_1 = 20
MESSAGE_INTERVAL_2 = 30
MESSAGE_STARDUST_1 = 15
MESSAGE_STARDUST_2 = 10
MESSAGE_STARDUST_3 = 5
# Cooldown before earning stardust again
MESSAGE_COOLDOWN = 180
# Max messages per day that can earn stardust

# Cost of one card pull
PULL_COST = 100 

GMT8 = ZoneInfo("Asia/Singapore")

LEADERBOARD_TYPES = {
        "pulls": {
            "title": "Most Pulls Done",
            "column": "total_pulls",
            "format": lambda val: f"{val} pull{'s' if val != 1 else ''}"
        },
        "stardust": {
            "title": f"Total Stardust Collected {emotes['stardust']}",
            "column": "total_stardust_collected",
            "format": lambda val: f"{val:,} {emotes['stardust']}"
        },
        "streak": {
            "title": "Longest Daily Streak",
            "column": "longest_daily_streak",
            "format": lambda val: f"{val} day{'s' if val != 1 else ''}"
        }
    }

AUTO_RECYCLE_OPTIONS = {
    0: "Off", 
    1: "Standard Only",
    2: "Standard, Holo, and Signed",
    3: "All Except Holo + Golden Signed"
}

class Database:
    _conn_pool = None

    @classmethod
    async def get_connection(cls):
        if not cls._conn_pool:
            cls._conn_pool = await aiosqlite.connect(
                DATABASE_PATH,
                timeout=30,
                check_same_thread=False
            )
            await cls._conn_pool.execute("PRAGMA journal_mode=WAL;")
            await cls._conn_pool.execute("PRAGMA busy_timeout=5000;")
            cls._conn_pool.row_factory = aiosqlite.Row
        return cls._conn_pool



    @classmethod
    @contextlib.asynccontextmanager
    async def connection(cls):
        conn = await cls.get_connection()
        try:
            yield conn
        finally:
            # Don't close the connection, just ensure transactions commit
            await conn.commit()

            
    @classmethod
    async def close(cls):
        if cls._conn_pool:
            await cls._conn_pool.close()
            cls._conn_pool = None

    

# ------------------- BANNER MANAGEMENT -------------------#


class BannerManager:
    def __init__(self, db_path):
        self.db_path = db_path

    async def activate_banner(self, banner_id):
        async with Database.connection() as db:
            
            try:
                await db.execute("UPDATE banners SET is_active = 0")
                await db.execute("UPDATE banners SET is_active = 1 WHERE id = ?", (banner_id,))
                
            except:
                
                raise

    async def get_active_banner(self):
        async with Database.connection() as db:
            cursor = await db.execute("SELECT id, name FROM banners WHERE is_active = 1")
            return await cursor.fetchone()

    async def add_banner(self, name):
        async with Database.connection() as db:
            await db.execute("INSERT INTO banners (name) VALUES (?)", (name,))
            



# ------------------- Pagination Embed for Pulls -------------------#


class PullResultView(View):
    def __init__(self, embeds, author, timeout=300):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.author = author
        self.current_index = 0

        self.prev_button = Button(label="Previous", style=discord.ButtonStyle.primary)
        self.next_button = Button(label="Next", style=discord.ButtonStyle.primary)

        self.prev_button.callback = self.go_previous
        self.next_button.callback = self.go_next

        self.add_item(self.prev_button)
        self.add_item(self.next_button)


    # only the command author can interact
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "Only the command's author can use these buttons.", ephemeral=True
            )
            return False
        return True

    # update buttons and re-render the embed
    async def update_buttons(self, interaction):
        self.prev_button.disabled = self.current_index == 0
        self.next_button.disabled = self.current_index == len(self.embeds) - 1
        await interaction.response.edit_message(embed=self.embeds[self.current_index], view=self)

    # go to previous card
    async def go_previous(self, interaction):
        self.current_index -= 1
        await self.update_buttons(interaction)

    # go to next card
    async def go_next(self, interaction):
        self.current_index += 1
        await self.update_buttons(interaction)




# ------------------- Inventory Management -------------------#


class InventoryView(View):
    def __init__(self, embeds, command_author, inventory_owner, card_list, bot, gacha, timeout=300, sort_order='rarity'):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.command_author = command_author
        self.inventory_owner = inventory_owner
        self.card_list = card_list
        self.bot = bot
        self.gacha = gacha
        self.current_index = 0
        self.mode = "collection"
        self.sort_order = sort_order  # 'rarity' or 'quantity'
        

        # UI Elements
        self.prev_button = Button(label="Previous", style=discord.ButtonStyle.primary, disabled=True)
        self.next_button = Button(label="Next", style=discord.ButtonStyle.primary)
        self.dropdown = self.create_dropdown(self.get_current_page_cards())
        self.sort_button = Button(
            label="Sort by Quantity" if self.sort_order == 'rarity' else "Sort by Rarity",
            style=discord.ButtonStyle.secondary
        )

        # Button callbacks
        self.prev_button.callback = self.go_previous
        self.next_button.callback = self.go_next
        self.sort_button.callback = self.toggle_sort_order

        # Add items to view
        self.add_item(self.prev_button)
        self.add_item(self.dropdown)
        self.add_item(self.next_button)
        self.add_item(self.sort_button)

        # Disable buttons if only one page
        if len(self.embeds) <= 1:
            self.prev_button.disabled = True
            self.next_button.disabled = True

    async def toggle_sort_order(self, interaction: discord.Interaction):
        self.sort_order = 'quantity' if self.sort_order == 'rarity' else 'rarity'
        self.sort_button.label = "Sort by Rarity" if self.sort_order == 'quantity' else "Sort by Quantity"
        
        # Preserve current page position
        original_page = self.current_index
        
        await self.rebuild_collection(interaction)
        
        # Restore nearest valid page position
        self.current_index = min(original_page, len(self.embeds)-1)
        
        await self.update_inventory_view(interaction)
        
    async def rebuild_collection(self, interaction):
        async with Database.connection() as db:
            try:
                order_clause = self.get_order_clause()
                cursor = await db.execute(f"""
                    SELECT cards.name, cards.artist_name, card_variants.id, 
                    card_variants.image_url, card_variants.holo_type, 
                    card_variants.signature_type, user_inventory.quantity
                    FROM user_inventory
                    INNER JOIN card_variants ON user_inventory.card_variant_id = card_variants.id
                    INNER JOIN cards ON card_variants.card_id = cards.id
                    WHERE user_inventory.user_id = ?
                    ORDER BY {order_clause}, cards.name
                """, (self.inventory_owner.id,))
                collection = await cursor.fetchall()
                
            except Exception as e:
                
                raise

        # Rebuild card list and embeds
        self.card_list, rarest_card = self.process_collection(collection)
        self.embeds = self.create_embeds(self.card_list, rarest_card)
        self.current_index = 0

        # Update footer with current sorting
        for embed in self.embeds:
            embed.set_footer(text=f"{embed.footer.text} | Sorting: {self.sort_order.capitalize()}")
        
        # Update view
        await self.update_inventory_view(interaction)

    def get_order_clause(self):
        if self.sort_order == 'rarity':
            return """CASE
                WHEN card_variants.holo_type = 1 AND card_variants.signature_type = 2 THEN 1
                WHEN card_variants.signature_type = 2 THEN 2
                WHEN card_variants.holo_type = 1 AND card_variants.signature_type = 1 THEN 3
                WHEN card_variants.signature_type = 1 THEN 4
                WHEN card_variants.holo_type = 1 THEN 5
                ELSE 6
            END"""
        else:
            return "user_inventory.quantity DESC"

    def process_collection(self, collection):
        card_list = []
        rarest_card = None

        for item in collection:
            card_name, artist_name, card_variant_id, image_url, holo_type, signature_type, quantity = item

            # Determine variation text
            variations = []
            if holo_type == 1:
                variations.append("Holo")
            if signature_type == 1:
                variations.append("Signed")
            elif signature_type == 2:
                variations.append("Golden Signed")
            variation_text = " ".join(variations) or "Standard"

            summary = f"**{card_name}** ({variation_text}), x{quantity}"


            # Store card data
            card_data = {
                "name": card_name,
                "summary": summary,
                "card_variant_id": card_variant_id,
                "image_url": image_url,
                "holo_type": holo_type,
                "signature_type": signature_type,
                "rarity_value": self.get_rarity_value(holo_type, signature_type)
            }
            card_list.append(card_data)

            # Update rarest card (based on rarity value, even when quantity sorting)
            if not rarest_card or card_data['rarity_value'] < rarest_card['rarity_value']:
                rarest_card = {
                    "image_url": image_url,
                    "rarity_value": card_data['rarity_value']
                }

        return card_list, rarest_card

    def create_embeds(self, card_list, rarest_card):
        embeds = []
        for i in range(0, len(card_list), 10):
            page_cards = card_list[i:i + 10]
            base_color = colors["blue"]

            embed = discord.Embed(
                description="\n".join([card["summary"] for card in page_cards]),
                color=base_color
            )
            embed.set_footer(text=f"Page {i//10 + 1} of {len(card_list)//10 + 1} | Sorting: {self.sort_order.capitalize()}")
            
            if rarest_card and i == 0:
                embed.set_thumbnail(url=rarest_card["image_url"])
                
            embed.set_author(
                name=f"{self.inventory_owner.display_name}'s Collection",
                icon_url=self.inventory_owner.display_avatar.url
            )
            embeds.append(embed)
        return embeds

    # Retrieve cards for the current page (10 per page)
    def get_current_page_cards(self):
        start = self.current_index * 10
        end = start + 10
        return self.card_list[start:end]

    # create dropdown based on the currently displayed cards on page
    def create_dropdown(self, page_cards):
        return CardDropdown(page_cards, self.inventory_owner.id, self)
    

    def get_rarity_value(self, holo, signature):
        if holo == 1 and signature == 2:  # Holo + Golden Signed
            return 1
        elif signature == 2:  # Golden Signed
            return 2
        elif holo == 1 and signature == 1:  # Holo + Signed
            return 3
        elif signature == 1:  # Signed
            return 4
        elif holo == 1:  # Holo
            return 5
        return 6

    # update the embed and dropdown when changing pages
    async def update_inventory_view(self, interaction):
        self.mode = "inventory"

        # Update dropdown and buttons
        self.dropdown = self.create_dropdown(self.get_current_page_cards())
        
        # Clear and rebuild view components
        self.clear_items()
        self.add_item(self.prev_button)
        self.add_item(self.dropdown)
        self.add_item(self.next_button)
        self.add_item(self.sort_button)  # Ensure sort button stays

        # Update button states
        self.prev_button.disabled = self.current_index == 0
        self.next_button.disabled = self.current_index == len(self.embeds) - 1

        # Get current embed and update footer
        current_embed = self.embeds[self.current_index]
        current_embed.set_footer(text=f"Page {self.current_index + 1}/{len(self.embeds)} | Sorting: {self.sort_order.capitalize()}")

        # Handle response properly
        if interaction.response.is_done():
            await interaction.followup.edit_message(
                message_id=interaction.message.id,
                embed=current_embed,
                view=self
            )
        else:
            await interaction.response.edit_message(
                embed=current_embed,
                view=self
            )


    
    # previous inventory page
    async def go_previous(self, interaction):
        self.current_index -= 1
        await self.update_inventory_view(interaction)

    # next inventory page
    async def go_next(self, interaction):
        self.current_index += 1
        await self.update_inventory_view(interaction)


    # show card details in inventory
    async def update_card_details_view(self, interaction, embed, card_variant_id):
        self.mode = "details"
        self.clear_items()

        # "Back to Inventory" button
        back_button = Button(label="Back to Collection", style=discord.ButtonStyle.secondary)
        back_button.callback = self.go_back_to_inventory

        self.add_item(back_button)

        # add recycle button only if the user owns the inventory
        if self.command_author.id == self.inventory_owner.id:
            recycle_button = Button(label="Recycle", style=discord.ButtonStyle.danger)

            async def recycle_callback(interaction):
                await self.open_recycle_ui(interaction, card_variant_id)

            recycle_button.callback = recycle_callback
            self.add_item(recycle_button)

        await interaction.response.edit_message(embed=embed, view=self)


    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.command_author.id:
            await interaction.response.send_message(
                "Only the command's author can use these buttons.",
                ephemeral=True
            )
            return False
        return True

    # Recycle UI
    async def open_recycle_ui(self, interaction, card_variant_id):
        async with Database.connection() as db:
            
            try:
                cursor = await db.execute(
                    """
                    SELECT 
                        cards.name, 
                        card_variants.holo_type, 
                        card_variants.signature_type, 
                        user_inventory.quantity
                    FROM card_variants
                    INNER JOIN cards ON card_variants.card_id = cards.id
                    INNER JOIN user_inventory ON user_inventory.card_variant_id = card_variants.id
                    WHERE card_variants.id = ? AND user_inventory.user_id = ?
                    """,
                    (card_variant_id, self.command_author.id)
                )
                result = await cursor.fetchone()
            except Exception as e:
                
                raise


        if not result:
            await interaction.response.send_message("Unable to fetch card details.", ephemeral=True)
            return

        card_name, holo_type, signature_type, quantity = result
        variation = self.gacha.get_variation_name(holo_type, signature_type)
        recycle_value = self.gacha.calculate_recycle_value(holo_type, signature_type)

        embed = discord.Embed(
            title=f"Recycle {card_name} ({variation})",
            description=f"**NOTE:** Recycling cards will permanently remove them from your inventory.\n\n"
                        f"You own **{quantity}** copies.\n"
                        f"Each copy is worth **{recycle_value} stardust {emotes['stardust']}**.\n\n"
                        "Select how many copies you want to recycle from the dropdown below.",
            color=colors["red"],
        )

        view = RecycleView(card_name, variation, quantity, recycle_value, card_variant_id, self)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)




    # back to inventory page from card details
    async def go_back_to_inventory(self, interaction: discord.Interaction):
        """Handle back navigation with current sort order"""
        # Use the existing InventoryView's sorting logic instead of hardcoded query
        async with Database.connection() as db:
            
            try:
                cursor = await db.execute(
                    f"""
                    SELECT 
                        cards.name AS card_name,
                        cards.artist_name,
                        card_variants.id AS card_variant_id,
                        card_variants.image_url,
                        card_variants.holo_type,
                        card_variants.signature_type,
                        user_inventory.quantity
                    FROM user_inventory
                    INNER JOIN card_variants ON user_inventory.card_variant_id = card_variants.id
                    INNER JOIN cards ON card_variants.card_id = cards.id
                    WHERE user_inventory.user_id = ?
                    ORDER BY {self.get_order_clause()}
                    """,
                    (self.inventory_owner.id,)
                )
                collection = await cursor.fetchall()
            except Exception as e:
                
                raise

        if not collection:
            await interaction.response.edit_message(
                content=f"{self.inventory_owner.display_name} has no cards in their collection.",
                embed=None,
                view=None
            )
            return

        # Rebuild using InventoryView's processing methods
        self.card_list, rarest_card = self.process_collection(collection)
        self.embeds = self.create_embeds(self.card_list, rarest_card)
        self.current_index = 0

        # Reset view components
        self.dropdown = self.create_dropdown(self.get_current_page_cards())
        self.clear_items()
        self.add_item(self.prev_button)
        self.add_item(self.dropdown)
        self.add_item(self.next_button)
        self.add_item(self.sort_button)

        # Update button states
        self.prev_button.disabled = self.current_index == 0
        self.next_button.disabled = self.current_index == len(self.embeds) - 1

        # Update the message
        await interaction.response.edit_message(
            embed=self.embeds[self.current_index],
            view=self
        )

    # recycle number of cards
    async def recycle_card(self, interaction, card_variant_id, quantity, recycle_value):
        user_id = interaction.user.id
        total_points = recycle_value * quantity

        async with Database.connection() as db:
            
            try:
                # update inventory and points
                await db.execute(
                    """
                    UPDATE user_inventory 
                    SET quantity = quantity - ? 
                    WHERE user_id = ? AND card_variant_id = ?
                    """,
                    (quantity, user_id, card_variant_id)
                )
                await db.execute(
                    """
                    DELETE FROM user_inventory
                    WHERE user_id = ? AND card_variant_id = ? AND quantity <= 0
                    """,
                    (user_id, card_variant_id)
                )
                await db.execute(
                    "UPDATE users SET currency = currency + ? WHERE discord_id = ?",
                    (total_points, user_id)
                )
                
            except Exception as e:
                
                raise

        await interaction.response.send_message(
            f"Recycled **x{quantity}** copies for **{total_points} stardust**!", ephemeral=True
        )





#-----------Dropdown for selecting card from inventory-------------#


class CardDropdown(discord.ui.Select):
    def __init__(self, card_list, user_id, parent_view):
        self.parent_view = parent_view

        options = [
            discord.SelectOption(
                label=card["summary"],
                value=str(card["card_variant_id"]),
                description=""
            )
            for card in card_list
        ]
        super().__init__(placeholder="Select a card to view", options=options)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        card_variant_id = int(self.values[0])

        # Fetch card details from the database
        async with Database.connection() as db:
            
            try:
                cursor = await db.execute(
                    """
                    SELECT 
                        cards.name, 
                        cards.artist_name, 
                        card_variants.image_url, 
                        card_variants.holo_type, 
                        card_variants.signature_type,
                        user_inventory.quantity,
                        user_inventory.user_id
                    FROM user_inventory
                    INNER JOIN card_variants ON user_inventory.card_variant_id = card_variants.id
                    INNER JOIN cards ON card_variants.card_id = cards.id
                    WHERE user_inventory.user_id = ? AND card_variants.id = ?
                    """,
                    (self.user_id, card_variant_id)
                )
                result = await cursor.fetchone()
            except Exception as e:
                
                raise

        if not result:
            await interaction.response.send_message("Could not fetch card details.", ephemeral=True)
            return

        # construct the embed from results
        card_name, artist_name, image_url, holo_type, signature_type, quantity, owner_id = result
        owner = interaction.guild.get_member(owner_id) 

        variations = []
        if holo_type == 1:
            variations.append("Holo")
        if signature_type == 1:
            variations.append("Signed")
        elif signature_type == 2:
            variations.append("Golden Signed")

        variation_text = " ".join(variations) if variations else "Standard"
        color = self.parent_view.gacha.get_rarity_color(holo_type, signature_type)

        embed = discord.Embed(
            title=card_name,
            description=(f"**Artist:** {artist_name}\n"
                         f"**Variation:** {variation_text}, x{quantity}\n"
                         f"**Owned by:** {owner.display_name if owner else 'Unknown'}"),
            color=color
        )
        embed.set_image(url=image_url)

        # pass card_variant_id to update_card_details_view
        await self.parent_view.update_card_details_view(interaction, embed, card_variant_id)





#----------Dropdown menu for recycling------------------#



class RecycleDropdown(discord.ui.Select):
    def __init__(self, card_name, variation, max_quantity, recycle_value, card_variant_id, parent_view):
        self.card_name = card_name
        self.variation = variation
        self.max_quantity = max_quantity
        self.recycle_value = recycle_value
        self.card_variant_id = card_variant_id
        self.parent_view = parent_view 

        # create options for the dropdown (1 to max_quantity)
        options = [
            discord.SelectOption(
                label=f"Recycle x{i}",
                description=f"Get {i * recycle_value} stardust",
                value=str(i)
            )
            for i in range(1, min(max_quantity + 1, 11))
        ]

        super().__init__(placeholder="Select quantity to recycle...", options=options)

    # recycle quantity user selected
    async def callback(self, interaction: discord.Interaction):
        quantity = int(self.values[0])
        total_points = quantity * self.recycle_value

        # update database
        async with Database.connection() as db:
            
            try:
                await db.execute(
                    """
                    UPDATE user_inventory 
                    SET quantity = quantity - ? 
                    WHERE user_id = ? AND card_variant_id = ?
                    """,
                    (quantity, interaction.user.id, self.card_variant_id)
                )
                await db.execute(
                    """
                    DELETE FROM user_inventory
                    WHERE user_id = ? AND card_variant_id = ? AND quantity <= 0
                    """,
                    (interaction.user.id, self.card_variant_id)
                )
                await db.execute(
                    "UPDATE users SET currency = currency + ? WHERE discord_id = ?",
                    (total_points, interaction.user.id)
                )
                
            except Exception as e:
                
                raise

        # edit ephemeral message
        await interaction.response.edit_message(
            content=(
                f"Successfully recycled **{quantity} copies** of **{self.card_name} ({self.variation})** "
                f"for **{total_points} stardust**!"
            ),
            embed=None,
            view=None
        )




#--------------Recycling Menu----------------#



class RecycleView(View):
    def __init__(self, card_name, variation, max_quantity, recycle_value, card_variant_id, parent_view):
        super().__init__(timeout=180)
        self.parent_view = parent_view

        # Add dropdown for recycling
        self.add_item(RecycleDropdown(card_name, variation, max_quantity, recycle_value, card_variant_id, parent_view))

        # "Cancel" button
        cancel_button = Button(label="Cancel", style=discord.ButtonStyle.secondary)

        async def cancel_callback(interaction: discord.Interaction):
            # Edit the ephemeral message when canceled
            await interaction.response.edit_message(
                content="Recycle cancelled.",
                embed=None,
                view=None
            )

        cancel_button.callback = cancel_callback
        self.add_item(cancel_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Restrict interaction to the command author."""
        if interaction.user.id != self.parent_view.command_author.id:
            await interaction.response.send_message(
                "Only the command's author can use these buttons.", ephemeral=True
            )
            return False
        return True

    # timeout message
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        self.stop()

        if hasattr(self, "message") and self.message:
            try:
                await self.message.edit(content="This interaction has timed out.", embed=None, view=None)
            except discord.NotFound:
                pass



class AutoRecycleView(discord.ui.View):
    def __init__(self, cog, author):
        super().__init__(timeout=30)
        self.cog = cog
        self.author = author
        self.add_item(self.RecycleSelect(cog))
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only command author can interact"""
        if interaction.user != self.author:  # Now using stored author
            await interaction.response.send_message(
                "❌ This isn't your auto-recycle menu!",
                ephemeral=True
            )
            return False
        return True

    class RecycleSelect(discord.ui.Select):
        def __init__(self, cog):
            options = [
                discord.SelectOption(
                    label=f"{AUTO_RECYCLE_OPTIONS[0]} (Default)",
                    value="0",
                    description="No automatic recycling"
                ),
                discord.SelectOption(
                    label=AUTO_RECYCLE_OPTIONS[1],
                    value="1",
                    description="Recycle only standard card duplicates"
                ),
                discord.SelectOption(
                    label=AUTO_RECYCLE_OPTIONS[2],
                    value="2",
                    description="Recycle standard, holo, and signed duplicates"
                ),
                discord.SelectOption(
                    label=AUTO_RECYCLE_OPTIONS[3],
                    value="3",
                    description="Keep only holo+golden signed variants"
                )
            ]
            super().__init__(placeholder="Choose recycling level...", options=options)

        async def callback(self, interaction: discord.Interaction):
            level = int(self.values[0])
            async with Database.connection() as db:
                await db.execute(
                    "UPDATE users SET auto_recycle_level = ? WHERE discord_id = ?",
                    (level, interaction.user.id)
                )
                await db.commit()  # Explicit commit
            
            embed = discord.Embed(
                title="Auto-Recycle Updated",
                description=f"**New setting:** {AUTO_RECYCLE_OPTIONS[level]}\n"
                            "Duplicate cards will now be automatically recycled after pulls!",
                color=colors["blue"]
            )
            await interaction.response.edit_message(embed=embed, view=None)




class BannerView(discord.ui.View):
    def __init__(self, cards, bot, original_embed):
        super().__init__(timeout=300)
        self.cards = cards
        self.bot = bot
        self.original_embed = original_embed
        self.add_item(self.CardDropdown(cards))

    class CardDropdown(discord.ui.Select):
        def __init__(self, cards):
            options = [
                discord.SelectOption(
                    label=card['name'],
                    value=str(card['id']),
                    description=f"by {card['artist_name']}"
                ) for card in cards
            ]
            super().__init__(
                placeholder="Select a card to preview...",
                options=options,
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: discord.Interaction):
            card_id = int(self.values[0])
            async with Database.connection() as db:
                cursor = await db.execute("""
                    SELECT name, image_url, artist_name 
                    FROM cards WHERE id = ?
                """, (card_id,))
                card = await cursor.fetchone()

            # Create detail embed
            embed = discord.Embed(
                title=card['name'],
                description=f"**Artist:** {card['artist_name']}",
                color=colors["blue"]
            )
            embed.set_image(url=card['image_url'])
            
            view = discord.ui.View(timeout=300)
            view.add_item(self.view.BackButton(
                self.view.cards,
                self.view.bot,
                self.view.original_embed
            ))
            
            await interaction.response.edit_message(
                embed=embed, 
                view=view
            )


    class BackButton(discord.ui.Button):
        def __init__(self, cards, bot, original_embed):
            super().__init__(
                label="Back to Banner",
                style=discord.ButtonStyle.secondary
            )
            self.cards = cards
            self.bot = bot
            self.original_embed = original_embed
                
        async def callback(self, interaction: discord.Interaction):
            # Pass the stored data to recreate BannerView
            view = BannerView(self.cards, self.bot, self.original_embed)
            await interaction.response.edit_message(
                embed=self.original_embed,
                view=view
            )






class BulkRecycleView(discord.ui.View):
    def __init__(self, cog, author):
        super().__init__(timeout=120)
        self.cog = cog
        self.author = author
        self.add_item(self.RecycleSelect(cog))

    class RecycleSelect(discord.ui.Select):
        def __init__(self, cog):
            self.cog = cog  # Store cog reference
            options = [
                discord.SelectOption(
                    label=f"{AUTO_RECYCLE_OPTIONS[1]}",
                    value="1",
                    description="Recycle all standard duplicates"
                ),
                discord.SelectOption(
                    label=f"{AUTO_RECYCLE_OPTIONS[2]}",
                    value="2",
                    description="Recycle standard/holo/signed duplicates"
                ),
                discord.SelectOption(
                    label=f"{AUTO_RECYCLE_OPTIONS[3]}",
                    value="3",
                    description="Keep only Holo+Golden Signed"
                )
            ]
            super().__init__(
                placeholder="Choose recycling tier...",
                options=options
            )

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer()
            level = int(self.values[0])
            total_recycled = 0
            recycled_info = {}

            async with Database.connection() as db:
                # Get all inventory items
                cursor = await db.execute("""
                    SELECT ui.card_variant_id, ui.quantity, 
                        cv.holo_type, cv.signature_type
                    FROM user_inventory ui
                    JOIN card_variants cv ON ui.card_variant_id = cv.id
                    WHERE ui.user_id = ?
                """, (interaction.user.id,))
                inventory = await cursor.fetchall()

                # Process recycling
                for row in inventory:
                    if not row: continue
                    variant_id, quantity, holo, sig = row
                    if quantity <= 1:
                        continue  # Keep at least 1 copy

                    if self.cog.should_recycle_card(level, holo, sig):
                        # Get current quantity
                        cursor = await db.execute(
                            "SELECT quantity FROM user_inventory WHERE user_id = ? AND card_variant_id = ?",
                            (interaction.user.id, variant_id)
                        )
                        result = await cursor.fetchone()
                        if not result: continue
                        
                        current_qty = result['quantity']
                        copies_to_recycle = current_qty - 1

                        if copies_to_recycle > 0:
                            recycle_value = self.cog.calculate_recycle_value(holo, sig)
                            total_recycled += recycle_value * copies_to_recycle

                            # Track by rarity
                            rarity = self.cog.get_rarity_name(holo, sig)
                            recycled_info[rarity] = recycled_info.get(rarity, {
                                'copies': 0,
                                'value': recycle_value
                            })
                            recycled_info[rarity]['copies'] += copies_to_recycle

                            # Update inventory
                            await db.execute(
                                "UPDATE user_inventory SET quantity = 1 WHERE user_id = ? AND card_variant_id = ?",
                                (interaction.user.id, variant_id)
                            )

                # Update currency if any recycling occurred
                if total_recycled > 0:
                    await db.execute(
                        """UPDATE users SET 
                            currency = currency + ?,
                            total_stardust_collected = total_stardust_collected + ?
                        WHERE discord_id = ?""",
                        (total_recycled, total_recycled, interaction.user.id)
                    )
                    await db.commit()


                # Build result embed
                if total_recycled > 0:
                    embed = discord.Embed(
                        title="Bulk Recycling Complete",
                        description=f"Recycled **{sum(info['copies'] for info in recycled_info.values())}** copies",
                        color=colors["green"]
                    )
                    
                    for rarity, info in recycled_info.items():
                        embed.add_field(
                            name=f"{rarity} x{info['copies']}",
                            value=f"{info['value']} {emotes['stardust']} each → **{info['copies'] * info['value']} {emotes['stardust']}**",
                            inline=False
                        )
                    
                    embed.set_footer(text=f"Total gained: {total_recycled}")
                else:
                    embed = discord.Embed(
                        title="No Cards Recycled",
                        description="No matching cards found for selected tier",
                        color=colors["blue"]
                    )
                

                self.view.stop()
                await interaction.followup.send(embed=embed, ephemeral=True)
                

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user != self.author:
                await interaction.response.send_message(
                    "Only the command's author can use these buttons.",
                    ephemeral=True
                )
                return False
            return True










#
#
#-----------------------GACHA CLASS------------------------------#
#
#





class Gacha(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # allowed channels for gaining points in chat
        self.allowed_channels = STARDUST_CHANNELS
        self._cd = commands.CooldownMapping.from_cooldown(1, 3.0, BucketType.user)
        self.ACHIEVEMENT_TIERS = {
            "stardust": [
                (1000, "Starlet"),
                (2000, "Cosmic Collector"),
                (5000, "Stellar Gatherer"),
                (10000, "Astral Explorer"),
                (25000, "Galactic Pioneer"),
                (50000, "Interstellar Aristocrat"),
                (100000, "Empyrean Tycoon"),
                (250000, "Star Baron"),
                (500000, "Celestial Superstar"),
                (1000000, "Stardust Millionaire")
            ],
            "streak": [
                (7, "Starbound"),
                (14, "Following The Starlit Path"),
                (30, "Stellar Voyage"),
                (60, "Pioneering New Orbits"),
                (90, "Into The Unknown"),
                (120, "Beyond the Horizon"),
                (180, "Phasing Nebulas"),
                (365, "Eternal Starfarer")
            ],
            "pulls": [
                (10, "Beginner"),
                (25, "Novice"),
                (50, "Amateur"),
                (75, "Hobbyist"),
                (100, "Connoisseur"),
                (150, "Enthusiast"),
                (250, "Pull Addict"),
                (500, "Master"),
                (1000, "Stargazer")
            ]
        }

    async def check_achievements(self, db, user_id: int, achievement_type: str, current_value: int):
        new_achievements = []
        reward = 0

        try:
            # Get achieved thresholds
            cursor = await db.execute(
                "SELECT tier FROM achievements WHERE user_id = ? AND achievement_type = ?",
                (user_id, achievement_type)
            )
            achieved_thresholds = {row[0] for row in await cursor.fetchall()}

            # Check all tiers
            for threshold, title in self.ACHIEVEMENT_TIERS.get(achievement_type, []):
                if current_value >= threshold and threshold not in achieved_thresholds:
                    # Update both currency and total collected
                    await db.execute(
                        """UPDATE users SET 
                            currency = currency + ?, 
                            total_stardust_collected = total_stardust_collected + ?
                        WHERE discord_id = ?""",
                        (100, 100, user_id)
                    )
                    await db.execute(
                        "INSERT INTO achievements (user_id, achievement_type, tier) VALUES (?, ?, ?)",
                        (user_id, achievement_type, threshold)
                    )
                    new_achievements.append((threshold, title))
                    reward += 100

        except Exception as e:
            print(f"Achievement error: {str(e)}")

        return new_achievements, reward


    async def command_channel_check(self, ctx: commands.Context):
        if ctx.channel.id not in COMMAND_CHANNELS:
            embed = discord.Embed(
            description=f"Commands can only be used in <#{COMMAND_CHANNELS[0]}>!",
            color=colors["blue"]
            )
            await ctx.send(embed = embed, ephemeral=True)
            return False
        return True

    def should_recycle_card(self, auto_level, holo, sig):
        if auto_level == 0:
            return False
        elif auto_level == 1:
            return holo == 0 and sig == 0
        elif auto_level == 2: 
            # Only allow: Standard(0,0), Holo(1,0), Signed(0,1)
            return (holo, sig) in {(0,0), (1,0), (0,1)}
        elif auto_level == 3:  # All except Holo+Golden
            return not (holo == 1 and sig == 2)
        return False
    
    def get_rarity_name(self, holo: int, sig: int) -> str:
        """Returns formatted rarity name for embeds"""
        if holo == 1 and sig == 2:
            return "Holo Golden Signed"
        elif holo == 1 and sig == 1:
            return "Holo Signed"
        elif sig == 2:
            return "Golden Signed"
        elif sig == 1:
            return "Signed"
        elif holo == 1:
            return "Holo"
        return "Standard"


    def get_rarity_color(self, holo_type, signature_type):
        if holo_type == 1 and signature_type == 2:
            return colors["rarity"]["holo_golden"]
        elif holo_type == 1 and signature_type == 1:
            return colors["rarity"]["holo_signed"] 
        elif signature_type == 2:
            return colors["rarity"]["golden_signed"]
        elif signature_type == 1:
            return colors["rarity"]["signed"]
        elif holo_type == 1:
            return colors["rarity"]["holo"]
        else:
            return colors["rarity"]["standard"]

    def pluralize(self, count: int, singular: str, plural: str = None) -> str:
        if not plural:
            plural = singular + 's'
        return f"{count} {singular if count == 1 else plural}"

#----------LISTENER FOR MESSAGE POINTS-----------------#



    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.channel.id not in self.allowed_channels or message.channel.id in COMMAND_CHANNELS:
            return

        async with Database.connection() as db:
            try:
                user_id = message.author.id
                now_gmt8 = datetime.now(GMT8)
                now_utc = datetime.now(timezone.utc)
                await db.execute(
                    """INSERT OR IGNORE INTO users 
                    (discord_id, currency, last_daily, total_stardust_collected, 
                        daily_message_count, last_message_points) 
                    VALUES (?, 0, NULL, 0, 0, NULL)""",
                    (user_id,)
                )
                
                cursor = await db.execute(
                    """SELECT daily_message_count, last_message_points, currency, total_stardust_collected 
                    FROM users WHERE discord_id = ?""",
                    (user_id,)
                )
                result = await cursor.fetchone()

                daily_message_count, last_message_points, currency, total_collected = result

                # Reset daily count at GMT+8 midnight
                if result['last_message_points']:
                    last_utc = datetime.fromisoformat(result['last_message_points']).replace(tzinfo=timezone.utc)
                    last_gmt8 = last_utc.astimezone(GMT8)
                    
                    if last_gmt8.date() != now_gmt8.date():
                        daily_message_count = 0
                    else:
                        daily_message_count = result['daily_message_count']
                else:
                    daily_message_count = 0

                # Enforce 3-minute cooldown
                if result['last_message_points']:
                    last_points_time = datetime.fromisoformat(result['last_message_points']).replace(tzinfo=timezone.utc)
                    elapsed = (now_utc - last_points_time).total_seconds()
                    
                    if elapsed < MESSAGE_COOLDOWN:
                        return
                    
                # Calculate tiered rewards
                if daily_message_count < MESSAGE_INTERVAL_1:
                    points_earned = MESSAGE_STARDUST_1
                elif daily_message_count < MESSAGE_INTERVAL_2:
                    points_earned = MESSAGE_STARDUST_2
                else:
                    points_earned = MESSAGE_STARDUST_3

                # Update user stats
                new_currency = result['currency'] + points_earned
                total_collected = result['total_stardust_collected'] + points_earned
                daily_message_count += 1
                
                await db.execute(
                    """UPDATE users SET 
                        currency = ?, 
                        daily_message_count = ?, 
                        last_message_points = ?,
                        total_stardust_collected = ?
                    WHERE discord_id = ?""",
                    (
                        new_currency,
                        daily_message_count,
                        now_utc.isoformat(), 
                        total_collected,
                        user_id
                    )
                )

                new_achievements, reward = await self.check_achievements(
                    db, user_id, "stardust", total_collected
                )

                # Send achievement notifications
                if new_achievements:
                    for threshold, title in new_achievements:
                        embed = discord.Embed(
                            title=f"Achievement Unlocked: {title}!",
                            description=f"{message.author.mention} you have passed **{threshold}** total stardust! {emotes['stardust']}\n"
                                    f"**Reward:** +100 {emotes['stardust']}",
                            color=colors["gold"]
                        )
                        await message.channel.send(embed=embed)

            except Exception as e:
                raise


    # calculate recycle values
    def calculate_recycle_value(self, holo_type: int, signature_type: int) -> int:
        if holo_type == 1 and signature_type == 2:  # Holo + Golden Signed
            return RECYCLE_HOLO_GOLDEN_SIGNED
        elif holo_type == 1 and signature_type == 1:  # Holo + Signed
            return RECYCLE_HOLO_SIGNED
        elif signature_type == 2:  # Golden Signed
            return RECYCLE_GOLDEN_SIGNED
        elif signature_type == 1:  # Signed
            return RECYCLE_SIGNED
        elif holo_type == 1:  # Holo
            return RECYCLE_HOLO
        else:  # Regular
            return RECYCLE_STANDARD

    async def get_next_serial(self, card_variant_id):
        async with Database.connection() as db:
            
            try:
                cursor = await db.execute("""
                    SELECT COALESCE(MAX(serial_number), 0) + 1 
                    FROM limited_card_instances 
                    WHERE card_variant_id = ?
                """, (card_variant_id,))
                return (await cursor.fetchone())[0]
            except Exception as e:
                
                raise
        

    async def update_rarity_value(self, user_id, new_card_variant_id):
        async with Database.connection() as db:
            
            try:
                # Get rarity of the new card variant
                cursor = await db.execute("""
                    SELECT holo_type, signature_type 
                    FROM card_variants 
                    WHERE id = ?
                """, (new_card_variant_id,))
                holo_type, signature_type = await cursor.fetchone()
            except Exception as e:
                
                raise

            # Calculate rarity value
            new_rarity = self.get_rarity_value(holo_type, signature_type)

            
            try:
                #  Update user's rarest card if the new one is rarer
                await db.execute("""
                    UPDATE users 
                    SET 
                        rarest_card_id = CASE WHEN ? < rarity_value THEN ? ELSE rarest_card_id END,
                        rarity_value = CASE WHEN ? < rarity_value THEN ? ELSE rarity_value END
                    WHERE discord_id = ?
                """, (new_rarity, new_card_variant_id, new_rarity, new_rarity, user_id))
                
            except Exception as e:
                
                raise

    async def check_card_set_completion(self, db, user_id, card_id):
        async with Database.connection() as db:
            
            try:
                # Count total variants for the card and how many the user owns
                cursor = await db.execute("""
                    SELECT COUNT(DISTINCT cv.id), 
                        COUNT(DISTINCT ui.card_variant_id)
                    FROM card_variants cv
                    LEFT JOIN user_inventory ui 
                        ON cv.id = ui.card_variant_id AND ui.user_id = ?
                    WHERE cv.card_id = ?
                """, (user_id, card_id))
                total_variants, owned_variants = await cursor.fetchone()
            except Exception as e:
                
                raise

            # If all variants are owned, mark the set as complete
            if owned_variants == total_variants:
                
                try:
                    await db.execute("""
                        INSERT OR IGNORE INTO user_card_sets (user_id, card_id)
                        VALUES (?, ?)
                    """, (user_id, card_id))
                    
                except Exception as e:
                    
                    raise


#--------------------- HELP COMMAND ------------------------------#

    @commands.cooldown(1, 3, BucketType.user)
    @commands.hybrid_command(
        name="help",
        description="List all available commands and their usage."
    )
    async def help(self, ctx: commands.Context):
        if not await self.command_channel_check(ctx):
            return
        
        embed = discord.Embed(
            title="KiichuBot Help Menu",
            description="Here are the available commands and how to use them:",
            color=colors["blue"]
        )

        commands_info = [
            ("`!dailies [user]`", "Claim your daily stardust!"),
            ("`!pull [1 or 10]`", "Spend stardust to pull 1 or 10 cards."),
            ("`!collection [user]`", "Access a user's card collection to view or manage it."),
            ("`!stardust`", "Check your current stardust balance."),
            ("`!profile [user]`", "View a user's profile to view their stats!"),
            ("`!leaderboard [pulls, stardust, streak] [page number]`", "View the leaderboard and your rank!"),
            ("`!autorecycle`", "Configure automatic recycling of duplicate cards when pulling."),
            ("`!bulkrecycle`", "Recycle duplicate cards from inventory."),
            ("`!banner`", "View the current cards on the banner!"),
        ]

        for cmd, desc in commands_info:
            embed.add_field(name=cmd, value=desc, inline=False)

        embed.set_footer(text="Use these commands to collect and manage your cards!")
        
        await ctx.send(embed=embed)





# ---------------------- DAILIES COMMAND ------------------------ #



    @commands.cooldown(1, 3, BucketType.user)
    @commands.hybrid_command(
        name="dailies",
        description=f"Claim your daily stardust! {emotes['stardust']}",
        aliases=["d", "daily"]
    )
    async def dailies(self, ctx: commands.Context):
        if not await self.command_channel_check(ctx):
            return
        user_id = ctx.author.id
        
        async with Database.connection() as db:
            try:
                await db.execute(
                    """INSERT OR IGNORE INTO users 
                    (discord_id, currency, total_stardust_collected, has_claimed_welcome) 
                    VALUES (?, 1000, 1000, 1)""",
                    (user_id,)
                )

                # Grant welcome bonus if existing user hasn't claimed
                await db.execute(
                    """UPDATE users SET
                        currency = currency + 1000,
                        total_stardust_collected = total_stardust_collected + 1000,
                        has_claimed_welcome = 1
                    WHERE discord_id = ? AND has_claimed_welcome = 0""",
                    (user_id,)
                )

                # Get current values with proper timezone
                now_gmt8 = datetime.now(GMT8)
                cursor = await db.execute(
                    """SELECT last_daily, current_daily_streak, longest_daily_streak,
                    total_stardust_collected FROM users WHERE discord_id = ?""",
                    (user_id,)
                )
                result = await cursor.fetchone()

                # Calculate new streak
                new_streak = 1
                if result['last_daily']:
                    last_daily_utc = datetime.fromisoformat(result['last_daily']).replace(tzinfo=timezone.utc)
                    last_daily_gmt8 = last_daily_utc.astimezone(GMT8)
                    
                    # Check if already claimed today in GMT+8
                    if last_daily_gmt8.date() == now_gmt8.date():
                        next_reset = (last_daily_gmt8 + timedelta(days=1)).replace(
                            hour=0, minute=0, second=0, microsecond=0
                        )
                        embed = discord.Embed(
                            description=f"Come back <t:{int(next_reset.timestamp())}:R> for your next daily!",
                            color=colors["blue"]
                        )
                        await ctx.send(embed=embed)
                        return
                    
                    # Calculate streak
                    if (last_daily_gmt8 + timedelta(days=1)).date() == now_gmt8.date():
                        new_streak = result['current_daily_streak'] + 1
                    else:
                        new_streak = 1

                # Update daily rewards (store times in UTC)
                await db.execute(
                    """UPDATE users SET
                        currency = currency + ?,
                        total_stardust_collected = total_stardust_collected + ?,
                        current_daily_streak = ?,
                        longest_daily_streak = MAX(?, longest_daily_streak),
                        last_daily = ?
                    WHERE discord_id = ?""",
                    (
                        DAILY_STARDUST_AMOUNT,
                        DAILY_STARDUST_AMOUNT,
                        new_streak,
                        new_streak,
                        now_gmt8.astimezone(timezone.utc).isoformat(),
                        user_id
                    )
                )

                # Get updated totals for achievement checks
                cursor = await db.execute(
                    """SELECT currency, total_stardust_collected 
                    FROM users WHERE discord_id = ?""",
                    (user_id,)
                )
                updated = await cursor.fetchone()
                new_currency = updated['currency']
                new_total = updated['total_stardust_collected']

                # Check both achievement types
                streak_achievements, streak_reward = await self.check_achievements(db, user_id, "streak", new_streak)
                stardust_achievements, stardust_reward = await self.check_achievements(db, user_id, "stardust", new_total)
                all_achievements = [(threshold, title, 'streak') for threshold, title in streak_achievements] + [(threshold, title, 'stardust') for threshold, title in stardust_achievements]

                # Debug output to console to confirm achievements are detected
                print(f"User {user_id} - Streak Achievements: {streak_achievements}, Stardust Achievements: {stardust_achievements}")

                await db.commit()

            except Exception as e:
                await ctx.send(f"Daily claim failed: {str(e)}")
                return
            
        main_embed = discord.Embed(
            description=f"{ctx.author.mention} you received **{DAILY_STARDUST_AMOUNT}** {emotes['stardust']}\n"
                        f"**Current Streak:** {self.pluralize(new_streak, 'day')}\n"
                        f"**Total Stardust:** {new_currency} {emotes['stardust']}",
            color=colors["blue"]
        )
        main_embed.set_author(
                name=f"Daily Reward Claimed!",
                icon_url=ctx.author.display_avatar.url
            )

        await ctx.send(embed=main_embed)

        for threshold, title, ach_type in all_achievements:
            embed = discord.Embed(
                title=f"Achievement Unlocked: {title}!",
                description=f"{ctx.author.mention} you have passed **{threshold}** {'day streak' if ach_type == 'streak' else 'total stardust <:Stardust:1341289644343693393>'}!\n"
                f"**Reward:** +100 {emotes['stardust']}",
                color=colors["gold"]
            )
            await ctx.send(embed=embed)



#-------------------- CHECK POINTS COMMAND -----------------------------#


    @commands.cooldown(1, 3, BucketType.user)
    @commands.hybrid_command(
        name="stardust",
        description="Check your current stardust.",
        aliases=["points", "balance", "sd"]
    )
    async def stardust(self, ctx: commands.Context, member: discord.Member = None):
        if not await self.command_channel_check(ctx):
            return
        target = member or ctx.author
        user_id = target.id

        async with Database.connection() as db:
            try:
                cursor = await db.execute(
                    "SELECT currency FROM users WHERE discord_id = ?",
                    (user_id,)
                )
                result = await cursor.fetchone()
            except Exception as e:
                await ctx.send(f"Error retrieving balance: {str(e)}")
                return

        points = result[0] if result else 0

        embed = discord.Embed(
            description=f"**{target.display_name}**, you currently have **{points}** stardust {emotes['stardust']}",
            color=colors["blue"]
        )
        embed.set_footer(text="Earn more stardust by chatting, claiming dailies, or recycling cards")
        embed.set_author(
                name=f"{target.name}'s Current Stardust",
                icon_url=target.display_avatar.url
            )

        await ctx.send(embed=embed)




#-------------------- CHECK STREAK COMMAND -----------------------------#


    @commands.cooldown(1, 3, BucketType.user)
    @commands.hybrid_command(
        name="streak",
        description="Check your current daily streak!",
        aliases=["currentstreak", "streaks"]
    )
    async def streak(self, ctx: commands.Context, member: discord.Member = None):
        if not await self.command_channel_check(ctx):
            return
        member = member or ctx.author
        user_id = member.id

        async with Database.connection() as db:
            try:
                cursor = await db.execute(
                    """SELECT current_daily_streak 
                    FROM users 
                    WHERE discord_id = ?""",
                    (user_id,)
                )
                result = await cursor.fetchone()

                if not result:
                    description = f"{member.mention} hasn't started collecting cards yet!"
                else:
                    streak = result['current_daily_streak']
                    description = f"{member.mention}'s current daily streak: **{self.pluralize(streak, 'day')}**"

                embed = discord.Embed(
                    description=description,
                    color=colors["blue"]
                )
                await ctx.send(embed=embed)

            except Exception as e:
                await ctx.send(f"Error checking streak: {str(e)}")


#----------------------- PULL COMMAND --------------------------------#


    @commands.cooldown(1, 3, BucketType.user)
    @commands.hybrid_command(name="pull",
                             description="Spend stardust to pull cards!",
                             aliases=["p", "roll"]
                             )
    async def pull(self, ctx: commands.Context, pulls: int = commands.parameter(description="Number of pulls (1 or 10)", default=1)):
        if not await self.command_channel_check(ctx):
            return
        if pulls not in {1, 10}:
            embed = discord.Embed(
                            description=f"You can only pull **1** or **10** cards at a time!",
                            color=colors["red"]
                        )
            await ctx.send(embed = embed)
            return

        user_id = ctx.author.id
        total_cost = pulls * PULL_COST
        recycled_info = {}

        async with Database.connection() as db:
            
            try:
                cursor = await db.execute("""
                    SELECT currency, total_pulls, total_cards_owned, total_unique_variants 
                    FROM users WHERE discord_id = ?
                """, (user_id,))
                result = await cursor.fetchone()

                if not result or result['currency'] < total_cost:
                    embed = discord.Embed(
                        description=f"You don't have enough stardust for this pull!",
                        color=colors["red"]
                    )
                    await ctx.send(embed=embed)
                    
                    return

                currency = result['currency']
                total_pulls = result['total_pulls'] + pulls
                total_cards_owned = result['total_cards_owned']

                await db.execute("""
                    UPDATE users SET currency = currency - ? 
                    WHERE discord_id = ?
                """, (total_cost, user_id))

                pulls_result = []
                special_messages = {}
                card_quantities = {}
                variant_batch = []
                variant_counts = {}

                for i in range(pulls):
                    variant_id, special_msg, qty, color = await self.generate_card_variant(db, user_id)
                    pulls_result.append((variant_id, color))
                    variant_batch.append((user_id, variant_id))
                    
                    # Track counts within this pull
                    variant_counts[variant_id] = variant_counts.get(variant_id, 0) + 1
                    
                    if special_msg:
                        special_messages[i] = special_msg
                    card_quantities[i] = qty

                # Insert all pulls into inventory
                await db.executemany("""
                    INSERT INTO user_inventory (user_id, card_variant_id, quantity)
                    VALUES (?, ?, 1)
                    ON CONFLICT(user_id, card_variant_id) 
                    DO UPDATE SET quantity = quantity + 1
                """, [(uid, vid) for uid, vid in variant_batch])

                # ========== AUTO-RECYCLE LOGIC ==========
                cursor = await db.execute(
                    "SELECT auto_recycle_level FROM users WHERE discord_id = ?",
                    (user_id,)
                )
                auto_level = (await cursor.fetchone())['auto_recycle_level']
                recycled_stardust = 0

                pre_pull_quantities = {}
                for variant_id in variant_counts.keys():
                    cursor = await db.execute(
                        "SELECT quantity FROM user_inventory WHERE user_id = ? AND card_variant_id = ?",
                        (user_id, variant_id)
                    )
                    result = await cursor.fetchone()
                    pre_pull = result['quantity'] - variant_counts[variant_id] if result else 0
                    pre_pull_quantities[variant_id] = pre_pull

                if auto_level > 0:
                    # Process recycling for each unique variant in batch
                    for variant_id, pull_count in variant_counts.items():
                        # Get current count from database
                        cursor = await db.execute(
                            "SELECT quantity FROM user_inventory WHERE user_id = ? AND card_variant_id = ?",
                            (user_id, variant_id)
                        )
                        current_qty = (await cursor.fetchone())['quantity']

                        # Get variant details
                        cursor = await db.execute(
                            "SELECT holo_type, signature_type FROM card_variants WHERE id = ?",
                            (variant_id,)
                        )
                        variant_data = await cursor.fetchone()
                        if not variant_data:
                            continue
                        
                        holo = variant_data['holo_type']
                        sig = variant_data['signature_type']

                        # Determine recycling eligibility
                        if self.should_recycle_card(auto_level, holo, sig):
                            new_copies = current_qty - pre_pull_quantities.get(variant_id, 0)
                            
                            # Calculate how many to keep (minimum 1 overall)
                            keep = 1 if pre_pull_quantities.get(variant_id, 0) == 0 else 0
                            copies_to_recycle = max(new_copies - keep, 0)

                            if copies_to_recycle > 0:
                                recycle_value = self.calculate_recycle_value(holo, sig)
                                recycled_stardust += recycle_value * copies_to_recycle

                                # Update inventory
                                await db.execute(
                                    "UPDATE user_inventory SET quantity = quantity - ? WHERE user_id = ? AND card_variant_id = ?",
                                    (copies_to_recycle, user_id, variant_id)
                                )
                                await db.execute(
                                    "DELETE FROM user_inventory WHERE quantity <= 0 AND user_id = ? AND card_variant_id = ?",
                                    (user_id, variant_id)
                                )

                                # Store grouped recycle info
                                rarity_name = self.get_rarity_name(holo, sig)
                                if rarity_name not in recycled_info:
                                    recycled_info[rarity_name] = {
                                        'copies': 0,
                                        'value': recycle_value,
                                        'total': 0
                                    }
                                recycled_info[rarity_name]['copies'] += copies_to_recycle
                                recycled_info[rarity_name]['total'] += recycle_value * copies_to_recycle

                    # Update currency if any recycling occurred
                    if recycled_stardust > 0:
                        await db.execute(
                            "UPDATE users SET currency = currency + ?, total_stardust_collected = total_stardust_collected + ? WHERE discord_id = ?",
                            (recycled_stardust, recycled_stardust, user_id)
                        )

                await db.execute(
                    "UPDATE users SET total_pulls = ? WHERE discord_id = ?",
                    (total_pulls, user_id)
                )
                
                new_achievements, _ = await self.check_achievements(db, user_id, "pulls", total_pulls)
                unique_card_ids = {cv[0] for cv in variant_batch}
                for card_id in unique_card_ids:
                    await self.check_card_set_completion(db, user_id, card_id)

                await db.commit()

            except Exception as e:
                await ctx.send(f"Pull failed: {str(e)}")
                return

        

        # Send pull results
        embeds = await self.create_pull_embeds(pulls_result, pulls, special_messages, card_quantities, user_id, pre_pull_quantities, ctx.author.display_name)
        if len(embeds) == 1:
            await ctx.send(embed=embeds[0])
        else:
            view = PullResultView(embeds, ctx.author)
            message = await ctx.send(embed=embeds[0], view=view)
            view.message = message


        if recycled_stardust > 0:
            recycle_embed = discord.Embed(
                title="Auto-Recycled Cards",
                color=colors["blue"]
            )
            
            # Sort by highest value first
            sorted_items = sorted(
                recycled_info.items(),
                key=lambda x: x[1]['value'],
                reverse=True
            )
            
            for rarity, info in sorted_items:
                recycle_embed.add_field(
                    name=f"{rarity} x{info['copies']}",
                    value=f"{info['value']} {emotes['stardust']} each → **{info['total']} {emotes['stardust']}**",
                    inline=False
                )
            
            recycle_embed.set_footer(text=f"Total gained: {recycled_stardust} stardust ")
            
            #await ctx.send(embed=recycle_embed)


        # Send achievement notifications
        if new_achievements:
            for threshold, title in new_achievements:
                embed = discord.Embed(
                    title=f"Achievement Unlocked: {title}!",
                    description=f"{ctx.author.mention} you have passed **{threshold}** total card pulls!\n"
                    f"**Reward:** +100 {emotes['stardust']}",
                    color=colors["gold"]
                )
                await ctx.send(embed=embed)


    async def create_pull_embeds(self, pulls_result, pulls, special_messages, card_quantities, user_id, pre_pull_quantities, author_name):
        embeds = []
        async with Database.connection() as db:
            
            try:
                for i, (card_variant_id, color) in enumerate(pulls_result):
                    cursor = await db.execute("""
                        SELECT cards.name, card_variants.image_url, cards.artist_name,
                            card_variants.holo_type, card_variants.signature_type,
                            card_variants.generation,
                            (SELECT serial_number FROM limited_card_instances
                            WHERE limited_card_instances.card_variant_id = card_variants.id
                            AND limited_card_instances.user_id = ?) AS serial_number
                        FROM card_variants
                        INNER JOIN cards ON card_variants.card_id = cards.id
                        WHERE card_variants.id = ?
                    """, (user_id, card_variant_id))
                    
                    result = await cursor.fetchone()
                    if not result:
                        continue

                    card_name, image_url, artist_name, holo_type, signature_type, generation, serial_number = result
                    description = f"**Artist:** {artist_name}"
                    
                    if not (holo_type == 1 or signature_type > 0):
                        description += f"\n**Standard**"

                    embed = discord.Embed(
                        title=card_name,
                        description=description,
                        color=color
                    )
                    embed.set_image(url=image_url)

                    if i in special_messages:
                        embed.add_field(name="✨ Special Pull! ✨", value=special_messages[i], inline=False)

                    if generation == 999:
                        embed.add_field(name="✨ Limited Edition! ✨", value=f"Serial #{serial_number}", inline=False)


                    footer_text = f"Card {i + 1} / {pulls} ㅤ|"
                    cursor = await db.execute(
                        "SELECT quantity FROM user_inventory WHERE user_id = ? AND card_variant_id = ?",
                        (user_id, card_variant_id)
                    )
                    result = await cursor.fetchone()
                    current_qty = result['quantity'] if result else 0
                    
                    # Check if user had this variant before pulling
                    had_before = pre_pull_quantities.get(card_variant_id, 0) > 0
                    footer_text += f" ㅤ{author_name} ㅤ| ㅤ"
                    footer_text += "New!" if not had_before else f"Owned: {current_qty}"
                    embed.set_footer(text=footer_text)

                    embeds.append(embed)
            except Exception as e:
                raise

        return embeds



    # Generate card Variants
    async def generate_card_variant(self, db, user_id):
        # Check for limited card first
        if random.random() < LIMITED_CARD_RATE:
            cursor = await db.execute("""
                SELECT c.id, c.max_copies, cv.id 
                FROM cards c
                LEFT JOIN card_variants cv 
                    ON c.id = cv.card_id 
                    AND cv.generation = 999
                WHERE c.is_limited = 1 
                AND c.banner_id = (SELECT id FROM banners WHERE is_active = 1)
                AND (
                    c.max_copies IS NULL OR 
                    (SELECT COUNT(*) FROM limited_card_instances 
                    WHERE card_variant_id = cv.id) < c.max_copies
                )
                ORDER BY RANDOM() 
                LIMIT 1
            """)
            limited_card = await cursor.fetchone()
            
            if limited_card:
                card_id, max_copies, variant_id = limited_card
                
                # Create variant if missing
                if not variant_id:
                    await db.execute("""
                        INSERT INTO card_variants 
                        (card_id, holo_type, signature_type, image_url, generation)
                        VALUES (?, 0, 0, '', 999)
                    """, (card_id,))
                    variant_id = (await db.execute("SELECT last_insert_rowid()")).fetchone()[0]
                    

                # Verify stock again before inserting
                cursor = await db.execute("""
                    SELECT COUNT(*) FROM limited_card_instances 
                    WHERE card_variant_id = ?
                """, (variant_id,))
                current_count = (await cursor.fetchone())[0]
                
                if max_copies and current_count >= max_copies:
                    if LIMITED_CARD_FALLBACK:
                        pass  # Fall through to regular pull
                    else:
                        return await self.generate_card_variant(db, user_id)
                else:
                    # Get next serial
                    serial = await self.get_next_serial(variant_id)
                    
                    # Insert limited instance
                    await db.execute("""
                        INSERT INTO limited_card_instances 
                        (card_variant_id, user_id, serial_number)
                        VALUES (?, ?, ?)
                    """, (variant_id, user_id, serial))
                    
                    # Update limited card image URL if missing
                    cursor = await db.execute("""
                        SELECT image_url FROM card_variants WHERE id = ?
                    """, (variant_id,))
                    if (await cursor.fetchone())[0] == '':
                        await db.execute("""
                            UPDATE card_variants 
                            SET image_url = (SELECT image_url FROM cards WHERE id = ?)
                            WHERE id = ?
                        """, (card_id, variant_id))
                    
                    return variant_id, "✨ **LIMITED EDITION!** ✨", 0  # No variations for limited
                
        # Regular card flow
        cursor = await db.execute("SELECT id FROM cards WHERE is_limited = 0 ORDER BY RANDOM() LIMIT 1")
        card_id = (await cursor.fetchone())[0]

        # determine holo type and signature type
        holo_type = 1 if random.random() < HOLO_DROP_RATE else 0
        signature_type = 1 if random.random() < SIGNED_DROP_RATE else 0
        if signature_type == 1 and random.random() < GOLDEN_SIGNED_CHANCE:
            signature_type = 2

        # special messages
        messages = {
            "holo": [
                "**HOLOGRAPHIC CARD!**\nKii looks extra shiny today.",
                "**HOLOGRAPHIC CARD!**\nKii blasts you with the light of a thousand suns.",
                "**HOLOGRAPHIC CARD!**\nShiny, but not more so than Kii's smile!",
                "**HOLOGRAPHIC CARD!**\nYou feel the cosmic fox power radiating from this card. "
            ],
            "signed": [
                "**SIGNED CARD!**\nFoxes can't write, but fox girls sure can!",
                "**SIGNED CARD!**\nIt seems this was signed by Kii herself. Lucky you!",
                "**SIGNED CARD!**\nYou're telling me a FOX signed this card??"
            ],
            "golden_signed": [
                "**GOLDEN SIGNED CARD!**\nIt seems this was signed by Kii herself. With her SPECIAL GOLD PEN, no less. Lucky you!",
                "**GOLDEN SIGNED CARD!**\nNot real gold, but a fox girl's affection is worth more than material wealth.",
                "**GOLDEN SIGNED CARD!**\nAll that glitters is gold!",
                "**GOLDEN SIGNED CARD!**\nYou're telling me a FOX (golden) signed this card?",
            ],
            "holo_signed": [
                "**HOLOGRAPHIC SIGNED CARD!**\nKii blasts you with the light of TWO thousand suns.",
                "**HOLOGRAPHIC SIGNED CARD!**\nImbued with Kii's cosmic fox powers AND personally signed by Kii herself!",
                "**HOLOGRAPHIC SIGNED CARD!**\nHolo AND signed? Your RNKii is on point today."
            ],
            "holo_golden": [
                "**HOLOGRAPHIC GOLDEN SIGNED CARD!**\nKii blasts you with the light of two thousand suns. Then the signature does another thousand for good measure.",
                "**HOLOGRAPHIC GOLDEN SIGNED CARD!**\nYou've seen holographic cards. You've seen golden signature cards. But both? It seems you have truly been blessed by the cosmic fox! Lucky lucky you!",
                "**HOLOGRAPHIC GOLDEN SIGNED CARD!**\nYou try to put it in your pocket, but the potent cosmic fox energy within burns straight through the fabric."
            ]
        }

        # Determine the correct message
        special_message = None
        if holo_type == 1 and signature_type == 2:
            special_message = random.choice(messages["holo_golden"])
        elif holo_type == 1 and signature_type == 1:
            special_message = random.choice(messages["holo_signed"])
        elif signature_type == 2:
            special_message = random.choice(messages["golden_signed"])
        elif signature_type == 1:
            special_message = random.choice(messages["signed"])
        elif holo_type == 1:
            special_message = random.choice(messages["holo"])

        # check if the variant already exists
        cursor = await db.execute(
            """
            SELECT id FROM card_variants
            WHERE card_id = ? AND holo_type = ? AND signature_type = ?
            """,
            (card_id, holo_type, signature_type)
        )
        result = await cursor.fetchone()

        if result:
            card_variant_id = result[0]
        else:
            cursor = await db.execute(
                """
                INSERT INTO card_variants (card_id, holo_type, signature_type)
                VALUES (?, ?, ?)
                """,
                (card_id, holo_type, signature_type)
            )
            
            card_variant_id = cursor.lastrowid

        # get how many copies the user already owns
        cursor = await db.execute(
            "SELECT quantity FROM user_inventory WHERE user_id = ? AND card_variant_id = ?",
            (user_id, card_variant_id)
        )
        owned_result = await cursor.fetchone()
        quantity_owned = owned_result[0] if owned_result else 1


        color = self.get_rarity_color(holo_type, signature_type)


        return card_variant_id, special_message, quantity_owned, color



    





#-------------------- VIEW COLLECTION COMMAND ---------------------------#



    @commands.cooldown(1, 3, BucketType.user)
    @commands.hybrid_command(
        name="collection",
        description="View a user's card collection.",
        aliases=["col", "inventory", "cards"]
    )
    async def collection(self, ctx: commands.Context, member: discord.Member = None):
        if not await self.command_channel_check(ctx):
            return
        member = member or ctx.author  # Default to command sender

        async with Database.connection() as db:
            
            try:
                cursor = await db.execute(
                    """
                    SELECT 
                        cards.name AS card_name,
                        cards.artist_name,
                        card_variants.id AS card_variant_id,
                        card_variants.image_url,
                        card_variants.holo_type,
                        card_variants.signature_type,
                        user_inventory.quantity
                    FROM user_inventory
                    INNER JOIN card_variants ON user_inventory.card_variant_id = card_variants.id
                    INNER JOIN cards ON card_variants.card_id = cards.id
                    WHERE user_inventory.user_id = ?
                    ORDER BY 
                        CASE
                            WHEN card_variants.holo_type = 1 AND card_variants.signature_type = 2 THEN 1
                            WHEN card_variants.signature_type = 2 THEN 2
                            WHEN card_variants.holo_type = 1 AND card_variants.signature_type = 1 THEN 3
                            WHEN card_variants.signature_type = 1 THEN 4
                            WHEN card_variants.holo_type = 1 THEN 5
                            ELSE 6
                        END,
                        cards.name;
                    """,
                    (member.id,)
                )
                collection = await cursor.fetchall()
            except Exception as e: 
                raise

        if not collection:
            embed = discord.Embed(
            description=f"**{member.display_name}** has no cards in their collection.",
            color=colors["blue"]
            )
            await ctx.send(embed = embed)
            return

        # Define rarity rankings for proper comparison
        def get_rarity_value(holo_type_val, signature_type_val):
            if holo_type_val == 1 and signature_type_val == 2:
                return 1
            elif signature_type_val == 2:
                return 2
            elif holo_type_val == 1 and signature_type_val == 1:
                return 3
            elif signature_type_val == 1:
                return 4
            elif holo_type_val == 1:
                return 5
            return 6


        # group collection into embeds and determine rarest card
        embeds = []
        card_list = []
        rarest_card = None

        for item in collection:
            card_name, artist_name, card_variant_id, image_url, holo_type, signature_type, quantity = item

            # determine variations
            variations = []
            if holo_type == 1:
                variations.append("Holo")
            if signature_type == 1:
                variations.append("Signed")
            elif signature_type == 2:
                variations.append("Golden Signed")

            variation_text = " ".join(variations) if variations else "Standard"
            card_summary = f"**{card_name}** ({variation_text}), x{quantity}"

            # store card data
            card_list.append({
                "name": card_name,
                "summary": card_summary,
                "card_variant_id": card_variant_id,
                "image_url": image_url,
                "rarity_value": get_rarity_value(holo_type, signature_type)
            })

            # determine the rarest card
            if rarest_card is None or get_rarity_value(holo_type, signature_type) < rarest_card["rarity_value"]:
                rarest_card = {
                    "image_url": image_url,
                    "rarity_value": get_rarity_value(holo_type, signature_type)
                }

        # create embeds (10 cards per page)
        for i in range(0, len(card_list), 10):
            page_cards = card_list[i:i + 10]
            embed = discord.Embed(
                description="\n".join([card["summary"] for card in page_cards]),
                color=colors["blue"]
            )
            embed.set_footer(text=f"Page {i // 10 + 1} of {len(card_list) // 10 + 1} | Sorting: Rarity")

            # add the rarest card thumbnail
            if rarest_card and i == 0:
                embed.set_thumbnail(url=rarest_card["image_url"])

            embed.set_author(
                name=f"{member.display_name}'s Collection",
                icon_url=member.display_avatar.url
            )

            embeds.append(embed)

        # pass the Gacha instance to the InventoryView
        view = InventoryView(embeds, ctx.author, member, card_list, self.bot, self)
        message = await ctx.send(embed=embeds[0], view=view)
        view.message = message




#-------------------- VIEW PROFILE COMMAND ---------------------------#

    @commands.cooldown(1, 3, BucketType.user)
    @commands.hybrid_command(
        name="profile",
        description="View your profile!"
    )
    async def profile(self, ctx: commands.Context, member: discord.Member = None):
        if not await self.command_channel_check(ctx):
            return
        member = member or ctx.author
        user_id = member.id

        async with Database.connection() as db:
            try:
                # Get base user stats
                cursor = await db.execute(
                    """SELECT currency, total_stardust_collected, total_pulls, 
                    rarest_card_id, current_daily_streak FROM users 
                    WHERE discord_id = ?""",
                    (user_id,)
                )
                result = await cursor.fetchone()

                # Handle missing user
                if not result:
                    embed = discord.Embed(
                        description=f"{member.mention} hasn't started collecting cards yet!",
                        color=colors["blue"]
                    )
                    await ctx.send(embed=embed)
                    return

                # Get leaderboard ranks
                rank_queries = {
                    "stardust": "total_stardust_collected",
                    "streak": "longest_daily_streak",
                    "pulls": "total_pulls"
                }
                
                ranks = {}
                for stat, column in rank_queries.items():
                    cursor = await db.execute(f"""
                        WITH user_stat AS (
                            SELECT {column} AS value FROM users WHERE discord_id = ?
                        )
                        SELECT CASE WHEN user_stat.value IS NULL THEN 'Unranked'
                            ELSE (SELECT COUNT(*) + 1 FROM users 
                            WHERE {column} > (SELECT value FROM user_stat))
                            END AS rank
                        FROM user_stat
                    """, (user_id,))
                    ranks[stat] = (await cursor.fetchone())[0]

            except Exception as e:
                await ctx.send(f"Error fetching profile: {str(e)}")
                return

        currency, total_stardust, total_pulls, rarest_card_id, current_streak = result
        current_streak = current_streak or 0  # Handle None case

        # Format ranks
        def format_rank(rank):
            return f"#{rank}" if isinstance(rank, int) else rank

        # Build embed
        embed = discord.Embed(color=colors["blue"])
        embed.set_author(
            name=f"{member.display_name}'s Profile",
            icon_url=member.display_avatar.url
        )
        
        # Main Stats
        embed.add_field(
            name="Current Stardust",
            value=f"{currency:,} {emotes['stardust']}",
            inline=True
        )
        embed.add_field(
            name="Total Collected",
            value=f"{total_stardust:,} {emotes['stardust']} | {format_rank(ranks['stardust'])}",
            inline=True
        )
        embed.add_field(
            name="Current Streak", 
            value=f"{self.pluralize(current_streak, 'day')} | {format_rank(ranks['streak'])}",
            inline=True
        )

        # Pulls and Ranks
        embed.add_field(
            name="Total Pulls",
            value=f"{self.pluralize(total_pulls, 'pull')} | {format_rank(ranks['pulls'])}",
            inline=True
        )

        # # Add rarest card thumbnail if available
        # if rarest_card_id:
        #     async with Database.connection() as db:
        #         cursor = await db.execute(
        #             """SELECT cards.name, card_variants.image_url 
        #             FROM card_variants
        #             INNER JOIN cards ON card_variants.card_id = cards.id
        #             WHERE card_variants.id = ?""",
        #             (rarest_card_id,)
        #         )
        #         rarest_card = await cursor.fetchone()
        #         if rarest_card:
        #             embed.set_thumbnail(url=rarest_card['image_url'])
        #             embed.add_field(
        #                 name="Rarest Card",
        #                 value=rarest_card['name'],
        #                 inline=False
        #             )

        await ctx.send(embed=embed)




#----------------RECYCLE----------------------------#



    async def fetch_user_card_names(self, user_id):
        """Fetch all unique card names from the user's inventory."""
        async with Database.connection() as db:
            
            try:
                cursor = await db.execute(
                    """
                    SELECT DISTINCT cards.name
                    FROM user_inventory
                    INNER JOIN card_variants ON user_inventory.card_variant_id = card_variants.id
                    INNER JOIN cards ON card_variants.card_id = cards.id
                    WHERE user_inventory.user_id = ?
                    """,
                    (user_id,)
                )
                return [row[0] for row in await cursor.fetchall()]
            except Exception as e:
                
                raise

    async def fetch_variations_for_card(self, user_id, card_name):
        """Fetch all variations of a specific card owned by the user."""
        async with Database.connection() as db:
            
            try:
                cursor = await db.execute(
                    """
                    SELECT DISTINCT card_variants.holo_type, card_variants.signature_type
                    FROM user_inventory
                    INNER JOIN card_variants ON user_inventory.card_variant_id = card_variants.id
                    INNER JOIN cards ON card_variants.card_id = cards.id
                    WHERE user_inventory.user_id = ? AND cards.name = ?
                    """,
                    (user_id, card_name)
                )
                return [
                    self.get_variation_name(holo_type, signature_type)
                    for holo_type, signature_type in await cursor.fetchall()
                ]
            except Exception as e:
                
                raise



    def get_variation_name(self, holo_type, signature_type):
        """Convert holo_type and signature_type values into a variation name."""
        if holo_type == 1 and signature_type == 2:
            return "Holo + Golden Signed"
        elif holo_type == 1 and signature_type == 1:
            return "Holo + Signed"
        elif signature_type == 2:
            return "Golden Signed"
        elif signature_type == 1:
            return "Signed"
        elif holo_type == 1:
            return "Holo"
        else:
            return "Standard"









#---------------------------- LEADERBOARD ------------------------------#



    @commands.cooldown(1, 5, BucketType.user)
    @commands.hybrid_command(name="leaderboard",
                            description="View various stat leaderboards",
                            aliases=["top"]
                            )
    async def leaderboard(self, ctx: commands.Context, board_type: str = "pulls", page: int = 1):
        if not await self.command_channel_check(ctx):
            return
        
        board_type = board_type.lower()
        if board_type not in LEADERBOARD_TYPES:
            return await ctx.send(f"Invalid leaderboard type! Available: {', '.join(LEADERBOARD_TYPES.keys())}")
        
        page = max(1, min(page, 100))
        per_page = 10
        offset = (page - 1) * per_page

        config = LEADERBOARD_TYPES[board_type]

        async with Database.connection() as db:
            cursor = await db.execute(f"""
                SELECT u.discord_id, {config['column']} 
                FROM users u
                WHERE {config['column']} > 0
                ORDER BY {config['column']} DESC
                LIMIT ? OFFSET ?
            """, (per_page, offset))
            entries = await cursor.fetchall()

            user_rank = "Unranked"
            try:
                rank_cursor = await db.execute(f"""
                    WITH user_stats AS (
                        SELECT {config['column']} AS score 
                        FROM users 
                        WHERE discord_id = ?
                    )
                    SELECT 
                        CASE WHEN user_stats.score IS NULL THEN -1
                        ELSE (SELECT COUNT(*) FROM users WHERE {config['column']} > user_stats.score) + 1
                        END AS rank
                    FROM user_stats
                """, (str(ctx.author.id),))
                raw_rank = (await rank_cursor.fetchone())[0]
                if raw_rank != -1:
                    user_rank = f"#{raw_rank}"
            except Exception as e:
                print(f"Rank error: {str(e)}")

        description_lines = []
        for idx, (discord_id, value) in enumerate(entries, start=offset+1):
            try:
                user = await self.bot.fetch_user(int(discord_id))
                name = user.display_name
            except:
                name = f"Unknown ({discord_id})"
            
            line = f"`#{idx:<3}` {name} | {config['format'](value)}"
            description_lines.append(line)

        embed = discord.Embed(
            title=f"{config['title']}",
            description='\n'.join(description_lines),
            color=colors["blue"]
        )
        
        embed.set_footer(
            text=f"Your rank: {user_rank} ㅤ|ㅤ Page {page}",
            icon_url=ctx.author.display_avatar.url
        )

        await ctx.send(embed=embed)



#--------------------- AUTO RECYCLE COMMANDS ----------------------#


    @commands.cooldown(1, 3, BucketType.user)
    @commands.hybrid_command(
        name="autorecycle",
        description="Configure automatic recycling of duplicate cards",
        aliases=["autorec", "auto-recycle"]
    )
    async def autorecycle(self, ctx: commands.Context):
        if not await self.command_channel_check(ctx):
            return

        async with Database.connection() as db:
            cursor = await db.execute(
                "SELECT auto_recycle_level FROM users WHERE discord_id = ?",
                (ctx.author.id,)
            )
            current_level = (await cursor.fetchone())['auto_recycle_level']

        embed = discord.Embed(
            title="Auto-Recycle Settings",
            description=f"**Current Mode:** {AUTO_RECYCLE_OPTIONS[current_level]}",
            color=colors["blue"]
        )
        embed.set_footer(text=f"Configure which duplicate cards get automatically recycled after pulls. (Always keep at least 1 copy, only recycles duplicates from new pulls)")
        view = AutoRecycleView(self, ctx.author)
        await ctx.send(embed=embed, view=view, ephemeral=True)






#--------------------- RECYCYLE ALL ---------------------------#

    @commands.cooldown(1, 3, BucketType.user)
    @commands.hybrid_command(
        name="bulkrecycle",
        description="Bulk recycle cards from your entire collection",
        aliases=["recycleall"]
    )
    async def recycle_all(self, ctx: commands.Context):
        if not await self.command_channel_check(ctx):
            return
        
        embed = discord.Embed(
            title="Bulk Recycling",
            description="**Warning:** This will permanently remove duplicate cards from your collection!\n"
                        "Choose which rarity tiers to recycle:",
            color=colors["blue"]
        )
        embed.add_field(
            name="Options",
            value="\n".join([f"**{k}** - {v}" for k, v in AUTO_RECYCLE_OPTIONS.items()]),
            inline=False
        )
        embed.set_footer(text="You'll keep 1 copy of each card. Process cannot be undone!")
        
        view = BulkRecycleView(self, ctx.author)
        await ctx.send(embed=embed, view=view, ephemeral=True)


#--------------------- BANNER COMMANDS ----------------------#




    # @commands.hybrid_command(name="banner", description="Manage banners")
    # @commands.has_permissions(administrator=True)
    # async def banner(self, ctx: commands.Context):
    #     if not await self.command_channel_check(ctx):
    #         return
    #     pass

    # @commands.hybrid_command(name="createbanner", description="Create a new banner")
    # @commands.has_permissions(administrator=True)
    # async def create_banner(self, ctx: commands.Context, name: str):
    #     if not await self.command_channel_check(ctx):
    #         return
    #     async with Database.connection() as db:
    #         await db.execute("INSERT INTO banners (name) VALUES (?)", (name,))
            
    #     await ctx.send(f"Created new banner: **{name}**")

    # @commands.hybrid_command(name="activatebanner", description="Set active banner")
    # @commands.has_permissions(administrator=True)
    # async def activate_banner(self, ctx: commands.Context, banner_id: int):
    #     if not await self.command_channel_check(ctx):
    #         return
    #     async with Database.connection() as db:
    #         # Deactivate all banners
    #         await db.execute("UPDATE banners SET is_active = 0")
    #         # Activate selected banner
    #         await db.execute("UPDATE banners SET is_active = 1 WHERE id = ?", (banner_id,))
            
    #     await ctx.send(f"Activated banner ID: {banner_id}")
    
    @commands.cooldown(1, 3, BucketType.user)
    @commands.hybrid_command(name="banner")
    async def current_banner(self, ctx: commands.Context):
        if not await self.command_channel_check(ctx):
            return
        
        async with Database.connection() as db:
            # Get active banner
            cursor = await db.execute("""
                SELECT id, name
                FROM banners WHERE is_active = 1
            """)
            banner = await cursor.fetchone()
            
            if not banner:
                return await ctx.send("No active banner!")
                
            # Get all base cards in banner
            cursor = await db.execute("""
                SELECT id, name, image_url, artist_name
                FROM cards 
                WHERE banner_id = ? AND is_limited = 0
                ORDER BY name
            """, (banner['id'],))
            cards = await cursor.fetchall()

        if not cards:
            embed = discord.Embed(
                description=f"This banner has no base cards yet!",
                color=colors["blue"]
            )
            await ctx.send(embed = embed)
            return
        
        card_list = "\n".join(
            f"• **{card['name']}** by *{card['artist_name']}*" 
            for card in cards
        )

        original_embed = discord.Embed(
            title=f"{banner['name']}",
            description=f"**{len(cards)}** base cards, with 6 variants each.\n{card_list}",
            color=colors["blue"]
        )
        
        view = BannerView(cards, self.bot, original_embed)
        await ctx.send(embed=original_embed, view=view)




#-----------------ADMIN POINT MANAGEMENT--------------------------#



    @commands.command(name="addpoints", hidden=True)
    @commands.has_permissions(administrator=True)
    async def add_points(self, ctx, member: discord.Member, amount: int):
        if amount <= 0:
            return await ctx.send("Amount must be positive!")
        
        async with Database.connection() as db:
            await db.execute(
                """UPDATE users 
                SET currency = currency + ?, 
                    total_stardust_collected = total_stardust_collected + ? 
                WHERE discord_id = ?""",
                (amount, amount, member.id)
            )
            embed = discord.Embed(
                description=f"You have added {amount} {emotes['stardust']} to {member.mention}'s balance\n"
                          f"**Current balance:** {await self.get_currency(db, member.id)} {emotes['stardust']}\n",
                color=colors["blue"]
            )
            await ctx.send(embed=embed)

    @commands.command(name="removepoints", hidden=True)
    @commands.has_permissions(administrator=True)
    async def remove_points(self, ctx, member: discord.Member, amount: int):
        async with Database.connection() as db:
            cursor = await db.execute(
                "SELECT currency FROM users WHERE discord_id = ?", 
                (member.id,)
            )
            balance = (await cursor.fetchone())['currency']
            
            if amount > balance:
                return await ctx.send("Cannot remove more points than user has!")
                
            await db.execute(
                "UPDATE users SET currency = currency - ? WHERE discord_id = ?",
                (amount, member.id)
            )
            embed = discord.Embed(
                description=f"You have removed {amount} {emotes['stardust']} from {member.mention}'s balance\n"
                          f"• New balance: {await self.get_currency(db, member.id)} {emotes['stardust']}\n"
                          f"• Total collected: {await self.get_total_collected(db, member.id)} {emotes['stardust']}",
                color=colors["blue"]
            )
            await ctx.send(embed=embed)

    @commands.command(name="setpoints", hidden=True)
    @commands.has_permissions(administrator=True)
    async def set_points(self, ctx, member: discord.Member, amount: int):
        async with Database.connection() as db:
            current_total = await self.get_total_collected(db, member.id)
            current_balance = await self.get_currency(db, member.id)
            
            # Calculate difference to update total collected
            difference = amount - current_balance
            new_total = max(current_total + difference, current_total)
            
            await db.execute(
                """UPDATE users 
                SET currency = ?,
                    total_stardust_collected = ?
                WHERE discord_id = ?""",
                (amount, new_total, member.id)
            )
            embed = discord.Embed(
                description=f"Set {member.mention}'s balance to {amount} {emotes['stardust']}\n"
                          f"• New balance: {amount} {emotes['stardust']}\n"
                          f"• Total collected: {new_total} {emotes['stardust']}",
                color=colors["blue"]
            )
            await ctx.send(embed=embed)

    async def get_currency(self, db, user_id: int) -> int:
        cursor = await db.execute(
            "SELECT currency FROM users WHERE discord_id = ?",
            (user_id,)
        )
        return (await cursor.fetchone())['currency']

    async def get_total_collected(self, db, user_id: int) -> int:
        cursor = await db.execute(
            "SELECT total_stardust_collected FROM users WHERE discord_id = ?",
            (user_id,)
        )
        return (await cursor.fetchone())['total_stardust_collected']







#------------------- TROLL COMMANDS --------------------------#

    @commands.cooldown(1, 3, BucketType.user)
    @commands.command(name="trade", hidden=True)
    async def trade_troll(self, ctx):
        if not await self.command_channel_check(ctx):
            return
        await ctx.send("There is NO trading here! Grahhh")

    @commands.cooldown(1, 3, BucketType.user)
    @commands.command(name="kii", hidden=True)
    async def kii_troll(self, ctx):
        if not await self.command_channel_check(ctx):
            return
        await ctx.send("kii who?")

    @commands.cooldown(1, 3, BucketType.user)
    @commands.command(name="kiichan", hidden=True)
    async def kiichan_troll(self, ctx):
        if not await self.command_channel_check(ctx):
                    return
        await ctx.send("kiichan who?", ephemeral=True)

    @commands.cooldown(1, 3, BucketType.user)
    @commands.command(name="gamble")
    async def gamble_troll(self, ctx):
        if not await self.command_channel_check(ctx):
                    return
        await ctx.send("We do NOT promote gambling here!")

    @commands.cooldown(1, 3, BucketType.user)
    @commands.command(name="hila", hidden=True)
    async def hila_troll(self, ctx, arg: str = None):
        if not await self.command_channel_check(ctx):
            return
        await ctx.send(f"sorry, hindi ko speak tagalog... {emotes['pien']}")

    @commands.cooldown(1, 3, BucketType.user)
    @commands.command(name="push", hidden=True)
    async def push_troll(self, ctx, arg: str = None):
        if not await self.command_channel_check(ctx):
            return
        await ctx.send(f"please stop pushing me... you're supposed to pull! {emotes['pien']}")

    @commands.cooldown(1, 3, BucketType.user)
    @commands.command(name="seed", hidden=True)
    async def seed_troll(self, ctx):
        if not await self.command_channel_check(ctx):
            return
        embed = discord.Embed()
        embed.set_image(url="https://i.ibb.co/BHWjd16x/YesHenry.png")  # Replace with actual URL
        await ctx.send("Yes Henry...", embed=embed)

    @commands.cooldown(1, 3, BucketType.user)
    @commands.command(name="yeshenry", hidden=True)
    async def seed_troll2(self, ctx):
        if not await self.command_channel_check(ctx):
            return
        embed = discord.Embed()
        embed.set_image(url="https://i.ibb.co/BHWjd16x/YesHenry.png")
        await ctx.send("Yes Henry...", embed=embed)

    @pull.error
    async def pull_error(self, ctx, error):
        if not await self.command_channel_check(ctx):
            return
        if isinstance(error, commands.BadArgument):
            args = ctx.message.content.split()[1:]
            if args and args[0].lower() in ['one', 'ten']:
                await ctx.send("Who types out the number? - Seed, Feb 2025",)
                return








async def setup(bot):
    await bot.add_cog(Gacha(bot))