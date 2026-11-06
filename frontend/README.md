# collectIQ · CMS Administration

A functioning banking IAM workspace in the existing Next.js App Router application. This frontend does not modify or expose collection cases, customer balances or financial records.

## Run locally

Use Node.js **22.12 or newer** (verified with Node 24) and npm. A `.nvmrc` pins Node 24 for nvm users.

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000/admin/dashboard (Next.js may choose another port if occupied). `.env.local` explicitly selects `IAM_ADAPTER=mock`. It contains no credentials and is ignored by Git. `.env.example` is committed.

```bash
npm run typecheck
npm run lint
npm test
npx playwright install chromium
npm run test:e2e
npm run build
npm start
```

Playwright uses port 3006, reuses a running development server outside CI, and starts one otherwise. Tests create fictional employees. A production build intentionally does **not** expose the mock workspace: it displays the identity integration screen until a live, verified IAM session is available.

## Architecture and directory map

```text
app/
  admin/                 Server route files, authenticated layout, loading/error boundaries
  api/v1/[...path]/      Same-origin BFF; development adapter or live IAM proxy
  providers.tsx          TanStack Query and verified session context
components/
  auth/                  Server-side permission gate
  layout/                Shared responsive sidebar, header, profile and help
  tables/                TanStack Table with remote sorting and pagination
  ui/                    shadcn-style Radix dialog, CVA button, feedback and display primitives
features/
  dashboard/             Computed KPIs, account distribution, requests and activity
  users/                 Listing, validated creation/editing, details and role assignment
  roles/                 Catalog, detail tabs and grouped permission matrix
  teams/                 Team creation/editing, supervisors and member management
  access-requests/       Change requests and independent review
  audit/                 Read-only filtered audit log and event inspector
  catalog/               Permission catalog, scopes and IAM configuration status
lib/
  api/                   Shared contracts, fetch client, errors and query/mutation hooks
  auth/                  Session verification, route permissions and mock-mode guard
  validation/            Zod write contracts shared with the isolated mock service
mocks/                   Deterministic fictional fixtures and server-only development service
tests/                  Component, service, API boundary and Playwright tests
```

Layouts and route files are Server Components. Interactive feature components own their forms and view state. Data flows through query hooks → typed same-origin client → BFF → IAM adapter. UI components do not import mock fixtures. TanStack Query invalidates IAM queries after mutations. Search is debounced by 250 ms, fetches are cancellable and bounded by timeouts, and table sorting/filtering/pagination happen in the adapter. Page size is capped at 100.

The reusable UI includes `AdminShell`, `PageHeader`, `Panel`, `DataTable`, `Badge`, `Avatar`, `SearchInput`, `QueryState`, `EmptyState`, `Notice`, `Field`, `Button`, `Dialog`, `UserForm`, `ChangeForm`, `RequestDetails` and `PermissionMatrix`. Dialogs use Radix focus management and restore focus. The navigation becomes a modal drawer on mobile; wide tables scroll horizontally. CSS respects reduced motion.

## Pages

- `/admin/dashboard`: six computed administration KPIs, user status distribution, pending reviews, audit activity and functioning quick actions.
- `/admin/users`: user search, role/status/team filters, sorting and pagination; validated user provisioning. `?status=ACTIVE` initializes the status filter.
- `/admin/users/[id]`: employee profile, approved roles, effective scoped permissions, memberships, scopes, account lifecycle and audit activity. Ordinary role assignment applies immediately; privileged assignment creates a request.
- `/admin/roles`: all ten requested system-defined roles, with six MVP and four inactive future roles. No Integration/Support Engineer role.
- `/admin/roles/[id]`: role metadata, assigned users, approved permission matrix and change history. Selecting a checkbox requests a change; it does not alter the approved mapping.
- `/admin/permissions`: searchable, module-filtered seed-managed catalog, classifications and role links. No unrestricted permission creation.
- `/admin/teams`: create/edit teams, choose an active supervisor, add/move/remove members with destructive confirmation and region validation.
- `/admin/access-scopes`: approved user/role scope assignments, boundary references, protected grant requests and confirmed revocation. All six scope types are represented; this region-limited administrator cannot grant GLOBAL.
- `/admin/access-requests`: searchable requests, status filter, existing/proposed access, justification, history, related audit records, approval/rejection comments and explicit self-review restrictions.
- `/admin/audit-logs`: search, actor/action/outcome/date filters, pagination and read-only event detail. Date boundaries and business display use Asia/Karachi; API timestamps retain UTC offsets.
- `/admin/settings`: truthful read-only integration and policy status. Unimplemented review scheduling and session policy integration are labeled accordingly.

