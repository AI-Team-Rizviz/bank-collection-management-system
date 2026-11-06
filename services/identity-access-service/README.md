# Identity & Access Service (IAM)

Independent identity-and-authorization microservice for the Bank Collection Management System (CMS).
It owns the PostgreSQL schema **`iam`** and nothing else, and is consumed over REST by the other CMS services
(policy-strategy, delinquency, collections, communication, reporting, future AI services) so that **no other service ever
reads IAM tables**.

> Fictional data only. Roles/permissions are CMS design assumptions, not Allied Bank Pakistan's real access policy.

## 1. Responsibilities

| In scope | Out of scope |
|---|---|
| Users (username, password hash, status), roles, permissions, user-role and role-permission mapping | MFA, SSO / external identity providers, rate limiting (gateway) |
| Teams, memberships, access scopes (OWN/TEAM/BRANCH/REGION/PORTFOLIO/GLOBAL) | Business data (cases, policies...) - owned by other services |
| Authorization decisions (RBAC + scope) for IAM itself and for other services | Enforcing permissions *inside* other services (they call IAM / use the contract below) |
| Maker-checker for privileged changes, append-only security audit | Real bank SSO integration (configurable, provider-agnostic) |

## 2. Project structure

```text
services/identity-access-service/
├── app/
│   ├── main.py                    # app factory (docs gating, CORS, request-id middleware, routers under /api/v1)
│   ├── cli.py                     # operator CLI: bootstrap-admin
│   ├── api/deps.py                # token -> Principal, require_permission(...)
│   ├── api/v1/                    # users, roles, permissions, teams, scopes, access_requests, authorization, audit, health
│   ├── core/                      # config (pydantic-settings), database, security (Principal), exceptions, logging
│   ├── domain/                    # models (SQLAlchemy), enums, policies.py (pure RBAC+scope evaluation, maker-checker triggers)
│   ├── application/               # user/role/permission/team/scope/access/authorization services (business rules)
│   ├── infrastructure/            # tokens.py (token issue/validation), audit_repository.py
│   └── schemas/                   # Pydantic v2 request/response models
├── migrations/                    # Alembic (version table: iam.alembic_version_iam)
├── scripts/db/init_iam_roles.sql  # one-off DBA script: iam_migrator / iam_user roles + schema grants
├── tests/{unit,integration,security}
├── Dockerfile, docker-compose.dev.yml, requirements.lock, pyproject.toml, .env.example
../../data_seed/seed/identity/     # ALL IAM seed data lives in the repo's existing seeding package
```

There is intentionally no repository layer: services use SQLAlchemy directly (avoids boilerplate; the ORM already is the abstraction).

## 3. Dependencies

Python >= 3.11 (developed on 3.12), FastAPI, SQLAlchemy 2 (sync) + psycopg 3, Alembic, Pydantic v2 + pydantic-settings,
PyJWT[crypto], httpx, Typer; dev: pytest, Ruff. Sync SQLAlchemy matches the existing `data_seed` module; FastAPI runs the
sync endpoints in its thread pool. `requirements.lock` pins the runtime closure used by the Docker image.

```bash
cd services/identity-access-service
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## 4. Database configuration

Configuration is read from the process environment, then `services/identity-access-service/.env` (git-ignored; see `.env.example`).
Credentials are never logged or printed. `DATABASE_URL` uses the **runtime** role; Alembic uses `MIGRATION_DATABASE_URL`
(falls back to `DATABASE_URL`).

| Role | Purpose | Privileges |
|---|---|---|
| `iam_migrator` | DDL via Alembic | owns schema `iam` |
| `iam_user` | service runtime + seeding | `USAGE` on `iam`; `SELECT/INSERT/UPDATE/DELETE` on tables; **only `SELECT, INSERT` on `audit_logs`**; no access to any other schema |

**One-time setup by a DBA/superuser** (passwords are psql variables, never stored in the script):

```bash
psql -d bank-cms -v migrator_pw="'<generated>'" -v runtime_pw="'<generated>'" -f scripts/db/init_iam_roles.sql
```

then put the `iam_user` URL into `.env` (`postgresql+psycopg://iam_user:<runtime_pw>@localhost:5432/bank-cms`, URL-encode special
characters). If PostgreSQL runs in Docker use the Compose service name / `host.docker.internal` instead of `localhost`.
The script and the migrations only touch schema `iam`; other services' schemas and Alembic histories are never modified.

