# Automated test report

Generated: 09 October 2026 · Command: `pytest` · Result: **76 passed, 0 failed**

Run on SQLite locally (Python 3.13). GitHub Actions re-runs the suite against PostgreSQL 16 on every push.

## Accounts & authentication (`tests/test_accounts.py`)

| # | What is checked | Result |
|---|---|---|
| 1 | Register requires aston email | ✅ Pass |
| 2 | Register rejects weak password | ✅ Pass |
| 3 | Register sends code to demo inbox and stores only hash | ✅ Pass |
| 4 | Wrong code then right code verifies and signs in | ✅ Pass |
| 5 | Code locks after five attempts | ✅ Pass |
| 6 | Unverified user cannot sign in | ✅ Pass |
| 7 | Lockout after five failed sign ins | ✅ Pass |
| 8 | Staff cannot use customer sign in | ✅ Pass |
| 9 | Password reset via demo inbox | ✅ Pass |
| 10 | Forgot password does not reveal accounts | ✅ Pass |
| 11 | Demo inbox is scoped to session | ✅ Pass |
| 12 | Profile update and delete account | ✅ Pass |
| 13 | Sign out requires post | ✅ Pass |
| 14 | Reset link for other students is never shown in demo inbox | ✅ Pass |
| 15 | Disabled account cannot sign in | ✅ Pass |
| 16 | Terms page | ✅ Pass |

## AI features (`tests/test_ai.py`)

| # | What is checked | Result |
|---|---|---|
| 1 | Association rules learn co purchases | ✅ Pass |
| 2 | Recommendations never include out of stock | ✅ Pass |
| 3 | Rules require lift above one | ✅ Pass |
| 4 | Intake period helpers | ✅ Pass |
| 5 | Suggested reorder formula | ✅ Pass |

## Returns, reviews & contact (`tests/test_returns_reviews_support.py`)

| # | What is checked | Result |
|---|---|---|
| 1 | Return only after delivery and not hygiene items | ✅ Pass |
| 2 | Approved return restocks | ✅ Pass |
| 3 | Reject needs reason | ✅ Pass |
| 4 | Only buyers can review once | ✅ Pass |
| 5 | Contact form validation and storage | ✅ Pass |
| 6 | Contact honeypot blocks bots | ✅ Pass |

## Catalogue, basket, checkout & stock (`tests/test_shop.py`)

| # | What is checked | Result |
|---|---|---|
| 1 | Category and price filters | ✅ Pass |
| 2 | Invalid price filter is reported not crashing | ✅ Pass |
| 3 | Search highlights and suggests | ✅ Pass |
| 4 | Search escapes html | ✅ Pass |
| 5 | Stock badges | ✅ Pass |
| 6 | Basket caps quantity to stock | ✅ Pass |
| 7 | Cannot add out of stock | ✅ Pass |
| 8 | Checkout requires login | ✅ Pass |
| 9 | Order reduces stock including bundle components | ✅ Pass |
| 10 | Insufficient stock rolls back everything | ✅ Pass |
| 11 | Cancel returns stock | ✅ Pass |
| 12 | Invalid status transition rejected | ✅ Pass |
| 13 | Stock can never be negative | ✅ Pass |
| 14 | Full checkout journey | ✅ Pass |
| 15 | Halls delivery needs room | ✅ Pass |
| 16 | Customised bundle keeps discount | ✅ Pass |
| 17 | Users cannot see other orders | ✅ Pass |

## Simulated payments: Stripe-style cards, 3-D Secure, Apple Pay (`tests/test_payments.py`)

| # | What is checked | Result |
|---|---|---|
| 1 | Payment page has no card number field | ✅ Pass |
| 2 | Must choose a method and tick the box | ✅ Pass |
| 3 | Failed card creates no order and keeps stock (declined-declined) | ✅ Pass |
| 4 | Failed card creates no order and keeps stock (no_funds-insufficient funds) | ✅ Pass |
| 5 | Failed card creates no order and keeps stock (expired-expired) | ✅ Pass |
| 6 | Failed card creates no order and keeps stock (made-up-Choose one of the test cards) | ✅ Pass |
| 7 | Successful card records only brand last4 and reference | ✅ Pass |
| 8 | 3d secure approve | ✅ Pass |
| 9 | 3d secure fail creates no order | ✅ Pass |
| 10 | 3d secure page needs a pending payment | ✅ Pass |
| 11 | Apple pay confirm | ✅ Pass |
| 12 | Apple pay cancel and direct access | ✅ Pass |

## Admin, permissions & security (`tests/test_staff_security.py`)

