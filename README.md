# KiichuBot
## Developed by: Augustine Suter
This is a Card collecting Discord bot where users can collect and show off virtual trading cards through a gacha-style system. They can chat to earn points, do their dailies, and spend points on rolling for cards of different rarities! It combines a Discord bot, a small web API, and a SQLite database into one cohesive app.

Since this is a WIP and just a passion project, many features are incomplete/many bugs may arise, and I will do my best to address them.

## High‑Level Overview

At a high level, the project has four main pieces:

1. **Discord Bot**  
   - Listens for commands in Discord (e.g. pulling cards, viewing banners, checking inventories).  
   - Sends rich embeds and interactive buttons to guide users through actions.

2. **Card & Gacha System**  
   - Defines banners (gacha pools), cards, and card variants (i.e. different rarities: base, holo, signed, golden signed, etc.).  
   - Implements the logic for rolling on banners, awarding cards, and updating inventories.

3. **Database Layer**  
   - Uses SQLite to store users, currencies, inventories, banners, cards, and variants.  
   - Keeps track of both long‑term stats (total stardust earned) and current state (current balance, owned cards).
   - These stats are readily availalbe to be viewed via commands for the players to see leaderboards, profiles, and card collections.

4. **Web API & Integrations**  
   - Exposes a small HTTP API to handle Twitch OAuth and other integrations.  
   - Allows Twitch events and external services (like Streamerbot) to grant rewards to the correct Discord user.

Together, these components let users interact entirely through Discord as well as Twitch during a stream, while the database and API keep everything persistent and connected to external services.

## Typical User Flow

- A new user joins and runs a command like `!dailies` to initialize their account and earn starter rewards.  
- They roll on a banner to get cards, which are stored in their inventory in the database.  
- They can link their Twitch account to the same profile and earn more pulls through streams via donations or channel redeems.  
- Leaderboards and info commands read from the database to show progress and card collections.

This structure keeps the gameplay inside Discord, while the underlying services handle storage, image links, and account linking behind the scenes.