## 5. Migrations

```bash
export MIGRATION_DATABASE_URL=postgresql+psycopg://iam_migrator:<pw>@localhost:5432/bank-cms
alembic upgrade head            # creates 13 tables + iam.alembic_version_iam
alembic check                   # models == schema (no drift)
alembic downgrade base          # drops IAM tables only
```

Tables: `users, roles, permissions, role_permissions, role_conflicts, user_roles, teams, team_members, access_scopes,
user_access_scopes, access_requests, access_approvals, audit_logs`. No cross-service foreign keys: other services store IAM
user UUIDs by value only. `audit_logs` has no FKs (history outlives entities) and a trigger rejects every `UPDATE`/`DELETE`.

### ER diagram

```mermaid
erDiagram
    users ||--o{ user_roles : holds
    roles ||--o{ user_roles : "granted via"
    roles ||--o{ role_permissions : maps
    permissions ||--o{ role_permissions : "granted by"
    roles ||--o{ role_conflicts : "mutually exclusive (SoD)"
    users ||--o{ team_members : "member of"
    teams ||--o{ team_members : has
    users ||--o{ user_access_scopes : "has scope"
    access_scopes ||--o{ user_access_scopes : "assigned as"
    users ||--o{ access_requests : "requests (maker)"
    access_requests ||--o{ access_approvals : "decided by (checker)"
    users ||--o{ access_approvals : approves
    users { uuid id PK
            string external_identity_id UK
            string username UK
            string email UK
            string status
            int authz_version }
    roles { uuid id PK
            string code UK
            bool is_system
            bool is_privileged
            string status }
    permissions { uuid id PK
                  string code UK
                  bool is_sensitive
                  array allowed_scope_types }
    access_scopes { uuid id PK
                    string scope_type
                    string scope_value }
    access_requests { uuid id PK
                      string request_type
                      string status
                      uuid requested_by FK }
    audit_logs { bigint id PK
                 timestamptz occurred_at
                 string action
                 string outcome }
```

## 6. Authentication architecture

Authentication ("who are you?") is a plain **username + password login handled by this service**.

* `POST /api/v1/auth/login {"username", "password"}` -> `{"access_token", "token_type": "bearer", "expires_in"}`. The only
  unauthenticated endpoint besides `/health`. Clients then send `Authorization: Bearer <access token>`.
* Passwords are stored only as salted **scrypt** hashes (`core/passwords.py`, stdlib, no extra dependency). Unknown user, wrong
  password, no password set and deactivated account all return the *same* `401`, and a hash is derived in every case (no timing oracle).
  Success and failure are audited (`auth.login`, `auth.login_failed`).
* `infrastructure/tokens.py` signs tokens **HS256** with `JWT_SECRET_KEY` and validates every request: signature, issuer, audience,
  **expiry** (small leeway), required `exp, iss, aud, sub`. The algorithm is fixed server-side (`none` and other algorithms are rejected).
  Lifetime: `ACCESS_TOKEN_TTL_SECONDS` (default 1h).
* **Identity mapping:** token `sub` -> `iam.users.external_identity_id` (defaults to `local-<username>`). Unknown and deactivated users get an
  *identical* `403`; all token failures return the same generic `401`.
* **Service identities:** a token whose `sub` is listed in `SERVICE_SUBJECTS` is a service principal. It may call
  `POST /authorization/check` for any user and nothing else. Such subjects cannot be registered as users. Mint one with
  `python -m app.cli issue-service-token --subject svc-name --days 90`.
