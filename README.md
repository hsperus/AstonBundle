# AstonBundle

E-commerce platform for **DG4AGA Aston Global Advantage, Group 2 (2026/27)**.

AstonBundle sells first-week essentials (bedding, kitchen kit, UK plug adapters, winter wear, study supplies) to new Aston University students, especially international students. Students order before they fly and choose a delivery slot at their halls reception that matches their arrival date.

> **Fictional business. Test data only.** No real payments are taken and no real emails are sent. Every product, price, review, order and person in the database is generated test data.

---

## 1. Quick start (local, no database server needed)

Requirements: Python 3.11, 3.12 or 3.13. (Django 5.1 does not support Python 3.14: some pages crash with `'super' object has no attribute 'dicts'`.)

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then set DJANGO_SECRET_KEY to a long random string
python manage.py migrate
python manage.py seed              # catalogue + test accounts + synthetic history + trains the AI (about 1 minute)
python manage.py runserver
```

Then open http://127.0.0.1:8000.

If `DATABASE_URL` is empty, the app uses a local SQLite file, so you can start without installing PostgreSQL.

## 2. Run with PostgreSQL (recommended; this is how the assessed release runs)

With Docker:

```bash
cp .env.example .env               # set DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS
docker compose up --build -d
docker compose exec web python manage.py seed
```

Without Docker, create a database and set the connection string in `.env`:

```
DATABASE_URL=postgres://USER:PASSWORD@HOST:5432/astonbundle
```

## 3. Deployment

The deployed release runs as two containers: the Django app served by Gunicorn, and PostgreSQL 16 (see `docker-compose.yml`). Static files are served by WhiteNoise.

Production checklist:

| Setting | Value |
|---|---|
| `DJANGO_DEBUG` | `false` |
| `DJANGO_SECRET_KEY` | long random value, kept only in the server’s `.env` (never committed) |
| `DJANGO_ALLOWED_HOSTS` | your domain, e.g. `astonbundle.example.com` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://astonbundle.example.com` |
| HTTPS | put the app behind a TLS proxy (Caddy, Nginx or the host’s load balancer). With HTTPS on, set `DJANGO_SECURE_SSL_REDIRECT=true`. |

Then run `python manage.py migrate` and `python manage.py seed` once. `python manage.py check --deploy` reports only the optional HSTS preload warnings.

## 4. Test accounts (for markers)

| Role | Email | Password | Sign in at |
|---|---|---|---|
| Student (customer) | demo.student@aston.ac.uk | `Student2026!demo` | `/account/sign-in/` |
| Owner (all admin areas) | owner@astonbundle.example | `Owner2026!demo` | `/staff/sign-in/` |
| Stock manager | stock@astonbundle.example | `Stock2026!demo` | `/staff/sign-in/` |
| Customer support | support@astonbundle.example | `Support2026!demo` | `/staff/sign-in/` |

Passwords can be changed with environment variables before seeding (`SEED_OWNER_PASSWORD`, etc.). **Change them on the live site after marking.**

To test registration, use any address ending in `@aston.ac.uk` (for example `marker.test@aston.ac.uk`). The 6-digit code appears in the **Demo inbox** (`/account/demo-inbox/`) in the same browser.

## 5. What the platform does (brief → feature)

| Brief requirement | Where |
|---|---|
| Home, About, Contact, navigation, category browsing, searchable catalogue | `/`, `/about/`, `/contact/`, `/shop/<category>/`, header search |
| Category and price filtering (plus stock, rating and sort) | filter panel on every listing |
| Contact form that records enquiries | `/contact/` → admin **Enquiries** inbox, with reply by (simulated) email |
| Registration, sign-in, sign-out, password change and reset | `@aston.ac.uk` only, 6-digit email code, lockout after 5 failed attempts, reset link valid for 30 minutes |
| Manage account details | `/account/profile/`: name, halls/room, arrival date, phone, delete account (anonymises) |
| Basket add/update/remove, simulated checkout | session basket; 3-step checkout with delivery-slot choice; simulated payment in the style of Stripe test mode (pick a test card: success, declined, insufficient funds, expired, 3-D Secure) or a simulated Apple Pay sheet; no card fields, only brand + last 4 digits of the test card are stored |
| Order history, status, returns, reviews | `/account/orders/` with timeline; per-item returns within 30 days (hygiene items blocked); verified-buyer reviews |
| Role-based admin, no public admin sign-up | `/staff/`: roles Owner / Stock manager / Customer support, checked on the server; staff join only by invitation |
| Product CRUD | Admin → Products (create, edit, image upload with alt text, hide, delete, bulk actions, CSV export) |
| Customer records with minimal data | Admin → Customers: masked by default; each “reveal” is logged; accounts can be suspended and restored |
| Orders: view, filter, update status | Admin → Orders: filter by status, date and customer; allowed status changes only; customer emailed |
| Inventory | image/icon, category, description, price, stock and threshold for each product; stock can never go below 0 (database CHECK constraint, row locking); every change logged with a reason |
| Low-stock and out-of-stock thresholds | per product; rule explained on the Inventory page |
| Operational summaries | Admin dashboard: KPIs, orders chart, low stock, forecast |
| AI extension | “Frequently bought together” (association rules) and demand forecast (quantile gradient boosting), see §7 |
| Extension: student accommodation | `/living/`: Bundle House, a fictional residence six minutes from campus — four room types (price per week, contract total, size, availability, an accessible studio) and seven shared facilities. Students send a booking request (validated, honeypot, rate-limited); it arrives in Admin → Enquiries as topic “Accommodation”. Nothing is reserved or paid |