## Development adapter and governance

The adapter runs only when **both** `IAM_ADAPTER=mock` and `NODE_ENV=development` (or `test`). `NODE_ENV=production` always disables it, regardless of environment configuration. A server-managed fictional administrator session requires no password, token or localStorage entry. Its permissions are recomputed from approved roles on each server request.

Fixtures contain 24 fictional identities, 10 roles, 3 Punjab teams, approved scopes, a permission catalog, pending requests and audit activity. Changes persist in the local Node server process across navigation and hot reload; restart the server to reset them. All local browser tabs share this development state. This is not durable storage or a production multi-instance database.

The mock service validates writes independently of UI controls. It enforces permissions and organizational boundaries, duplicate identity checks, active supervisor requirements, role conflicts, inactive/future role restrictions, maker-checker approval, immutable reviewed decisions and revalidation when applying a request. Self-approval and self-rejection are denied. Current-user account deactivation is blocked. Privileged account reactivation also requires review. System Administrator mappings cannot acquire collection/customer permissions. Resource permissions are effective only when the user has a compatible approved scope for that role.

The session delegates administration to Punjab. Valid scope references are the target user ID for OWN, existing Punjab team IDs for TEAM, existing Punjab branch IDs for BRANCH, `Punjab` for REGION, and `PUNJAB-RETAIL` for PORTFOLIO. GLOBAL exceeds this session's authority and is rejected by the service. Scope and role-permission changes requested from this UI always go through review. Authorized scope revocations narrow access and apply immediately with audit evidence.

Every successful mutation and approval decision appends an audit record. The development service keeps audit history in memory; production append-only guarantees belong to IAM/database infrastructure. The logged-in administrator can review seeded requests from Fatima Khan and cannot review requests submitted by Ahmed Raza. There is no identity-switching production bypass.

Latency is simulated at the server boundary. For deterministic error/retry checks in development:

```bash
curl -H 'x-mock-failure: true' http://localhost:3000/api/v1/users
```

Expected: HTTP 503 with a normalized error. Empty tables, loading skeletons, query retries and mutation errors have explicit UI feedback.

## Contracts and backend assumptions

The IAM directory was inspected before implementation. It currently contains SQLAlchemy models, enums and pure authorization policies; its API and schema directories have no implemented HTTP contracts/OpenAPI document. `lib/api/types.ts` and `lib/validation/schemas.ts` are therefore **proposed frontend contracts**, not a claim of live compatibility.

The client base path is centralized as `/api/v1`. The BFF keeps `IAM_API_BASE_URL` server-only. Shared models cover `Session`, `User`, `Role`, `Permission`, `Team`, `Scope`, discriminated `Change`, `AccessRequest`, `AuditEvent`, `Dashboard`, `Settings`, `Page<T>` and normalized `ApiError`.

Implemented adapter endpoints:

| Method       | Path                                                          | Contract                                                  |
| ------------ | ------------------------------------------------------------- | --------------------------------------------------------- |
| GET          | `/me`, `/me/permissions`                                      | Session / effective IAM permission codes                  |
| GET          | `/dashboard`                                                  | Computed summary and recent records                       |
| GET / POST   | `/users`                                                      | `Page<User>` / validated provisioning                     |
| GET / PATCH  | `/users/:id`                                                  | `UserDetails` composite / permitted profile fields        |
| POST         | `/users/:id/deactivate`, `/users/:id/reactivate`              | Audited status change or pending privileged request       |
| GET / POST   | `/users/:id/roles`                                            | Approved roles / ordinary change or privileged request    |
| GET          | `/users/:id/scopes`                                           | Approved scope assignments                                |
| GET          | `/roles`, `/roles/:id`, `/roles/:id/permissions`              | Paged catalog / `RoleDetails` composite / permission list |
| GET          | `/permissions`                                                | Paged seed-managed permission catalog                     |
| GET / POST   | `/teams`                                                      | Paged teams / validated team creation                     |
| PATCH        | `/teams/:id`                                                  | Permitted team editing                                    |
| POST         | `/teams/:id/members`                                          | Validated member addition/move/removal                    |
| GET / DELETE | `/scopes`, `/scopes/:id`                                      | Paged assignments / audited revocation                    |
| GET / POST   | `/access-requests`                                            | Paged requests / validated change proposal                |
| GET          | `/access-requests/:id`                                        | Request detail                                            |
| POST         | `/access-requests/:id/approve`, `/access-requests/:id/reject` | Independent decision with comment                         |
| GET          | `/audit-logs`                                                 | Paged, filtered read-only events                          |
| GET          | `/settings`                                                   | Read-only configuration status                            |

