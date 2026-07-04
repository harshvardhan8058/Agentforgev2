-- 0006_create_enterprise_identity.sql
-- Enterprise identity: organizations, users, memberships, teams, team_memberships,
-- and api_keys (Req 8.1). Strictly additive; every statement is idempotent
-- (CREATE ... IF NOT EXISTS) so re-running the migration is a no-op (Req 8.3).
-- No plaintext password or API-key secret is ever stored — only the argon2id hash
-- (Req 8.5).

CREATE TABLE IF NOT EXISTS organizations (
    id         UUID PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,                       -- argon2id; never plaintext (Req 8.5)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memberships (
    user_id    UUID NOT NULL REFERENCES users(id)         ON DELETE CASCADE,
    org_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,                           -- owner | admin | member | viewer
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, org_id)                       -- at most one membership per (user, org) (Req 2.7)
);
CREATE INDEX IF NOT EXISTS memberships_org_idx ON memberships (org_id);

CREATE TABLE IF NOT EXISTS teams (
    id         UUID PRIMARY KEY,
    org_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, name)
);

CREATE TABLE IF NOT EXISTS team_memberships (
    team_id    UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, user_id)
);

CREATE TABLE IF NOT EXISTS api_keys (
    id         UUID PRIMARY KEY,
    org_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,                           -- role granted to this key
    key_prefix TEXT NOT NULL,                           -- first 8 chars of the secret (indexed)
    key_hash   TEXT NOT NULL,                           -- argon2id hash of the secret (Req 8.5)
    revoked_at TIMESTAMPTZ,                             -- NULL => active
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS api_keys_prefix_active_idx
    ON api_keys (key_prefix) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS api_keys_org_idx ON api_keys (org_id);
