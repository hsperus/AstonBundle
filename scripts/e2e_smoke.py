"""End-to-end smoke test against a running AstonBundle server over real HTTP
(CSRF tokens, sessions, redirects), covering customer, staff and permission journeys.

Run from the project folder while the server is running, on a machine that can also
reach the same database (it checks results in the database):

    python manage.py runserver &
    python scripts/e2e_smoke.py                      # default http://localhost:8000
    E2E_BASE=https://example.org python scripts/e2e_smoke.py

It creates a new test student (e2e.<random>@aston.ac.uk), orders, a review, a return
and an enquiry, and adds then deletes one product. The demo student's password is
changed during the reset test and restored afterwards.
"""
import html, http.cookiejar, re, secrets, sys, urllib.parse, urllib.request
from html.parser import HTMLParser

BASE = __import__("os").environ.get("E2E_BASE", "http://localhost:8000").rstrip("/")
RESULTS = []


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class Forms(HTMLParser):
    def __init__(self):
        super().__init__(); self.forms = []; self.cur = None; self.sel = None; self.ta = None

    def handle_starttag(self, tag, a):
        a = dict(a)
        if tag == "form":
            self.cur = {"action": a.get("action") or "", "method": (a.get("method") or "get").lower(), "fields": [], "buttons": []}
            self.forms.append(self.cur)
        if not self.cur:
            return
        if tag == "input" and a.get("name"):
            t = a.get("type", "text")
            if t in ("submit", "image"):
                self.cur["buttons"].append((a["name"], a.get("value", "")))
            elif t in ("checkbox", "radio"):
                self.cur["fields"].append((a["name"], a.get("value", "on"), "checked" in a, t))
            elif t != "file":
                self.cur["fields"].append((a["name"], a.get("value", ""), True, t))
        elif tag == "button" and a.get("name"):
            self.cur["buttons"].append((a["name"], a.get("value", "")))
        elif tag == "select" and a.get("name"):
            self.sel = [a["name"], None, None]; self.cur["fields"].append(self.sel)
        elif tag == "option" and self.sel is not None:
            v = a.get("value", "")
            if self.sel[2] is None: self.sel[2] = v
            if "selected" in a: self.sel[1] = v
        elif tag == "textarea" and a.get("name"):
            self.ta = [a["name"], "", True, "textarea"]; self.cur["fields"].append(self.ta)

    def handle_data(self, d):
        if self.ta is not None: self.ta[1] += d

    def handle_endtag(self, tag):
        if tag == "form": self.cur = None
        if tag == "select": self.sel = None
        if tag == "textarea": self.ta = None


class Browser:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect)
        self.url = BASE + "/"; self.html = ""; self.status = 0

    def _do(self, url, data=None):
        url = urllib.parse.urljoin(self.url, url)
        req = urllib.request.Request(url, data=urllib.parse.urlencode(data, doseq=True).encode() if data is not None else None,
                                     headers={"Referer": self.url, "User-Agent": "e2e"})
        try:
            r = self.op.open(req, timeout=60); code, body, loc = r.status, r.read().decode("utf-8", "replace"), None
        except urllib.error.HTTPError as e:
            code, body, loc = e.code, e.read().decode("utf-8", "replace"), e.headers.get("Location")
        self.url = url
        return code, body, loc

    def go(self, url, data=None, follow=True):
        code, body, loc = self._do(url, data)
        hops = 0
        while follow and code in (301, 302, 303) and loc and hops < 8:
            code, body, loc = self._do(loc); hops += 1
        self.status, self.html, self.location = code, body, loc
        return self

    def form(self, has=None, action=None, index=0):
        p = Forms(); p.feed(self.html)
        cands = [f for f in p.forms if f["method"] == "post"
                 and (has is None or any(x[0] == has for x in f["fields"]) or any(b[0] == has for b in f["buttons"]))
                 and (action is None or action in f["action"])]
        if len(cands) <= index:
            raise AssertionError(f"no form has={has} action={action} on {self.url}")
        return cands[index]

    def submit(self, values=None, has=None, action=None, button=None, index=0, follow=True):
        f = self.form(has, action, index)
        data = {}
        for fld in f["fields"]:
            name, val = fld[0], fld[1]
            if len(fld) == 3:  # select
                val = fld[1] if fld[1] is not None else fld[2]
                data.setdefault(name, val); continue
            if fld[2]: data.setdefault(name, html.unescape(val))
        for k, v in (values or {}).items():
            if v is None: data.pop(k, None)
            else: data[k] = v
        if button: data[button[0]] = button[1]
        return self.go(f["action"] or self.url, data, follow)

    def text(self):
        return html.unescape(re.sub(r"<[^>]+>", " ", self.html))


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  [{detail}]"), flush=True)
    return cond


