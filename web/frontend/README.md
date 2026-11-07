# Quickpass Web Portal

The web portal where Guardians, Teachers, and Admins follow attendance: a React 19, Vite, and Tailwind CSS single-page app that talks straight to Supabase with `@supabase/supabase-js`.

[Web Portal Setup](../../docs/web-portal-setup.md) explains how to set up Supabase and publish the portal. [Architecture](../../docs/architecture.md#the-web-portal-and-authentication) explains how sign-in and Row-Level Security work.

## Development

Node.js 22.12 or newer:

```bash
cp .env.example .env   # fill in VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY
npm install
npm run dev            # http://localhost:3000
```

| Script | What it does |
|:---|:---|
| `npm run dev` | Starts the development server on port 3000 |
| `npm run build` | Type-checks and builds the portal into `dist/` |
| `npm run preview` | Serves the built `dist/` locally |
| `npm test` | Runs the Vitest suite |
| `npm run typecheck` | Runs the TypeScript compiler (`tsc -b`) |
| `npm run lint` | Runs oxlint |

## Layout

| Path | Contents |
|:---|:---|
| `src/pages/` | The sign-in page and the Guardian, Teacher, and Admin portals |
| `src/components/` | The navigation bar, route protection, and UI building blocks |
| `src/context/` | The signed-in Web Account and the School Settings |
| `src/lib/supabase.ts` | Every call to Supabase, behind the `PortalBackend` interface that the tests replace |
| `src/lib/i18n.ts`, `src/locales/` | The Spanish and English text, and the School Language's date and time formats |
| `src/__tests__/` | The Vitest tests |
| `vercel.json`, `netlify.toml` | Each host's rule to answer every path with `index.html` |