Lists use `page`, `pageSize`, `search`, relevant filters, `sort` and `direction`. Responses are `{ items, total, page, pageSize }`. Mutations return `{ message, user?, request? }`. Failures use `{ message }` and an HTTP status. Unknown, unauthorized and invalid operations are rejected rather than treated as successful placeholders. No POST `/roles` or permission-creation UI is exposed because this workspace manages the predefined catalog.

Differences to reconcile with IAM:

- Frontend models use camelCase presentation contracts and readable fictional IDs; backend entities use snake_case and UUIDs. Add a mapping adapter or agree canonical response DTOs.
- Backend user status currently supports ACTIVE/INACTIVE. SUSPENDED and PENDING_ACTIVATION are explicit development extensions.
- Backend requests currently define ASSIGN_ROLE, GRANT_SCOPE, GRANT_ROLE_PERMISSION and REVOKE_ROLE_PERMISSION. Role revocation and privileged deactivation/reactivation are proposed extensions. Frontend approval success uses APPLIED, matching the domain enum; no temporary “approved but not applied” access is shown.
- Employee references, supervisor presentation, dashboard summaries, composite detail responses, settings, list query semantics, membership writes and scope revocation require agreed endpoints.
- Production permission IDs, scope-resource matching, role conflicts, organization directories and authoritative effective-access resolution must come from IAM. Frontend scope values never authorize production access.
- Selector lookup requests are bounded to 100 records for the supplied fictional dataset; replace with search/paged directory pickers when integrating a larger organization.

## Authentication and live integration

To select the live proxy:

```dotenv
IAM_ADAPTER=live
IAM_API_BASE_URL=https://your-private-iam-service
```

The example port in `.env.example` is illustrative, not a confirmed service port. Never prefix private service credentials or URLs with `NEXT_PUBLIC_`.

The session verifier sends only the HttpOnly access-token cookie as a Bearer token to IAM `/api/v1/me` and validates the returned session shape. Missing/invalid/expired/unreachable sessions fail closed. Route-level server gates and UI permission checks improve access behavior; the IAM service remains authoritative for every read and mutation. The proxy restricts resources, disallows upstream redirects, normalizes errors, bounds requests with timeouts and rejects writes whose Origin does not match the application origin.

**Sign-in** is a username/password form at `/login`. The server route `/api/auth/login` forwards the credentials to the IAM service (`POST /api/v1/auth/login`), which verifies them and returns a signed access token; the token is stored in an HttpOnly `iam_access_token` cookie (`Secure` in production) and `/api/auth/logout` clears it. MFA, lockout/rate limiting and password-reset flows are not implemented (apply rate limiting at the gateway). `npm start` with mock configuration displays the sign-in-required screen and API requests return 401.

Before live rollout, implement/confirm IAM endpoints, DTO mapping and pagination semantics; confirm the session lifecycle and CSRF flow; enforce all role, scope, separation-of-duty, approval transaction and append-only audit policies in the backend; and run integration/security tests against that service. A live backend was not available for verification.

## Verification

Verified locally: **37 Vitest tests passed**, **2 Playwright journeys passed**, lint and strict TypeScript checks passed, and the production build succeeded. Desktop (1512 px) and mobile (390 px) layouts were visually inspected. Production smoke checks returned the identity integration screen and HTTP 401 for IAM APIs with mock configuration.

Automated coverage includes computed KPIs, remote user/audit filtering and pagination, creation validation, role rendering, permission requests, team membership, self-approval visibility, unauthorized UI actions, empty/error states, API errors and cancellation, cross-origin mutation rejection, missing-session denial, independent approval/application, duplicate writes, policy role conflicts, regional boundaries, scope prerequisites and production mock exclusion.

Playwright exercises the complete dashboard → create user → assign ordinary role → request privileged role → verify self-review denial → inspect audit lifecycle, plus all nine top-level pages and the mobile navigation drawer. Separate production smoke checks verify mock configuration cannot provide a production session.

No backend microservice files are required to run the local frontend.
