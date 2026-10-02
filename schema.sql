create table if not exists searches (
  id bigint generated always as identity primary key,
  client_id text,
  query text not null,
  created_at timestamptz default now()
);
create table if not exists saved_products (
  id bigint generated always as identity primary key,
  client_id text not null,
  product_id text not null,
  product jsonb not null,
  created_at timestamptz default now(),
  unique (client_id, product_id)
);
alter table searches enable row level security;
alter table saved_products enable row level security;
