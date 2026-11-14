CREATE SCHEMA IF NOT EXISTS aggieconnect;
SET search_path TO aggieconnect;

CREATE TABLE IF NOT EXISTS users (
  id uuid PRIMARY KEY,
  tenant_id text NOT NULL,
  object_id text NOT NULL,
  email text,
  display_name text,
  major text,
  academic_level text,
  interests text[] NOT NULL DEFAULT '{}',
  organizations text[] NOT NULL DEFAULT '{}',
  career_goals text[] NOT NULL DEFAULT '{}',
  show_reminders boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, object_id)
);

CREATE TABLE IF NOT EXISTS opportunities (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  graph_message_id text NOT NULL,
  content_hash text NOT NULL,
  classifier_version text NOT NULL,
  received_at timestamptz NOT NULL,
  title text NOT NULL,
  summary text NOT NULL,
  category text NOT NULL CHECK (category IN ('internship','scholarship','research','event','academic','emergency','general','other')),
  priority text NOT NULL CHECK (priority IN ('emergency','urgent','deadline','general')),
  tags text[] NOT NULL DEFAULT '{}',
  sender text,
  source_link text,
  location text,
  event_start timestamptz,
  event_end timestamptz,
  deadline_at timestamptz,
  deadline_date date,
  confidence numeric NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  needs_review boolean NOT NULL DEFAULT false,
  verified_source boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, graph_message_id),
  UNIQUE (user_id, id),
  CHECK (event_end IS NULL OR event_start IS NULL OR event_end > event_start)
);

CREATE TABLE IF NOT EXISTS saved_opportunities (
  user_id uuid NOT NULL,
  opportunity_id uuid NOT NULL,
  saved_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, opportunity_id),
  FOREIGN KEY (user_id, opportunity_id) REFERENCES opportunities(user_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS calendar_events (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  opportunity_id uuid NOT NULL,
  transaction_id uuid NOT NULL UNIQUE,
  payload_hash text NOT NULL,
  graph_event_id text,
  web_link text,
  state text NOT NULL CHECK (state IN ('pending','added')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, opportunity_id),
  FOREIGN KEY (user_id, opportunity_id) REFERENCES opportunities(user_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS opportunities_feed_idx
  ON opportunities(user_id, received_at DESC, id);
CREATE INDEX IF NOT EXISTS saved_owner_idx
  ON saved_opportunities(user_id, saved_at DESC);
