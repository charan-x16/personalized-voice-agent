# Svara API contract

`openapi.json` is the generated, reviewable contract between `apps/api` and
API consumers such as `apps/web`. FastAPI remains the source of truth.

From the repository root:

```bash
pnpm api:export-openapi
pnpm api:check-openapi
```

Do not edit `openapi.json` by hand. Runtime response validation in the web app
remains intentionally stricter than generated transport types.