* In `production` the app refuses to start without a `JWT_SECRET_KEY` of at least 32 characters. If it is missing in other
  environments, protected endpoints and login fail closed with `503`.

### Passwords

* Admins may set an initial password when creating a user (`password`, 10-128 chars); without one the user cannot log in.
* Operators set/reset passwords with `python -m app.cli set-password --username <name>` (interactive prompt, audited).
  There is no self-service change/reset endpoint yet.

### Local development login

Seed the catalog and demo users (`python -m seed.cli identity seed --demo-users` in `data_seed`). Every demo user shares the development
password `DemoPass!2345` (override with `DEMO_USER_PASSWORD`):

```bash
curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
     -d '{"username":"sysadmin001","password":"DemoPass!2345"}'      # -> access_token
```

**Bootstrapping real administrators** (no shared secret, no default admin): after the catalog is seeded, an operator with DB access runs, once per person
(maker-checker needs at least two):

```bash
python -m app.cli bootstrap-admin --username <name> --email <addr> --display-name "<name>"   # prompts for the password
```

Every run is audited.

## 13. Tests

```bash
export TEST_DATABASE_URL=postgresql+psycopg://<user>@127.0.0.1:5432/postgres   # a role allowed to CREATE DATABASE; any server you can throw data away on
pytest                    # 217+ tests; creates and drops its own disposable database, never touches bank-cms
pytest tests/unit         # no database needed
ruff check app tests
```

Without `TEST_DATABASE_URL` the DB tests are skipped (visibly), never silently passed. A disposable server is e.g.
`docker run --rm -p 55432:5432 -e POSTGRES_HOST_AUTH_METHOD=trust postgres:16` with `TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55432/postgres`.
Layout: `tests/unit` (policy engine, token validation, schemas), `tests/integration` (API + database: integrity, concurrency, audit, Alembic up/down/no-drift,
seed idempotency), `tests/security` (every endpoint requires auth, deny-by-default, token failure modes, privilege-escalation attempts, error hygiene).

## 14. Seed data

`data_seed/seed/identity/` (the repo's single seeding package): `roles.py` (10 roles + SoD conflicts), `permissions.py` (44-permission catalog), `role_permissions.py`, `teams.py`
(3 fictional teams, branch/region/portfolio/global scopes), `demo_users.py` (14 fictional dev users, `@example.invalid`, no passwords exist), `runner.py`.
Seeding is idempotent (upsert on stable codes), additive for role-permission links (re-seeding never silently removes an approved grant, never reactivates a deactivated system role),
uses the IAM service's own DB credentials (`IAM_DATABASE_URL` or this service's `.env`), and **demo users refuse to seed unless `APP_ENV` is `development`/`test`**.

## 15. Consistency and revocation behaviour

| Consumer path | Freshness | Revocation takes effect |
|---|---|---|
| IAM's own endpoints | Evaluated live against the database on every request | Immediately |
| `POST /authorization/check` | Live | Immediately |
| Consumer-side cache of an **allowed, non-sensitive** decision | Response carries `cache_ttl_seconds` (default 60) and `authz_version` | Within `cache_ttl_seconds` |
| **Sensitive** permissions (`is_sensitive`) and every deny | `cache_ttl_seconds = 0` - consumers must call IAM each time | Immediately |
| Roles baked into a token | Not used: tokens carry identity only, so a stale token cannot retain privileges | n/a |

Every change to a user's effective access (role/scope grant or revoke, role-definition change, deactivation) bumps `users.authz_version`;
consumers can use it to invalidate cached entries. Net effect: a revoked privileged role stops working immediately for sensitive actions and for IAM itself, and within `cache_ttl_seconds`
for cached non-sensitive decisions. A deactivated user is refused by IAM immediately; other services that validate tokens locally keep
accepting the *identity* until the access token expires, which is why they must still ask IAM before authorizing (§16).