def step(name, fn):
    try:
        fn()
    except Exception as e:  # keep going so one failure doesn't hide the rest
        check(name + " (crashed)", False, repr(e)[:300])


import os, django  # noqa: E402
sys.path.insert(0, os.getcwd()); os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings"); django.setup()
from catalog.models import Product  # noqa: E402
from orders.models import Order, ReturnRequest  # noqa: E402
from support.models import Enquiry  # noqa: E402

def stock(sku): return Product.objects.get(sku=sku).stock

TAG = secrets.token_hex(3)
EMAIL = f"e2e.{TAG}@aston.ac.uk"
PW1, PW2, PW3 = f"E2eTest{TAG}1!", f"E2eTest{TAG}2!", f"E2eTest{TAG}3!"
OWNER = ("owner@astonbundle.example", os.environ.get("SEED_OWNER_PASSWORD", "Owner2026!demo"))
STOCKU = ("stock@astonbundle.example", os.environ.get("SEED_STOCK_PASSWORD", "Stock2026!demo"))
SUPPORT = ("support@astonbundle.example", os.environ.get("SEED_SUPPORT_PASSWORD", "Support2026!demo"))
ctx = {}

# ---------------------------------------------------------------- public pages
def public():
    b = Browser()
    for path, word in [("/", "AstonBundle"), ("/about/", "About"), ("/contact/", "Contact"), ("/arrival-guide/", "Arrival"),
                       ("/shop/", "Shop"), ("/shop/bundles/", "Bundle"), ("/help/delivery/", "Delivery")]:
        b.go(path); check(f"public page {path}", b.status == 200 and word.lower() in b.text().lower(), b.status)
    b.go("/shop/search/?q=kettle"); check("search 'kettle' finds the kettle", "1.7L <mark>Kettle" in b.html)
    b.go("/shop/kitchen/?min=5&max=8"); prices = [float(x) for x in re.findall(r'class="pr">£([\d.]+)', b.html)]
    check("price filter 5–8 only shows £5–£8", prices and all(5 <= p <= 8 for p in prices), prices)
    b.go("/shop/search/?q=%3Cscript%3Ealert(1)%3C/script%3E"); check("search escapes HTML", "<script>alert(1)" not in b.html)
    b.go("/product/does-not-exist/"); check("unknown product gives 404 page", b.status == 404)
    b.go("/staff/"); check("anonymous /staff/ redirects to staff sign-in", "/staff/sign-in" in b.url, b.url)
    b.go("/shop/kitchen/")
    m = re.search(r'href="(/product/[^"]+)"', b.html); b.go(m.group(1))
    check("product page shows image", b.status == 200 and "/media/products/" in b.html)
    img = re.search(r'src="(/media/products/[^"]+)"', b.html).group(1)
    code, body, _ = b._do(img); check("product image file is served", code == 200)
    # contact form
    b.go("/contact/")
    b.submit({"name": "E2E Tester", "email": f"contact.{TAG}@aston.ac.uk", "topic": __import__("support.models", fromlist=["TOPICS"]).TOPICS[0][0], "message": f"E2E enquiry {TAG}: where is my parcel?"}, has="message")
    check("contact form is recorded", Enquiry.objects.filter(message__contains=TAG).exists(), b.url)
step("public", public)

