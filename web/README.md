# /web

Next.js 15 App Router front end (React 19, TypeScript, Tailwind v4, shadcn/ui). The galaxy-tier
cinematic UI: hero, the FAILED to VERIFIED recovery reveal, the 3D Merkle explorer, animated stats,
the C2PA manifest display. Typed against the FastAPI backend via openapi-typescript + openapi-fetch +
TanStack Query, regenerated from `/openapi.json`. Built on the working core (loop before beauty).

## Develop

```
pnpm install         # install deps
pnpm dev             # dev server (Turbopack) on http://localhost:3000
pnpm build           # production build (webpack, the deploy path)
pnpm lint            # eslint
pnpm typecheck       # tsc --noEmit
pnpm generate:api    # regenerate the typed client from the backend OpenAPI schema
```

The typed client reads its base URL from `NEXT_PUBLIC_API_BASE_URL` (see `.env.example`); it defaults
to `http://localhost:8000` in development. Regenerate the client whenever the API changes; never
hand-write response types the schema can produce.