## 16. Integrating other microservices

1. **Authenticate the end user** yourself: validate the bearer token with the same `JWT_SECRET_KEY` and checks as §6 (or call `GET /api/v1/me` with it). Take only `sub` from it.
2. **Fetch resource attributes from your own authoritative store** (never from the request body): `assigned_user_id` (IAM user UUID), `assigned_team_id`, `branch_id`, `region_id`, `portfolio_id`.
3. **Ask IAM** with your *service* token: `POST /api/v1/authorization/check {"subject": <sub>, "permission": "...", "resource": {...}}`; require `allowed == true`.
4. **Fail closed**: if IAM is unreachable, times out or returns anything unexpected, deny (return 503/403) - never fall back to allow. Cache only `allowed && cache_ttl_seconds > 0`
   decisions, keyed by (subject, permission, resource attributes), for at most `cache_ttl_seconds`, and drop entries when you observe a higher `authz_version`.
5. Store IAM user UUIDs as plain columns (`created_by`, `assigned_to`) - **no foreign keys** into `iam`.

```python
# illustrative consumer helper (kept out of this repo on purpose: a shared client library would couple services)
async def require_permission(sub: str, permission: str, resource: dict) -> None:
    try:
        r = await iam.post("/api/v1/authorization/check", json={"subject": sub, "permission": permission, "resource": resource}, timeout=2.0)
        r.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(503, "authorization unavailable")           # fail closed
    if not r.json()["allowed"]:
        raise HTTPException(403, "forbidden")
```

End users calling `/authorization/check` may only check themselves and may not pass `resource` (they could fabricate it); only service identities can supply resource context.
No shared client package is shipped: the contract is one HTTP call, and sharing code would tightly couple release cycles.

## 17. Security limitations (read before production)

* Two colluding administrators (requester + checker) can still escalate; stronger governance needs N-of-M approvals (the schema allows several approvals per request; the service currently requires one) and out-of-band review of the audit log.
* `X-Forwarded-For` is deliberately **not** trusted: audit `ip_address` is the direct peer (the gateway's address behind a proxy) until a trusted-proxy policy is configured.
* No rate limiting / lockout on `/auth/login`; apply at the gateway. Token revocation lists / introspection are not implemented (privileges are live-checked; identities rely on token expiry - keep access tokens short-lived).
* `valid_until` is checked at evaluation time; there is no background job that closes expired assignments in the tables (they simply stop counting).
* Audit immutability is enforced by a trigger and by the runtime role's grants, but a database superuser/owner can still disable the trigger; ship audit rows to WORM storage / SIEM for tamper evidence.
* The demo users share a well-known password and the dev compose file uses a throwaway `JWT_SECRET_KEY`: development only. Demo users must never exist in production (the seeder refuses).
* Verified with PostgreSQL 14 only; the schema uses `gen_random_uuid()` (PG13+ core).
* IAM trusts the resource attributes supplied by an authenticated service identity; consumer services are responsible for passing *authoritative* values.

## 18. Production deployment considerations

* Run behind a gateway/TLS terminator; set `APP_ENV=production` (strong `JWT_SECRET_KEY` enforced, docs off, stack traces off), restrict `CORS_ALLOWED_ORIGINS`.
* Separate DB roles (`iam_migrator` for CI/CD migration jobs, `iam_user` for pods); inject secrets from a secrets manager, not files; rotate the runtime password.
* Run migrations as a release step, not on pod start. Scale horizontally (stateless); size the DB pool (`pool_size=10`) against `max_connections`.
* Generate a random `JWT_SECRET_KEY` (secret store, never committed), use short-lived access tokens, monitor `auth.login_failed`, `auth.login_denied` and `authz.denied` audit actions.
* Backups/retention for `audit_logs` per bank policy; consider partitioning by month once volume grows.
* Provide at least two bootstrap administrators before enabling maker-checker, and document an out-of-band break-glass procedure (it deliberately does not exist in code).
