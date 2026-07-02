-- ============================================================
-- Schema pentru aplicatia de fotbal amator (Squad Finder)
-- Migrare din MongoDB -> PostgreSQL (Supabase)
-- ============================================================
-- Ruleaza acest fisier in Supabase Dashboard -> SQL Editor -> New query
-- ============================================================

create extension if not exists "uuid-ossp";

-- ----------------------------------------------------------
-- USERS
-- Nu folosim Supabase Auth (pastram JWT propriu),
-- deci acesta e un tabel normal, nu o extensie a auth.users.
-- ----------------------------------------------------------
create table users (
    id              uuid primary key default uuid_generate_v4(),
    email           text unique not null,
    hashed_password text not null,
    full_name       text not null,
    city            text not null default 'București',
    position        text not null default 'midfielder',
    level           text not null default 'intermediate',
    avatar_url      text,
    created_at      timestamptz not null default now()
);

create index idx_users_email on users(email);

-- ----------------------------------------------------------
-- MATCHES
-- ----------------------------------------------------------
create table matches (
    id              uuid primary key default uuid_generate_v4(),
    organizer_id    uuid not null references users(id) on delete cascade,
    organizer_name  text not null default '',
    title           text not null,
    location_name   text not null,
    location_lat    double precision not null,
    location_lng    double precision not null,
    scheduled_at    timestamptz not null,
    players_needed  integer not null,
    current_players integer not null default 1,
    format          text not null,
    level           text not null,
    cost_per_player numeric not null default 0,
    description     text not null default '',
    status          text not null default 'open',  -- open | full | cancelled
    invite_code     text unique not null,
    created_at      timestamptz not null default now()
);

create index idx_matches_status on matches(status);
create index idx_matches_scheduled_at on matches(scheduled_at);
create index idx_matches_invite_code on matches(invite_code);

-- ----------------------------------------------------------
-- MATCH_PLAYERS (jucatorii inscrisi la un meci)
-- ----------------------------------------------------------
create table match_players (
    id          uuid primary key default uuid_generate_v4(),
    match_id    uuid not null references matches(id) on delete cascade,
    user_id     uuid not null references users(id) on delete cascade,
    user_name   text not null default '',
    position    text not null default '',
    status      text not null default 'confirmed',  -- confirmed | waitlist | cancelled
    joined_at   timestamptz not null default now()
);

create index idx_match_players_match on match_players(match_id);
create index idx_match_players_user on match_players(user_id);
create index idx_match_players_status on match_players(status);

-- ----------------------------------------------------------
-- AVAILABILITY ("sunt liber acum, cauta-mi meci")
-- ----------------------------------------------------------
create table availability (
    id              uuid primary key default uuid_generate_v4(),
    user_id         uuid not null references users(id) on delete cascade,
    user_name       text not null default '',
    position        text not null default '',
    level           text not null default '',
    location_lat    double precision not null,
    location_lng    double precision not null,
    radius_km       integer not null default 5,
    available_until timestamptz not null,
    is_active       boolean not null default true,
    created_at      timestamptz not null default now()
);

create index idx_availability_user on availability(user_id);
create index idx_availability_active on availability(is_active, available_until);

-- ----------------------------------------------------------
-- PLAYER_STATS (goluri/assisturi per meci)
-- ----------------------------------------------------------
create table player_stats (
    id          uuid primary key default uuid_generate_v4(),
    user_id     uuid not null references users(id) on delete cascade,
    match_id    uuid not null references matches(id) on delete cascade,
    goals       integer not null default 0,
    assists     integer not null default 0,
    created_at  timestamptz not null default now(),
    unique (user_id, match_id)
);

create index idx_player_stats_user on player_stats(user_id);

-- ----------------------------------------------------------
-- PLAYER_RATINGS
-- ----------------------------------------------------------
create table player_ratings (
    id           uuid primary key default uuid_generate_v4(),
    rater_id     uuid not null references users(id) on delete cascade,
    rater_name   text not null default '',
    rated_id     uuid not null references users(id) on delete cascade,
    match_id     uuid not null references matches(id) on delete cascade,
    fair_play    integer not null,
    punctuality  integer not null,
    skill        integer not null,
    created_at   timestamptz not null default now(),
    unique (rater_id, rated_id, match_id)
);

create index idx_player_ratings_rated on player_ratings(rated_id);

-- ----------------------------------------------------------
-- NOTIFICATIONS
-- ----------------------------------------------------------
create table notifications (
    id          uuid primary key default uuid_generate_v4(),
    user_id     uuid not null references users(id) on delete cascade,
    type        text not null,
    title       text not null,
    message     text not null,
    is_read     boolean not null default false,
    data        jsonb not null default '{}'::jsonb,
    created_at  timestamptz not null default now()
);

create index idx_notifications_user on notifications(user_id, is_read);

-- ----------------------------------------------------------
-- REPORTS (raportare jucatori problematici)
-- ----------------------------------------------------------
create table reports (
    id                  uuid primary key default uuid_generate_v4(),
    reporter_id         uuid not null references users(id) on delete cascade,
    reporter_name       text not null default '',
    reported_user_id    uuid not null references users(id) on delete cascade,
    reason              text not null,
    comment             text not null default '',
    match_id            uuid references matches(id) on delete set null,
    status              text not null default 'pending',
    created_at          timestamptz not null default now()
);

create index idx_reports_reported on reports(reported_user_id);

-- ----------------------------------------------------------
-- VENUES (terenuri de fotbal)
-- ----------------------------------------------------------
create table venues (
    id              uuid primary key default uuid_generate_v4(),
    name            text not null,
    address         text not null,
    city            text not null default 'București',
    location_lat    double precision not null default 44.4268,
    location_lng    double precision not null default 26.1025,
    surface_type    text not null default 'artificial',  -- grass | artificial | indoor
    price_per_hour  numeric not null default 0,
    contact         text not null default '',
    working_hours   text not null default '08:00 - 22:00',
    description     text not null default '',
    photos          jsonb not null default '[]'::jsonb,
    added_by        uuid references users(id) on delete set null,
    verified        boolean not null default false,
    created_at      timestamptz not null default now(),
    unique (name, city)
);

create index idx_venues_city on venues(city);

-- ----------------------------------------------------------
-- VENUE_REVIEWS
-- ----------------------------------------------------------
create table venue_reviews (
    id          uuid primary key default uuid_generate_v4(),
    venue_id    uuid not null references venues(id) on delete cascade,
    user_id     uuid not null references users(id) on delete cascade,
    user_name   text not null default '',
    quality     integer not null,
    surface     integer not null,
    facilities  integer not null,
    comment     text not null default '',
    created_at  timestamptz not null default now(),
    unique (venue_id, user_id)
);

create index idx_venue_reviews_venue on venue_reviews(venue_id);

-- ============================================================
-- IMPORTANT: RLS (Row Level Security)
-- ============================================================
-- Deoarece NU folosim Supabase Auth, ci JWT propriu, backend-ul
-- foloseste service_role key ca sa vorbeasca cu baza de date
-- (service_role ocoleste RLS complet). E ok pentru acest proiect
-- cata vreme service_role key ramane DOAR pe server (.env backend),
-- niciodata in frontend/app mobil.
--
-- De aceea NU activam RLS aici - toata protectia se face in
-- codul FastAPI (get_current_user, verificari de ownership etc).
-- Daca la un moment dat vrei sa accesezi Supabase direct din
-- frontend (fara backend), atunci ai nevoie de RLS + Supabase Auth.
-- ============================================================