| # | What is checked | Result |
|---|---|---|
| 1 | Anonymous and customers cannot open admin | ✅ Pass |
| 2 | Role permissions checked on server (support-staff:products-403) | ✅ Pass |
| 3 | Role permissions checked on server (support-staff:inventory-403) | ✅ Pass |
| 4 | Role permissions checked on server (support-staff:customers-200) | ✅ Pass |
| 5 | Role permissions checked on server (stock-staff:customers-403) | ✅ Pass |
| 6 | Role permissions checked on server (stock-staff:inventory-200) | ✅ Pass |
| 7 | Role permissions checked on server (stock-staff:access-403) | ✅ Pass |
| 8 | Role permissions checked on server (owner-staff:access-200) | ✅ Pass |
| 9 | No public admin registration | ✅ Pass |
| 10 | Staff invite flow | ✅ Pass |
| 11 | Stock adjustment needs reason and is logged | ✅ Pass |
| 12 | Product form rejects negative stock and missing alt | ✅ Pass |
| 13 | Customer details masked and reveal logged | ✅ Pass |
| 14 | Csrf is enforced | ✅ Pass |
| 15 | Security headers | ✅ Pass |
| 16 | Support can suspend and restore customer | ✅ Pass |
| 17 | Return photos are not public | ✅ Pass |
| 18 | Staff can change own password | ✅ Pass |
| 19 | Staff can change password | ✅ Pass |
| 20 | Support can disable customer and it is logged | ✅ Pass |

## Manual and tool-based checks

| Check | Tool / method | Result |
|---|---|---|
| Every reachable page loads (175 pages as guest, student and Owner) | Playwright crawler | No HTTP errors, no JavaScript errors |
| No horizontal scrolling at 390 px (phone) and 1440 px (desktop) | Playwright crawler | Pass on all crawled pages |
| WCAG 2.1 A/AA + best-practice rules | axe-core 4.10 on one page of each type | 0 violations after fixes (contrast, ARIA labels, landmark names, scrollable tables) |
| Full purchase journey: register → verify code → basket → delivery slot → test payment → track order | Playwright, real browser | Pass |
| Admin pages for Owner, Stock and Support roles | Playwright + role matrix tests | Correct pages or 403 |
| Production settings | `python manage.py check --deploy` | Only optional HSTS-preload warnings |
| Content-Security-Policy blocks inline scripts | Browser test (axe injection was refused until CSP was bypassed) | Pass |
| Python 3.11 compatibility | `python3.11 -m py_compile` | Pass |

## Manual test script (for the team to repeat on the deployed site)

| # | Steps | Expected |
|---|---|---|
| M1 | Register with `name@gmail.com` | Error: must end with @aston.ac.uk |
| M2 | Register with an @aston.ac.uk address, open Demo inbox, enter code | Signed in, “Verified student” badge |
| M3 | Enter a wrong code 5 times | Code locked, “Send a new code” works |
| M4 | Kitchen category → price max 15 → In stock only | Only matching products, active filter chips |
| M5 | Search “adaptor” | “Did you mean adapter?” |
| M6 | Add a low-stock product with quantity 10 | Quantity capped, message shown |
| M7 | Bundle → Customise → untick 2 items → add | Lower price, same % discount |
| M8 | Checkout without ticking the test-order box | Error, no order created |
| M9 | Pay with test card Visa •••• 4242 | Confirmation shows “Paid with Visa •••• 4242”, stock reduced (Admin → Inventory) |
| M9a | Pay with Visa •••• 0002 (declined) | Error “Your card was declined”, no order, basket kept |
| M9b | Pay with Visa •••• 3155, then Approve / Fail on the 3-D Secure page | Approve: order placed. Fail: error, no order |
| M9c | Pay with Apple Pay → Confirm with Face ID / Cancel | Confirm: “Paid with Apple Pay · Visa •••• 4242”. Cancel: back to payment, no order |
| M10 | Cancel the order while “Placed” | Cancelled, stock restored |
| M11 | As Owner mark an order Processing → Dispatched → Delivered | Customer sees timeline, Demo inbox has emails |
| M12 | Request a return for food containers | Blocked (hygiene) |
| M13 | Request a return for a pan set, Owner approves with “Put back in stock” | Stock +1, order shows Returned |
| M14 | Write a review for a delivered item | Review on product page, rating updated |
| M15 | Sign in as Support, open /staff/products/ | 403 page |
| M16 | Inventory → Remove stock larger than available | Error: stock cannot be negative |
| M17 | Sign in with a wrong password 5 times | Locked for 15 minutes |
| M18 | Forgot password → Demo inbox link → new password | Can sign in with the new password |
| M19 | Keyboard only: Tab through home, product, checkout | Visible focus ring, everything reachable |
| M20 | Phone width (390 px): home, product, checkout, admin dashboard | No sideways scrolling; menus open |
