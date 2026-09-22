# DEPLOY.md — hosting the frontend on Netlify

## What gets deployed, and what does not

**Only the frontend.** There is no FastAPI service in this repo (`API-01` was
never built), no TigerGraph workspace and no LLM. The deployed site runs
entirely on fixture data: `VITE_USE_MOCK_API` defaults to `true` and every
screen is served from `frontend/src/fixtures/`.

So the site is a real, clickable app — search comparison, build view,
dashboard and the per-question eval table all work — but **it is not answering
real questions**. Worth saying that when you share the link, or people will
reasonably assume the pipelines are live. `config-docs/AUDIT.md` records what
is and is not implemented.

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
cd frontend && npm install && npm run build
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
  GitHub Pages, both work with public repos. Read `config-docs/AUDIT.md`
  first — it documents plainly what is and is not built, which is the sort of
  thing you want to be deliberate about publishing.
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
| `VITE_USE_MOCK_API` | `true` | Explicit, so the deployed mode is visible here rather than buried in `config.ts`. |

**The SPA rewrite is load-bearing, not boilerplate.** The app uses
`BrowserRouter`, so `/build`, `/dashboard` and `/eval` are client-side routes
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

## Do not set `VITE_API_KEY`

It is compiled into the bundle and shipped to every visitor, so it is not a
secret. It exists to deter casual access on a shared network, nothing more.
On a public site leave it unset. Never reuse a value that protects anything
real. The same applies to `TG_PASSWORD`, `TG_SECRET` and `LLM_API_KEY` — those
are backend-only and must never appear in a `VITE_`-prefixed variable.

## Pointing it at a real backend later

Once `API-01` exists and is hosted somewhere reachable, set two variables
under **Site configuration → Environment variables** and redeploy:

```
VITE_USE_MOCK_API = false
VITE_API_BASE_URL = https://<your-api-host>
```

No code change is needed — components never touch fixtures, they call
`services/*Service.ts`, and each service branches on `config.useMockApi` at
its own boundary. The backend will also need CORS configured for the Netlify
origin, and note that the two SSE endpoints authenticate with a short-lived
`?token=` rather than the `X-API-Key` header, because `EventSource` cannot
send custom headers.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Build fails on `tsc: not found` | Netlify skipped devDependencies. Check that `NODE_ENV` is not set to `production` in the site's environment variables. |
| Site loads but `/dashboard` 404s | The `[[redirects]]` block was removed or overridden in the UI. |
| Blank page, console 404s on `/assets/...` | Someone set a subpath. This build uses absolute asset paths; it must be served from a domain root. |
| Stale UI after a deploy | The `index.html` cache header was changed to something long-lived. |
