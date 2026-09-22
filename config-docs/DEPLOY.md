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

## One-time setup

Everything is already committed in `netlify.toml` at the repo root, so there
is nothing to configure in the Netlify UI.

1. Sign in at [app.netlify.com](https://app.netlify.com) with the GitHub
   account that can see `AI-Club-World/tigergraph-agentic-graph-rag`.
2. **Add new site → Import an existing project → GitHub**, and pick the repo.
   Netlify will ask for access to the org; a private org repo is fine on the
   free tier.
3. Choose the branch to deploy — `application-integration`.
4. Netlify reads `netlify.toml` and pre-fills base, build command and publish
   directory. **Do not override them.** Click Deploy.

First build takes roughly a minute. You get a URL like
`https://<random-name>.netlify.app`, renameable under
**Site configuration → Change site name**.

Every push to the deployed branch redeploys automatically. Pull requests get
their own preview URL.

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
