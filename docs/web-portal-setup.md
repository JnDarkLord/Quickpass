# Web Portal Setup

How to set up the School's Supabase project and publish the Quickpass web portal, where Guardians, Teachers, and Admins follow attendance from a browser.

The portal is optional. Without it, the desktop program works on its own, with the attendance stored on the station. With it, the stations send their Check-ins and Check-outs to Supabase (Cloud Sync), and the portal shows them:

- **Guardians** see their own children, the Students who share their Family Code.
- **Teachers** see the Students of the Grade they teach.
- **Admins** see the whole School, can filter by date, Grade, and Section, export to Excel from the browser, and can view the portal as a Teacher or a Guardian would.

Each Role has a **Day View**, with today's Check-ins, Check-outs, and Attendance Status, and a **Year View**, with the attendance and punctuality history. On a holiday or a weekday without classes, the Day View says so and marks nobody absent.

The portal is a static website: HTML, CSS, and JavaScript that talk straight to Supabase from the browser. There's no server of its own to run. Supabase's Row-Level Security decides what each signed-in person can read.

## What you need

- A Supabase project. The free plan is enough to start.
- Node.js 22.12 or newer, with npm, to build the portal or run it on your computer.
- A static host for the published portal: Cloudflare Pages, Vercel, Netlify, or your own web server.

## 1. Create the Supabase project

