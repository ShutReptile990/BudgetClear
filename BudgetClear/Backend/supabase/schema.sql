-- Run once in the Supabase SQL Editor before switching on Supabase mode.
-- Safe to rerun. Do not create a public bucket or add public read policies.
create extension if not exists pgcrypto with schema extensions;

create table if not exists public.csv_uploads (
  id uuid primary key,
  user_id uuid not null references auth.users(id),
  original_filename text not null,
  object_path text not null unique,
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes bigint not null check (size_bytes > 0),
  row_count integer not null check (row_count > 0),
  currency text check (currency in ('USD', 'GBP', 'INR', 'EUR')),
  created_at timestamptz not null default now(),
  check (object_path = user_id::text || '/' || id::text || '.csv')
);
alter table public.csv_uploads add column if not exists currency text;

create table if not exists public.audits (
  id text primary key,
  user_id uuid not null references auth.users(id),
  budget_name text not null,
  original_filename text,
  created_at timestamptz not null default now(),
  record_count integer not null check (record_count >= 0),
  declared_total text,
  calculated_total text,
  difference text,
  discrepancy_count integer not null default 0,
  data_quality_count integer not null default 0,
  review_suggestion_count integer not null default 0,
  reconciliation_status text not null default 'completed',
  source_ids uuid[] not null,
  snapshot_json text not null,
  snapshot_sha256 text not null,
  check (cardinality(source_ids) between 1 and 50),
  check (snapshot_sha256 = encode(extensions.digest(snapshot_json, 'sha256'), 'hex'))
);
create index if not exists audits_user_created on public.audits(user_id, created_at desc);
create index if not exists csv_uploads_user_created on public.csv_uploads(user_id, created_at desc);

alter table public.csv_uploads enable row level security;
alter table public.audits enable row level security;
revoke all on public.csv_uploads, public.audits from anon, public;
revoke all on public.csv_uploads, public.audits from authenticated;
grant select, insert on public.csv_uploads, public.audits to authenticated;

drop policy if exists csv_read_own on public.csv_uploads;
create policy csv_read_own on public.csv_uploads for select to authenticated
using (user_id = (select auth.uid()));
drop policy if exists csv_insert_own on public.csv_uploads;
create policy csv_insert_own on public.csv_uploads for insert to authenticated
with check (user_id = (select auth.uid()));
drop policy if exists audits_read_own on public.audits;
create policy audits_read_own on public.audits for select to authenticated
using (user_id = (select auth.uid()));
drop policy if exists audits_insert_own on public.audits;
create policy audits_insert_own on public.audits for insert to authenticated
with check (user_id = (select auth.uid()));

create or replace function public.budgetclear_validate_sources()
returns trigger language plpgsql set search_path = '' as $$
declare source_id uuid;
begin
  foreach source_id in array new.source_ids loop
    if not exists (select 1 from public.csv_uploads where id = source_id and user_id = new.user_id) then
      raise exception 'CSV source does not belong to this auditor';
    end if;
  end loop;
  return new;
end;
$$;
drop trigger if exists validate_audit_sources on public.audits;
create trigger validate_audit_sources before insert on public.audits
for each row execute function public.budgetclear_validate_sources();

create or replace function public.budgetclear_immutable()
returns trigger language plpgsql set search_path = '' as $$
begin
  raise exception 'BudgetClear evidence records are immutable';
end;
$$;
drop trigger if exists immutable_audits on public.audits;
create trigger immutable_audits before update or delete on public.audits
for each row execute function public.budgetclear_immutable();
drop trigger if exists immutable_csv_uploads on public.csv_uploads;
create trigger immutable_csv_uploads before update or delete on public.csv_uploads
for each row execute function public.budgetclear_immutable();

insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
values ('budgetclear-csv', 'budgetclear-csv', false, 20971520, array['text/csv'])
on conflict (id) do update set public = false,
  file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists budgetclear_csv_insert on storage.objects;
create policy budgetclear_csv_insert on storage.objects for insert to authenticated
with check (bucket_id = 'budgetclear-csv' and (storage.foldername(name))[1] = (select auth.uid())::text);
drop policy if exists budgetclear_csv_read on storage.objects;
create policy budgetclear_csv_read on storage.objects for select to authenticated
using (bucket_id = 'budgetclear-csv' and (storage.foldername(name))[1] = (select auth.uid())::text);
-- Only failed uploads without committed metadata can be removed. No UPDATE/upsert policy.
drop policy if exists budgetclear_csv_cleanup on storage.objects;
create policy budgetclear_csv_cleanup on storage.objects for delete to authenticated
using (bucket_id = 'budgetclear-csv' and (storage.foldername(name))[1] = (select auth.uid())::text
       and not exists (select 1 from public.csv_uploads where object_path = name));

notify pgrst, 'reload schema';
