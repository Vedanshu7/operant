# Operant web

Operator frontend for Operant: type a goal, watch a discovery or replay run live,
and answer every approval, intervention and clarification the run raises.

Stack: Vite 7 · React 18 · TypeScript (strict, `noUncheckedIndexedAccess`) ·
Tailwind CSS v4 (`@tailwindcss/vite`) · react-router 7 (declarative) ·
TanStack Query 5 · `@microsoft/fetch-event-source` · zod 4 · MSW 2 · Vitest 3.

## Scripts

| Command          | What it does                                                                       |
| ---------------- | ---------------------------------------------------------------------------------- |
| `pnpm dev`       | Vite dev server on http://localhost:5173, proxies `/api` → `http://127.0.0.1:7080` |
| `pnpm build`     | Type-check then build to `dist/`                                                   |
| `pnpm preview`   | Serve `dist/` locally                                                              |
| `pnpm typecheck` | `tsc --noEmit` for app and config                                                  |
| `pnpm lint`      | ESLint (typescript-eslint strict, react-hooks) + Prettier check                    |
| `pnpm test`      | Vitest (jsdom + Testing Library + MSW)                                             |
| `pnpm gen:api`   | Regenerate `src/api/schema.d.ts` from the running backend                          |

## Dev with the backend

```sh
# terminal 1: Operant API on 127.0.0.1:7080
# terminal 2:
cd web
pnpm install
pnpm dev
```

Open http://localhost:5173. You are sent to `/login` to paste the API token; it is kept in
`localStorage` under `operant.token` and sent as `Authorization: Bearer …` on every request
(including the SSE stream). A 401 from any call clears the page back to `/login`.

## Dev with mocks (no backend)

```sh
cd web
VITE_USE_MOCKS=1 pnpm dev
```

`src/main.tsx` starts the MSW service worker (`public/mockServiceWorker.js`) with the handlers in
`src/mocks/handlers.ts`. Every endpoint in the contract is covered with realistic fixtures
(`src/mocks/fixtures.ts`), including:

- a scripted SSE stream for `GET /runs/:id/events` that walks through approval → clarification →
  intervention → success at 1.5 s per event
- a 409 on `POST /capabilities/:id/approve` when the stability gate fails (use the `force` checkbox)
- mutable in-memory state for approvals, interventions, profiles and secret refs

A token of `mock-token` is stored automatically so the login page is skipped.
If `public/mockServiceWorker.js` is missing, regenerate it with `pnpm msw init public --save`.

## Build

```sh
pnpm build     # dist/
pnpm preview   # sanity-check the bundle
```

Serve `dist/` from any static host and reverse-proxy `/api` to the Operant API.

## API types

`src/api/types.ts` is hand-written against the v1 contract. Once the backend exposes
`http://127.0.0.1:7080/openapi.json`:

```sh
pnpm gen:api   # writes src/api/schema.d.ts
```

Then point `src/api/client.ts` at `openapi-fetch`'s `createClient<paths>()` and retire `types.ts`.

## Layout

```
src/
  api/        client.ts (fetch wrapper, bearer, 401), queries.ts (react-query hooks), types.ts
  components/ one component per file (ApprovalCard, InvokeForm, EventTimeline, …)
  hooks/      useRunStream (SSE reducer + reconnect), useAuthedBlobUrl (authenticated images)
  lib/        status colours / terminal set, auth token, formatting, zod schema builder
  mocks/      MSW handlers, fixtures, scripted SSE, browser worker, node server
  pages/      one page per route
  test/       vitest setup and render helper
```

## Safety notes baked into the UI

- Approval, intervention and clarification cards render only what the API sends. No secret value is
  ever requested, stored or displayed; the Secrets page manages references only.
- Sensitive capability inputs render as `type="password"`.
- Denying a `sensitive_export` approval requires a note.