1. Create a project at [supabase.com](https://supabase.com).
2. Note these values, from the project's **Connect** dialog and its API keys settings:
   - the **Project URL**, such as `https://abcdefghijklmnop.supabase.co`;
   - the **anon** public key, which is safe to publish in the portal;
   - the **service_role** secret key, which bypasses Row-Level Security and belongs only in the stations' `.env`;
   - the **database connection string**, such as `postgresql://postgres:[YOUR-PASSWORD]@db.abcdefghijklmnop.supabase.co:5432/postgres`. Supabase's direct connection uses IPv6. If your network has no IPv6, use the **Session pooler** connection string instead.

## 2. Create the database

The files in `supabase/migrations/` create the tables, the Authorized Email check, the Row-Level Security policies, and the functions the portal calls. Apply them **in order of their number**, and apply any new ones whenever you update Quickpass. They are safe to run again.

In the Supabase dashboard's **SQL Editor**, open each file in turn, paste its contents, and run it.

Or, with `psql` and the connection string:

```bash
export DATABASE_URL='postgresql://postgres:[YOUR-PASSWORD]@db.abcdefghijklmnop.supabase.co:5432/postgres'
for f in supabase/migrations/*.sql; do psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"; done
```

## 3. Connect the stations

In each station's `.env` (see [Desktop Setup](desktop-setup.md)):

```ini
SUPABASE_URL=https://abcdefghijklmnop.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<the service_role key>
DATABASE_URL=<the database connection string>
```

`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` turn on Cloud Sync. `DATABASE_URL` lets the station's searches and reports read the history in Supabase. The first station to start finishes the setup wizard and sends the School Settings to Supabase. Every station after it downloads them. Until then, the portal shows only a message, in English, saying Quickpass is not set up yet.

## 4. Configure Supabase Auth

People sign in to the portal with their email and a password, or with Google. Only an **Authorized Email** can sign in: the email of a Guardian, Teacher, or Admin that's registered in Quickpass. Supabase refuses any other address, and the portal tells the person to contact the School.

![Web Portal Authentication, Authorized Email and RLS Routing](images/web-portal-auth-workflow.svg)

In the Supabase dashboard, under **Authentication**:

1. **URL Configuration:** set the **Site URL** to the portal's public address, such as `https://attendance.example.org`, and add the same address to **Redirect URLs**. Add `http://localhost:3000` as well if you'll run the portal on your computer. Sign-ins with Google and the links in Supabase's emails only return to these addresses.
2. **Email provider:** it's on by default. With **Confirm email** on, the default, Supabase emails a confirmation link to each person who creates a password, and they can sign in once they've clicked it. Supabase's built-in email service only sends a few messages an hour, so set up your own SMTP server under **Authentication > Emails** before inviting the whole School.
3. **Google provider (optional):** to offer "Sign in with Google", enable the Google provider and give it a Google Cloud OAuth client ID and secret. In Google Cloud, the client's authorized redirect URI is the callback URL that the Supabase provider page shows, `https://<project-ref>.supabase.co/auth/v1/callback`.

### Who can sign in

- **Guardians:** the email entered for a Guardian when a Student's Badge is registered or edited in the desktop window.
- **Teachers and Admins:** the `email` column of their row in Supabase's `users` table. The desktop window has no email field for Teachers and Admins yet, so add it in the dashboard's **Table Editor**. Cloud Sync brings it to the stations.

The first time, a person uses the portal's **First time? Activate** link to set a password for their Authorized Email, or signs in with Google.

## 5. Try the portal on your computer

```bash
cd web/frontend
cp .env.example .env      # Windows: copy .env.example .env
npm install
npm run dev
```

Fill in `web/frontend/.env` with the Project URL and the anon key:

```ini
VITE_SUPABASE_URL=https://abcdefghijklmnop.supabase.co
VITE_SUPABASE_ANON_KEY=<the anon key>
```

Then open `http://localhost:3000`. Vite reads `web/frontend/.env`, not the `.env` in the repository root.

## 6. Publish the portal

`npm run build` writes the portal to `web/frontend/dist/`. Vite builds `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` into the files, so on a static host you set them as **environment variables in the host's dashboard**, and the host builds the portal from your copy of the repository. Changing either one takes a new build.

A School Language switch, or a change to the Grades and Sections, needs no rebuild. The portal reads the School Settings from Supabase each time it loads.

The portal uses client-side routes such as `/admin` and `/guardian`, so the host must answer every path with `index.html`. Each host below does, as noted.

Every host takes these settings:

| Setting | Value |
|:---|:---|
| Root (base) directory | `web/frontend` |
| Build command | `npm run build` |
| Output (publish) directory | `dist` |
| Environment variables | `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` |
| Node.js version | 22.12 or newer |

After the first deployment, add the portal's address to Supabase's **Site URL** and **Redirect URLs** (step 4), if you haven't already.

### Cloudflare Pages

1. In the Cloudflare dashboard, create a Pages project and connect it to your repository.
2. Set the **Root directory** to `web/frontend`, the **Build command** to `npm run build`, and the **Build output directory** to `dist`.
3. Add `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` as environment variables, and `NODE_VERSION` set to `22` if the build uses an older Node.js.
4. Deploy.

SPA routing: Cloudflare Pages answers unknown paths with `index.html` on its own, because the portal has no `404.html`. Don't add a `_redirects` file for it: Cloudflare applies its rules even to files that exist, so a catch-all rule would also replace the portal's scripts.

### Vercel

1. Import your repository as a new Vercel project.
2. Set the **Root Directory** to `web/frontend`. Vercel detects Vite and fills in the build command and output directory.
3. Add `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` under the project's environment variables.
4. Deploy.

SPA routing: `web/frontend/vercel.json` rewrites every path to `index.html`.

### Netlify

1. Import your repository as a new Netlify site.
2. Set the **Base directory** to `web/frontend`, the **Build command** to `npm run build`, and the **Publish directory** to `dist`. Netlify reads the publish directory relative to the base directory, so the dashboard may show it as `web/frontend/dist`.
3. Add `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` as environment variables, and `NODE_VERSION` set to `22` if the build uses an older Node.js.
4. Deploy.

SPA routing: `web/frontend/netlify.toml` rewrites every path to `index.html`.

### Your own web server (nginx)

Build the portal with `web/frontend/.env` filled in (step 5), then copy the contents of `web/frontend/dist/` to the server:

```bash
cd web/frontend
npm ci
npm run build
```

A sample nginx server block:

```nginx
server {
    listen 80;
    server_name attendance.example.org;

    root /var/www/quickpass;   # the contents of web/frontend/dist
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Serve the portal over HTTPS, for example with a free certificate from Let's Encrypt. People type their passwords into it.

## Keys and security

- The anon key is meant to be public. It only lets the browser call Supabase as an anonymous or signed-in user, and Row-Level Security limits what that user can read.
- The service_role key gets past Row-Level Security. Keep it in the stations' `.env` files only. Never put it in `web/frontend/.env`, in a host's settings, or in the repository.
- The portal can't read the Admin Secret Key. The School Settings function it calls returns only the public fields.
