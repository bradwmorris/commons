-- Commons foundation. Explicit migration command; ordinary startup does not migrate.
CREATE TABLE objects (
  id uuid PRIMARY KEY,
  kind text NOT NULL CHECK (kind IN ('user','task','memory','note','entity','source','theme','event','chat')),
  title text NOT NULL,
  description text NOT NULL DEFAULT '',
  fields jsonb NOT NULL DEFAULT '{}',
  revision bigint NOT NULL DEFAULT 1,
  created_by uuid,
  updated_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE accounts (
  id uuid PRIMARY KEY REFERENCES objects(id),
  username text UNIQUE NOT NULL,
  password_hash text NOT NULL,
  role text NOT NULL CHECK (role IN ('admin','member','reader')),
  active boolean NOT NULL DEFAULT true
);
CREATE TABLE credentials (
  id uuid PRIMARY KEY,
  account_id uuid NOT NULL REFERENCES accounts(id),
  secret_hash text UNIQUE NOT NULL,
  mode text NOT NULL CHECK (mode IN ('session','agent')),
  label text NOT NULL,
  write_kinds text[] NOT NULL DEFAULT '{}',
  expires_at timestamptz NOT NULL,
  revoked boolean NOT NULL DEFAULT false
);
CREATE TABLE audit_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  object_id uuid NOT NULL REFERENCES objects(id),
  actor_id uuid NOT NULL REFERENCES accounts(id),
  credential_id uuid REFERENCES credentials(id),
  action text NOT NULL,
  revision bigint NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE artifacts (
  id uuid PRIMARY KEY,
  object_id uuid NOT NULL REFERENCES objects(id),
  body text NOT NULL,
  origin text NOT NULL DEFAULT 'caller_supplied' CHECK (origin = 'caller_supplied'),
  created_by uuid NOT NULL REFERENCES accounts(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE connections (
  id uuid PRIMARY KEY,
  from_id uuid NOT NULL REFERENCES objects(id),
  to_id uuid NOT NULL REFERENCES objects(id),
  kind text NOT NULL CHECK (kind IN ('involves','about','related_to','depends_on','derived_from','themed')),
  explanation text NOT NULL,
  created_by uuid NOT NULL REFERENCES accounts(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (from_id <> to_id)
);
CREATE TABLE receipts (
  credential_id uuid NOT NULL REFERENCES credentials(id),
  request_key text NOT NULL,
  request_hash text NOT NULL,
  result jsonb NOT NULL,
  PRIMARY KEY (credential_id, request_key)
);
CREATE INDEX objects_search ON objects USING gin (to_tsvector('english', title || ' ' || description));
