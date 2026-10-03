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
  equipment type (free text with suggestions; sent as its own field, the description is sent exactly as
  typed), and optionally upload a photo for an **AI visual assessment** (a vision model describes visible
  damage, wear, leaks or corrosion; the card shows the findings, severity, a damage chip and the
  model's confidence, and always carries the caveat *"AI-generated visual assessment — not a
  substitute for professional inspection"*). A photo that is not equipment gets a neutral card and
  no ticket. The text-diagnosis result card has two states:
  * **Valid issue**: severity badge, ticket number, diagnosis, recommended action, **two
    confidence tiles** (see below), and a banner showing whether the answer is *based on similar past cases* or *general
    reasoning*; similar cases are listed below.
  * **Not an equipment issue** (`is_valid_issue: false`): a neutral message with the assistant's
    reply and a "No ticket created" notice. No severity, ticket id or confidence is rendered.
* **Attach a photo (optional)** (Diagnose page, on the main form): next to the description, with a
  thumbnail, file name, size and a Remove button (JPEG/PNG/WebP up to 5 MB, checked in the browser before
  sending). With a photo the request goes out as `multipart/form-data` and the AI weighs the photo together with
  the description in ONE diagnosis; without one it is the same JSON request as always. The result card then says
  **"Diagnosis based on your description and the photo you attached"** and keeps **what the AI sees in your
  photo** (findings, a damage chip, the vision model's own severity and confidence, and the *not a substitute for
  professional inspection* caveat) as part of the explanation, and later attempts after "No, try something else"
  keep showing it. If the photo could not be used (not equipment, or image analysis unavailable) an amber notice
  says so and the diagnosis is based on the description alone. "Try again" re-sends the same photo. The standalone
  **Diagnose from a photo** card below the form is unchanged, for people who only have a photo.
* **Thumbs up / down** (Diagnose page, on the first diagnosis): *Was this diagnosis correct?* Each verdict
  now teaches the knowledge base and the UI says how: a thumbs up saves a **provisional fix** (one end-user
  click is one confirmation, so it counts as verified once a technician reviews it), a thumbs down records
  **an approach that did not work**, so similar future problems avoid it. The same goes for "Yes, it's fixed"
  in a session. Retrieved cases carry a **Verified fix** or **Provisional · confirmed once** chip. When a past
  failure influenced an answer, an amber notice says so and lists what did not work. The History bar and the
  Stats page count verified, provisional and failed fixes. On the History page a provisional ticket shows a
  **Provisional** chip and a technician's **Verify** button (the same call as Confirm), which upgrades that same
  record to verified.
* **Iterative flow** (Diagnose page): every valid diagnosis opens a *session*. The card is labelled
  **Attempt 1 of 4** and asks **"Did this solve it?"**. *No, try something else* swaps a different solution
  into the same card (**Attempt 2 of 4**, then 3, 4) while the earlier ones collect in a collapsible
  **Previous attempts that did not work** list. *Yes, it's fixed* ends in a green **Resolved!** panel (and
  says if the solution was added to the knowledge base). If the last attempt fails, an amber (not red)
  notice asks the user to **escalate to a human technician**. Buttons are disabled while a new solution is
  being generated, a failed request keeps the same question available (nothing was saved), and an expired
  session (the server restarted) says so. The equipment type is now free text with suggestions: any
  device is accepted.
* **History** (`/history`): paginated ticket table with a **Review** column: each ticket is *Pending review*
  (medium/high severity marked "Review first"), *Confirmed* or *Corrected*. A technician can **Confirm** a
  correct diagnosis or **Correct** it with the real root cause and fix (an inline form); either adds the case
  to the knowledge base. When the backend has a technician access code set, clicking Verify/Confirm/Correct first
  shows an "Enter technician code" box; a wrong code shows "Invalid technician code." and nothing is saved. The
  code is held in memory for the tab only (a reload asks again) and is sent as the `X-Technician-Code` header to
  those two endpoints only. With no code configured nothing is asked. Each row also shows its **session**: *In progress* / *Resolved in N attempts* /
  *Needs a human technician*, and *Show details* lists every attempt with whether it worked, then compares
  the AI's first version with the technician's. A bar at the top
  shows the knowledge base growing (seed vs verified records), and tabs filter by review status. Cases
  retrieved on the Diagnose page that came from a technician carry a "Verified by a technician" chip.
* **Stats** (`/stats`): a small dashboard fed by `GET /api/v1/stats`: stat cards for diagnoses performed,
  the share resolved from similar cases, knowledge-base size and technician-verified cases, plus panels for
  similar-case vs general-reasoning split, seed vs verified records, average confidences and review
  progress. It has loading, error (with **Try again**) and empty states; a value the backend cannot give
  (e.g. an average with nothing to average) shows "—", never a misleading 0.

## Structure

```
src/
  api/client.ts      typed fetch wrapper; every failure becomes an ApiError (network/timeout/validation/server)
  types/api.ts       TypeScript mirror of the backend contracts
  pages/             DiagnosePage, HistoryPage, StatsPage
  components/        ResultCard, SessionFlow, SessionBadge, PhotoAttachment, PhotoFindings, BasisBanner, ...
  lib/               error-to-message mapping, formatting helpers
```

## Notes

* Two different readings are shown, styled differently on purpose, each with a tooltip:
  **Match confidence** (`retrieval_confidence`: how closely the report matches past cases) and
  **AI confidence** (`llm_confidence`: the model's own certainty, independent of any match). When
  the model gave no usable number the AI tile is dashed and says "estimate unavailable". A backend
  that does not send the new fields yet (e.g. mid-redeploy) is tolerated: the Match tile falls back
  to the deprecated `confidence_score` and the AI tile is simply omitted.
* Errors: unreachable backend and timeouts show a clear message with **Try again**; a 422's
  `error.details[].message` is shown inline on the form field.
* **Rate limit (HTTP 429):** the backend allows 10 AI requests per minute per client. Past that the
  app shows "Too many requests, please wait a moment (about N seconds) and try again" (N comes from the
  `Retry-After` header, which the backend exposes to browsers via CORS) with a **Try again** button.
  A refused request does not count against the limit, so retrying cannot make the wait longer.
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