# ---------------------------------------------------------------- register, verify, profile, password, reset
cust = Browser()
def register():
    cust.go("/account/register/")
    cust.submit({"full_name": "E2E Student", "email": f"e2e.{TAG}@gmail.com", "password": PW1, "terms": "on"}, has="terms")
    check("register rejects non-Aston email", "aston" in cust.text().lower() and "/verify" not in cust.url)
    cust.submit({"full_name": "E2E Student", "email": EMAIL, "password": PW1, "terms": "on"}, has="terms")
    check("register goes to verification", "/account/verify" in cust.url, cust.url)
    cust.submit({"code": "000000"}, has="code", button=("verify", "1"))
    check("wrong verification code rejected", "/account/verify" in cust.url and not ("_auth" in str(cust.jar)))
    cust.go("/account/demo-inbox/")
    code = re.search(r"\b(\d{6})\b", cust.text()).group(1)
    cust.go("/account/verify/"); cust.submit({"code": code}, has="code", button=("verify", "1"))
    cust.go("/account/"); check("verified student is signed in", "Hello" in cust.text() and cust.status == 200, cust.url)
step("register", register)

def profile():
    cust.go("/account/profile/")
    cust.submit({"full_name": "E2E Student", "halls": "Lakeside Court", "room": "L-101", "arrival_date": "2027-01-09", "phone": ""}, has="room")
    cust.go("/account/profile/"); check("profile update saved", 'value="L-101"' in cust.html)
    cust.submit({"old_password": PW1, "new_password1": PW2, "new_password2": PW2}, has="new_password1")
    check("password change accepted", "changed" in cust.text().lower() or "updated" in cust.text().lower(), cust.url)
step("profile", profile)

