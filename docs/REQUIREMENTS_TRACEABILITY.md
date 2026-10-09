# Requirements traceability: brief → implementation → evidence

Source: *DG4AGA E-Commerce Platform Development Project Brief 2026/27*. Test names refer to `tests/`; M-numbers refer to the manual script in `docs/TEST_REPORT.md`.

| Ref | Brief requirement | Implementation (file / page) | Evidence |
|---|---|---|---|
| 2.1 | Business name, purpose, scope, audience, stakeholders | About page; README §0 | About page |
| 2.2 | Logo, colour scheme, typography | `static/css/astonbundle.css`, `templates/partials/logo.html` | All pages |
| 2.3 | ≥5 categories × ≥5 products | 5 categories, 58 products, 5 bundles (`catalog/seed_data.py`); product photos in `catalog/seed_images/` | Home → Shop by category |
| 2.4 | Fictional / licensed content, sources acknowledged | About → Credits; README §9 | — |
| 3.1a | Home, About, Contact, navigation, category browsing, search | `core`, `catalog` apps | `test_search_highlights_and_suggests`, M5 |
| 3.1b | Category and price filtering | `catalog/views.py::_filters` | `test_category_and_price_filters`, `test_invalid_price_filter_is_reported_not_crashing`, M4 |
| 3.1c | Contact form records or routes enquiries | `support` app → Admin Enquiries (with reply) | `test_contact_form_validation_and_storage`, `test_contact_honeypot_blocks_bots` |
| 3.1d | Registration, sign-in/out, password update or reset | `accounts/views.py` | `test_register_*`, `test_wrong_code_then_right_code…`, `test_lockout…`, `test_password_reset_via_demo_inbox`, `test_sign_out_requires_post` |
| 3.1e | View/manage account details | `/account/profile/` | `test_profile_update_and_delete_account` |
| 3.1f | Basket add/update/remove; simulated checkout, no real payment data | `orders/basket.py`, `orders/views.py`, `orders/payments.py` (Stripe-style test cards, 3-D Secure, Apple Pay sheet; no card fields) | `test_full_checkout_journey`, `tests/test_payments.py` (12 tests), `test_basket_caps_quantity_to_stock`, `test_customised_bundle_keeps_discount`, M6–M9 |
| 3.1g | Previous orders, status, eligible returns, ratings/reviews | `/account/orders/`, return form, `reviews` app | `test_return_only_after_delivery_and_not_hygiene_items`, `test_only_buyers_can_review_once`, `test_users_cannot_see_other_orders` |
| 3.2a | Role-based admin, no public admin self-registration | `staff/views.py::staff_area`, `accounts.models.PERMISSIONS`, invitations | `test_role_permissions_checked_on_server` (7 cases), `test_no_public_admin_registration`, `test_staff_invite_flow` |
| 3.2b | Create, view, update, remove products | Admin → Products | `test_product_form_rejects_negative_stock_and_missing_alt` |
| 3.2c | Manage customer records, minimise personal data | Admin → Customers (masked, logged reveal, suspend/restore) | `test_customer_details_masked_and_reveal_logged`, `test_support_can_suspend_and_restore_customer` |
| 3.2d | View/filter orders; update order or shipment status | Admin → Orders (status state machine, shipment number, customer email) | `test_invalid_status_transition_rejected`, M11 |
| 3.3a | Image/reference, category, description, price, stock per product | `catalog.models.Product` | — |
| 3.3b | Update stock on actions; no negative stock | `inventory/services.py`, DB `CHECK (stock >= 0)`, row locks | `test_order_reduces_stock_including_bundle_components`, `test_insufficient_stock_rolls_back_everything`, `test_cancel_returns_stock`, `test_approved_return_restocks`, `test_stock_can_never_be_negative`, `test_stock_adjustment_needs_reason_and_is_logged` |
| 3.3c | Low/out-of-stock thresholds, justified | per-product threshold; rule shown on Admin → Inventory | `test_stock_badges` |
| 3.3d | Operational summaries | Admin dashboard (KPIs, chart, low stock, forecast) | M11 |
| 4a | Framework, persistent DB, deployed release | Django 5.1 + PostgreSQL 16, Docker | **Deployment: team to complete** |
| 4b | Server-side validation, password hashing, RBAC, secret management | Django forms, PBKDF2, `staff_area`, `.env` | `test_csrf_is_enforced`, `test_security_headers` |
| 4c | Protection against common web vulnerabilities | CSRF, CSP, XSS escaping, clickjacking, lockout, honeypot, rate limit, private return photos | `test_search_escapes_html`, `test_return_photos_are_not_public` |
| 4d | Accessible, responsive, usable, clear errors | WCAG-AA tokens, error summaries, 4 breakpoints | axe-core 0 violations, M19–M20 |
| 4e | Testing of journeys, permissions, validation, DB, failures | 76 automated tests + manual script | `docs/TEST_REPORT.md` |
| 4f | Sustainability, ethics, social, accessibility, security, data governance | About → “Doing this responsibly”; privacy and accessibility pages; AI model cards | **Portfolio narrative: team to write** |
| 4g | Fictional/test data only | seed data; Demo inbox; test checkout | README |
| 6 | AI-enabled feature, evaluated, limitations and risks | `ai/recommender.py`, `ai/forecast.py`, Admin → AI insights | `test_association_rules_learn_co_purchases`, `test_recommendations_never_include_out_of_stock`, `test_rules_require_lift_above_one`, `test_suggested_reorder_formula` |
| 8 | README covering setup, dependencies, DB, licences, testing, limitations | `README.md` | — |
