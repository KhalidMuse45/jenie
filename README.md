# Jenie

An AI-assisted hierarchical delegation system operated through iMessage.

Jenie helps an organization delegate responsibilities, break them into tasks,
propose assignments, approve delegation plans, notify assignees, and track work.

The deterministic domain model is the source of truth. The language model is only
a natural-language interface to it: it interprets text into typed intents and
never decides permissions, invents identifiers, or holds state.

```
Message → LLM interprets → Typed intent → Permission engine → Domain rules → Transaction
```

## Status

Milestone 1 — organizations, hierarchy, permissions, and messaging identities.
No work items, message transport, or AI yet.

## Requirements

- Python 3.12+
- PostgreSQL 16+ (17 recommended)
- [uv](https://docs.astral.sh/uv/)

## Setup

Install `uv` if you do not have it:

```bash
brew install uv
```

PostgreSQL, either via [Postgres.app](https://postgresapp.com) or Homebrew:

```bash
brew install postgresql@17 && brew services start postgresql@17
```

Or run it in Docker instead, on port 5433:

```bash
docker compose up -d postgres
```

Create the databases:

```bash
createdb jenie_dev
createdb jenie_test
```

> Postgres.app does not add `psql` to your `PATH`. Either use its
> `Contents/Versions/<v>/bin` directory or create the databases from its UI.

Install dependencies and configure the environment:

```bash
cd backend
uv sync --all-groups
cp .env.example .env
```

`DATABASE_URL` must use the async driver — `postgresql+asyncpg://`, not
`postgresql://`. A plain URL fails at runtime rather than at startup.

## Running

```bash
cd backend
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

```bash
curl http://localhost:8000/health
# {"data":{"status":"ok","database":"ok"},"error":null}
```

### Seed development data

```bash
uv run python -m app.seed
```

Creates ColorStack UMN with Khalid (President, superadmin) → Sarah (VP) →
Izra and Marwa, each with a pre-verified iMessage address. Identifiers are
derived with `uuid5`, so the script is safe to re-run and `JENIE_DEFAULT_ORG_ID`
survives a rebuilt database. Copy the printed value into `.env`.

`/health` returns 503 when the database is unreachable, so a process manager can
tell "running" apart from "able to serve".

## Development

```bash
cd backend

uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format .       # format
```

Tests run against `jenie_test` and never touch `jenie_dev`. Override the target
with `JENIE_TEST_DATABASE_URL`.

### Migrations

```bash
uv run alembic revision --autogenerate -m "add work items"
uv run alembic upgrade head
uv run alembic downgrade -1
```

Always read a generated migration before committing it. Autogenerate misses
`CHECK` constraints, partial indexes, and type changes it cannot infer.

## Layout

```
backend/
  app/
    api/          HTTP routes and the response envelope
    database/     engine, session, ORM models
    domain/       enumerations and domain services
      organizations/  hierarchy traversal (OrgGraph)
      identity/       address normalization and sender resolution
      permissions/    the authorization engine
    config.py     settings from the environment
    logging.py    structlog configuration
    main.py       application factory
    seed.py       development organization
  alembic/        migrations
  tests/
docker-compose.yml
```

Later milestones add the rest of `app/domain/` (work, delegation, approvals,
audit), `app/application/` (commands and queries), `app/messaging/`, `app/ai/`,
and `app/notifications/`.

## Conventions

- All timestamps stored in UTC; converted only for display.
- UUID primary keys; sequential identifiers are never an authorization mechanism.
- Every endpoint returns `{"data": ..., "error": ...}`.
- `error.message` is a sentence a person can read — it is relayed to users verbatim.
- Authority is evaluated against a membership, never a user. One person may hold
  memberships in several organizations without carrying permissions between them.
- Hierarchy traversals go through `OrgGraph`, never ad-hoc recursive SQL.
- Authorization goes through `app/domain/permissions`, never a role check in a
  route handler. See [docs/permissions.md](docs/permissions.md).
- A message's sender is established from a *verified* messaging identity, never
  from anything the message says about who sent it.
- Addresses are normalized once on the way in. `address_norm` is the only column
  ever matched against; `address_raw` exists for debugging.
