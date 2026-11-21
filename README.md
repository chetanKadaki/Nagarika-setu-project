# NagarikSetu

A responsive civic-service platform for complaint tracking, GeoAI visualization, independent work verification, and NagarikSetu Guide support for approved scheme explanations and engineer work tracking.

The application is not connected to a government system and does not file official complaints. AI recommendations and scheme explanations are guidance only; designated government officers make verification decisions.

Citizens register with their own email, mobile number, and NagarikSetu password, and must verify email before signing in. Engineers can submit a professional registration application, but must verify email and receive department-officer approval before accessing assigned work. Government officers and verification officers are created only through administrator invitations. Administrators are created using the protected backend bootstrap command; there is no public administrator registration.

Officers assign complaints only to approved engineers whose department and registered skills match the report category, and designate a separate verification officer. Engineers can start or resume complaint work, record progress, and submit before/after photos; citizens can view a timestamped assignment, work, photo, and verification timeline for their own reports and submit one rating after official closure. Officers can also create work tasks linked to a featured government scheme; the task is assigned only to an approved engineer whose department and registered skills match, and its assignment, progress, and completion are tracked separately from complaint verification. Scheme pages show linked task status and assigned engineer name, department, registration number, and skills.

Engineers may explicitly opt in to share live GPS while an assigned complaint or scheme task is in progress. The browser requests location permission after the engineer chooses **Share live location**; updates are limited to at most one every 30 seconds, visible only to government officers, and the latest coordinate is removed when sharing is stopped or work is submitted/completed. Locations older than 90 seconds are excluded from the officer live view and cleaned up when that view refreshes. The engineer can stop sharing at any time. Maps use satellite imagery, and device location is otherwise only accessed after the user requests it.

Signed-in engineers, department officers, and verification officers see role-specific home dashboards backed by their server-scoped complaint data. Complaint and work-submission GPS accuracy and capture timestamps are stored only when the user explicitly captures device location; manually entered coordinates have no claimed accuracy. Verification displays both locations, their calculated distance, and a review flag when they are more than 500 m apart. GPS and browser timestamps are evidence for human review, not proof of presence or an automatic rejection.

Citizen reports accept up to five photos, videos, audio files, or PDFs (20 MB each; 60 MB total). The API validates declared media types against file signatures, stores evidence outside the database, and restricts downloads to users authorized for that complaint. Configure `COMPLAINT_UPLOAD_PATH` to choose the local evidence directory; the default is `backend/data/complaint-attachments`.
The report form includes a camera-capture input for supported mobile browsers, alongside a standard file picker. A visible **Sign up** action opens citizen account registration.

The public dashboard at `/api/public/dashboard` shows aggregate counts and recent complaint/resolution statuses without names, free-text titles/descriptions, exact addresses, or exact coordinates. Public map coordinates are rounded to two decimal places and ward names are reduced to a ward number when possible. New reports also receive a preliminary, keyword-based category/severity/department suggestion and possible nearby-duplicate references. These rules are not a trained AI model and do not make assignment, verification, or closure decisions. An officer must confirm or change the suggestion before assigning an eligible engineer.

## Run locally (Windows)

1. Install Node.js, Python 3.11+, and Ollama.
2. Install frontend packages from the project root:

   ```powershell
   npm install
   ```

3. Configure and install the API from a PowerShell window:

   ```powershell
   cd backend
   Copy-Item .env.example .env
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements-dev.txt
   ollama pull llama3.2
   ollama pull nomic-embed-text
   python -m uvicorn app.main:app --reload
   ```

4. In a second PowerShell window, from the project root, run:

   ```powershell
   npm run dev
   ```

5. Open the Vite URL printed in the terminal. The development server proxies `/api` requests to `http://127.0.0.1:8000`.

The API creates its SQLite database and tables automatically on first startup. Default demo-account seeding is disabled. Existing local accounts are preserved and grandfathered as active with verified email; existing complaint and work records are not deleted. New accounts require email verification. Configure SMTP before citizen or engineer registration, password reset, or official invitations can send mail.