## 6. Architecture

* **Django 5.1** (Python), server-rendered templates, a small vanilla-JS file for convenience (every feature works without JavaScript).
* **PostgreSQL 16** (SQLite for quick local runs).
* Django apps:

| App | Role |
|---|---|
| `core` | home, about, guide, help pages, error pages, seed command |
| `accounts` | custom user, roles, email verification, Demo inbox, staff invites, audit log |
| `catalog` | categories, products, bundles, search and filters |
| `orders` | basket, delivery slots, checkout, orders, returns |
| `inventory` | stock movements, purchase orders; all stock changes go through `inventory/services.py` |
| `reviews` | product reviews (verified buyers only) |
| `support` | contact form and enquiries |
| `staff` | admin panel |
| `ai` | recommender and forecast |
| `living` | student accommodation: room types, facilities, booking requests |

* **Design system:** `static/css/astonbundle.css` (tokens and UI kit from the team’s Claude Design files) plus `static/css/site.css` (layout and responsive rules).

### Security measures

* Passwords hashed with PBKDF2 (Django default), minimum 10 characters, letter + number, common-password check.
* Sign-in lockout for 15 minutes after 5 failed attempts. Verification codes are stored only as hashes, expire after 10 minutes, and allow 5 attempts.
* CSRF protection on every form. Strict Content-Security-Policy (no inline scripts). `X-Frame-Options: DENY`, `nosniff`, same-origin referrer policy. Secure, HttpOnly cookies in production.
* Server-side validation on all forms. Role checks on every admin request (`staff_area` decorator). Users can only see their own orders.
* Secrets only in environment variables (`.env` is git-ignored).
* Contact form: honeypot field and rate limit. CSV exports escape formula characters.
* Simulated email: the Demo inbox only shows messages for addresses used in the same browser session, and password-reset links only for the public demo account or an account created in that session. Set `EMAIL_BACKEND` to an SMTP backend to send real email (the Demo inbox then switches off).
* Fonts are self-hosted (no third-party requests).

## 7. AI features

Both models are trained by `python manage.py train_models` (the seed command runs it), or by **Retrain now** on Admin → AI insights. Each run is stored with its evaluation results (`ModelRun`).

**1. “Frequently bought together” (`ai/recommender.py`)**

* Item-to-item association rules from past baskets: support, confidence and lift. Score = confidence × √lift. Only rules with lift > 1 and seen in at least 4 orders are kept.
* Bundle contents are excluded from training, so the model learns real co-purchases rather than our own bundle definitions.
* Evaluation: time-based 80/20 split, hide one item per test basket, hit rate@3. Current seed: **54% vs 21%** for a “most popular” baseline.
* Shown on Home, Product and Basket with a “Smart suggestion” label and an explanation page. Out-of-stock items are never suggested.

**2. Demand forecast (`ai/forecast.py`)**

* scikit-learn `GradientBoostingRegressor` with quantile loss (P10 / P50 / P90).
* Direct multi-horizon: each training row predicts week *t+h* from information known at week *t*.
* The target is normalised by last year’s units × recent growth, because tree models cannot extrapolate.
* Back-test on the September 2026 intake (trained only on earlier data), current seed: **MAE 80.1 vs 23.4** for the seasonal-naive baseline; WAPE 83% vs 24%. **The model does not currently beat the baseline.** Across random seeds of the synthetic history the result is unstable (the original 31-product catalogue gave model wins on seeds 2026, 1 and 4 but large losses on seeds 2 and 3), so this needs work before it is claimed as an improvement.
* The 80% range for a period total is calibrated from back-test errors.
* Admin sees the chart, a model card, the back-test table and a suggested reorder (top of range − stock − open purchase orders). A person must create the purchase order; the model never orders or changes prices.

