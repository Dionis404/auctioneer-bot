CREATE TABLE IF NOT EXISTS auctions (
    auction_id      text PRIMARY KEY,
    item_name       text,
    item_type       text,           -- wearable | collectible | nft
    supply          int,
    sfl_price       numeric,
    ingredients     jsonb,
    start_at        timestamptz,
    end_at          timestamptz,
    chapter_limit   int,
    start_id        int,
    raw             jsonb,
    results_fetched boolean DEFAULT false,
    updated_at      timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auction_results (
    auction_id        text PRIMARY KEY REFERENCES auctions(auction_id),
    my_status         text,          -- winner | loser
    participant_count int,
    supply            int,
    leaderboard       jsonb,
    fetched_at        timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS item_total_supply (
    item_name    text PRIMARY KEY,
    total_supply bigint,
    updated_at   timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auction_notifications (
    id            serial PRIMARY KEY,
    auction_id    text REFERENCES auctions(auction_id),
    kind          text,              -- reminder_1h | started | results
    chat_id       bigint,
    message_id    bigint,
    sent_at       timestamptz DEFAULT now(),
    delete_at     timestamptz,
    deleted       boolean DEFAULT false
);
