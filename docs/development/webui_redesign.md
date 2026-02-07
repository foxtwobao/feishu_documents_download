# Web Admin Redesign (v1 draft)

## Context & Goals
- Replace the existing Next.js client with an experience aligned to `docs/development/requirement.md` §12.
- Leverage the current FastAPI stack (`larksync/web`) which already exposes OAuth, task orchestration, SSE logging, artifact bundling, etc.
- Reuse the CLI runtime (`SyncEngine`, `DriveSpaceSynchronizer`, Typer commands) through the web task service instead of duplicating download logic in the UI.
- Deliver a task-centric console that allows end users to authenticate with Feishu, stage sync jobs, monitor progress, and retrieve artifacts.

## High-Level Architecture

| Area | Responsibility | Notes |
| --- | --- | --- |
| Next.js App Router (`webui-client/`) | UI, navigation, fetching, optimistic UX | React + TypeScript + Tailwind (utility classes from globals) |
| Auth Flow | Start via `GET /auth/authorize`, complete via redirect to `/auth/callback` | Tokens stored server-side; UI only receives `user_id`, `display_name`, `avatar_url` |
| Task APIs | `/tasks` CRUD, `/tasks/preview`, `/tasks/{id}/stream` | Backed by `SyncTaskService` which wraps CLI runtime |
| Real-time updates | Server-Sent Events stream, fallback polling | UI attaches to SSE to surface progress/log lines |
| Notifications | Optional Feishu bot/email toggles via `/tasks` payload flags (future) | Keep schema extensible |

## Page Map

1. **`/auth/login`** — Explains OAuth flow, starts authorization, links to CLI fallback.
2. **`/auth/callback`** — Handles redirect params, stores session (in `localStorage`), routes to dashboard.
3. **`/` Dashboard** — Summary cards (latest status, storage root hint, quick actions) + list of recent tasks.
4. **`/tasks/new`** — Task composer: select mode (`docx`, `file`, `space`), dynamic parameter inputs, preview request, schedule execution. Shows plan summary (total files, samples) returned from `/tasks/preview`.
5. **`/tasks/[id]`** — Task detail: header with status timeline, live progress bar, SSE log stream, artifact list, retry/cancel controls.
6. **`/settings/profile`** — Display user profile, token expiry status, logout.
7. **`/settings/preferences`** (future) — Client-side defaults (incremental flag, limit, notification target).

## Data Flow

```
User → /auth/authorize (Feishu) → callback → FastAPI stores tokens → redirect with user_id → UI saves session → API requests include `X-User-ID`
```

1. **Session bootstrap**
   - UI keeps `user_id`, `display_name`, `avatar_url` in `localStorage`.
   - On app mount, try `/users/me` (legacy compatibility) to refresh profile & expiry.
   - Logout triggers `POST /auth/logout`, clears storage, redirects to `/auth/login`.

2. **Task creation**
   - Form input → `POST /tasks/preview` with {task_type, payload, incremental, limit}.
   - UI renders preview summary; user confirms to submit `POST /tasks`.
   - Response includes runtime snapshot; UI redirects to task detail.

3. **Task monitoring**
   - Task detail subscribes to `/tasks/{id}/stream` via EventSource.
   - For each `status` event, update runtime badges/progress; for `log` event append to log panel.
   - Once `download_ready`, enable `taskDownloadUrl`.

4. **Artifacts download**
   - On request, fetch `GET /tasks/{id}/download` (browser handles zip).
   - UI verifies `download_ready` flag before enabling button.

5. **Scheduler & future enhancements**
   - Schedule time is optional field on composer; stored as ISO string.
   - Future toggles (webhook, Feishu bot) attach to payload under `extra`.

## Component & Hook Layout

```
webui-client/
  app/
    layout.tsx        # Shell, theming, session provider
    page.tsx          # Dashboard
    auth/
      login/page.tsx
      callback/page.tsx
    tasks/
      page.tsx        # list view
      new/page.tsx    # composer
      [id]/page.tsx   # detail
    settings/
      profile/page.tsx
  components/
    Shell.tsx         # Side nav + header
    TaskList.tsx      # Shared list tiles
    TaskComposer.tsx  # Form with dynamic sections
    TaskPlanPreview.tsx
    TaskProgress.tsx
    TaskLogsPanel.tsx
    SessionGuard.tsx  # Redirect unauthenticated users
    Toasts.tsx        # Global notifications
  lib/
    api.ts            # REST wrappers (fetch, SSE helper)
    auth.ts           # Session storage helpers
    sse.ts            # EventSource manager with teardown
    mutations.ts      # Imperative actions (create, retry, cancel)
```

> Keep components atomically testable; avoid mixing fetch logic with presentational markup. Hooks (`useTasks`, `useTaskStream`) live under `lib/hooks/`.

## Reusing CLI Runtime
- `SyncTaskService` already bridges to `DriveSpaceSynchronizer`/`SyncEngine`; no additional HTTP endpoints are needed.
- Frontend simply orchestrates parameters (`task_type`, `payload`, `incremental`, `limit`, optional `schedule_at`).
- Task detail surfaces `runtime_snapshot` fields (`current_stage`, `current_item`, etc.) to map to progress UI.

## Error Handling & UX
- Normalize API errors into typed objects with `.code`, `.message`.
- Display toast + inline form errors (e.g., invalid token, auth_required).
- SSE disconnects revert to poll every 5s; escalate after three failures.

## Implementation Phases
1. **Scaffold** — Reset App Router pages, session provider, navigation shell.
2. **Auth Flow** — Implement login, callback, logout, guard.
3. **Task Management** — Task list, composer (preview + create), detail with SSE.
4. **Enhancements** — Dashboard summary, notifications, settings.

## Open Questions
- Confirm whether backend `/users/me` returns token expiry (needed for warning banner).
- Determine storage root display (call `GET /users/me` or new endpoint).
- Align notification preferences schema with backend before UI toggle goes live.

