# DEPLOY.md — hosting the frontend on Netlify

## What gets deployed, and what does not

**Only the frontend.** The FastAPI backend, TigerGraph and the LLM are not
hosted by Netlify. The bundle's mode is fixed at build time:

- **Mock mode** (`VITE_USE_MOCK_API=true`): every screen replays
  `frontend/src/fixtures/` and the header shows a `mock data` chip. The site is
  clickable but **does not answer real questions**. Say so when you share the
  link. The committed `netlify.toml` sets this for Git-linked builds.
- **Live mode** (any other value, including unset, which is the code default in
  `frontend/src/config.ts`): the bundle calls the backend at
  `VITE_API_BASE_URL`. A folder deploy built locally without
  `VITE_USE_MOCK_API=true` is a live build. With no reachable backend, its
  health indicators show the services offline and those features are blocked.

For a fixture-only demo from a folder deploy, build with the flag set:

```bash
cd frontend && VITE_USE_MOCK_API=true npm run build
```

## The free path: deploy the built folder, not the repo

> **Do not use "Import an existing project".** This repository is **private**
> and owned by a GitHub **Organization** (`AI-Club-World`). Netlify puts
> Git-linked deploys of private *org-owned* repos behind the **Pro plan
> ($20/month)** and will show an upgrade wall with a card form. Vercel's free
> Hobby tier has the same restriction. An earlier revision of this file said
> the free tier was fine here; that was wrong.
>
> The paywall is on the **Git integration**, not on hosting. Deploying the
> built folder directly is free, unlimited, and needs no card.

Build locally, then ship `frontend/dist`:

```bash
cd frontend && npm install && npm run build   # add VITE_USE_MOCK_API=true for a fixture demo
```

**Either** drag the `frontend/dist` folder onto
[app.netlify.com/drop](https://app.netlify.com/drop) — no account strictly
required, though signing in keeps the site in your dashboard so you can rename
it and redeploy later.

**Or** use the CLI, which is repeatable:

```bash
npm install -g netlify-cli
netlify deploy --dir=frontend/dist --prod
```

Either way you get `https://<name>.netlify.app`, renameable under **Site
configuration → Change site name**.

**Trade-off:** no automatic redeploy on push. After changing the frontend,
re-run the build and drop/`netlify deploy` again. For sharing a demo that is
usually the right trade; a paid plan buys automation, not capability.

### If you want push-to-deploy without paying

Two options, both free:

- **Make the repository public.** Git integration on Netlify's free tier, and
  GitHub Pages, both work with public repos. Check first that nothing in the
  repo should stay private: no `.env`, no run outputs under `out/`.
- **Mirror only `frontend/dist` to a separate public repo** and point GitHub
  Pages or Netlify at that. Keeps the source private and the built output
  public. Note that a JS bundle is readable, so treat anything in it as public
  regardless.

Cloudflare Pages is often suggested as the free alternative for private repos.
It may well work here, but after getting Netlify's terms wrong once, this file
will not assert it — check the current limits before relying on it.

### When `netlify.toml` applies

The committed `netlify.toml` configures **Git-linked** builds: base directory,
build command, publish path. On a folder deploy you have already built
locally, so those settings do not apply — but the `[[redirects]]` block still
matters. Netlify reads redirects and headers from the deployed directory, so
for a folder deploy the SPA rewrite must travel *inside* `dist`. That is what
`frontend/public/_redirects` is for: Vite copies `public/` into `dist/` on
every build, so the rewrite is always present in the artifact you upload.

## What `netlify.toml` does, and why

| Setting | Value | Why |
|---|---|---|
| `base` | `frontend` | The app is not at the repo root; the build has to run inside `frontend/`. |
| `command` | `npm run build` | `tsc --noEmit && vite build` — type-check then bundle. |
| `publish` | `dist` | Relative to `base`, so `frontend/dist`. |
| `NODE_VERSION` | `20` | Pinned so a Netlify default bump cannot silently change the build. |
| `VITE_USE_MOCK_API` | `true` | Git-linked builds are fixture demos. The code default is live (`false`), so this line is what makes the deployed site mock. Remove it only when a backend is reachable (see below). |

**The SPA rewrite is load-bearing, not boilerplate.** The app uses
`BrowserRouter`, so `/build`, `/dashboard`, `/history` (and the `/eval`,
`/benchmarks` redirects) are client-side routes
with no file behind them. Serving `frontend/dist` from a plain static server
and requesting those paths returns **404** — verified, not assumed:

```
/            -> HTTP 200
/dashboard   -> HTTP 404
/eval        -> HTTP 404
/build       -> HTTP 404
```

The `from = "/*" -> to = "/index.html"` rule with **status 200** (a rewrite,
not a 301 redirect) makes the request reach `index.html` so the router can
resolve it, while the URL stays as typed. Remove that block and any shared
deep link or browser refresh breaks.

Cache headers are split deliberately: fingerprinted files under `/assets/*`
are immutable and cached for a year, while `index.html` must revalidate every
time or a deploy would keep serving the previous bundle's asset references.

## No key in the site

The site carries no API key: the UI asks for one at sign-in and keeps only a
session token for the tab (README, Security model). The build refuses to run
with `VITE_API_KEY` set. For a live site:

- serve the backend over HTTPS (the key is sent once, at sign-in);
- give visitors the viewer key (`OGR_API_KEY`) and keep `OGR_ADMIN_KEY` for
  whoever may build, upload, switch embeddings or start benchmarks;
- never reuse a value that protects anything real.

`TG_PASSWORD`, `TG_SECRET`, `TG_TOKEN`, `LLM_API_KEY`, the provider keys and
`CLOUDFLARE_API_TOKEN` are backend-only. They must never appear in a
`VITE_`-prefixed variable.

## Pointing it at a real backend

With the backend hosted somewhere the browser can reach, set these under
**Site configuration → Environment variables** (or in `frontend/.env` for a
folder deploy) and rebuild:

```
VITE_USE_MOCK_API = false
VITE_API_BASE_URL = https://<your-api-host>
```

Delete the `VITE_USE_MOCK_API = "true"` line from `netlify.toml`, or override
it in the UI. No code change is needed: components never touch fixtures, and
each `services/*Service.ts` branches on `config.useMockApi`. Two more things:

- Add the Netlify origin to the backend's `OGR_CORS_ORIGINS`.
- The two SSE endpoints authenticate with a short-lived single-use `?token=`,
  not the session header, because `EventSource` cannot send custom headers.
- Sessions live in the backend's memory: a backend restart signs everyone out.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Build fails on `tsc: not found` | Netlify skipped devDependencies. Check that `NODE_ENV` is not set to `production` in the site's environment variables. |
| Site loads but `/dashboard` 404s on refresh | The `[[redirects]]` block was removed or overridden in the UI. |
| Blank page, console 404s on `/assets/...` | Someone set a subpath. This build uses absolute asset paths; it must be served from a domain root. |
| Stale UI after a deploy | The `index.html` cache header was changed to something long-lived. |
| Deployed site shows `mock data` when you expected live | `VITE_USE_MOCK_API=true` is still set in `netlify.toml` or the site environment |
| Live site shows every service offline | `VITE_API_BASE_URL` is unreachable from the browser, or the origin is missing from `OGR_CORS_ORIGINS` |
