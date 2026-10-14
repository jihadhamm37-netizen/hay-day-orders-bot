/* Admin panel — vanilla JS single-page app (no external scripts, strict CSP). */
(() => {
  "use strict";
  const ROOT = document.getElementById("app");
  const PANEL = ROOT.dataset.panel;

  // ------------------------------------------------------------ helpers
  // ignore null/false children everywhere (conditional UI pieces)
  for (const proto of [Element.prototype, DocumentFragment.prototype]) {
    for (const fn of ["replaceChildren", "append"]) {
      const orig = proto[fn];
      proto[fn] = function (...kids) { return orig.apply(this, kids.filter((k) => k !== null && k !== undefined && k !== false)); };
    }
  }
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "html") el.innerHTML = v;
      else if (k === "value") el.value = v;
      else if (k === "checked") el.checked = !!v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat(Infinity)) {
      if (c === null || c === undefined || c === false) continue;
      el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  }
  const cookie = (n) => (document.cookie.split("; ").find((c) => c.startsWith(n + "=")) || "").split("=")[1] || "";

  class ApiError extends Error {}
  async function api(method, path, body, isForm) {
    const opts = { method, credentials: "same-origin", headers: { "X-CSRF-Token": cookie("hd_csrf") } };
    if (body !== undefined) {
      if (isForm) opts.body = body;
      else { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    }
    let res;
    try { res = await fetch("/api" + path, opts); } catch { throw new ApiError("تعذر الاتصال بالخادم."); }
    let data = {};
    try { data = await res.json(); } catch { /* empty */ }
    if (res.status === 401 && !path.startsWith("/auth/")) { state.me = null; renderLogin(); throw new ApiError(data.error || "انتهت الجلسة"); }
    if (!res.ok || data.ok === false) throw new ApiError(data.error || `خطأ ${res.status}`);
    return data.data;
  }
  const GET = (p) => api("GET", p);
  const POST = (p, b) => api("POST", p, b ?? {});

  function toast(msg, err) {
    const t = h("div", { class: "t" + (err ? " err" : "") }, msg);
    document.getElementById("toast").append(t);
    setTimeout(() => t.remove(), err ? 6000 : 3200);
  }
  async function run(fn, okMsg) {
    try { const r = await fn(); if (okMsg) toast(okMsg); return r; }
    catch (e) { toast(e.message || String(e), true); throw e; }
  }
  const money = (v) => (v === null || v === undefined) ? "—" :
    Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const usdt = (v) => h("span", { class: "num" }, money(v) + " USDT");
  const dt = (s) => s ? new Date(s).toLocaleString("en-GB", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
  const q = (o) => { const p = new URLSearchParams(); for (const [k, v] of Object.entries(o)) if (v !== "" && v !== null && v !== undefined) p.set(k, v); const s = p.toString(); return s ? "?" + s : ""; };
  const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());

  const ORDER = { pending_confirmation: ["بانتظار تأكيد الطلب", ""], awaiting_payment: ["بانتظار الدفع", "warn"], proof_received: ["إثبات الدفع مستلم", "info"],
    payment_review: ["الدفع قيد المراجعة", "warn"], payment_confirmed: ["الدفع مؤكد", "info"], processing: ["قيد التنفيذ", "info"],
    delivered: ["تم التسليم", "ok"], cancelled: ["ملغي", ""], rejected: ["مرفوض", "danger"] };
  const PAY = { pending: ["بانتظار المراجعة", "warn"], approved: ["مقبول", "ok"], rejected: ["مرفوض", "danger"] };
  const FARM = { available: ["متوفرة", "ok"], reserved: ["محجوزة", "warn"], sold: ["مباعة", "info"], disabled: ["معطلة", ""] };
  const pill = (map, k) => h("span", { class: "pill " + ((map[k] || [])[1] || "") }, (map[k] || [k])[0]);

  function modal(title, body, { wide } = {}) {
    const bg = h("div", { class: "modal-bg" });
    const close = () => { bg.remove(); document.removeEventListener("keydown", esc); };
    const esc = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", esc);
    bg.addEventListener("mousedown", (e) => { if (e.target === bg) close(); });
    const box = h("div", { class: "card modal" + (wide ? " wide" : ""), role: "dialog", "aria-modal": "true" },
      h("div", { class: "card-h" }, h("h3", null, title), h("span", { style: "flex:1" }),
        h("button", { class: "btn sm", onclick: close, "aria-label": "إغلاق" }, "✕")),
      h("div", { class: "card-b" }, body));
    bg.append(box);
    document.body.append(bg);
    return { close, box };
  }
  function confirmBox(text, { danger, okText = "تأكيد" } = {}) {
    return new Promise((resolve) => {
      let done = false;
      const m = modal("تأكيد", h("div", null, h("p", null, text), h("div", { class: "btn-row" },
        h("button", { class: "btn " + (danger ? "danger solid" : "primary"), onclick: () => { done = true; m.close(); resolve(true); } }, okText),
        h("button", { class: "btn", onclick: () => { m.close(); resolve(false); } }, "إلغاء"))));
      const obs = new MutationObserver(() => { if (!document.body.contains(m.box)) { obs.disconnect(); if (!done) resolve(false); } });
      obs.observe(document.body, { childList: true });
    });
  }
  const field = (label, input) => h("label", { class: "f" }, h("span", null, label), input);
  const table = (heads, rows, empty = "لا توجد بيانات") => rows.length
    ? h("div", { class: "table-wrap" }, h("table", null, h("thead", null, h("tr", null, heads.map((x) => h("th", null, x)))), h("tbody", null, rows)))
    : h("div", { class: "empty" }, empty);
  function pager(page, count, size, go) {
    if (page === 0 && count < size) return document.createTextNode("");
    return h("div", { class: "pager" },
      h("button", { class: "btn sm", disabled: page === 0, onclick: () => go(page - 1) }, "السابق"),
      h("span", { class: "muted small" }, `صفحة ${page + 1}`),
      h("button", { class: "btn sm", disabled: count < size, onclick: () => go(page + 1) }, "التالي"));
  }

  // ------------------------------------------------------------- state
  const state = { me: null, counts: { payments: 0, chats: 0, alerts: 0 }, lastPay: null };
  const can = (p) => state.me && state.me.perms.includes(p);

  // ------------------------------------------------------------- login
  function renderLogin(err) {
    ROOT.innerHTML = "";
    const user = h("input", { type: "text", autocomplete: "username", dir: "ltr", required: true });
    const pass = h("input", { type: "password", autocomplete: "current-password", dir: "ltr", required: true });
    const msg = h("div");
    const btn = h("button", { class: "btn primary", type: "submit", style: "width:100%" }, "دخول");
    const form = h("form", null, field("اسم المستخدم", user), field("كلمة المرور", pass), msg, btn);
    form.addEventListener("submit", async (e) => {
      e.preventDefault(); btn.disabled = true; msg.innerHTML = "";
      try {
        const r = await api("POST", "/auth/login", { username: user.value, password: pass.value });
        if (r.step === "code") return renderCode(r.ticket);
        if (r.warning) toast(r.warning);
        boot();
      } catch (ex) { msg.replaceChildren(h("p", { class: "notice danger" }, ex.message)); btn.disabled = false; }
    });
    ROOT.append(h("div", { class: "login" }, h("div", { class: "card" }, h("div", { class: "card-b" },
      h("div", { class: "brand", style: "padding:0 0 14px" }, h("div", { class: "brand-mark" }, "🌾"),
        h("div", null, h("h1", null, "لوحة التحكم"), h("small", null, "متجر مزارع Hay Day"))),
      err ? h("p", { class: "notice danger" }, err) : null, form))));
    user.focus();
  }
  function renderCode(ticket) {
    ROOT.innerHTML = "";
    const code = h("input", { type: "text", inputmode: "numeric", autocomplete: "one-time-code", dir: "ltr", maxlength: "6", style: "letter-spacing:6px;text-align:center;font-size:22px" });
    const msg = h("div");
    const form = h("form", null, h("p", { class: "muted" }, "أرسلنا رمزاً من 6 أرقام إلى حسابك في تيليجرام."),
      field("رمز التحقق", code), msg, h("button", { class: "btn primary", type: "submit", style: "width:100%" }, "تأكيد"),
      h("p", null, h("a", { href: "#", onclick: (e) => { e.preventDefault(); renderLogin(); } }, "رجوع")));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await api("POST", "/auth/verify", { ticket, code: code.value }); boot(); }
      catch (ex) { msg.replaceChildren(h("p", { class: "notice danger" }, ex.message)); }
    });
    ROOT.append(h("div", { class: "login" }, h("div", { class: "card" }, h("div", { class: "card-b" }, h("h1", null, "🔐 التحقق بخطوتين"), form))));
    code.focus();
  }

  // ------------------------------------------------------------- shell
  const NAV = [
    ["dashboard", "▦", "الرئيسية", "view"],
    ["chats", "✉", "المحادثات", "chat", "chats"],
    ["codes", "#", "أكواد العملاء", "customers"],
    ["payments", "$", "مراجعة الدفع", "payments", "payments"],
    ["orders", "≡", "الطلبات", "orders"],
    ["farms", "◫", "المزارع والمخزون", "view"],
    ["methods", "⇄", "وسائل الدفع", "view"],
    ["alerts", "!", "التنبيهات", "view", "alerts"],
    ["-"],
    ["settings", "⚙", "الإعدادات والذكاء الاصطناعي", "settings"],
    ["admins", "◉", "المشرفون", "admins"],
    ["audit", "☰", "سجل التدقيق", "view"],
    ["backups", "⤓", "النسخ الاحتياطي", "backup"],
    ["account", "○", "حسابي", "view"],
  ];
  let mainEl, titleEl, sideEl, navEl;

  function renderShell() {
    ROOT.innerHTML = "";
    navEl = h("nav", { class: "nav" });
    sideEl = h("aside", { class: "side" },
      h("div", { class: "brand" }, h("div", { class: "brand-mark" }, "HD"), h("div", null, "HD Agent", h("small", null, "لوحة الإدارة"))),
      navEl,
      h("div", { class: "nav-sep" }),
      h("div", { class: "nav" }, h("a", { href: "#", onclick: async (e) => { e.preventDefault(); await POST("/auth/logout"); state.me = null; renderLogin(); } },
        h("span", { class: "ico" }, "⎋"), "تسجيل الخروج")));
    titleEl = h("h1");
    mainEl = h("div", { class: "stack" });
    const menuBtn = h("button", { class: "btn sm menu-btn", "aria-label": "القائمة", onclick: () => toggleSide(true) }, "☰");
    ROOT.append(h("div", { class: "shell" }, sideEl, h("main", { class: "main" },
      h("div", { class: "topbar" }, menuBtn, titleEl, h("span", { class: "spacer" }),
        h("span", { class: "who" }, `${state.me.username} · ${state.me.role_label}`)), mainEl)));
    renderNav();
  }
  let scrim = null;
  function toggleSide(open) {
    sideEl.classList.toggle("open", open);
    if (open && !scrim) { scrim = h("div", { class: "scrim", onclick: () => toggleSide(false) }); document.body.append(scrim); }
    if (!open && scrim) { scrim.remove(); scrim = null; }
  }
  function renderNav() {
    const cur = (location.hash.slice(2) || "dashboard").split("/")[0];
    navEl.replaceChildren(...NAV.filter((n) => n[0] === "-" || can(n[3])).map((n) => n[0] === "-" ? h("div", { class: "nav-sep" }) :
      h("a", { href: "#/" + n[0], class: cur === n[0] || (cur === "chat" && n[0] === "chats") || (cur === "order" && n[0] === "orders") ? "active" : "" },
        h("span", { class: "ico" }, n[1]), n[2], n[4] && state.counts[n[4]] ? h("span", { class: "badge" }, state.counts[n[4]]) : null)));
  }

  async function refreshCounts() {
    try {
      const s = await GET("/stats/overview");
      const prev = state.lastPay;
      state.counts = { payments: s.pending_payments, chats: s.customers.taken_over, alerts: s.unread_alerts };
      if (prev !== null && s.pending_payments > prev) toast(`إثبات دفع جديد بانتظار المراجعة (${s.pending_payments})`);
      state.lastPay = s.pending_payments;
      renderNav();
      document.title = (s.pending_payments ? `(${s.pending_payments}) ` : "") + "HD Agent — لوحة التحكم";
    } catch { /* ignore */ }
  }

  // ------------------------------------------------------------ router
  const ROUTES = {};
  async function route() {
    if (!state.me) return;
    toggleSide(false);
    document.querySelectorAll(".modal-bg").forEach((m) => m.remove());
    const [name, arg] = (location.hash.slice(2) || "dashboard").split("/");
    const r = ROUTES[name] || ROUTES.dashboard;
    renderNav();
    mainEl.replaceChildren(h("div", { class: "empty" }, "جارٍ التحميل…"));
    try { await r(arg); } catch (e) { if (!(e instanceof ApiError)) console.error(e); mainEl.replaceChildren(h("p", { class: "notice danger" }, e.message || "خطأ")); }
  }
  const setTitle = (t) => { titleEl.textContent = t; };

  // ========================================================= dashboard
  function barChart(days) {
    const W = 720, H = 220, P = 26, n = days.length;
    const max = Math.max(1, ...days.map((d) => Math.max(+d.revenue, +d.profit)));
    const bw = (W - P * 2) / n;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "chart"); svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "الإيراد والربح اليومي");
    const mk = (t, a) => { const e = document.createElementNS(svg.namespaceURI, t); for (const k in a) e.setAttribute(k, a[k]); return e; };
    days.forEach((d, i) => {
      const x = W - P - (i + 1) * bw; // right-to-left: newest on the left edge
      const rh = (H - P * 2) * (+d.revenue / max), dh = (H - P * 2) * (+d.profit / max);
      const g = mk("g", {});
      const t = mk("title", {}); t.textContent = `${d.day}\nالإيراد: ${money(d.revenue)} (${d.orders} طلب)\nالربح: ${money(d.profit)}`;
      g.append(t, mk("rect", { class: "bar", x: x + bw * .12, y: H - P - rh, width: bw * .38, height: Math.max(rh, 0), rx: 2 }),
        mk("rect", { class: "bar2", x: x + bw * .5, y: H - P - dh, width: bw * .38, height: Math.max(dh, 0), rx: 2 }));
      if (i % 5 === 0 || i === n - 1) { const tx = mk("text", { x: x + bw / 2, y: H - 8, "text-anchor": "middle" }); tx.textContent = d.day.slice(5); g.append(tx); }
      svg.append(g);
    });
    const top = mk("text", { x: W - 4, y: 14, "text-anchor": "end" }); top.textContent = money(max); svg.append(top);
    return svg;
  }
  const kpi = (label, value, sub, cls) => h("div", { class: "card kpi " + (cls || "") }, h("div", { class: "label" }, label),
    h("div", { class: "value num" }, value), sub ? h("div", { class: "sub" }, sub) : null);

  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  const cur = (v, c) => h("span", { class: "num" }, money(v) + " " + (c || "USDT"));
  const TOOL_AR = { land: "أدوات أرض", barn: "أدوات حظيرة", silo: "أدوات صومعة" };
  const toolTxt = (o) => `${TOOL_AR[o.tool_type || "land"]} ${o.tools}`;
  const specLine = (o) => `المستوى ${o.lvl} · مخزن ${o.barn} · صومعة ${o.silo} · ${toolTxt(o)}`;

  // ========================================================= dashboard
  ROUTES.dashboard = async () => {
    setTitle("نظرة عامة");
    const [s, days, top, alerts] = await Promise.all([GET("/stats/overview"), GET("/stats/daily?days=30"), GET("/stats/top-levels"), GET("/alerts?unread=true")]);
    const usdt = s.sales.find((x) => x.currency === "USDT") || { revenue: 0, profit: 0, today: 0, month: 0, orders: 0, farms: 0, farms_without_cost: 0 };
    const st = s.orders_by_status;
    const aiOn = state.me.ai_configured;
    mainEl.replaceChildren(
      aiOn ? null : h("div", { class: "notice" }, "المساعد المجاني المدمج يرد على العملاء ويبيع تلقائياً (بدون أي اشتراك). يفهم المستوى والمخزن والصومعة والأدوات والعدد، ويحوّل الشكاوى فقط للإدارة."),
      h("div", { class: "grid kpis" },
        kpi("الإيرادات (USDT)", money(usdt.revenue), `${usdt.orders} طلب مسلّم · ${usdt.farms} مزرعة`),
        kpi("الأرباح (USDT)", money(usdt.profit), usdt.farms_without_cost ? `${usdt.farms_without_cost} مزرعة بلا تكلفة مسجلة` : "الإيراد − التكلفة"),
        kpi("اليوم", money(usdt.today), "USDT"),
        kpi("آخر 30 يوماً", money(usdt.month), "USDT"),
        kpi("دفعات بانتظار المراجعة", s.pending_payments, "", s.pending_payments ? "warn" : ""),
        kpi("بانتظار الدفع", (st.awaiting_payment || 0), "مزارع محجوزة مؤقتاً"),
        kpi("محادثات مع الإدارة", s.customers.taken_over, "الرد الآلي متوقف لها", s.customers.taken_over ? "warn" : ""),
        kpi("المخزون المتوفر", s.stock.available, `محجوز ${s.stock.reserved} · مباع ${s.stock.sold}`),
        kpi("العملاء", s.customers.total, `نشطون 24 ساعة: ${s.customers.active_24h} · جدد اليوم: ${s.customers.new_today}`)),
      s.sales.filter((x) => x.currency !== "USDT").length ? h("div", { class: "notice" }, "عملات أخرى: " + s.sales.filter((x) => x.currency !== "USDT").map((x) => `${x.currency}: إيراد ${money(x.revenue)} / ربح ${money(x.profit)}`).join(" · ")) : null,
      h("div", { class: "grid two" },
        h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "آخر 30 يوماً"), h("span", { style: "flex:1" }),
          h("div", { class: "legend" }, h("span", null, h("i", { style: "background:var(--brand)" }), "الإيراد"), h("span", null, h("i", { style: "background:var(--accent)" }), "الربح"))),
          h("div", { class: "card-b" }, barChart(days))),
        h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "تنبيهات جديدة"), h("span", { style: "flex:1" }), h("a", { href: "#/alerts" }, "الكل")),
          alerts.length ? h("div", { class: "card-b stack" }, alerts.slice(0, 8).map(alertRow)) : h("div", { class: "empty" }, "لا توجد تنبيهات"))),
      h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "الطلبات حسب الحالة")),
        h("div", { class: "card-b btn-row" }, Object.entries(ORDER).map(([k, [l, c]]) => h("a", { href: "#/orders/" + k, class: "pill " + c }, `${l}: ${st[k] || 0}`)))),
      h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "المستويات الأكثر مبيعاً")),
        table(["المستوى", "المزارع", "الإيراد"], top.map((t) => h("tr", null, h("td", { class: "num" }, t.lvl), h("td", { class: "num" }, t.farms), h("td", null, cur(t.revenue, t.currency)))), "لا توجد مبيعات بعد")));
  };
  function alertRow(a) {
    const cls = { error: "danger", warning: "warn", info: "" }[a.level];
    return h("div", { class: "notice " + cls }, h("div", { class: "wrap" }, a.message), h("div", { class: "small muted" }, dt(a.created_at)));
  }

  // ============================================================== chats
  ROUTES.chats = async () => {
    setTitle("المحادثات");
    let waiting = false, page = 0;
    const search = h("input", { type: "search", placeholder: "الاسم أو الكود أو رقم العميل", dir: "auto" });
    const tabs = h("div", { class: "tabs" });
    const body = h("div");
    const aiState = (await GET("/ai/status")).enabled;
    const aiBtn = h("button", { class: "btn " + (aiState ? "danger" : "primary"), onclick: async () => {
      await run(() => POST("/ai/toggle", { enabled: !aiState }), aiState ? "تم إيقاف الرد الآلي لجميع العملاء" : "تم تشغيل الرد الآلي"); route(); } },
      aiState ? "إيقاف الرد الآلي مؤقتاً (للجميع)" : "تشغيل الرد الآلي");
    const renderTabs = () => tabs.replaceChildren(...[[false, "كل العملاء"], [true, "محوّلة للإدارة"]].map(([k, l]) =>
      h("button", { class: waiting === k ? "on" : "", onclick: () => { waiting = k; page = 0; renderTabs(); load(); } }, l)));
    const load = async () => {
      const items = await GET("/customers" + q({ q: search.value.trim(), waiting: waiting || "", page }));
      body.replaceChildren(table(["العميل", "آخر رسالة", "الرد", "المشتريات", "آخر نشاط"], items.map((c) => h("tr", { class: "click", onclick: () => (location.hash = "#/chat/" + c.id) },
        h("td", null, h("b", null, c.first_name || "—"), h("div", { class: "small muted mono" }, (c.access_code || "") + " · #" + c.id)),
        h("td", { class: "wrap small" }, c.last_role === "user" ? h("b", null, (c.last_message || "").slice(0, 80)) : (c.last_message || "").slice(0, 80)),
        h("td", null, c.ai_paused ? h("span", { class: "pill warn" }, "الإدارة") : h("span", { class: "pill ok" }, "آلي"), c.is_banned ? h("span", { class: "pill danger" }, "محظور") : null),
        h("td", null, `${c.delivered_orders} · `, cur(c.spent)), h("td", null, dt(c.last_message_at)))), "لا توجد محادثات"),
      pager(page, items.length, 50, (p) => { page = p; load(); }));
    };
    search.addEventListener("input", debounce(() => { page = 0; load(); }, 400));
    renderTabs();
    mainEl.replaceChildren(
      h("div", { class: "card" }, h("div", { class: "card-b btn-row" }, h("span", null, "حالة الرد الآلي: ", aiState ? h("span", { class: "pill ok" }, "يعمل") : h("span", { class: "pill danger" }, "متوقف")), h("span", { style: "flex:1" }), can("chat") ? aiBtn : null)),
      h("div", { class: "card" }, h("div", { class: "card-h" }, tabs, h("span", { style: "flex:1" }), search), body));
    await load();
  };

  ROUTES.chat = async (id) => {
    const c = await GET("/customers/" + id);
    setTitle(`${c.first_name || "عميل"} — ${c.access_code || "#" + c.id}`);
    const roleLbl = { user: "العميل", assistant: "البوت", admin: "الإدارة", system: "النظام" };
    const log = h("div", { class: "chatlog" }, c.messages.map((m) => h("div", { class: "msg " + m.role },
      h("div", { class: "msg-h" }, roleLbl[m.role] + (m.author ? ` (${m.author})` : ""), " · ", dt(m.created_at)), h("div", { class: "msg-b" }, m.content))));
    const input = h("textarea", { placeholder: "اكتب ردك للعميل…", style: "min-height:70px" });
    const send = async () => {
      if (!input.value.trim()) return;
      await run(() => POST(`/customers/${id}/message`, { text: input.value, takeover: true }), "تم الإرسال");
      ROUTES.chat(id);
    };
    const notes = h("textarea", { style: "min-height:60px" }); notes.value = c.notes || "";
    mainEl.replaceChildren(
      h("div", { class: "btn-row" }, h("a", { class: "btn sm", href: "#/chats" }, "→ المحادثات"),
        c.ai_paused ? h("button", { class: "btn sm primary", onclick: async () => { await run(() => POST(`/customers/${id}/ai`, { enabled: true }), "عاد الرد الآلي لهذا العميل"); ROUTES.chat(id); } }, "إعادة الرد الآلي")
          : h("button", { class: "btn sm danger", onclick: async () => { await run(() => POST(`/customers/${id}/ai`, { enabled: false }), "تم تحويل المحادثة للإدارة"); ROUTES.chat(id); } }, "تحويل المحادثة للإدارة (إيقاف الرد الآلي)"),
        can("customers") ? h("button", { class: "btn sm " + (c.is_banned ? "" : "danger"), onclick: async () => { await run(() => POST(`/customers/${id}/ban`, { banned: !c.is_banned }), "تم"); ROUTES.chat(id); } }, c.is_banned ? "فك الحظر" : "حظر") : null),
      h("div", { class: "grid two" },
        h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "المحادثة"), h("span", { style: "flex:1" }), c.ai_paused ? h("span", { class: "pill warn" }, "تتولاها الإدارة") : h("span", { class: "pill ok" }, "الرد الآلي يعمل")),
          h("div", { class: "card-b" }, log, h("div", { class: "stack", style: "margin-top:12px" }, input, h("div", { class: "btn-row" },
            h("button", { class: "btn primary", onclick: send }, "إرسال للعميل"), h("span", { class: "small muted" }, "إرسال رد يحوّل المحادثة للإدارة تلقائياً."))))),
        h("div", { class: "stack" },
          h("div", { class: "card" }, h("div", { class: "card-b" }, h("dl", { class: "kv" }, h("dt", null, "الكود"), h("dd", { class: "mono" }, c.access_code || "—"),
            h("dt", null, "الجهاز"), h("dd", null, c.device_label || (c.device_id ? "مربوط" : "لم يُستخدم بعد")),
            h("dt", null, "اللغة"), h("dd", null, c.lang), h("dt", null, "انضم"), h("dd", null, dt(c.created_at)), h("dt", null, "آخر نشاط"), h("dd", null, dt(c.last_seen_at))))),
          h("div", { class: "card" }, h("div", { class: "card-h" }, h("h3", null, "طلبات العميل")),
            table(["الطلب", "الحالة", "الإجمالي"], c.orders.map((o) => h("tr", { class: "click", onclick: () => (location.hash = "#/order/" + o.id) },
              h("td", { class: "mono" }, o.ref), h("td", null, pill(ORDER, o.status)), h("td", null, cur(o.total, o.currency)))), "لا توجد طلبات")),
          h("div", { class: "card" }, h("div", { class: "card-h" }, h("h3", null, "ملاحظات داخلية")), h("div", { class: "card-b" }, notes,
            h("button", { class: "btn sm", style: "margin-top:8px", onclick: () => run(() => POST(`/customers/${id}/notes`, { notes: notes.value }), "تم الحفظ") }, "حفظ"))))));
    log.scrollTop = log.scrollHeight;
  };

  // ============================================================ payments
  ROUTES.payments = async () => {
    setTitle("مراجعة الدفع");
    let status = "pending", page = 0;
    const search = h("input", { type: "search", placeholder: "رقم الطلب / رقم العميل", dir: "auto", style: "max-width:280px" });
    const tabs = h("div", { class: "tabs" });
    const body = h("div");
    const renderTabs = () => tabs.replaceChildren(...[["pending", "بانتظار المراجعة"], ["approved", "مقبولة"], ["rejected", "مرفوضة"], ["", "الكل"]]
      .map(([k, l]) => h("button", { class: status === k ? "on" : "", onclick: () => { status = k; page = 0; renderTabs(); load(); } }, l)));
    const load = async () => {
      const items = await GET("/payments" + q({ status, search: search.value.trim(), page }));
      body.replaceChildren(table(["الطلب", "العميل", "المبلغ", "الوسيلة", "رقم العملية", "الحالة", "التاريخ"], items.map((p) => h("tr", { class: "click", onclick: () => paymentModal(p.id, load) },
        h("td", { class: "mono" }, p.order_ref), h("td", null, h("span", { class: "num" }, p.customer_id), p.username ? h("div", { class: "small muted" }, "@" + p.username) : null),
        h("td", null, cur(p.amount, p.currency)), h("td", null, p.method_name), h("td", { class: "mono" }, p.txid || "—"),
        h("td", null, pill(PAY, p.status)), h("td", null, dt(p.created_at)))), "لا توجد دفعات"),
      pager(page, items.length, 50, (x) => { page = x; load(); }));
    };
    search.addEventListener("input", debounce(() => { page = 0; load(); }, 400));
    renderTabs();
    mainEl.replaceChildren(h("div", { class: "notice warn" }, "لا توافق على أي دفعة قبل التأكد من وصول المبلغ فعلياً في حسابك ومطابقة المبلغ ورقم العملية. عند القبول تُسلَّم المزارع للعميل تلقائياً."),
      h("div", { class: "card" }, h("div", { class: "card-h" }, tabs, h("span", { style: "flex:1" }), search), body));
    await load();
  };
  async function paymentModal(id, reload) {
    const p = await GET("/payments/" + id);
    const reason = h("input", { type: "text", placeholder: "سبب الرفض — يظهر للعميل" });
    const closeOrder = h("input", { type: "checkbox" });
    const quick = ["لم يصل المبلغ", "المبلغ لا يطابق الطلب", "الإثبات غير واضح أو غير صحيح", "رقم العملية غير صحيح"];
    const acts = p.status === "pending" ? h("div", { class: "stack" },
      h("button", { class: "btn primary", onclick: async () => { if (!(await confirmBox(`تأكيد وصول ${money(p.amount)} ${p.currency}؟ سيتم تسليم المزارع للعميل فوراً.`))) return;
        await run(() => POST(`/payments/${id}/approve`), "تم قبول الدفع وتسليم الطلب"); m.close(); reload(); refreshCounts(); } }, "قبول الدفع وتسليم الطلب"),
      h("div", { class: "card", style: "padding:12px" }, field("سبب الرفض", reason), h("div", { class: "btn-row", style: "margin-bottom:10px" }, quick.map((x) => h("button", { class: "btn sm", onclick: () => { reason.value = x; } }, x))),
        h("label", { class: "switch f" }, closeOrder, "رفض الطلب بالكامل وإلغاء الحجز (بدلاً من السماح بإرسال إثبات جديد)"),
        h("button", { class: "btn danger", onclick: async () => { await run(() => POST(`/payments/${id}/reject`, { reason: reason.value, close_order: closeOrder.checked }), "تم الرفض"); m.close(); reload(); refreshCounts(); } }, "رفض"))) : null;
    const m = modal(`دفعة الطلب ${p.order_ref}`, h("div", { class: "grid two" },
      h("div", null, p.proof_file_id ? h("img", { class: "proof", src: `/api/payments/${id}/proof`, alt: "إثبات الدفع", onerror: (e) => e.target.replaceWith(h("div", { class: "notice warn" }, "تعذر تحميل الصورة.")) }) : h("div", { class: "empty" }, "لا توجد صورة")),
      h("div", { class: "stack" }, h("dl", { class: "kv" }, h("dt", null, "الحالة"), h("dd", null, pill(PAY, p.status)), h("dt", null, "حالة الطلب"), h("dd", null, pill(ORDER, p.order_status)),
        h("dt", null, "العميل"), h("dd", null, h("a", { href: "#/chat/" + p.customer_id }, String(p.customer_id)), p.username ? " @" + p.username : ""),
        h("dt", null, "المبلغ"), h("dd", null, cur(p.amount, p.currency)), h("dt", null, "الوسيلة"), h("dd", null, `${p.method_name} (${p.account})`),
        h("dt", null, "رقم العملية"), h("dd", { class: "mono" }, p.txid || "—"), h("dt", null, "الطلب"), h("dd", null, `${specLine(p.offer)} × ${p.quantity}`),
        p.reviewed_by ? [h("dt", null, "روجع بواسطة"), h("dd", null, `${p.reviewed_by} — ${dt(p.reviewed_at)}`)] : null,
        p.reject_reason ? [h("dt", null, "سبب الرفض"), h("dd", null, p.reject_reason)] : null), acts)), { wide: true });
  }

  // ============================================================== orders
  ROUTES.orders = async (initial) => {
    setTitle("الطلبات");
    let status = initial || "", page = 0;
    const search = h("input", { type: "search", placeholder: "رقم الطلب أو رقم العميل", dir: "auto", style: "max-width:240px" });
    const sel = h("select", { style: "max-width:220px" }, h("option", { value: "" }, "كل الحالات"), Object.entries(ORDER).map(([k, [l]]) => h("option", { value: k }, l)));
    sel.value = status;
    const body = h("div");
    const load = async () => {
      const items = await GET("/orders" + q({ status, search: search.value.trim(), page }));
      body.replaceChildren(table(["الطلب", "العميل", "المزرعة", "الكمية", "الإجمالي", "الحالة", "التاريخ"], items.map((o) => h("tr", { class: "click", onclick: () => (location.hash = "#/order/" + o.id) },
        h("td", { class: "mono" }, o.ref), h("td", null, h("span", { class: "num" }, o.customer_id), o.username ? h("div", { class: "small muted" }, "@" + o.username) : null),
        h("td", { class: "small" }, specLine(o.offer)), h("td", { class: "num" }, o.quantity), h("td", null, cur(o.total, o.currency)),
        h("td", null, pill(ORDER, o.status), o.failure_reason ? h("div", { class: "small", style: "color:var(--danger)" }, "فشل التسليم") : null), h("td", null, dt(o.created_at)))), "لا توجد طلبات"),
      pager(page, items.length, 50, (x) => { page = x; load(); }));
    };
    sel.addEventListener("change", () => { status = sel.value; page = 0; load(); });
    search.addEventListener("input", debounce(() => { page = 0; load(); }, 400));
    mainEl.replaceChildren(h("div", { class: "card" }, h("div", { class: "card-h" }, h("div", { class: "filters", style: "flex:1" }, sel, search)), body));
    await load();
  };

  ROUTES.order = async (id) => {
    const o = await GET("/orders/" + id);
    setTitle(`الطلب ${o.ref}`);
    const acts = h("div", { class: "btn-row" });
    const reasonAct = (label, path, cls) => h("button", { class: "btn " + cls, onclick: async () => {
      const r = prompt("السبب (يظهر للعميل):"); if (!r) return;
      await run(() => POST(`/orders/${id}/${path}`, { reason: r }), "تم"); ROUTES.order(id); } }, label);
    if (["pending_confirmation", "awaiting_payment", "proof_received", "payment_review", "payment_confirmed"].includes(o.status)) {
      acts.append(reasonAct("إلغاء الطلب", "cancel", "danger"), reasonAct("رفض الطلب", "reject", "danger"));
    }
    if (["payment_confirmed", "processing", "delivered"].includes(o.status)) {
      acts.append(h("button", { class: "btn", onclick: async () => { const r = await run(() => POST(`/orders/${id}/redeliver`)); toast(r.delivered ? "تم إرسال البيانات" : "فشل الإرسال", !r.delivered); ROUTES.order(id); } },
        o.status === "delivered" ? "إعادة إرسال البيانات للعميل" : "تسليم / إعادة محاولة التسليم"));
    }
    const msg = h("input", { type: "text", placeholder: "رسالة مخصصة للعميل (اختياري)" });
    acts.append(h("button", { class: "btn", onclick: async () => { await run(() => POST(`/orders/${id}/notify`, { text: msg.value }), "تم إرسال الإشعار"); msg.value = ""; } }, "إرسال إشعار بالحالة للعميل"));
    mainEl.replaceChildren(
      h("div", { class: "btn-row" }, h("a", { class: "btn sm", href: "#/orders" }, "→ الطلبات"), h("a", { class: "btn sm", href: "#/chat/" + o.customer_id }, "محادثة العميل")),
      h("div", { class: "grid kpis" }, kpi("الحالة", ORDER[o.status][0]), kpi("الإجمالي", money(o.total), o.currency), kpi("الكمية", o.quantity, `سعر الوحدة ${money(o.unit_price)}`),
        kpi("العميل", o.customer_id, o.username ? "@" + o.username : (o.first_name || ""))),
      o.failure_reason ? h("div", { class: "notice danger" }, o.failure_reason) : null,
      o.reason ? h("div", { class: "notice" }, "السبب: " + o.reason) : null,
      h("div", { class: "card" }, h("div", { class: "card-b stack" }, h("dl", { class: "kv" },
        h("dt", null, "المزرعة"), h("dd", null, `${o.offer.name} — ${specLine(o.offer)}`),
        h("dt", null, "الوسيلة"), h("dd", null, o.method_name || "—"),
        h("dt", null, "محجوز حتى"), h("dd", null, dt(o.reserved_until)), h("dt", null, "أُنشئ"), h("dd", null, dt(o.created_at)),
        h("dt", null, "أُكّد"), h("dd", null, dt(o.confirmed_at)), h("dt", null, "دُفع"), h("dd", null, dt(o.paid_at)), h("dt", null, "سُلّم"), h("dd", null, dt(o.delivered_at))),
        msg, acts)),
      h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "المزارع المرتبطة")),
        table(["#", "Token ID (مخفي)", "السعر", "التكلفة", "حالة المزرعة", "نشطة في الطلب"], o.items.map((i) => h("tr", null, h("td", { class: "num" }, i.farm_id), h("td", { class: "mono" }, i.token_hint),
          h("td", null, money(i.price)), h("td", null, i.cost == null ? "—" : money(i.cost)), h("td", null, pill(FARM, i.status)), h("td", null, i.active ? "نعم" : "لا"))), "لم تُحجز مزارع بعد")),
      h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "الدفعات")),
        table(["#", "المبلغ", "الوسيلة", "رقم العملية", "الحالة", "سبب الرفض"], o.payments.map((p) => h("tr", { class: "click", onclick: () => paymentModal(p.id, () => ROUTES.order(id)) },
          h("td", { class: "num" }, p.id), h("td", null, cur(p.amount, p.currency)), h("td", null, p.method_name), h("td", { class: "mono" }, p.txid || "—"), h("td", null, pill(PAY, p.status)), h("td", { class: "small" }, p.reject_reason || ""))), "لا توجد دفعات")),
      h("p", { class: "small muted" }, "Token ID وكلمة المرور لا تُعرض في اللوحة — تصل للعميل فقط بعد تأكيد الدفع."));
  };

  // =============================================================== farms
  ROUTES.farms = async () => {
    setTitle("المزارع والمخزون");
    let status = "available", page = 0;
    const selected = new Set();
    const f = { min_level: h("input", { type: "text", placeholder: "أقل مستوى", dir: "ltr", inputmode: "numeric" }), max_level: h("input", { type: "text", placeholder: "أعلى مستوى", dir: "ltr", inputmode: "numeric" }),
      min_price: h("input", { type: "text", placeholder: "أقل سعر", dir: "ltr" }), max_price: h("input", { type: "text", placeholder: "أعلى سعر", dir: "ltr" }),
      search: h("input", { type: "search", placeholder: "رقم أو اسم أو Token ID كامل", dir: "auto" }) };
    const tabs = h("div", { class: "tabs" });
    const body = h("div"), bulk = h("div", { class: "btn-row" });
    const summary = await GET("/farms/summary");
    const renderTabs = () => tabs.replaceChildren(...[["available", `متوفرة (${summary.stock.available})`], ["reserved", `محجوزة (${summary.stock.reserved})`], ["sold", `مباعة (${summary.stock.sold})`], ["disabled", `معطلة (${summary.stock.disabled})`], ["", "الكل"]]
      .map(([k, l]) => h("button", { class: status === k ? "on" : "", onclick: () => { status = k; page = 0; selected.clear(); renderTabs(); load(); } }, l)));
    const renderBulk = () => {
      bulk.replaceChildren();
      if (!can("catalog") || !selected.size) return;
      const act = async (action) => { const r = await run(() => POST("/farms/bulk", { ids: [...selected], action })); toast(`تم: ${r.done}` + (r.skipped ? ` — تخطي ${r.skipped} (مرتبطة بطلبات)` : "")); selected.clear(); route(); };
      bulk.append(h("span", { class: "muted small" }, `محدد: ${selected.size}`), h("button", { class: "btn sm", onclick: () => act("disable") }, "تعطيل"), h("button", { class: "btn sm", onclick: () => act("enable") }, "تفعيل"),
        h("button", { class: "btn sm danger", onclick: async () => { if (await confirmBox(`حذف ${selected.size} مزرعة؟ لا يمكن حذف المرتبطة بطلبات.`, { danger: true })) act("delete"); } }, "حذف"));
    };
    const load = async () => {
      const items = await GET("/farms" + q({ status, page, ...Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value.trim()])) }));
      const editable = (x) => ["available", "disabled"].includes(x.status);
      body.replaceChildren(table(["", "#", "الاسم", "المستوى", "مخزن", "صومعة", "أدوات", "السعر", "التكلفة", "Token ID", "الحالة", "الطلب", ""], items.map((x) => h("tr", null,
        h("td", null, can("catalog") && editable(x) ? h("input", { type: "checkbox", checked: selected.has(x.id), onchange: (e) => { e.target.checked ? selected.add(x.id) : selected.delete(x.id); renderBulk(); } }) : ""),
        h("td", { class: "num" }, x.id), h("td", null, x.name), h("td", { class: "num" }, x.lvl), h("td", { class: "num" }, x.barn), h("td", { class: "num" }, x.silo), h("td", null, toolTxt(x)),
        h("td", null, cur(x.price, x.currency)), h("td", null, x.cost == null ? "—" : money(x.cost)), h("td", { class: "mono" }, x.token_hint), h("td", null, pill(FARM, x.status)),
        h("td", { class: "mono" }, x.order_ref || "—"),
        h("td", null, can("catalog") && editable(x) ? h("div", { class: "btn-row", style: "flex-wrap:nowrap" }, h("button", { class: "btn sm", onclick: () => farmForm(x) }, "تعديل"),
          h("button", { class: "btn sm danger", onclick: async () => { if (await confirmBox("حذف هذه المزرعة نهائياً؟", { danger: true })) { await run(() => api("DELETE", "/farms/" + x.id), "تم الحذف"); route(); } } }, "حذف")) : ""))),
        "لا توجد مزارع"), pager(page, items.length, 50, (p) => { page = p; load(); }));
      renderBulk();
    };
    Object.values(f).forEach((i) => i.addEventListener("input", debounce(() => { page = 0; load(); }, 400)));
    renderTabs();
    mainEl.replaceChildren(
      h("div", { class: "btn-row" }, can("catalog") ? h("button", { class: "btn primary", onclick: () => farmForm() }, "＋ مزرعة واحدة") : null,
        can("catalog") ? h("button", { class: "btn", onclick: importModal }, "إضافة مجموعة / استيراد CSV") : null),
      h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "العروض المتوفرة كما يراها البوت")),
        table(["الاسم", "المستوى", "مخزن", "صومعة", "الأدوات", "السعر", "المتوفر"], summary.offers.map((o) => h("tr", null, h("td", null, o.name), h("td", { class: "num" }, o.lvl), h("td", { class: "num" }, o.barn), h("td", { class: "num" }, o.silo), h("td", null, toolTxt(o)), h("td", null, cur(o.price, o.currency)), h("td", { class: "num" }, o.available))), "لا يوجد مخزون متوفر")),
      h("div", { class: "card" }, h("div", { class: "card-h" }, tabs), h("div", { class: "card-b" }, h("div", { class: "filters" }, Object.values(f)), h("div", { style: "margin-top:10px" }, bulk)), body));
    await load();
  };

  function farmFields(x) {
    const i = { name: h("input", { type: "text", value: x?.name || "" }), lvl: h("input", { type: "number", min: 1, value: x?.lvl ?? "", dir: "ltr" }),
      barn: h("input", { type: "number", min: 0, value: x?.barn ?? 0, dir: "ltr" }), silo: h("input", { type: "number", min: 0, value: x?.silo ?? 0, dir: "ltr" }),
      tools: h("input", { type: "number", min: 0, value: x?.tools ?? 0, dir: "ltr" }),
      tool_type: h("select", null, h("option", { value: "land" }, "أدوات أرض"), h("option", { value: "barn" }, "أدوات حظيرة"), h("option", { value: "silo" }, "أدوات صومعة")), price: h("input", { type: "text", inputmode: "decimal", value: x?.price ?? "", dir: "ltr" }),
      currency: h("input", { type: "text", value: x?.currency || "USDT", dir: "ltr" }), cost: h("input", { type: "text", inputmode: "decimal", value: x?.cost ?? "", dir: "ltr", placeholder: "اختياري — لحساب الربح" }),
      description: h("textarea", { style: "min-height:60px" }) };
    i.description.value = x?.description || ""; i.tool_type.value = x?.tool_type || "land";
    const grid = h("div", null, field("الاسم", i.name), h("div", { class: "form-grid" }, field("المستوى", i.lvl), field("المخزن", i.barn), field("الصومعة", i.silo), field("نوع الأدوات", i.tool_type), field("عدد الأدوات", i.tools),
      field("السعر", i.price), field("العملة", i.currency), field("التكلفة (للأرباح)", i.cost)), field("الوصف (يراه البوت ويذكره للعميل)", i.description));
    const values = () => ({ name: i.name.value, lvl: i.lvl.value, barn: i.barn.value, silo: i.silo.value, tools: i.tools.value, tool_type: i.tool_type.value, price: i.price.value, currency: i.currency.value, cost: i.cost.value, description: i.description.value });
    return { grid, values };
  }

  function farmForm(x) {
    const { grid, values } = farmFields(x);
    const tok = h("input", { type: "text", dir: "ltr", autocomplete: "off", placeholder: x ? "اتركه فارغاً لعدم التغيير" : "" });
    const pw = h("input", { type: "text", dir: "ltr", autocomplete: "off", placeholder: x ? "اتركه فارغاً لعدم التغيير" : "" });
    const st = h("select", null, h("option", { value: "available" }, "متوفرة"), h("option", { value: "disabled" }, "معطلة")); st.value = x?.status || "available";
    const form = h("form", null, grid, h("div", { class: "form-grid" }, field("Token ID", tok), field("كلمة المرور", pw)), x ? field("الحالة", st) : null,
      h("p", { class: "small muted" }, "تُشفّر Token ID وكلمة المرور فوراً ولا تُعرض مرة أخرى في اللوحة."), h("button", { class: "btn primary", type: "submit" }, x ? "حفظ" : "إضافة"));
    const m = modal(x ? `تعديل المزرعة #${x.id}` : "مزرعة جديدة", form, { wide: true });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = values();
      if (tok.value.trim()) body.token_id = tok.value.trim();
      if (pw.value.trim()) body.password = pw.value.trim();
      if (x) body.status = st.value;
      await run(() => x ? api("PATCH", "/farms/" + x.id, body) : POST("/farms", body), "تم الحفظ");
      m.close(); route();
    });
  }

  function importModal() {
    let mode = "text";
    const { grid, values } = farmFields(null);
    const ta = h("textarea", { dir: "ltr", placeholder: "ID: 24-40798340\nPassword: كلمة_المرور\n\nID: 24-40798341\nPassword: كلمة_المرور", autocomplete: "off", spellcheck: "false", style: "min-height:160px" });
    const file = h("input", { type: "file", accept: ".csv,text/csv" });
    const report = h("div"), box = h("div"), tabs = h("div", { class: "tabs" });
    const renderMode = () => {
      tabs.replaceChildren(h("button", { class: mode === "text" ? "on" : "", onclick: () => { mode = "text"; renderMode(); } }, "مجموعة بنفس المواصفات"),
        h("button", { class: mode === "csv" ? "on" : "", onclick: () => { mode = "csv"; renderMode(); } }, "ملف CSV"));
      box.replaceChildren(...(mode === "text" ? [h("p", { class: "small muted" }, "املأ المواصفات المشتركة مرة واحدة، ثم الصق المزارع بصيغة ID: … / Password: … (سطرين لكل مزرعة)، أو كل مزرعة في سطر: TokenID:كلمة المرور"), grid, field("المزارع", ta)]
        : [h("p", { class: "small muted" }, "صف العناوين مطلوب: name,lvl,barn,silo,tools,tool_type,price,currency,token_id,password,cost,description — tool_type: land أو barn أو silo (الأعمدة الأساسية: lvl, price, token_id, password)"), file]));
      report.replaceChildren();
    };
    const send = (preview) => {
      if (mode === "text") return POST("/farms/import-text", { text: ta.value, defaults: values(), preview });
      if (!file.files[0]) throw new ApiError("اختر ملفاً.");
      const fd = new FormData(); fd.append("file", file.files[0]);
      return api("POST", `/farms/import?preview=${preview}`, fd, true);
    };
    const issues = (r) => { const all = [...r.errors, ...r.duplicates_in_file, ...r.duplicates_in_db]; return all.length ? h("ul", { class: "list-issues" }, all.slice(0, 300).map((x) => h("li", null, x))) : null; };
    const check = async () => { const r = await run(() => send(true));
      report.replaceChildren(h("div", { class: "notice " + (r.valid ? "" : "warn") }, `صالح: ${r.valid} · أخطاء: ${r.errors.length} · مكرر بالملف: ${r.duplicates_in_file.length} · موجود مسبقاً: ${r.duplicates_in_db.length}`), issues(r),
        r.valid ? h("button", { class: "btn primary", style: "margin-top:10px", onclick: save }, `حفظ ${r.valid} مزرعة`) : null); };
    const save = async () => { const r = await run(() => send(false)); toast(`تمت إضافة ${r.inserted} مزرعة`); m.close(); route(); };
    renderMode();
    const m = modal("إضافة مزارع", h("div", { class: "stack" }, tabs, box, h("button", { class: "btn", onclick: check }, "فحص قبل الحفظ"), report), { wide: true });
  }

  // ============================================================= methods
  ROUTES.methods = async () => {
    setTitle("وسائل الدفع");
    const items = await GET("/methods");
    const form = (x) => {
      const i = { name: h("input", { type: "text", value: x?.name || "" }), kind: h("select", null, h("option", { value: "binance_pay" }, "Binance Pay"), h("option", { value: "manual" }, "تحويل يدوي"), h("option", { value: "other" }, "أخرى")),
        account: h("input", { type: "text", dir: "ltr", value: x?.account || "" }), currency: h("input", { type: "text", dir: "ltr", value: x?.currency || "USDT" }),
        instructions: h("textarea"), require_txid: h("input", { type: "checkbox", checked: x ? x.require_txid : false }), is_active: h("input", { type: "checkbox", checked: x ? x.is_active : true }),
        sort_order: h("input", { type: "number", value: x?.sort_order ?? 0, dir: "ltr" }) };
      i.kind.value = x?.kind || "binance_pay"; i.instructions.value = x?.instructions || "";
      const f = h("form", null, field("الاسم الظاهر للعميل", i.name), h("div", { class: "form-grid" }, field("النوع", i.kind), field("العملة", i.currency), field("الترتيب", i.sort_order)),
        field("المعرّف / رقم الحساب (Pay ID، محفظة، حساب)", i.account), field("تعليمات الدفع", i.instructions),
        h("label", { class: "switch f" }, i.require_txid, "طلب رقم العملية من العميل بعد الصورة"), h("label", { class: "switch f" }, i.is_active, "مفعّلة"),
        h("button", { class: "btn primary", type: "submit" }, "حفظ"));
      const m = modal(x ? "تعديل وسيلة الدفع" : "وسيلة دفع جديدة", f);
      f.addEventListener("submit", async (e) => { e.preventDefault();
        const body = Object.fromEntries(Object.entries(i).map(([k, el]) => [k, el.type === "checkbox" ? el.checked : el.value]));
        await run(() => x ? api("PATCH", "/methods/" + x.id, body) : POST("/methods", body), "تم الحفظ"); m.close(); route(); });
    };
    mainEl.replaceChildren(h("div", { class: "notice" }, "يمكنك إضافة أكثر من وسيلة، وأكثر من معرّف لنفس النوع (مثلاً حسابا Binance Pay). يرى العميل الوسائل المفعّلة بنفس عملة طلبه بعد تأكيد الطلب."),
      h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "الوسائل"), h("span", { style: "flex:1" }), can("methods") ? h("button", { class: "btn primary", onclick: () => form() }, "＋ وسيلة جديدة") : null),
        table(["الاسم", "النوع", "المعرّف", "العملة", "رقم العملية", "الحالة", ""], items.map((x) => h("tr", null, h("td", null, x.name), h("td", null, { binance_pay: "Binance Pay", manual: "تحويل يدوي", other: "أخرى" }[x.kind]),
          h("td", { class: "mono" }, x.account), h("td", null, x.currency), h("td", null, x.require_txid ? "مطلوب" : "—"), h("td", null, x.is_active ? h("span", { class: "pill ok" }, "مفعّلة") : h("span", { class: "pill" }, "معطلة")),
          h("td", null, can("methods") ? h("div", { class: "btn-row", style: "flex-wrap:nowrap" }, h("button", { class: "btn sm", onclick: () => form(x) }, "تعديل"),
            h("button", { class: "btn sm danger", onclick: async () => { if (await confirmBox("حذف الوسيلة؟", { danger: true })) { await run(() => api("DELETE", "/methods/" + x.id), "تم الحذف"); route(); } } }, "حذف")) : ""))), "لا توجد وسائل")));
  };

  // ============================================================ settings
  ROUTES.settings = async () => {
    setTitle("الإعدادات والذكاء الاصطناعي");
    const items = await GET("/settings");
    const inputs = {};
    const groups = { "الذكاء الاصطناعي": ["ai_enabled", "welcome_text", "ai_instructions", "handoff_text"],
      "معلومات المتجر التي يعتمد عليها البوت": ["store_name", "store_info", "warranty_policy", "delivery_policy", "payment_policy", "extra_faq"],
      "قواعد الطلبات": ["reservation_minutes", "max_quantity", "max_open_orders"] };
    const byKey = Object.fromEntries(items.map((i) => [i.key, i]));
    const cards = Object.entries(groups).map(([title, keys]) => h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, title)), h("div", { class: "card-b" },
      keys.filter((k) => byKey[k]).map((k) => { const s = byKey[k]; let el;
        if (s.kind === "bool") { el = h("input", { type: "checkbox", checked: s.value === "true" }); inputs[k] = el; return h("label", { class: "switch f" }, el, s.label); }
        el = s.kind === "longtext" ? h("textarea") : h("input", { type: "text", dir: s.kind === "int" ? "ltr" : "auto" }); el.value = s.value; inputs[k] = el; return field(s.label, el); }))));
    mainEl.replaceChildren(
      state.me.ai_configured ? h("div", { class: "notice" }, "البوت يجيب فقط من بيانات المخزون والطلبات الحقيقية ومن النصوص أدناه. لا يستطيع تغيير الأسعار أو تأكيد الدفع.")
        : h("div", { class: "notice" }, "يعمل المساعد المجاني المدمج (بدون اشتراك). رسالة الترحيب ونصوص الدعم أدناه تُستخدم كما هي؛ تعليمات الذكاء الاصطناعي لا تُستخدم إلا عند إضافة مفتاح Claude."),
      ...cards, h("div", { class: "btn-row" }, h("button", { class: "btn primary", onclick: async () => {
        const body = {}; for (const [k, el] of Object.entries(inputs)) body[k] = el.type === "checkbox" ? el.checked : el.value;
        await run(() => api("PUT", "/settings", body), "تم الحفظ — يُطبق فوراً"); } }, "حفظ الإعدادات")));
  };

  // ================================================================ codes
  ROUTES.codes = async () => {
    setTitle("أكواد العملاء");
    let page = 0;
    const search = h("input", { type: "search", placeholder: "بحث بالاسم أو الكود", dir: "auto", style: "max-width:260px" });
    const body = h("div");
    const name = h("input", { type: "text", placeholder: "اسم العميل (اختياري)" });
    const count = h("input", { type: "number", min: 1, max: 200, value: 1, dir: "ltr", style: "max-width:110px" });
    const notes = h("input", { type: "text", placeholder: "ملاحظة (اختياري)" });
    const created = h("div");
    const create = async () => {
      const r = await run(() => POST("/codes", { name: name.value, count: count.value, notes: notes.value }), "تم إنشاء الأكواد");
      const text = r.map((c) => c.access_code + (c.first_name ? " — " + c.first_name : "")).join("\n");
      created.replaceChildren(h("div", { class: "notice" }, h("pre", { class: "mono", style: "margin:0;white-space:pre-wrap" }, text),
        h("button", { class: "btn sm", style: "margin-top:8px", onclick: () => { navigator.clipboard.writeText(r.map((c) => c.access_code).join("\n")); toast("تم النسخ"); } }, "نسخ الأكواد")));
      name.value = ""; notes.value = ""; count.value = 1; load();
    };
    const load = async () => {
      const items = await GET("/customers" + q({ q: search.value.trim(), page }));
      body.replaceChildren(table(["العميل", "الكود", "الجهاز", "الحالة", "المشتريات", "آخر نشاط", ""], items.map((c) => h("tr", null,
        h("td", null, h("a", { href: "#/chat/" + c.id }, c.first_name || "عميل #" + c.id), c.notes ? h("div", { class: "small muted" }, c.notes) : null),
        h("td", null, h("span", { class: "mono" }, c.access_code || "—"), c.access_code ? h("button", { class: "btn sm", style: "margin-inline-start:6px", onclick: () => { navigator.clipboard.writeText(c.access_code); toast("تم النسخ"); } }, "نسخ") : null),
        h("td", { class: "small" }, c.device_id ? (c.device_label || "مربوط") : h("span", { class: "muted" }, "لم يُستخدم")),
        h("td", null, !c.code_active ? h("span", { class: "pill danger" }, "موقوف") : c.device_id ? h("span", { class: "pill ok" }, "مفعّل") : h("span", { class: "pill" }, "جديد")),
        h("td", null, `${c.delivered_orders} · `, h("span", { class: "num" }, money(c.spent))),
        h("td", null, dt(c.last_seen_at)),
        h("td", null, h("div", { class: "btn-row", style: "flex-wrap:nowrap" },
          c.device_id ? h("button", { class: "btn sm", onclick: async () => { if (await confirmBox("فك ربط الجهاز؟ سيخرج العميل ويمكنه الدخول بنفس الكود من جهاز جديد.")) { await run(() => POST(`/customers/${c.id}/reset-device`), "تم فك الربط"); load(); } } }, "فك الجهاز") : null,
          h("button", { class: "btn sm " + (c.code_active ? "danger" : ""), onclick: async () => { await run(() => POST(`/customers/${c.id}/code`, { active: !c.code_active }), c.code_active ? "تم إيقاف الكود" : "تم تفعيل الكود"); load(); } }, c.code_active ? "إيقاف" : "تفعيل"))))),
        "لا توجد أكواد بعد"), pager(page, items.length, 50, (p) => { page = p; load(); }));
    };
    search.addEventListener("input", debounce(() => { page = 0; load(); }, 400));
    mainEl.replaceChildren(
      h("div", { class: "notice" }, "كل عميل يدخل التطبيق بكود يبدأ بـ HD-. الكود يُربط بأول جهاز يدخل منه ولا يعمل على جهاز آخر حتى تفك الربط. رابط التطبيق: ", h("b", { class: "mono" }, location.origin + "/"), " — وملف أندرويد: ", h("a", { href: "/download" }, location.origin + "/download")),
      can("customers") ? h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "إنشاء أكواد")), h("div", { class: "card-b stack" },
        h("div", { class: "form-grid" }, field("الاسم", name), field("العدد", count), field("ملاحظة", notes)),
        h("div", null, h("button", { class: "btn primary", onclick: create }, "إنشاء")), created)) : null,
      h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "العملاء والأكواد"), h("span", { style: "flex:1" }), search), body));
    await load();
  };

  // ============================================================ alerts
  ROUTES.alerts = async () => {
    setTitle("التنبيهات");
    const items = await GET("/alerts");
    mainEl.replaceChildren(h("div", { class: "btn-row" }, h("button", { class: "btn", onclick: async () => { await run(() => POST("/alerts/read"), "تم"); refreshCounts(); route(); } }, "تعليم الكل كمقروء")),
      h("div", { class: "card" }, table(["", "التنبيه", "النوع", "الوقت"], items.map((a) => h("tr", null,
        h("td", null, a.is_read ? "" : h("span", { class: "badge" }, "جديد")), h("td", { class: "wrap" }, a.message),
        h("td", null, pill({ error: ["خطأ", "danger"], warning: ["تحذير", "warn"], info: ["معلومة", "info"] }, a.level)), h("td", null, dt(a.created_at)))))));
  };

  // ============================================================ admins
  ROUTES.admins = async () => {
    setTitle("المشرفون والصلاحيات");
    const r = await GET("/admins");
    const roleSel = (v) => { const s = h("select", null, Object.entries(r.roles).map(([k, l]) => h("option", { value: k }, l))); s.value = v || "admin"; return s; };
    const add = () => {
      const i = { username: h("input", { type: "text", dir: "ltr", autocomplete: "off" }), password: h("input", { type: "password", dir: "ltr", autocomplete: "new-password" }),
        telegram_id: h("input", { type: "text", dir: "ltr", inputmode: "numeric", placeholder: "لتفعيل رمز الدخول والإشعارات" }), role: roleSel() };
      const form = h("form", null, field("اسم المستخدم", i.username), field("كلمة المرور (10+ أحرف، كبيرة وصغيرة ورقم)", i.password), field("Telegram User ID", i.telegram_id), field("الدور", i.role),
        h("button", { class: "btn primary", type: "submit" }, "إضافة"));
      const m = modal("مشرف جديد", form);
      form.addEventListener("submit", async (e) => { e.preventDefault(); await run(() => POST("/admins", { username: i.username.value, password: i.password.value, telegram_id: i.telegram_id.value.trim() || null, role: i.role.value }), "تمت الإضافة"); m.close(); route(); });
    };
    const edit = (a) => {
      const i = { role: roleSel(a.role), telegram_id: h("input", { type: "text", dir: "ltr", value: a.telegram_id ?? "" }), is_active: h("input", { type: "checkbox", checked: a.is_active }),
        password: h("input", { type: "password", dir: "ltr", autocomplete: "new-password", placeholder: "اتركها فارغة لعدم التغيير" }) };
      const form = h("form", null, field("الدور", i.role), field("Telegram User ID", i.telegram_id), field("كلمة مرور جديدة", i.password), h("label", { class: "switch f" }, i.is_active, "الحساب نشط"),
        h("p", { class: "small muted" }, "أي تعديل يُنهي جلسات هذا المشرف المفتوحة."), h("button", { class: "btn primary", type: "submit" }, "حفظ"));
      const m = modal("تعديل " + a.username, form);
      form.addEventListener("submit", async (e) => { e.preventDefault(); const body = { role: i.role.value, telegram_id: i.telegram_id.value.trim() || null, is_active: i.is_active.checked }; if (i.password.value) body.password = i.password.value;
        await run(() => api("PATCH", "/admins/" + a.id, body), "تم الحفظ"); m.close(); route(); });
    };
    mainEl.replaceChildren(
      h("div", { class: "notice" }, "الصلاحيات: المالك = كل شيء · المشرف = المخزون والطلبات والشحن والأرصدة والإعدادات · الدعم الفني = عرض ومراجعة الشحن والطلبات فقط."),
      r.env_owners.length ? h("div", { class: "notice" }, "مالكون عبر متغير البيئة OWNER_TELEGRAM_IDS (في البوت): ", h("span", { class: "mono" }, r.env_owners.join(", "))) : null,
      h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "حسابات اللوحة"), h("span", { style: "flex:1" }), h("button", { class: "btn primary", onclick: add }, "＋ مشرف جديد")),
        table(["المستخدم", "الدور", "Telegram ID", "الحالة", "آخر دخول", ""], r.admins.map((a) => h("tr", null, h("td", { class: "mono" }, a.username), h("td", null, r.roles[a.role]),
          h("td", { class: "mono" }, a.telegram_id ?? "—"), h("td", null, a.is_active ? h("span", { class: "pill ok" }, "نشط") : h("span", { class: "pill" }, "معطّل")), h("td", null, dt(a.last_login_at)),
          h("td", null, h("button", { class: "btn sm", onclick: () => edit(a) }, "تعديل")))))));
  };

  // ============================================================= audit
  ROUTES.audit = async () => {
    setTitle("سجل نشاط الإدارة");
    let page = 0;
    const actor = h("input", { type: "search", placeholder: "المنفّذ (web:… / tg:…)", dir: "ltr" });
    const action = h("select", null, [["", "كل العمليات"], ["deposit.", "الشحن"], ["wallet.", "الأرصدة"], ["order.", "الطلبات"], ["type.", "الأنواع"], ["account", "الحسابات"], ["settings.", "الإعدادات"], ["admin.", "المشرفون"], ["auth.", "تسجيل الدخول"], ["backup.", "النسخ الاحتياطي"], ["user.", "الحظر"]].map(([v, l]) => h("option", { value: v }, l)));
    const body = h("div");
    const load = async () => {
      const items = await GET("/audit" + q({ actor: actor.value.trim(), action: action.value, page }));
      body.replaceChildren(table(["الوقت", "المنفّذ", "العملية", "العنصر", "التفاصيل", "IP"], items.map((a) => h("tr", null, h("td", null, dt(a.created_at)), h("td", { class: "mono" }, a.actor),
        h("td", { class: "mono" }, a.action), h("td", { class: "mono" }, a.entity ? `${a.entity} #${a.entity_id ?? ""}` : "—"),
        h("td", { class: "wrap small mono" }, a.details ? JSON.stringify(a.details).slice(0, 260) : "—"), h("td", { class: "mono small" }, a.ip || "—")))),
      pager(page, items.length, 50, (p) => { page = p; load(); }));
    };
    actor.addEventListener("input", debounce(() => { page = 0; load(); }, 400));
    action.addEventListener("change", () => { page = 0; load(); });
    mainEl.replaceChildren(h("div", { class: "card" }, h("div", { class: "card-h" }, h("div", { class: "filters", style: "flex:1" }, actor, action)), body));
    await load();
  };

  // =========================================================== backups
  ROUTES.backups = async () => {
    setTitle("النسخ الاحتياطي");
    const items = await GET("/backups");
    mainEl.replaceChildren(
      h("div", { class: "notice warn" }, "احتفظ بالنسخ مع مفتاح ENCRYPTION_KEY في مكان آمن منفصل — بدون المفتاح لا يمكن فك كلمات مرور الحسابات."),
      h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "النسخ على الخادم"), h("span", { style: "flex:1" }),
        h("button", { class: "btn primary", onclick: async () => { await run(() => POST("/backups"), "تم إنشاء النسخة"); route(); } }, "＋ نسخة الآن")),
        table(["الملف", "الحجم", "التاريخ", ""], items.map((b) => h("tr", null, h("td", { class: "mono" }, b.name), h("td", { class: "num" }, (b.size / 1024).toFixed(1) + " KB"), h("td", null, dt(b.created_at)),
          h("td", null, h("a", { class: "btn sm", href: "/api/backups/" + encodeURIComponent(b.name) }, "تنزيل")))), "لا توجد نسخ بعد")));
  };

  // ============================================================ account
  ROUTES.account = async () => {
    setTitle("حسابي");
    const cur = h("input", { type: "password", autocomplete: "current-password", dir: "ltr" });
    const nw = h("input", { type: "password", autocomplete: "new-password", dir: "ltr" });
    const form = h("form", null, field("كلمة المرور الحالية", cur), field("كلمة المرور الجديدة", nw), h("button", { class: "btn primary", type: "submit" }, "تغيير كلمة المرور"));
    form.addEventListener("submit", async (e) => { e.preventDefault(); await run(() => POST("/auth/password", { current: cur.value, new: nw.value }), "تم التغيير — سجّل الدخول من جديد"); state.me = null; renderLogin(); });
    mainEl.replaceChildren(h("div", { class: "card" }, h("div", { class: "card-b" }, h("dl", { class: "kv" }, h("dt", null, "المستخدم"), h("dd", { class: "mono" }, state.me.username),
      h("dt", null, "الدور"), h("dd", null, state.me.role_label), h("dt", null, "Telegram ID"), h("dd", { class: "mono" }, state.me.telegram_id ?? "غير مربوط — اطلب من المالك ربطه لتفعيل التحقق بخطوتين")))),
      h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "تغيير كلمة المرور")), h("div", { class: "card-b" }, form)));
  };

  // -------------------------------------------------------------- boot
  let poll = null;
  async function boot() {
    try { state.me = await api("GET", "/auth/me"); } catch { return renderLogin(); }
    renderShell();
    await refreshCounts();
    route();
    clearInterval(poll);
    poll = setInterval(refreshCounts, 30000);
  }
  window.addEventListener("hashchange", route);
  boot();
})();
