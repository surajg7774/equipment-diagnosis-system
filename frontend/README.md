# Equipment Diagnosis System - frontend

React + Vite + TypeScript + Tailwind CSS (v4) UI for the diagnosis backend in the parent folder.

## Run it

```bash
# 1. start the backend first (see the parent README): http://127.0.0.1:8000
# 2. then:
cd frontend
npm install
npm run dev          # http://localhost:5173
```

No configuration is needed. The browser only ever talks to the Vite dev server, which proxies
`/api` and `/health` to the backend (the backend has no CORS configuration, so calling it
cross-origin from the browser would be blocked). To point at a backend elsewhere, copy
`.env.example` to `.env` and set `BACKEND_URL`.

Other scripts: `npm run build` (type-check + production build), `npm run lint`.

## Pages

* **Diagnose** (`/`): describe a problem (min 10 characters, validated inline), optionally pick an
  equipment type (a UI hint only: it changes the placeholder; the backend's diagnose endpoint takes
  just a description, and the text is sent exactly as typed), and optionally upload a photo (clearly labelled *experimental*: the backend uses a placeholder
  model). The result card has two states:
  * **Valid issue**: severity badge, ticket number, diagnosis, recommended action, confidence bar,
    and a banner showing whether the answer is *based on similar past cases* or *general
    reasoning*; similar cases are listed below.
  * **Not an equipment issue** (`is_valid_issue: false`): a neutral message with the assistant's
    reply and a "No ticket created" notice. No severity, ticket id or confidence is rendered.
* **History** (`/history`): paginated ticket table with thumbs up/down feedback per row,
  expandable details and an empty state.

## Structure

```
src/
  api/client.ts      typed fetch wrapper; every failure becomes an ApiError (network/timeout/validation/server)
  types/api.ts       TypeScript mirror of the backend contracts
  pages/             DiagnosePage, HistoryPage
  components/        ResultCard, BasisBanner, SeverityBadge, ConfidenceBar, FeedbackButtons, ...
  lib/               error-to-message mapping, formatting helpers
```

## Notes

* `confidence_score` is the *retrieval similarity* (how well past cases match), not the model's
  certainty. The UI labels it "Match confidence" and says so.
* Errors: unreachable backend and timeouts show a clear message with **Try again**; a 422's
  `error.details[].message` is shown inline on the form field.
* Vite binds to `localhost` (IPv6 `::1` on some Windows setups): open <http://localhost:5173>
  rather than `127.0.0.1:5173`.

## Deploying (Vercel)

1. Import the repo in Vercel, set **Root Directory** to `frontend` (framework: Vite).
2. **Build command** `npm run build`, **Output directory** `dist` (also set in `vercel.json`).
3. Add the environment variable **`VITE_API_BASE_URL`** = your backend URL
   (e.g. `https://my-api.onrender.com`). It is baked in at build time; the build fails with a clear
   message if it is missing. The backend must list your Vercel URL in its `ALLOWED_ORIGINS`.
4. `vercel.json` rewrites every path to `index.html`, so reloading `/history` works.

No backend address is hardcoded in `src/`. The `127.0.0.1:8000` fallback in `vite.config.ts` only
configures the **dev-server proxy** (Node, never shipped to the browser).