To enable Google sign-in, create an OAuth client ID of type **Web application** in Google Cloud Console and add the exact Vite origin to its authorized JavaScript origins. The development server normally uses `http://127.0.0.1:5173`; add `http://localhost:5173` too if you open the app with that hostname. Set the same client ID in the project-root `.env` as `VITE_GOOGLE_CLIENT_ID` and in `backend/.env` as `GOOGLE_CLIENT_ID`, then restart both development servers. These are client IDs, not client secrets; do not put a client secret in frontend configuration. Without a configured client ID, the Google sign-in option is hidden.

## Authentication, database, and email setup

- The local `.env.example` uses SQLite. For MySQL, first create the `nagariksetu` database and apply `backend/migrations/0001_nagariksetu_auth.sql` once using a MySQL client. The API creates the remaining application tables on startup.
- Set `DATABASE_URL` to `mysql+pymysql://USER:URL_ENCODED_PASSWORD@HOST:3306/nagariksetu`. Do not commit credentials; URL-encode reserved characters in the password.
- Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER`, and `SMTP_STARTTLS` in `backend/.env`. Use port 587 with STARTTLS or port 465 with implicit TLS. Registration fails with a configuration error if email delivery is unavailable; tokens are never returned by the API or stored in plaintext.
- Email verification links expire after 24 hours, password reset links after 60 minutes, and official invitations after 3 days. Login attempts are rate-limited and audited. Password reset and account deactivation revoke active sessions.
- Existing accounts in an upgraded database remain active and are treated as verified per the selected migration policy. New citizen accounts cannot sign in until email verification. Public engineer applications stay pending until both email verification and officer approval.
- To create the first administrator, set `BOOTSTRAP_ADMIN_NAME`, `BOOTSTRAP_ADMIN_EMAIL`, and `BOOTSTRAP_ADMIN_PASSWORD` in `backend/.env`, then run once from the `backend` directory:

  ```powershell
  python -m app.bootstrap_admin
  ```

  The command refuses to run if an administrator already exists. Remove the bootstrap password from the environment after it succeeds. Administrators invite officers and verification officers through the administrator dashboard.

## Security and production configuration

- Set `ENVIRONMENT=production`, a unique random `JWT_SECRET` of at least 32 characters, `SEED_DEMO_ACCOUNTS=false`, an HTTPS `FRONTEND_ORIGIN`, and explicit `ALLOWED_HOSTS`.
- Configure a MySQL-compatible `DATABASE_URL` and working SMTP settings before production startup.
- Do not deploy development secrets, a local SQLite database, or the Vite development server.
- Keep the API behind HTTPS and a deployment gateway that applies shared rate limiting; configure database backups and private evidence storage before handling real reports.
- Access tokens are short-lived, session-revocable, and held in browser memory only. Passwords are salted and hashed with PBKDF2-HMAC-SHA256 (600,000 iterations); API roles and complaint ownership are enforced server-side.
- SQLite connections enable foreign-key checks and a busy timeout. To use MySQL, install the included PyMySQL driver and set `DATABASE_URL` to a protected `mysql+pymysql://...` connection string.
- Scheme uploads are restricted to PDF/plain text, capped at 10 MB, and indexed only for officer accounts. Ollama errors are not returned with internal exception details.
- Satellite tiles are fetched by the browser from Esri's public imagery service; avoid displaying private or precise locations without consent.
- Complaint evidence is stored on the local filesystem by default. Configure a private, backed-up storage path or object-storage adapter before accepting real reports; do not expose the evidence directory through static hosting.

The application does not implement MFA, shared distributed rate limiting, secure evidence-object storage, work PDF/document uploads, full GIS analytics/marker clustering, speech-to-text, computer-vision analysis, GIS-based routing, push notifications/SLA escalation, or a government integration. The notification panel refreshes role-scoped dashboard updates while the app is open and stores read status in the browser; it does not send push notifications. Add and configure the remaining capabilities before a real deployment.

## Tests

Run the API tests from `backend`:

```powershell
python -m pytest -q
```

The suite covers SQLite constraints/rollback, password hashing, token claims, role-scoped access, engineer registration and approval, complaint and scheme-task eligibility, work start/progress, officer-only live locations, upload limits, independent verification, the rework loop, and officer-only official completion.

Type-check and build the frontend from the project root:

```powershell
npm run build
```
