/* AstonBundle — progressive enhancement only. Every feature works without JavaScript;
   this file adds convenience (auto-submit, steppers, OTP boxes, etc.). */
(function () {
  "use strict";
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  var store = {
    get: function (k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* storage blocked */ } }
  };

  // Announcement bar
  var ann = $("[data-ann]");
  if (ann && store.get("ab-ann-dismissed") === "jan27") ann.classList.add("hidden");
  $$("[data-dismiss-ann]").forEach(function (b) {
    b.addEventListener("click", function () { ann.classList.add("hidden"); store.set("ab-ann-dismissed", "jan27"); });
  });

  // Mobile drawer + staff sidebar
  function wireToggle(openSel, closeSel, panel) {
    if (!panel) return;
    $$(openSel).forEach(function (b) {
      b.addEventListener("click", function () { panel.classList.add("open"); b.setAttribute("aria-expanded", "true"); var f = panel.querySelector("a,button"); if (f) f.focus(); });
    });
    $$(closeSel).forEach(function (b) {
      b.addEventListener("click", function () { panel.classList.remove("open"); $$(openSel).forEach(function (o) { o.setAttribute("aria-expanded", "false"); }); });
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && panel.classList.contains("open")) { panel.classList.remove("open"); var o = $(openSel); if (o) o.focus(); } });
  }
  wireToggle("[data-open-drawer]", "[data-close-drawer]", $("[data-drawer]"));
  wireToggle("[data-open-filters]", "[data-close-filters]", $("[data-filters]"));
  wireToggle("[data-open-side]", "[data-close-side]", $("[data-side]"));

  // Auto-submit forms when a select / checkbox / radio changes
  $$("form[data-autosubmit]").forEach(function (form) {
    form.addEventListener("change", function (e) {
      var t = e.target;
      if (t.tagName === "SELECT" || t.type === "checkbox" || t.type === "radio" || (t.type === "number" && form.querySelector("[data-stepper]"))) {
        if (form.closest("[data-filters]") && window.matchMedia("(max-width: 900px)").matches) return; // mobile sheet uses Apply
        form.submit();
      }
    });
  });

  // Quantity steppers
  $$("[data-stepper]").forEach(function (st) {
    var input = st.querySelector("input");
    $$("[data-step]", st).forEach(function (btn) {
      btn.addEventListener("click", function () {
        var min = parseInt(input.min || "0", 10), max = parseInt(input.max || "99", 10);
        var v = (parseInt(input.value, 10) || 0) + parseInt(btn.getAttribute("data-step"), 10);
        v = Math.max(min, Math.min(max, v));
        if (String(v) !== input.value) { input.value = v; input.dispatchEvent(new Event("change", { bubbles: true })); }
      });
    });
  });

  // Show / hide password
  $$("[data-toggle-pw]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var input = btn.parentNode.querySelector("input");
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.setAttribute("aria-pressed", show ? "true" : "false");
      btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
      btn.querySelector(".i").className = "i " + (show ? "i-eyeoff" : "i-eye");
    });
  });

  // Password strength
  var pw = $("[data-strength]");
  if (pw) {
    var bar = $("[data-strength-bar]"), txt = $("[data-strength-text]");
    var check = function () {
      var v = pw.value, reqs = { len: v.length >= 10, letter: /[A-Za-z]/.test(v), num: /\d/.test(v), sym: /[^A-Za-z0-9]/.test(v) };
      Object.keys(reqs).forEach(function (k) {
        var li = $('[data-req="' + k + '"]'); if (!li) return;
        li.className = reqs[k] ? "y" : "n";
        li.querySelector(".i").className = "i s16 " + (reqs[k] ? "i-check" : "i-minus");
      });
      var score = (reqs.len ? 1 : 0) + (reqs.letter && reqs.num ? 1 : 0) + (reqs.sym ? 1 : 0) + (v.length >= 14 ? 1 : 0);
      if (bar) $$("span", bar).forEach(function (s, i) { s.className = i < score ? (score >= 3 ? "on" : "mid") : ""; });
      if (txt) txt.innerHTML = v ? "<b>Strength: " + ["too weak", "weak", "fair", "strong", "very strong"][score] + ".</b>" + (score < 3 ? " Add a symbol or make it longer." : "") : "";
    };
    pw.addEventListener("input", check); check();
  }

  // OTP boxes
  var otp = $("[data-otp]");
  if (otp) {
    var boxes = $$("input", otp), hidden = $("[data-otp-value]");
    var sync = function () { hidden.value = boxes.map(function (b) { return b.value; }).join(""); };
    boxes.forEach(function (b, i) {
      b.addEventListener("input", function () {
        b.value = b.value.replace(/\D/g, "").slice(-1);
        b.classList.toggle("fill", !!b.value);
        if (b.value && boxes[i + 1]) boxes[i + 1].focus();
        sync();
        if (hidden.value.length === 6) b.form.requestSubmit ? b.form.requestSubmit(b.form.querySelector("[name=verify]")) : b.form.submit();
      });
      b.addEventListener("keydown", function (e) {
        if (e.key === "Backspace" && !b.value && boxes[i - 1]) { boxes[i - 1].focus(); boxes[i - 1].value = ""; sync(); }
      });
      b.addEventListener("paste", function (e) {
        var digits = (e.clipboardData || window.clipboardData).getData("text").replace(/\D/g, "").slice(0, 6);
        if (!digits) return;
        e.preventDefault();
        digits.split("").forEach(function (d, j) { if (boxes[j]) { boxes[j].value = d; boxes[j].classList.add("fill"); } });
        sync();
        (boxes[digits.length] || boxes[5]).focus();
      });
    });
    var f = otp.closest("form");
    f.addEventListener("submit", sync);
  }

  // Countdown (verification code)
  $$("[data-countdown]").forEach(function (el) {
    var s = parseInt(el.getAttribute("data-countdown"), 10);
    var tick = function () {
      if (s <= 0) { el.textContent = "0:00"; return; }
      el.textContent = Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2);
      s -= 1; setTimeout(tick, 1000);
    };
    tick();
  });

  // Copy button
  $$("[data-copy]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (navigator.clipboard) navigator.clipboard.writeText(b.getAttribute("data-copy")).then(function () { b.lastChild.textContent = "Copied"; });
    });
  });

  // Arrival Guide checklist (saved on this device only)
  var cl = $("[data-checklist]");
  if (cl) {
    var boxesC = $$("input[type=checkbox]", cl), saved = {};
    try { saved = JSON.parse(store.get("ab-checklist") || "{}"); } catch (e) { saved = {}; }
    var update = function () {
      var done = boxesC.filter(function (b) { return b.checked; }).length;
      var t = $("[data-progress-text]"); if (t) t.textContent = done + " of " + boxesC.length + " done";
      $$("[data-progress] span").forEach(function (s, i) { s.className = i < Math.round(5 * done / boxesC.length) ? "on" : ""; });
    };
    boxesC.forEach(function (b) {
      b.checked = !!saved[b.name];
      b.addEventListener("change", function () { saved[b.name] = b.checked; store.set("ab-checklist", JSON.stringify(saved)); update(); });
    });
    update();
  }

  // Tabs (product page)
  $$("[data-tabs]").forEach(function (wrap) {
    var tabs = $$("[role=tab]", wrap);
    var select = function (tab) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.classList.toggle("on", on); t.setAttribute("aria-selected", on ? "true" : "false"); t.tabIndex = on ? 0 : -1;
        document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
      });
    };
    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () { select(t); });
      t.addEventListener("keydown", function (e) {
        var n = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (n) { var next = tabs[(i + n + tabs.length) % tabs.length]; select(next); next.focus(); }
      });
    });
    $$("[data-tabpanel-hidden]", wrap).forEach(function (p) { p.hidden = true; });
  });

  // Bundle customise
  var bf = $("[data-bundle-form]");
  if (bf) {
    var cust = $("[data-customise]", bf), items = $$("[data-item]", bf);
    var full = parseFloat(bf.getAttribute("data-bundle-full")), price = parseFloat(bf.getAttribute("data-bundle-price"));
    var gbp = function (v) { return "£" + v.toFixed(2); };
    var recalc = function () {
      items.forEach(function (i) { i.disabled = !cust.checked; if (!cust.checked) i.checked = true; });
      var chosen = items.filter(function (i) { return i.checked; });
      var sum = chosen.reduce(function (a, i) { return a + parseFloat(i.getAttribute("data-price")) * parseInt(i.getAttribute("data-qty"), 10); }, 0);
      var pay = full ? sum * price / full : sum;
      $("[data-full]", bf).textContent = gbp(sum);
      $("[data-saving]", bf).textContent = "−" + gbp(sum - pay);
      $("[data-price]", bf).textContent = gbp(pay);
      $("[data-count]", bf).textContent = chosen.reduce(function (a, i) { return a + parseInt(i.getAttribute("data-qty"), 10); }, 0);
      var btn = bf.querySelector("button[type=submit]");
      btn.disabled = chosen.length < 2;
    };
    cust.addEventListener("change", recalc); items.forEach(function (i) { i.addEventListener("change", recalc); });
    recalc();
  }

  // Checkout: delivery type + day/slot selection
  var dtypes = $$("[data-dtype]");
  if (dtypes.length) {
    var showFor = function () {
      var v = (dtypes.filter(function (r) { return r.checked; })[0] || {}).value || "halls";
      $$("[data-show-for]").forEach(function (el) { el.hidden = el.getAttribute("data-show-for") !== v; });
    };
    dtypes.forEach(function (r) { r.addEventListener("change", showFor); }); showFor();
  }
  var days = $$("[data-day]");
  if (days.length) {
    var showSlots = function () {
      var d = (days.filter(function (r) { return r.checked; })[0] || {}).value;
      days.forEach(function (r) { r.parentNode.classList.toggle("on", r.checked); });
      $$("[data-slots-for]").forEach(function (g) {
        var on = g.getAttribute("data-slots-for") === d;
        g.hidden = !on;
        $$("input", g).forEach(function (i) { if (!on) { i.checked = false; } });
      });
    };
    days.forEach(function (r) { r.addEventListener("change", showSlots); });
    $$(".slot input").forEach(function (i) {
      i.addEventListener("change", function () { $$(".slot").forEach(function (s) { s.classList.toggle("on", s.querySelector("input").checked); }); });
    });
    showSlots();
  }

  // Return item cards
  $$("[data-ri] input").forEach(function (i) { i.addEventListener("change", function () { i.closest("[data-ri]").classList.toggle("on", i.checked); }); });

  // Character counters
  $$("textarea[data-count]").forEach(function (t) {
    var out = document.getElementById(t.getAttribute("data-count"));
    var upd = function () { out.textContent = t.value.length + " / " + t.maxLength; };
    t.addEventListener("input", upd);
  });

  // Confirm dangerous actions
  $$("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (e) { if (!window.confirm(f.getAttribute("data-confirm"))) e.preventDefault(); });
  });

  // Prevent double submission
  $$("[data-once]").forEach(function (b) {
    b.form && b.form.addEventListener("submit", function () { setTimeout(function () { b.disabled = true; b.setAttribute("aria-busy", "true"); }, 0); });
  });

  // Toasts
  $$("[data-toast]").forEach(function (t) {
    var close = function () { t.remove(); };
    $$("[data-close-toast]", t).forEach(function (b) { b.addEventListener("click", close); });
    setTimeout(close, 7000);
  });

  // Make horizontally scrollable tables reachable with the keyboard
  var markScroll = function () {
    $$(".tbox").forEach(function (t, i) {
      if (t.scrollWidth > t.clientWidth + 1 && !t.hasAttribute("tabindex")) {
        t.tabIndex = 0; t.setAttribute("role", "region");
        var h = t.closest("section") && t.closest("section").querySelector("h2");
        t.setAttribute("aria-label", (h ? h.textContent.trim() + " – " : "") + "scrollable table " + (i + 1));
      }
    });
  };
  markScroll(); window.addEventListener("load", markScroll); window.addEventListener("resize", markScroll);

  // Focus the error summary so screen readers announce it
  var fe = $("[data-focus]"); if (fe) fe.focus();

  // Staff bulk selection
  var bulk = $("[data-bulk]");
  if (bulk) {
    var all = $("[data-select-all]", bulk), cbs = $$("input[name=sel]", bulk), cnt = $("[data-bulk-count]", bulk);
    var count = function () { cnt.textContent = cbs.filter(function (c) { return c.checked; }).length + " selected"; };
    if (all) all.addEventListener("change", function () { cbs.forEach(function (c) { c.checked = all.checked; }); count(); });
    cbs.forEach(function (c) { c.addEventListener("change", count); });
    count();
  }
})();
