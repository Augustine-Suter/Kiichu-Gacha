CREATE TABLE IF NOT EXISTS `prefixes` (
  `server_id` varchar(20) NOT NULL,
  `prefix` varchar(20) NOT NULL,
  PRIMARY KEY (`server_id`)
);


CREATE TABLE IF NOT EXISTS `msglog_webhooks` (
  `guild_id` varchar(20) NOT NULL,
  `webhook_url` text NOT NULL,
  PRIMARY KEY (`guild_id`)
);

CREATE TABLE IF NOT EXISTS `modlog_channels` (
  `guild_id` varchar(20) NOT NULL,
  `channel_id` varchar(20) NOT NULL,
  PRIMARY KEY (`guild_id`)
);


CREATE TABLE IF NOT EXISTS `blacklist` (
  `user_id` varchar(20) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS `warns` (
  `id` int(11) NOT NULL,
  `user_id` varchar(20) NOT NULL,
  `server_id` varchar(20) NOT NULL,
  `moderator_id` varchar(20) NOT NULL,
  `reason` varchar(255) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
);



CREATE TABLE IF NOT EXISTS automated_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL,
    message TEXT NOT NULL,
    interval_seconds INTEGER NOT NULL,
    next_run DATETIME NOT NULL
);



-- Users Table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id TEXT NOT NULL UNIQUE,
    currency INTEGER NOT NULL DEFAULT 0,
    total_stardust_collected INTEGER NOT NULL DEFAULT 0,
    total_pulls INTEGER NOT NULL DEFAULT 0,
    total_cards_owned INTEGER NOT NULL DEFAULT 0,
    total_unique_variants INTEGER NOT NULL DEFAULT 0,
    rarest_card_id INTEGER DEFAULT NULL,
    current_daily_streak INTEGER NOT NULL DEFAULT 0,
    longest_daily_streak INTEGER NOT NULL DEFAULT 0,
    last_daily DATETIME DEFAULT NULL,
    daily_message_count INTEGER NOT NULL DEFAULT 0,
    last_message_points DATETIME DEFAULT NULL,
    rarity_value INTEGER DEFAULT 6,
    auto_recycle_level INTEGER NOT NULL DEFAULT 0,
    has_claimed_welcome INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (rarest_card_id) REFERENCES card_variants (id) ON DELETE SET NULL
);

-- Banners Table
CREATE TABLE IF NOT EXISTS banners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    is_active BOOLEAN DEFAULT 0,
    start_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    end_date DATETIME DEFAULT NULL
);

-- Cards Table
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    image_url TEXT NOT NULL,
    artist_name TEXT NOT NULL,
    flavor_text TEXT DEFAULT NULL,
    description TEXT DEFAULT NULL,
    banner_id INTEGER NOT NULL REFERENCES banners(id) DEFAULT 1,
    is_limited BOOLEAN DEFAULT 0,
    max_copies INTEGER DEFAULT NULL
);

-- Card Variants Table
CREATE TABLE IF NOT EXISTS card_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    holo_type INTEGER NOT NULL,
    signature_type INTEGER NOT NULL,
    image_url TEXT NOT NULL,
    generation INTEGER DEFAULT 1
);

-- User Inventory Table
CREATE TABLE IF NOT EXISTS user_inventory (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    card_variant_id INTEGER NOT NULL REFERENCES card_variants(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 1,
    obtained_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, card_variant_id)
);

-- Limited Card Instances Table
CREATE TABLE IF NOT EXISTS limited_card_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_variant_id INTEGER NOT NULL REFERENCES card_variants(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    serial_number INTEGER NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(card_variant_id, serial_number)
);



CREATE TABLE IF NOT EXISTS user_card_sets (
    user_id INTEGER NOT NULL REFERENCES users(id),
    card_id INTEGER NOT NULL REFERENCES cards(id),
    completed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, card_id)
);



-- Initial Data
INSERT OR IGNORE INTO banners (id, name, is_active) VALUES (1, 'Casual Kiichan', 1);


CREATE TABLE IF NOT EXISTS achievements (
    user_id INTEGER NOT NULL,
    achievement_type TEXT NOT NULL,
    tier INTEGER NOT NULL,
    PRIMARY KEY (user_id, achievement_type, tier),
    FOREIGN KEY (user_id) REFERENCES users(discord_id) ON DELETE CASCADE
);



-- Indexes for leaderboard optimization
CREATE INDEX IF NOT EXISTS idx_users_pulls ON users(total_pulls);
CREATE INDEX IF NOT EXISTS idx_users_stardust ON users(total_stardust_collected);
CREATE INDEX IF NOT EXISTS idx_users_streak ON users(longest_daily_streak);
CREATE INDEX IF NOT EXISTS idx_users_last_daily ON users(last_daily);
CREATE INDEX IF NOT EXISTS idx_variant_rarity ON card_variants(holo_type, signature_type, card_id, image_url);

-- Indexes
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_inventory_unique ON user_inventory (user_id, card_variant_id);
CREATE INDEX IF NOT EXISTS idx_inventory_user ON user_inventory(user_id);
CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name);
CREATE INDEX IF NOT EXISTS idx_variants_holo_sig ON card_variants(holo_type, signature_type);
CREATE INDEX IF NOT EXISTS idx_inventory_sorting ON user_inventory(user_id, quantity);
CREATE INDEX IF NOT EXISTS idx_variants_rarity ON card_variants(holo_type, signature_type);
CREATE INDEX IF NOT EXISTS idx_banners_active ON banners(is_active);