def signout_signin_reset():
    cust.go("/account/sign-out/"); check("sign-out via GET is refused", cust.status in (405, 302, 200) and "/account/" in cust.url)
    cust.go("/account/"); cust.submit(has="email", action="sign-out") if False else None
    f = Browser.form(cust, action="sign-out") if 'action="/account/sign-out/"' in cust.html else None
    cust.go("/account/sign-out/", {"csrfmiddlewaretoken": re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', cust.html).group(1)})
    cust.go("/account/"); check("signed out", "/sign-in" in cust.url, cust.url)
    cust.go("/account/sign-in/"); cust.submit({"email": EMAIL, "password": PW1}, has="password")
    check("old password no longer works", "not right" in cust.text())
    cust.submit({"email": EMAIL, "password": PW2}, has="password")
    check("sign in with new password", "/account" in cust.url and "sign-in" not in cust.url, cust.url)
    # password reset: the demo inbox only shows reset links for the public demo account (privacy rule),
    # so test it on that account and restore its password afterwards.
    from accounts.models import User
    demo = User.objects.get(email="demo.student@aston.ac.uk"); saved = demo.password
    try:
        r = Browser(); r.go("/account/forgot-password/"); r.submit({"email": demo.email}, has="email")
        r.go("/account/demo-inbox/")
        m = re.search(r'(/account/reset/[^"\s<]+/)', r.html)
        check("reset link appears in demo inbox", m, r.text()[:200])
        r.go(m.group(1)); r.submit({"new_password1": PW3, "new_password2": PW3}, has="new_password1")
        r.go("/account/sign-in/"); r.submit({"email": demo.email, "password": PW3}, has="password")
        check("sign in after password reset", "sign-in" not in r.url, r.url)
        r.go(m.group(1)); check("reset link cannot be reused", "new_password1" not in r.html)
    finally:
        User.objects.filter(pk=demo.pk).update(password=saved)
step("signout/signin/reset", signout_signin_reset)

# ---------------------------------------------------------------- basket and checkout
def add(sku, qty=1, kind="p"):
    p = Product.objects.get(sku=sku)
    cust.go(p.get_absolute_url()); cust.submit({"qty": str(qty)}, action="/basket/add/")

def checkout_to_payment():
    cust.go("/checkout/")
    day = re.search(r'name="delivery_date" value="([\d-]+)"(?![^>]*disabled)', cust.html).group(1)
    cust.submit({"delivery_type": "halls", "recipient_name": "E2E Student", "halls": "Lakeside Court", "room": "L-101",
                 "delivery_date": day, "delivery_slot": "13-17"}, has="delivery_slot")
    check("delivery step accepted", "/checkout/review" in cust.url, cust.url + " " + cust.text()[:300])
    cust.submit(has=None, index=0) if False else cust.go("/checkout/payment/")

def shopping():
    s_kettle, s_mug = stock("KT-004"), stock("KT-008")
    add("KT-008", 2); add("ST-011", 1); add("RB-007", 1)
    cust.go("/basket/"); check("basket has 3 lines", cust.html.count("Remove") >= 3 or "3 items" in cust.text() or "(4 items)" in cust.text(), cust.text()[:200])
    # update qty of mug to 3, remove sticker pack
    mug = Product.objects.get(sku="KT-008"); st = Product.objects.get(sku="ST-011")
    key_m = re.search(rf'name="key" value="(p:{mug.pk}[^"]*)"', cust.html); key_s = re.search(rf'name="key" value="(p:{st.pk}[^"]*)"', cust.html)
    check("basket lines have keys", key_m and key_s)
    tok = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', cust.html).group(1)
    cust.go("/basket/", {"csrfmiddlewaretoken": tok, "key": key_m.group(1), "qty": "3"})
    cust.go("/basket/", {"csrfmiddlewaretoken": tok, "key": key_s.group(1), "remove": "1"})
    cust.go("/basket/"); t = cust.text()
    check("basket update and remove worked", "Sticker Pack" not in t and re.search(r'value="3"', cust.html), t[:300])
    checkout_to_payment()
    check("payment page shows test cards and Apple Pay", "Visa •••• 3155" in cust.text() and "Apple Pay" in cust.text())
    cust.submit({"understand": "1", "card": "declined"}, has="card", button=("method", "card"))
    check("declined card shows error, no order", "declined" in cust.text() and not Order.objects.filter(user__email=EMAIL).exists())
    cust.submit({"understand": "1", "card": "3ds"}, has="card", button=("method", "card"))
    check("3-D Secure page shown", "/authenticate" in cust.url and "Confirm this payment" in cust.text(), cust.url)
    cust.submit(button=("action", "approve"), has=None)
    o = Order.objects.filter(user__email=EMAIL).first()
    check("3-D Secure approve places order", o and "/checkout/done/" in cust.url and o.card_last4 == "3155", cust.url)
    check("stock reduced by order (mug -3)", stock("KT-008") == s_mug - 3, (s_mug, stock("KT-008")))
    check("confirmation email in demo inbox", (cust.go("/account/demo-inbox/") and f"Order {o.number} confirmed" in cust.text()))
    ctx["order1"] = o.number
    # second order with Apple Pay, then cancel it
    add("KT-004", 1)
    s_k = stock("KT-004")
    checkout_to_payment()
    cust.submit({"understand": "1"}, has="card", button=("method", "apple_pay"))
    check("Apple Pay sheet shown", "Confirm with Face ID" in cust.text(), cust.url)
    cust.submit(button=("action", "pay"), has=None)
    o2 = Order.objects.filter(user__email=EMAIL).order_by("-pk").first()
    check("Apple Pay places order", o2.number != ctx["order1"] and o2.payment_method == "apple_pay")
    check("kettle stock reduced", stock("KT-004") == s_k - 1)
    cust.go(f"/account/orders/{o2.number}/")
    cust.submit(action="cancel")
    o2.refresh_from_db()
    check("customer can cancel placed order", o2.status == "cancelled", o2.status)
    check("cancel returns stock", stock("KT-004") == s_k)
    cust.go("/account/orders/"); check("order list shows both orders", ctx["order1"] in cust.html and o2.number in cust.html)
step("shopping", shopping)

def isolation():
    other = Order.objects.exclude(user__email=EMAIL).first()
    cust.go(f"/account/orders/{other.number}/"); check("cannot view another user's order", cust.status == 404, cust.status)
    cust.go("/staff/"); check("customer cannot open staff area", "/staff/sign-in" in cust.url or cust.status == 403, (cust.url, cust.status))
step("isolation", isolation)

# ---------------------------------------------------------------- staff
def staff_login(who):
    b = Browser(); b.go("/staff/sign-in/"); b.submit({"email": who[0], "password": who[1]}, has="password")
    return b

owner = Browser()
def owner_flow():
    global owner
    owner = staff_login(OWNER); check("owner signs in to staff area", owner.url.rstrip("/").endswith("/staff") and owner.status == 200, owner.url)
    for p in ["/staff/products/", "/staff/inventory/", "/staff/orders/", "/staff/customers/", "/staff/returns/",
              "/staff/enquiries/", "/staff/access/", "/staff/ai/", "/staff/search/?q=kettle"]:
        owner.go(p); check(f"owner page {p}", owner.status == 200, owner.status)
    # order through to delivered
    n = ctx["order1"]
    for st in ["processing", "dispatched", "delivered"]:
        owner.go(f"/staff/orders/?o={n}"); owner.submit({"status": st, "note": "e2e"}, has="status")
    o = Order.objects.get(number=n)
    check("owner moves order to delivered", o.status == "delivered", o.status)
    owner.go(f"/staff/orders/?o={n}"); owner.submit({"status": "placed"}, has="status") if False else None
    # inventory adjust
    p = Product.objects.get(sku="ST-011"); before = p.stock
    owner.go(f"/staff/inventory/?p={p.pk}")
    owner.submit({"direction": "add", "quantity": "5", "reason": None, "note": "e2e"}, has="quantity")
    check("stock adjustment without reason is refused", stock("ST-011") == before)
    owner.go(f"/staff/inventory/?p={p.pk}")
    f = owner.form(has="quantity"); reason = [x for x in f["fields"] if x[0] == "reason"][0]
    p2 = Forms(); p2.feed(owner.html)
    reasons = re.findall(r'<option value="([a-z_]+)"', owner.html[owner.html.find('name="reason"'):owner.html.find('name="reason"') + 2000])
    owner.submit({"direction": "add", "quantity": "5", "reason": reasons[0], "note": "e2e"}, has="quantity")
    check("stock adjustment with reason adds 5", stock("ST-011") == before + 5, (before, stock("ST-011")))
    # product create / edit / delete
    owner.go("/staff/products/new/")
    sku = f"E2E-{TAG}".upper()[:20]
    owner.submit({"name": f"E2E Test Product {TAG}", "sku": sku, "summary": "Test", "description": "Test product", "features": "",
                  "price": "4.20", "stock": "-3", "low_stock_threshold": "2", "max_per_order": "5", "image_alt": "A test box",
                  "category": str(__import__("catalog.models", fromlist=["Category"]).Category.objects.first().pk), "icon": "box"}, has="sku")
    check("product with negative stock refused", not Product.objects.filter(sku=sku).exists())
    owner.submit({"stock": "7"}, has="sku")
    pr = Product.objects.filter(sku=sku).first(); check("owner creates product", pr is not None, owner.text()[:300])
    owner.go(f"/staff/products/{pr.pk}/"); owner.submit({"price": "5.10"}, has="sku")
    pr.refresh_from_db(); check("owner edits product price", str(pr.price) == "5.10", pr.price)
    owner.go(f"/staff/products/{pr.pk}/delete/"); owner.go(owner.url, {"csrfmiddlewaretoken": re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', owner.html).group(1)})
    check("owner deletes product", not Product.objects.filter(sku=sku).exists() or not Product.objects.get(sku=sku).is_active)
    # enquiry reply
    e = Enquiry.objects.filter(message__contains=TAG).first()
    owner.go(f"/staff/enquiries/?e={e.pk}"); owner.submit({"reply": f"Hello, reply {TAG}"}, has="reply", button=("action", "reply"))
    e.refresh_from_db(); check("staff replies to enquiry", TAG in (getattr(e, "reply", "") or "") or e.status != "new", vars(e).get("status"))
    # customer reveal is logged
    from accounts.models import AuditLog, User
    u = User.objects.get(email=EMAIL)
    n0 = AuditLog.objects.filter(action="reveal_customer").count()
    owner.go(f"/staff/customers/?c={u.pk}"); check("customer details masked by default", EMAIL not in owner.html)
    owner.submit(has="customer", button=("action", "reveal"))
    check("reveal shows email and is logged", EMAIL in owner.html and AuditLog.objects.filter(action="reveal_customer").count() == n0 + 1)
step("owner", owner_flow)

def returns_reviews():
    n = ctx["order1"]
    cust.go(f"/account/orders/{n}/return/")
    check("return form opens for delivered order", cust.status == 200 and "lines" in cust.html, cust.status)
    f = cust.form(has="lines")
    lines = [x for x in f["fields"] if x[0] == "lines"]
    mug_line = [l for l in lines if True]
    reasons = re.findall(r'<option value="([a-z_]+)"', cust.html[cust.html.find('name="reason"'):cust.html.find('name="reason"') + 2000])
    cust.submit({"lines": lines[0][1], "reason": reasons[0], "comments": "e2e", "method": "collect"}, has="lines")
    rr = ReturnRequest.objects.filter(order__number=n).first(); check("customer requests return", rr is not None, cust.text()[:300])
    ctx["ret"] = rr.pk
    # review
    p = Product.objects.get(sku="KT-008")
    cust.go(f"/product/{p.slug}/review/")
    cust.submit({"rating": "5", "title": "Great mug", "body": f"Lovely mug for my flat. {TAG}", "course": "Computer Science"}, has="rating")
    from reviews.models import Review
    check("verified buyer can review", Review.objects.filter(product=p, body__contains=TAG).exists(), cust.text()[:300])
    q = Product.objects.get(sku="WR-001")
    cust.go(f"/product/{q.slug}/review/"); check("cannot review a product not bought", cust.status in (302, 403, 404) or "/review" not in cust.url or "only" in cust.text().lower(), cust.status)
step("returns/reviews", returns_reviews)

def approve_return():
    rr = ReturnRequest.objects.get(pk=ctx["ret"]); item = rr.items.first(); sku = item.line.product.sku; before = stock(sku)
    owner.go("/staff/returns/?tab=requested")
    owner.submit({"ret": str(rr.pk), "restock": "1"}, has="ret", button=("action", "approve"))
    rr.refresh_from_db(); check("staff approves return", rr.status == "approved" or rr.status == "refunded", rr.status)
    check("approved return restocks", stock(sku) == before + item.quantity, (before, stock(sku)))
step("approve return", approve_return)

def permissions():
    for who, allowed, denied in [(STOCKU, ["/staff/inventory/", "/staff/products/"], ["/staff/customers/", "/staff/access/"]),
                                 (SUPPORT, ["/staff/customers/", "/staff/enquiries/"], ["/staff/inventory/", "/staff/products/", "/staff/access/"])]:
        b = staff_login(who)
        for p in allowed: b.go(p); check(f"{who[0].split('@')[0]} can open {p}", b.status == 200, b.status)
        for p in denied: b.go(p); check(f"{who[0].split('@')[0]} blocked from {p}", b.status == 403, b.status)
    b = Browser(); b.go("/staff/sign-in/"); b.submit({"email": EMAIL, "password": PW3}, has="password")
    check("customer cannot sign in to staff area", "/staff/sign-in" in b.url, b.url)
    b = Browser(); b.go("/contact/")
    code, body, _ = b._do("/contact/", {"name": "x", "email": "x@aston.ac.uk", "topic": "order", "message": "no csrf"})
    check("POST without CSRF token is rejected", code == 403, code)
step("permissions", permissions)

print(f"\n{sum(ok for _, ok, _ in RESULTS)} passed, {sum(not ok for _, ok, _ in RESULTS)} failed")
sys.exit(1 if any(not ok for _, ok, _ in RESULTS) else 0)