**Honest limitations:** the order history is **synthetic** (generated by `seed` with intake seasonality and buyer “personas”), so the metrics show that the method works, not real customer behaviour. The range calibration is in-sample. New products have no history (cold start).

## 8. Tests

```bash
pytest                    # 86 tests, about 5 seconds (SQLite or PostgreSQL)
```

The tests cover:

* registration and verification, lockout, password reset, Demo inbox privacy, account deletion
* filters, search (with HTML escaping), basket limits, the full checkout journey, stock reservation for bundles, atomic rollback when stock runs out, cancellation, invalid status changes, the database stock constraint
* returns rules, approve and restock, rejection reason, verified-buyer reviews, contact validation and honeypot
* role permissions for every admin area, staff invitations, stock adjustments, product form validation, customer masking and audit log
* CSRF and security headers
* AI rule learning, out-of-stock filtering, lift > 1, intake dates, reorder formula

GitHub Actions (`.github/workflows/tests.yml`) runs the tests against PostgreSQL on every push.

End-to-end smoke test over real HTTP (89 checks: registration, password reset, basket, every payment outcome, cancellation, returns, reviews, accommodation requests, admin journeys and role permissions):

```bash
python manage.py runserver          # in one terminal
python scripts/e2e_smoke.py         # in another; E2E_BASE=https://… to target another server
```

Evidence documents for the evidence pack:

* `docs/TEST_REPORT.md`: every automated test, the tool-based checks (crawler, axe accessibility audit) and a 20-step manual test script.
* `docs/REQUIREMENTS_TRACEABILITY.md`: each brief requirement → where it is implemented → which test proves it.
* `docs/AI_USE_NOTE.md`: draft record for the AI-use statement.

## 9. Data sources and licences

| Item | Source and licence |
|---|---|
| Products, prices, reviews, orders, people | Fictional, written or generated by the team (`catalog/seed_data.py`, `core/management/commands/seed.py`) |
| Fonts | Bricolage Grotesque, Atkinson Hyperlegible, Alegreya Sans — SIL Open Font Licence 1.1, self-hosted from Fontsource (`static/fonts/`, licence files included). No requests go to Google. |
| Icons | Outline icons based on Lucide, ISC Licence |
| Illustrations and logo | made by the team |
| Product photos | Generated with OpenAI `gpt-image-1`; branded items use the team’s own AstonBundle logo as a reference image. No third-party logos. Prompts: `catalog/seed_images/_prompts.json`. See `docs/AI_USE_NOTE.md`. |
| Accommodation photos | Generated with OpenAI `gpt-image-1` using the team’s AstonBundle logo as a reference image; the building is fictional and does not show any real Aston University residence or logo. Prompts: `living/seed_images/_prompts.json`. |
| Libraries | Django (BSD-3), scikit-learn (BSD-3), NumPy (BSD-3), WhiteNoise (MIT), Gunicorn (MIT), psycopg (LGPL-3), Pillow (MIT-CMU), python-dotenv (BSD-3), dj-database-url (BSD-2) |
| Weather figures (Arrival Guide) | rounded typical values for guidance |
| Exchange rates | indicative, fixed in `config/settings.py` (`FX_RATES`); only used for the “≈” estimate |

## 10. Known limitations

* Bundle House is a fictional residence. Booking requests are recorded for staff to answer; there is no room allocation, contract signing or rent payment.

* Payments and emails are simulations by design (brief §3.1 and the ethics rules). The card and Apple Pay screens imitate Stripe test mode and Apple Pay; they are not connected to either service.
* Product photos are AI-generated images, not photos of real stock. Admins can replace them by uploading photos.
* The AI is trained on synthetic data (see §7).
* Delivery-slot capacity is a fixed number per slot (`SLOT_CAPACITY`).
* Retraining runs in a background thread. On a multi-server deployment, run `python manage.py train_models` as a scheduled job instead.
* Dark mode from the design files is not implemented.
* Because email is simulated, “verification” proves the flow, not ownership of a real inbox. With a real SMTP backend it becomes real verification.

## 11. Useful commands

```bash
python manage.py seed --reset        # wipe orders/reviews/etc. and regenerate
python manage.py seed --no-history   # catalogue + accounts only
python manage.py train_models        # retrain both AI models
python manage.py createsuperuser     # creates an Owner account
```
