-- FORCLOS schema. Aiven for PostgreSQL. Idempotent: safe to re-run.
create extension if not exists pg_trgm;

-- ---------------------------------------------------------------- external data (real, public)

create table if not exists bodacc_notices (
  id               text primary key,          -- BODACC record id: upsert key, ingestion is idempotent
  siren            text,
  denomination     text,
  is_legal_person  boolean,
  ville            text,
  cp               text,
  departement      text,
  tribunal         text,
  date_parution    date not null,
  jugement_famille text,
  jugement_nature  text,
  jugement_date    date,
  event_kind       text not null,             -- OPENING | CONVERSION | PRONOUNCED_LJ | PLAN_RESOLUTION | PLAN | CLOSURE | OTHER
  procedure        text,                      -- SAUVEGARDE | SAUVEGARDE_ACCELEREE | REDRESSEMENT | LIQUIDATION
  complement       text,                      -- judgment free text (officers, cessation date)
  officers         jsonb not null default '[]',
  url              text,
  raw              jsonb not null,
  first_seen_at    timestamptz not null default now(),
  last_seen_at     timestamptz not null default now()
);
create index if not exists bodacc_siren_idx on bodacc_notices (siren);
create index if not exists bodacc_parution_idx on bodacc_notices (date_parution desc);
create index if not exists bodacc_denom_trgm on bodacc_notices using gin (denomination gin_trgm_ops);

create table if not exists ingest_runs (
  id          serial primary key,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  since       date,
  fetched     int,
  inserted    int,
  updated     int,
  error       text
);

create table if not exists company_cache (     -- API Recherche d'entreprises responses (offline fallback)
  cache_key  text primary key,                 -- 'search:<q>|<cp>' or 'siren:<siren>'
  payload    jsonb not null,
  fetched_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- the creditor's ledger (fictional)

create table if not exists customers (
  id                serial primary key,
  crm_name          text not null,             -- as typed by sales: often a trade name
  crm_siren         text,                      -- may be null, wrong or stale
  address           text,
  postal_code       text,
  city              text,
  payment_terms     text not null default 'NET30',  -- NET30 | CASH (new deliveries paid on delivery)
  verified_siren    text,                      -- written ONLY by identity resolution (rule or agent)
  identity_status   text not null default 'UNVERIFIED',  -- UNVERIFIED | VERIFIED | REVIEW | NOT_FOUND
  identity_evidence jsonb,
  dataset           text not null default 'demo',  -- demo | bench
  bench_case_id     text,
  created_at        timestamptz not null default now()
);
create index if not exists customers_verified_siren_idx on customers (verified_siren);
create index if not exists customers_name_trgm on customers using gin (crm_name gin_trgm_ops);

create table if not exists contracts (
  id                  serial primary key,
  customer_id         int not null references customers(id) on delete cascade,
  kind                text not null,          -- FRAMEWORK_SUPPLY | ONE_OFF_SALE | SERVICES
  retention_of_title  boolean not null default false,  -- clause de réserve de propriété
  published_security  boolean not null default false,  -- out of scope -> REVIEW
  signed_on           date,
  body                text
);

create table if not exists invoices (
  id            serial primary key,
  customer_id   int not null references customers(id) on delete cascade,
  number        text not null,
  invoice_date  date not null,
  due_date      date not null,
  amount_cents  bigint not null,
  paid_cents    bigint not null default 0,
  contract_id   int references contracts(id)
);

create table if not exists documents (       -- delivery notes, orders, payment advices
  id           serial primary key,
  customer_id  int not null references customers(id) on delete cascade,
  invoice_id   int references invoices(id) on delete cascade,
  kind         text not null,                -- DELIVERY_NOTE | ORDER | PAYMENT | CONTRACT
  doc_date     date,                         -- as printed; the agent must read the body, not trust this
  body         text not null,                -- plain text or JSON-as-text
  added_by     text not null default 'seed', -- seed | judge
  created_at   timestamptz not null default now()
);

-- ---------------------------------------------------------------- cases: the agent's durable memory

create table if not exists cases (
  id                       serial primary key,
  customer_id              int not null references customers(id) on delete cascade,
  siren                    text not null,
  status                   text not null default 'DETECTED',  -- DETECTED | INVESTIGATING | READY | NEEDS_REVIEW | CLOSED
  anchor_notice_id         text references bodacc_notices(id),
  opening_judgment_date    date,
  current_procedure        text,
  claim_deadline           date,
  revendication_deadline   date,
  relief_deadline          date,
  exposure_cents           bigint not null default 0,    -- all unpaid
  declare_cents            bigint not null default 0,    -- unpaid AND pre-opening
  notes                    jsonb not null default '[]',
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  unique (customer_id, siren)
);

create table if not exists case_events (     -- every notice ever linked to a case: temporal memory
  case_id     int not null references cases(id) on delete cascade,
  notice_id   text not null references bodacc_notices(id),
  linked_at   timestamptz not null default now(),
  primary key (case_id, notice_id)           -- replaying a notice is a no-op
);

create table if not exists invoice_classifications (   -- append-only: the UI shows how decisions changed
  id                    serial primary key,
  case_id               int not null references cases(id) on delete cascade,
  invoice_id            int not null references invoices(id) on delete cascade,
  category              text not null,       -- DECLARE | POST_OPENING | PAID | REVIEW
  fait_generateur       date,
  basis                 text,                -- DELIVERY | SERVICE_PERFORMED | ORDER_ACCEPTANCE | CONTRACT_CONCLUSION | INVOICE_DATE
  evidence_document_id  int references documents(id),
  rationale             text,
  decided_by            text not null,       -- RULE | AGENT
  run_id                uuid,
  created_at            timestamptz not null default now()
);
create or replace view current_classifications as
  select distinct on (case_id, invoice_id) * from invoice_classifications
  order by case_id, invoice_id, id desc;

create table if not exists agent_runs (
  id          uuid primary key,
  case_id     int references cases(id) on delete cascade,
  customer_id int references customers(id) on delete cascade,
  task        text not null,                 -- RESOLVE_IDENTITY | INVESTIGATE_CASE
  status      text not null default 'RUNNING',  -- RUNNING | DONE | ERROR
  summary     text,
  model       text,
  input_tokens int, output_tokens int,
  started_at  timestamptz not null default now(),
  finished_at timestamptz
);

create table if not exists agent_steps (     -- the evidence trail streamed to the UI
  id          bigserial primary key,
  run_id      uuid not null references agent_runs(id) on delete cascade,
  kind        text not null,                 -- NOTE | TOOL_CALL | TOOL_RESULT | DECISION | ERROR
  tool        text,
  payload     jsonb,
  created_at  timestamptz not null default now()
);
create index if not exists agent_steps_run_idx on agent_steps (run_id, id);

create table if not exists actions (
  id          serial primary key,
  case_id     int not null references cases(id) on delete cascade,
  kind        text not null,                 -- CLAIM_DRAFT | PAYMENT_TERMS_CASH | REVENDICATION_ALERT | LAWYER_REVIEW
  payload     jsonb not null,
  status      text not null default 'PROPOSED',  -- PROPOSED | APPLIED | DISMISSED
  created_at  timestamptz not null default now(),
  applied_at  timestamptz,
  unique (case_id, kind)                     -- re-investigation updates, never duplicates
);

create table if not exists benchmark_runs (
  id        serial primary key,
  run_at    timestamptz not null default now(),
  split     text not null,                   -- dev | holdout
  system    text not null,                   -- NAIVE | RULES | FORCLOS
  metrics   jsonb not null,
  details   jsonb not null
);
