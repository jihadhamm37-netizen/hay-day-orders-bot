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

  const ORDER = { pending: ["بانتظار التأكيد", ""], processing: ["قيد المعالجة", "info"], completed: ["مكتمل", "ok"],
    cancelled: ["ملغي", ""], needs_review: ["يحتاج إلى مراجعة", "danger"] };
  const DEP = { awaiting_payment: ["بانتظار الدفع", ""], under_review: ["قيد المراجعة", "warn"], approved: ["مقبول", "ok"],
    rejected: ["مرفوض", "danger"], cancelled: ["ملغي", ""] };
  const ACC = { available: ["متوفر", "ok"], reserved: ["محجوز", "warn"], sold: ["مباع", "info"], disabled: ["موقوف", ""] };
  const KIND = { deposit: "شحن رصيد", purchase: "شراء مزرعة", refund: "استرداد", admin_credit: "إضافة من الإدارة", admin_debit: "خصم من الإدارة" };
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
  const state = { me: null, counts: { deposits: 0, review: 0, alerts: 0 }, lastDeposits: null };
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
    const form = h("form", null, h("p", { class: "muted" }, "أرسلنا رمزاً من 6 أرقام إلى حسابك في تيليجرام عبر البوت."),
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
    ["dashboard", "📊", "الرئيسية", "view"],
    ["deposits", "💰", "طلبات الشحن", "deposits", "deposits"],
    ["orders", "🧾", "الطلبات", "orders", "review"],
    ["types", "📦", "الأنواع والمخزون", "view"],
    ["users", "👥", "المستخدمون والأرصدة", "users"],
    ["transactions", "💼", "الحركات المالية", "users"],
    ["alerts", "🔔", "التنبيهات", "view", "alerts"],
    ["-"],
    ["settings", "⚙️", "الإعدادات والرسائل", "settings"],
    ["admins", "🛡️", "المشرفون", "admins"],
    ["audit", "📜", "سجل العمليات", "view"],
    ["backups", "🗄️", "النسخ الاحتياطي", "backup"],
    ["account", "👤", "حسابي", "view"],
  ];
  let mainEl, titleEl, sideEl, navEl;

  function renderShell() {
    ROOT.innerHTML = "";
    navEl = h("nav", { class: "nav" });
    sideEl = h("aside", { class: "side" },
      h("div", { class: "brand" }, h("div", { class: "brand-mark" }, "🌾"), h("div", null, "متجر المزارع", h("small", null, "لوحة الإدارة"))),
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
      h("a", { href: "#/" + n[0], class: cur === n[0] || (cur === "type" && n[0] === "types") || (cur === "user" && n[0] === "users") ? "active" : "" },
        h("span", { class: "ico" }, n[1]), n[2], n[4] && state.counts[n[4]] ? h("span", { class: "badge" }, state.counts[n[4]]) : null)));
  }

  async function refreshCounts() {
    try {
      const s = await GET("/stats/overview");
      const prev = state.lastDeposits;
      state.counts = { deposits: s.deposits.pending_review, review: s.sales.needs_review, alerts: s.unread_alerts };
      if (prev !== null && s.deposits.pending_review > prev) toast(`💰 طلب شحن جديد بانتظار المراجعة (${s.deposits.pending_review})`);
      state.lastDeposits = s.deposits.pending_review;
      renderNav();
      document.title = (state.counts.deposits ? `(${state.counts.deposits}) ` : "") + "لوحة التحكم";
    } catch { /* ignore */ }
  }

  // ------------------------------------------------------------ router
  const ROUTES = {};
  async function route() {
    if (!state.me) return;
    toggleSide(false);
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
    const max = Math.max(1, ...days.map((d) => Math.max(+d.revenue, +d.deposits)));
    const bw = (W - P * 2) / n;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "chart"); svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "الإيرادات والشحن اليومي");
    const mk = (t, a) => { const e = document.createElementNS(svg.namespaceURI, t); for (const k in a) e.setAttribute(k, a[k]); return e; };
    days.forEach((d, i) => {
      const x = W - P - (i + 1) * bw; // right-to-left: newest on the left edge
      const rh = (H - P * 2) * (+d.revenue / max), dh = (H - P * 2) * (+d.deposits / max);
      const g = mk("g", {});
      const t = mk("title", {}); t.textContent = `${d.day}\nمبيعات: ${money(d.revenue)} (${d.sales})\nشحن: ${money(d.deposits)}`;
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

  ROUTES.dashboard = async () => {
    setTitle("نظرة عامة");
    const [s, days, top, alerts] = await Promise.all([GET("/stats/overview"), GET("/stats/daily?days=30"), GET("/stats/top-types"), GET("/alerts?unread=true")]);
    mainEl.replaceChildren(
      h("div", { class: "grid kpis" },
        kpi("إجمالي الإيرادات", money(s.sales.revenue), `${s.sales.completed} عملية بيع مكتملة`),
        kpi("مبيعات اليوم", money(s.sales.today_revenue), `${s.sales.today_count} عملية`),
        kpi("آخر 30 يوماً", money(s.sales.month_revenue), "USDT"),
        kpi("إجمالي المشحون", money(s.deposits.total_deposited), `اليوم: ${money(s.deposits.today_deposited)}`),
        kpi("شحن بانتظار المراجعة", s.deposits.pending_review, `${money(s.deposits.pending_amount)} USDT`, s.deposits.pending_review ? "warn" : ""),
        kpi("أرصدة العملاء", money(s.users.balances), `${s.users.with_balance} عميل لديهم رصيد`),
        kpi("المخزون المتوفر", s.stock.available, `قيمته ${money(s.stock.stock_value)} USDT`),
        kpi("حسابات مباعة", s.stock.sold, `محجوز ${s.stock.reserved} · موقوف ${s.stock.disabled}`),
        kpi("طلبات تحتاج مراجعة", s.sales.needs_review, "تسليم فشل أو لم يُؤكد", s.sales.needs_review ? "danger" : ""),
        kpi("أنواع نفد مخزونها", s.out_of_stock_types, "", s.out_of_stock_types ? "warn" : ""),
        kpi("المستخدمون", s.users.users, `جدد اليوم: ${s.users.new_today}`),
        kpi("تعديلات يدوية", money(s.adjustments.credits), `خصم ${money(s.adjustments.debits)} · استرداد ${money(s.adjustments.refunds)}`)),
      h("div", { class: "grid two" },
        h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "آخر 30 يوماً"), h("span", { style: "flex:1" }),
          h("div", { class: "legend" }, h("span", null, h("i", { style: "background:var(--brand)" }), "المبيعات"), h("span", null, h("i", { style: "background:var(--accent)" }), "الشحن"))),
          h("div", { class: "card-b" }, barChart(days))),
        h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "تنبيهات جديدة"), h("span", { style: "flex:1" }), h("a", { href: "#/alerts" }, "الكل")),
          alerts.length ? h("div", { class: "card-b stack" }, alerts.slice(0, 8).map(alertRow)) : h("div", { class: "empty" }, "لا توجد تنبيهات ✅"))),
      h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "الأنواع الأكثر مبيعاً")),
        table(["النوع", "LVL", "المبيعات", "الإيرادات"], top.map((t) => h("tr", { class: "click", onclick: () => (location.hash = "#/type/" + t.id) },
          h("td", null, t.name), h("td", { class: "num" }, t.lvl), h("td", { class: "num" }, t.sales), h("td", null, usdt(t.revenue)))), "لا توجد مبيعات بعد")));
  };
  function alertRow(a) {
    const cls = { error: "danger", warning: "warn", info: "" }[a.level];
    return h("div", { class: "notice " + cls }, h("div", null, a.message), h("div", { class: "small muted" }, dt(a.created_at)));
  }

  // ============================================================ alerts
  ROUTES.alerts = async () => {
    setTitle("التنبيهات");
    const items = await GET("/alerts");
    mainEl.replaceChildren(h("div", { class: "btn-row" }, h("button", { class: "btn", onclick: async () => { await run(() => POST("/alerts/read"), "تم"); refreshCounts(); route(); } }, "✔️ تعليم الكل كمقروء")),
      h("div", { class: "card" }, table(["", "التنبيه", "النوع", "الوقت"], items.map((a) => h("tr", null,
        h("td", null, a.is_read ? "" : h("span", { class: "badge" }, "جديد")), h("td", { class: "wrap" }, a.message),
        h("td", null, pill({ error: ["خطأ", "danger"], warning: ["تحذير", "warn"], info: ["معلومة", "info"] }, a.level)), h("td", null, dt(a.created_at)))))));
  };

  // ============================================================= types
  ROUTES.types = async () => {
    setTitle("أنواع المزارع والمخزون");
    const f = { lvl: h("input", { type: "text", placeholder: "LVL (مثال: >=70)", dir: "ltr" }), barn: h("input", { type: "text", placeholder: "Barn", dir: "ltr" }),
      silo: h("input", { type: "text", placeholder: "Silo", dir: "ltr" }), tools: h("input", { type: "text", placeholder: "Tools (أدوات)", dir: "ltr" }), price: h("input", { type: "text", placeholder: "السعر (مثال: <=15)", dir: "ltr" }) };
    const body = h("div");
    const load = async () => {
      const items = await GET("/types" + q({ lvl: f.lvl.value.trim(), barn: f.barn.value.trim(), silo: f.silo.value.trim(), tools: f.tools.value.trim(), price: f.price.value.trim() }));
      const tools = (t) => h("td", { onclick: (ev) => ev.stopPropagation() }, h("div", { class: "btn-row", style: "flex-wrap:nowrap" },
        h("a", { class: "btn sm", href: "#/type/" + t.id, title: "فتح وإضافة حسابات" }, "فتح"),
        can("catalog") ? h("button", { class: "btn sm", onclick: () => typeForm(t) }, "تعديل") : null,
        can("catalog") ? h("button", { class: "btn sm", onclick: async () => { await run(() => api("PATCH", "/types/" + t.id, { is_active: !t.is_active }), t.is_active ? "تم إيقاف البيع" : "تم تفعيل البيع"); load(); } }, t.is_active ? "إيقاف" : "تفعيل") : null,
        can("catalog") ? h("button", { class: "btn sm danger", onclick: () => deleteType(t, load) }, "حذف") : null));
      body.replaceChildren(table(["", "النوع", "LVL", "Barn", "Silo", "Tools", "السعر", "متوفر", "محجوز", "مباع", "موقوف", "البيع"],
        items.map((t) => h("tr", { class: "click", onclick: () => (location.hash = "#/type/" + t.id) },
          tools(t), h("td", null, h("b", null, t.name)), h("td", { class: "num" }, t.lvl), h("td", { class: "num" }, t.barn), h("td", { class: "num" }, t.silo), h("td", { class: "num" }, t.tools),
          h("td", null, usdt(t.price)), h("td", null, h("span", { class: "pill " + (t.available_raw ? "ok" : "danger") }, t.available_raw)),
          h("td", { class: "num" }, t.reserved), h("td", { class: "num" }, t.sold), h("td", { class: "num" }, t.disabled),
          h("td", null, t.is_active ? h("span", { class: "pill ok" }, "مفعّل") : h("span", { class: "pill" }, "موقوف")))), "لا توجد أنواع — أضف أول نوع"));
    };
    Object.values(f).forEach((i) => i.addEventListener("input", debounce(load, 350)));
    mainEl.replaceChildren(h("div", { class: "card" }, h("div", { class: "card-h" }, h("div", { class: "filters", style: "flex:1" }, Object.values(f)),
      can("catalog") ? h("button", { class: "btn primary", onclick: () => typeForm() }, "＋ نوع جديد") : null), body));
    await load();
  };
  function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

  async function deleteType(t, after) {
    const msg = t.total
      ? `حذف «${t.name}»؟ سيتم حذف الحسابات غير المباعة (${t.available_raw + t.disabled}) نهائياً، ويُخفى النوع من البوت واللوحة، وتبقى المزارع المباعة (${t.sold}) وطلباتها في السجل.`
      : `حذف «${t.name}» نهائياً؟ النوع فارغ.`;
    if (!(await confirmBox(msg, { danger: true, okText: "حذف" }))) return;
    const r = await run(() => api("DELETE", "/types/" + t.id));
    toast("تم حذف النوع" + (r && r.accounts_removed ? ` و${r.accounts_removed} حساب غير مباع` : ""));
    after();
  }

  function typeForm(t) {
    const i = {
      name: h("input", { type: "text", value: t?.name || "", placeholder: "اختياري — مثل: مزرعة VIP" }),
      lvl: h("input", { type: "number", min: 1, value: t?.lvl ?? "", required: true, dir: "ltr" }),
      barn: h("input", { type: "number", min: 0, value: t?.barn ?? "", required: true, dir: "ltr" }),
      silo: h("input", { type: "number", min: 0, value: t?.silo ?? "", required: true, dir: "ltr" }),
      tools: h("input", { type: "number", min: 0, value: t?.tools ?? 0, dir: "ltr" }),
      price: h("input", { type: "text", inputmode: "decimal", value: t?.price ?? "", required: true, dir: "ltr" }),
      sort_order: h("input", { type: "number", value: t?.sort_order ?? 0, dir: "ltr" }),
      description: h("textarea", { style: "min-height:70px" }), is_active: h("input", { type: "checkbox", checked: t ? t.is_active : true }),
    };
    i.description.value = t?.description || "";
    const form = h("form", null, field("الاسم", i.name), h("div", { class: "form-grid" }, field("LVL — المستوى", i.lvl), field("Barn — المخزن", i.barn),
      field("Silo — الصومعة", i.silo), field("Tools — أدوات أرض", i.tools), field("السعر USDT", i.price), field("ترتيب العرض", i.sort_order)),
      field("وصف يظهر للزبون (اختياري)", i.description), h("label", { class: "switch f" }, i.is_active, "متاح للبيع"),
      t ? h("p", { class: "small muted" }, "تغيير سعر النوع يطبق على كل حساباته عدا ما له سعر خاص.") : null,
      h("button", { class: "btn primary", type: "submit" }, t ? "حفظ التعديلات" : "إنشاء النوع"));
    const m = modal(t ? "تعديل النوع" : "نوع مزرعة جديد", form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = { name: i.name.value, lvl: i.lvl.value, barn: i.barn.value, silo: i.silo.value, tools: i.tools.value, price: i.price.value,
        sort_order: i.sort_order.value, description: i.description.value, is_active: i.is_active.checked };
      const r = await run(() => t ? api("PATCH", "/types/" + t.id, body) : POST("/types", body), "تم الحفظ");
      m.close();
      if (!t) location.hash = "#/type/" + r.id; else route();
    });
  }

  ROUTES.type = async (id) => {
    const t = await GET("/types/" + id);
    setTitle(t.name);
    const accBox = h("div");
    let status = "available", page = 0, search = "";
    const selected = new Set();
    const tabs = h("div", { class: "tabs" });
    const searchIn = h("input", { type: "search", placeholder: "بحث برقم الحساب أو ID كامل", dir: "auto", style: "max-width:260px" });
    searchIn.addEventListener("input", debounce(() => { search = searchIn.value.trim(); page = 0; loadAcc(); }, 400));
    const bulkBar = h("div", { class: "btn-row" });
    const renderTabs = () => tabs.replaceChildren(...[["available", `متوفر (${t.available_raw})`], ["reserved", `محجوز (${t.reserved})`], ["sold", `مباع (${t.sold})`], ["disabled", `موقوف (${t.disabled})`], ["", "الكل"]]
      .map(([k, l]) => h("button", { class: status === k ? "on" : "", onclick: () => { status = k; page = 0; selected.clear(); renderTabs(); loadAcc(); } }, l)));
    const renderBulk = () => {
      bulkBar.replaceChildren();
      if (!can("catalog") || !selected.size) return;
      const ids = [...selected];
      const act = async (action, extra = {}) => {
        const r = await run(() => POST("/accounts/bulk", { ids, action, ...extra }));
        toast(`تم: ${r.done}` + (r.failed.length ? ` — فشل ${r.failed.length}` : ""), !!r.failed.length);
        selected.clear(); ROUTES.type(id);
      };
      bulkBar.append(h("span", { class: "muted small" }, `محدد: ${ids.length}`),
        h("button", { class: "btn sm", onclick: () => act("disable") }, "⏸ إيقاف"), h("button", { class: "btn sm", onclick: () => act("enable") }, "▶️ إتاحة"),
        h("button", { class: "btn sm", onclick: () => { const p = prompt("السعر الخاص (اتركه فارغاً لإلغائه):"); if (p !== null) act("price", { price: p.trim() || null }); } }, "💲 سعر خاص"),
        h("button", { class: "btn sm danger", onclick: async () => { if (await confirmBox(`حذف ${ids.length} حساب؟ لا يمكن حذف المباع.`, { danger: true })) act("delete"); } }, "🗑 حذف"));
    };
    const loadAcc = async () => {
      const items = await GET("/accounts" + q({ type_id: id, status, page, search }));
      const all = h("input", { type: "checkbox", onchange: (e) => { items.forEach((a) => e.target.checked ? selected.add(a.id) : selected.delete(a.id)); loadAcc(); } });
      accBox.replaceChildren(table([can("catalog") ? all : "", "#", "ID (مخفي)", "السعر", "الحالة", "الطلب", "أُضيف", ""], items.map((a) => h("tr", null,
        h("td", null, can("catalog") && ["available", "disabled"].includes(a.status) ? h("input", { type: "checkbox", checked: selected.has(a.id), onchange: (e) => { e.target.checked ? selected.add(a.id) : selected.delete(a.id); renderBulk(); } }) : ""),
        h("td", { class: "num" }, a.id), h("td", { class: "mono" }, a.login_hint, a.has_photo ? " 🖼" : ""),
        h("td", null, usdt(a.effective_price), a.custom_price ? h("span", { class: "pill info", style: "margin-inline-start:6px" }, "خاص") : null),
        h("td", null, pill(ACC, a.status)), h("td", { class: "mono" }, a.order_ref || "—"), h("td", null, dt(a.created_at)),
        h("td", null, can("catalog") && ["available", "disabled"].includes(a.status) ? h("button", { class: "btn sm", onclick: () => accountForm(a, () => ROUTES.type(id)) }, "تعديل") : ""))),
      "لا توجد حسابات بهذه الحالة"), pager(page, items.length, 50, (p) => { page = p; loadAcc(); }));
      renderBulk();
    };
    renderTabs();
    const tierText = t.tiers.length ? t.tiers.map((x) => `${money(x.price)} (${x.available})`).join(" · ") : "—";
    mainEl.replaceChildren(
      h("div", { class: "btn-row" }, h("a", { class: "btn sm", href: "#/types" }, "→ كل الأنواع"),
        can("catalog") ? h("button", { class: "btn sm", onclick: () => typeForm(t) }, "✏️ تعديل البيانات والسعر") : null,
        can("catalog") ? h("button", { class: "btn sm", onclick: async () => { await run(() => api("PATCH", "/types/" + id, { is_active: !t.is_active }), t.is_active ? "تم إيقاف البيع" : "تم تفعيل البيع"); route(); } }, t.is_active ? "⏸ إيقاف البيع" : "▶️ تفعيل البيع") : null,
        can("catalog") ? h("button", { class: "btn sm danger", onclick: () => deleteType(t, () => { location.hash = "#/types"; }) }, "حذف النوع") : null),
      h("div", { class: "grid kpis" }, kpi("LVL", t.lvl), kpi("Barn / Silo", `${t.barn} / ${t.silo}`), kpi("Tools — أدوات أرض", t.tools), kpi("السعر", money(t.price), "USDT"),
        kpi("متوفر", t.available_raw, "أسعار: " + tierText, t.available_raw ? "" : "danger"), kpi("مباع", t.sold), kpi("الحالة", t.is_active ? "مفعّل" : "موقوف")),
      photoCard("صورة المزرعة", "تظهر للزبون عند فتح هذا النوع في البوت، وتُرسل مع بيانات الدخول إذا لم يكن للحساب صورة خاصة.",
        `/api/types/${id}/photo`, !!t.photo_file_id, (fd) => api("POST", `/types/${id}/photo`, fd, true), () => api("DELETE", `/types/${id}/photo`)),
      can("catalog") ? importCard(id) : null,
      h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "الحسابات"), tabs, h("span", { style: "flex:1" }), searchIn), h("div", { class: "card-b", style: "padding-bottom:0" }, bulkBar), accBox));
    await loadAcc();
  };

  function accountForm(a, done) {
    const st = h("select", null, h("option", { value: "available" }, "متوفر"), h("option", { value: "disabled" }, "موقوف عن البيع"));
    st.value = a.status;
    const price = h("input", { type: "text", inputmode: "decimal", dir: "ltr", value: a.custom_price ?? "", placeholder: `سعر النوع: ${money(a.type_price)}` });
    const note = h("input", { type: "text", value: a.note || "" });
    const login = h("input", { type: "text", dir: "ltr", placeholder: "اتركه فارغاً لعدم التغيير", autocomplete: "off" });
    const pass = h("input", { type: "text", dir: "ltr", placeholder: "اتركه فارغاً لعدم التغيير", autocomplete: "off" });
    const form = h("form", null, field("الحالة", st), field("سعر خاص لهذا الحساب (فارغ = سعر النوع)", price), field("ملاحظة داخلية", note),
      h("p", { class: "small muted" }, "استبدال بيانات الدخول (تُشفّر فوراً ولا تُعرض مرة أخرى):"), h("div", { class: "form-grid" }, field("ID جديد", login), field("Password جديدة", pass)),
      h("div", { class: "btn-row" }, h("button", { class: "btn primary", type: "submit" }, "حفظ"),
        h("button", { class: "btn danger", type: "button", onclick: async () => { if (await confirmBox("حذف هذا الحساب نهائياً؟", { danger: true })) { await run(() => api("DELETE", "/accounts/" + a.id), "تم الحذف"); m.close(); done(); } } }, "حذف")));
    const pfile = h("input", { type: "file", accept: "image/*" });
    pfile.addEventListener("change", async () => { if (!pfile.files[0]) return; const fd = new FormData(); fd.append("file", pfile.files[0]);
      await run(() => api("POST", `/accounts/${a.id}/photo`, fd, true), "تم رفع صورة الحساب"); m.close(); done(); });
    form.append(h("div", { class: "card", style: "padding:12px;margin-top:12px" }, h("p", { class: "small muted", style: "margin-top:0" },
      "صورة خاصة بهذه المزرعة تُرسل للمشتري مع بيانات الدخول" + (a.has_photo ? " — ✅ يوجد صورة" : "")),
      h("div", { class: "btn-row" }, h("label", { class: "btn sm" }, "⬆️ رفع صورة", h("span", { style: "display:none" }, pfile)),
        a.has_photo ? h("a", { class: "btn sm", href: `/api/accounts/${a.id}/photo`, target: "_blank" }, "عرض") : null,
        a.has_photo ? h("button", { class: "btn sm danger", type: "button", onclick: async () => { await run(() => api("DELETE", `/accounts/${a.id}/photo`), "تم الحذف"); m.close(); done(); } }, "حذف الصورة") : null)));
    const m = modal(`حساب #${a.id} — ${a.login_hint}`, form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = { status: st.value, custom_price: price.value.trim() || null, note: note.value };
      if (login.value.trim()) body.login = login.value.trim();
      if (pass.value.trim()) body.password = pass.value.trim();
      await run(() => api("PATCH", "/accounts/" + a.id, body), "تم الحفظ");
      m.close(); done();
    });
  }

  function photoCard(title, hint, url, has, onUpload, onDelete) {
    const file = h("input", { type: "file", accept: "image/*" });
    const img = has ? h("img", { class: "proof", style: "max-height:240px;object-fit:contain", src: url + "?v=" + Date.now(), alt: title,
      onerror: (e) => e.target.replaceWith(h("div", { class: "notice warn" }, "تعذر تحميل الصورة من تيليجرام.")) }) : h("div", { class: "empty" }, "لا توجد صورة بعد");
    file.addEventListener("change", async () => {
      if (!file.files[0]) return;
      const fd = new FormData(); fd.append("file", file.files[0]);
      await run(() => onUpload(fd), "تم رفع الصورة"); route();
    });
    return h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, title), h("span", { style: "flex:1" }),
      can("catalog") ? h("label", { class: "btn sm primary" }, "⬆️ رفع صورة", h("span", { style: "display:none" }, file)) : null,
      can("catalog") && has ? h("button", { class: "btn sm danger", onclick: async () => { await run(onDelete, "تم الحذف"); route(); } }, "حذف") : null),
      h("div", { class: "card-b" }, h("p", { class: "small muted", style: "margin-top:0" }, hint), img));
  }

  function importCard(typeId) {
    let mode = "text";
    const ta = h("textarea", { dir: "ltr", placeholder: "user1:pass1\nuser2,pass2,12.5\nuser3 pass3", autocomplete: "off", spellcheck: "false" });
    const file = h("input", { type: "file", accept: ".csv,.txt,text/csv,text/plain" });
    const report = h("div");
    const inputBox = h("div", null, ta);
    const tabs = h("div", { class: "tabs" });
    const renderTabs = () => tabs.replaceChildren(
      h("button", { class: mode === "text" ? "on" : "", onclick: () => { mode = "text"; inputBox.replaceChildren(ta); renderTabs(); report.replaceChildren(); } }, "لصق نصي"),
      h("button", { class: mode === "csv" ? "on" : "", onclick: () => { mode = "csv"; inputBox.replaceChildren(file, h("p", { class: "small muted" }, "الأعمدة: id, password, price (اختياري), note (اختياري). صف العناوين اختياري.")); renderTabs(); report.replaceChildren(); } }, "ملف CSV"));
    renderTabs();
    const send = (preview) => {
      if (mode === "text") return POST(`/types/${typeId}/accounts`, { text: ta.value, preview });
      if (!file.files[0]) throw new ApiError("اختر ملفاً أولاً.");
      const fd = new FormData(); fd.append("file", file.files[0]);
      return api("POST", `/types/${typeId}/accounts/csv?preview=${preview}`, fd, true);
    };
    const issues = (r) => { const all = [...(r.errors || []), ...(r.duplicates_in_file || []), ...(r.duplicates_in_db || [])]; return all.length ? h("ul", { class: "list-issues" }, all.slice(0, 300).map((x) => h("li", null, x))) : null; };
    const check = async () => {
      const r = await run(() => send(true));
      report.replaceChildren(h("div", { class: "notice " + (r.valid ? "" : "warn") },
        `✅ صالح: ${r.valid} · ❌ أخطاء: ${r.errors.length} · ♻️ مكرر بالملف: ${r.duplicates_in_file.length} · 📦 موجود مسبقاً: ${r.duplicates_in_db.length}`),
        issues(r), r.valid ? h("div", { class: "btn-row", style: "margin-top:10px" }, h("button", { class: "btn primary", onclick: save }, `حفظ ${r.valid} حساب`)) : null);
    };
    const save = async () => {
      const r = await run(() => send(false));
      toast(`تم حفظ ${r.inserted} حساب`);
      ta.value = ""; file.value = "";
      report.replaceChildren(h("div", { class: "notice" }, `✅ تم حفظ ${r.inserted} حساب.`), issues(r));
      setTimeout(() => ROUTES.type(typeId), 900);
    };
    return h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, "إضافة حسابات"), tabs),
      h("div", { class: "card-b" }, h("p", { class: "small muted", style: "margin-top:0" }, "حساب في كل سطر: ID ثم كلمة المرور، وسعر خاص اختياري. يتم الفحص من التكرار والأخطاء قبل الحفظ، وتُشفّر البيانات في قاعدة البيانات."),
        inputBox, h("div", { class: "btn-row", style: "margin-top:10px" }, h("button", { class: "btn", onclick: check }, "🔎 فحص قبل الحفظ")), report));
  }

  // ============================================================ orders
  ROUTES.orders = async () => {
    setTitle("طلبات الشراء");
    let status = state.counts.review ? "needs_review" : "", page = 0;
    const search = h("input", { type: "search", placeholder: "رقم الطلب أو Telegram ID", dir: "auto", style: "max-width:240px" });
    const tabs = h("div", { class: "tabs" });
    const body = h("div");
    const renderTabs = () => tabs.replaceChildren(...[["", "الكل"], ["needs_review", "يحتاج مراجعة"], ["processing", "قيد المعالجة"], ["completed", "مكتمل"], ["cancelled", "ملغي"], ["pending", "بانتظار التأكيد"]]
      .map(([k, l]) => h("button", { class: status === k ? "on" : "", onclick: () => { status = k; page = 0; renderTabs(); load(); } }, l)));
    const load = async () => {
      const items = await GET("/orders" + q({ status, search: search.value.trim(), page }));
      body.replaceChildren(table(["الطلب", "الزبون", "النوع", "السعر", "الحالة", "الحساب", "التاريخ"], items.map((o) => h("tr", { class: "click", onclick: () => orderModal(o.id, load) },
        h("td", { class: "mono" }, o.ref), h("td", null, h("span", { class: "num" }, o.user_id), o.username ? h("div", { class: "small muted" }, "@" + o.username) : null),
        h("td", null, `${o.type_snapshot.name} · LVL ${o.type_snapshot.lvl}`), h("td", null, usdt(o.price)), h("td", null, pill(ORDER, o.status)),
        h("td", { class: "mono" }, o.account_id ? `#${o.account_id} ${o.login_hint || ""}` : "—"), h("td", null, dt(o.created_at)))), "لا توجد طلبات"),
      pager(page, items.length, 50, (p) => { page = p; load(); }));
    };
    search.addEventListener("input", debounce(() => { page = 0; load(); }, 400));
    renderTabs();
    mainEl.replaceChildren(h("div", { class: "card" }, h("div", { class: "card-h" }, tabs, h("span", { style: "flex:1" }), search), body));
    await load();
  };
  async function orderModal(id, reload) {
    const o = await GET("/orders/" + id);
    const acts = h("div", { class: "btn-row" });
    const m = modal(`الطلب ${o.ref}`, h("div", { class: "stack" },
      h("dl", { class: "kv" }, h("dt", null, "الحالة"), h("dd", null, pill(ORDER, o.status)), h("dt", null, "الزبون"), h("dd", null, h("a", { href: "#/user/" + o.user_id }, String(o.user_id)), o.username ? ` @${o.username}` : ""),
        h("dt", null, "النوع"), h("dd", null, `${o.type_snapshot.name} — LVL ${o.type_snapshot.lvl} · Barn ${o.type_snapshot.barn} · Silo ${o.type_snapshot.silo}`),
        h("dt", null, "السعر"), h("dd", null, usdt(o.price)), h("dt", null, "الحساب"), h("dd", { class: "mono" }, o.account_id ? `#${o.account_id} ${o.login_hint}` : "—"),
        h("dt", null, "أُنشئ"), h("dd", null, dt(o.created_at)), h("dt", null, "سُلّم"), h("dd", null, dt(o.delivered_at)),
        o.failure_reason ? [h("dt", null, "السبب"), h("dd", null, o.failure_reason)] : null, o.admin_note ? [h("dt", null, "ملاحظة"), h("dd", null, o.admin_note)] : null),
      o.transactions.length ? table(["العملية", "المبلغ", "النوع", "الوقت"], o.transactions.map((t) => h("tr", null, h("td", { class: "mono" }, t.ref), h("td", { class: "num" }, money(t.amount)), h("td", null, KIND[t.kind]), h("td", null, dt(t.created_at))))) : null,
      h("p", { class: "small muted" }, "🔒 بيانات الدخول لا تُعرض في اللوحة — تظهر للمشتري فقط."), acts), { wide: true });
    const done = () => { m.close(); reload(); refreshCounts(); };
    if (o.status === "needs_review") {
      acts.append(h("button", { class: "btn primary", onclick: async () => { const r = await run(() => POST(`/orders/${id}/redeliver`)); toast(r.delivered ? "تم التسليم ✅" : "فشل الإرسال مجدداً", !r.delivered); done(); } }, "🔁 إعادة إرسال البيانات"),
        h("button", { class: "btn", onclick: async () => { if (await confirmBox("تأكيد أن الزبون استلم البيانات بطريقة أخرى؟")) { await run(() => POST(`/orders/${id}/mark-delivered`, { note: "تأكيد يدوي من اللوحة" }), "تم"); done(); } } }, "✅ تم التسليم يدوياً"));
    }
    if (["needs_review", "completed", "processing"].includes(o.status) && can("wallet")) {
      acts.append(h("button", { class: "btn danger", onclick: () => refundForm(o, done) }, "↩️ استرداد المبلغ"));
    }
  }
  function refundForm(o, done) {
    const reason = h("input", { type: "text", required: true, placeholder: "يظهر للزبون" });
    const restock = h("input", { type: "checkbox", checked: o.status !== "completed" });
    const form = h("form", null, h("p", null, `سيُعاد ${money(o.price)} USDT إلى محفظة الزبون مرة واحدة فقط ويُلغى الطلب.`), field("سبب الاسترداد", reason),
      o.status !== "completed" ? h("label", { class: "switch f" }, restock, "إعادة الحساب إلى المخزون (فقط إذا تأكدت أن الزبون لم يستلم البيانات)") : null,
      h("button", { class: "btn danger solid", type: "submit" }, "تنفيذ الاسترداد"));
    const m = modal("استرداد " + o.ref, form);
    form.addEventListener("submit", async (e) => { e.preventDefault(); await run(() => POST(`/orders/${o.id}/refund`, { reason: reason.value, restock: restock.checked }), "تم الاسترداد"); m.close(); done(); });
  }

  // ========================================================== deposits
  ROUTES.deposits = async () => {
    setTitle("طلبات شحن USDT — Binance Pay");
    let status = "under_review", page = 0;
    const search = h("input", { type: "search", placeholder: "المرجع / Order ID / Telegram ID", dir: "auto", style: "max-width:260px" });
    const tabs = h("div", { class: "tabs" });
    const body = h("div");
    const renderTabs = () => tabs.replaceChildren(...[["under_review", "قيد المراجعة"], ["awaiting_payment", "بانتظار الدفع"], ["approved", "مقبول"], ["rejected", "مرفوض"], ["cancelled", "ملغي"], ["", "الكل"]]
      .map(([k, l]) => h("button", { class: status === k ? "on" : "", onclick: () => { status = k; page = 0; renderTabs(); load(); } }, l)));
    const load = async () => {
      const items = await GET("/deposits" + q({ status, search: search.value.trim(), page }));
      body.replaceChildren(table(["المرجع", "الزبون", "المبلغ", "Order ID", "الحالة", "التاريخ", "المراجِع"], items.map((d) => h("tr", { class: "click", onclick: () => depositModal(d, load) },
        h("td", { class: "mono" }, d.ref), h("td", null, h("span", { class: "num" }, d.user_id), d.username ? h("div", { class: "small muted" }, "@" + d.username) : null),
        h("td", null, usdt(d.amount), d.credited_amount && d.credited_amount !== d.amount ? h("div", { class: "small muted" }, "أُضيف " + money(d.credited_amount)) : null),
        h("td", { class: "mono" }, d.proof_txid || "—"), h("td", null, pill(DEP, d.status), d.auto_verified ? h("span", { class: "pill info", style: "margin-inline-start:4px" }, "آلي") : null),
        h("td", null, dt(d.created_at)), h("td", { class: "small" }, d.reviewed_by || "—"))), "لا توجد طلبات"),
      pager(page, items.length, 50, (p) => { page = p; load(); }));
    };
    search.addEventListener("input", debounce(() => { page = 0; load(); }, 400));
    renderTabs();
    mainEl.replaceChildren(h("div", { class: "notice warn" }, "⚠️ لا توافق على أي طلب قبل التأكد من وصول المبلغ فعلياً في سجل Binance Pay ومطابقة Order ID والمبلغ."),
      h("div", { class: "card" }, h("div", { class: "card-h" }, tabs, h("span", { style: "flex:1" }), search), body));
    await load();
  };
  function depositModal(d, reload) {
    const amount = h("input", { type: "text", inputmode: "decimal", dir: "ltr", value: d.amount });
    const reason = h("input", { type: "text", placeholder: "سبب الرفض — يظهر للزبون" });
    const quick = ["لم يصل المبلغ", "المبلغ المحوّل لا يطابق الطلب", "الإثبات غير واضح أو غير صحيح", "رقم العملية غير صحيح"];
    const acts = d.status === "under_review" || d.status === "awaiting_payment" ? h("div", { class: "stack" },
      d.status === "under_review" ? h("div", { class: "card", style: "padding:12px" }, field("المبلغ المضاف فعلياً (USDT)", amount),
        h("button", { class: "btn primary", onclick: async () => { if (!(await confirmBox(`تأكيد وصول ${amount.value} USDT وإضافتها لرصيد الزبون؟`))) return; await run(() => POST(`/deposits/${d.id}/approve`, { amount: amount.value }), "تم القبول وإضافة الرصيد"); m.close(); reload(); refreshCounts(); } }, "✅ قبول وإضافة الرصيد")) : null,
      h("div", { class: "card", style: "padding:12px" }, field("سبب الرفض", reason), h("div", { class: "btn-row", style: "margin-bottom:10px" }, quick.map((x) => h("button", { class: "btn sm", onclick: () => { reason.value = x; } }, x))),
        h("button", { class: "btn danger", onclick: async () => { await run(() => POST(`/deposits/${d.id}/reject`, { reason: reason.value }), "تم الرفض"); m.close(); reload(); refreshCounts(); } }, "❌ رفض الطلب"))) : null;
    const m = modal(`طلب الشحن ${d.ref}`, h("div", { class: "grid two" },
      h("div", null, d.proof_file_id ? h("img", { class: "proof", src: `/api/deposits/${d.id}/proof`, alt: "إثبات الدفع", loading: "lazy", onerror: (e) => e.target.replaceWith(h("div", { class: "notice warn" }, "تعذر تحميل صورة الإثبات من تيليجرام — راجعها من إشعار البوت.")) }) : h("div", { class: "empty" }, "لا توجد صورة")),
      h("div", { class: "stack" }, h("dl", { class: "kv" }, h("dt", null, "الحالة"), h("dd", null, pill(DEP, d.status)), h("dt", null, "الزبون"), h("dd", null, h("a", { href: "#/user/" + d.user_id }, String(d.user_id)), d.username ? " @" + d.username : ""),
        h("dt", null, "المبلغ المطلوب"), h("dd", null, usdt(d.amount)), h("dt", null, "Order ID"), h("dd", { class: "mono" }, d.proof_txid || "—"),
        h("dt", null, "معرّف الدفع المعروض"), h("dd", { class: "mono" }, d.pay_id_shown || "—"), h("dt", null, "أُنشئ"), h("dd", null, dt(d.created_at)),
        d.reviewed_by ? [h("dt", null, "روجع بواسطة"), h("dd", null, `${d.reviewed_by} — ${dt(d.reviewed_at)}`)] : null,
        d.credited_amount ? [h("dt", null, "المبلغ المضاف"), h("dd", null, usdt(d.credited_amount))] : null,
        d.reject_reason ? [h("dt", null, "سبب الرفض"), h("dd", null, d.reject_reason)] : null), acts)), { wide: true });
  }

  // ============================================================= users
  ROUTES.users = async () => {
    setTitle("المستخدمون والأرصدة");
    let page = 0;
    const search = h("input", { type: "search", placeholder: "Telegram User ID أو الاسم أو @username", dir: "auto" });
    const withBal = h("input", { type: "checkbox" });
    const body = h("div");
    const load = async () => {
      const items = await GET("/users" + q({ q: search.value.trim(), with_balance: withBal.checked || "", page }));
      body.replaceChildren(table(["Telegram ID", "الاسم", "الرصيد", "المشتريات", "آخر نشاط", ""], items.map((u) => h("tr", { class: "click", onclick: () => (location.hash = "#/user/" + u.id) },
        h("td", { class: "mono" }, u.id), h("td", null, u.first_name || "", u.username ? h("div", { class: "small muted" }, "@" + u.username) : null),
        h("td", null, usdt(u.balance)), h("td", { class: "num" }, u.orders_count), h("td", null, dt(u.last_seen_at)), h("td", null, u.is_banned ? h("span", { class: "pill danger" }, "محظور") : ""))), "لا يوجد مستخدمون"),
      pager(page, items.length, 50, (p) => { page = p; load(); }));
    };
    search.addEventListener("input", debounce(() => { page = 0; load(); }, 400));
    withBal.addEventListener("change", () => { page = 0; load(); });
    mainEl.replaceChildren(h("div", { class: "card" }, h("div", { class: "card-h" }, h("div", { class: "filters", style: "flex:1" }, search, h("label", { class: "switch" }, withBal, "لديهم رصيد فقط"))), body));
    await load();
  };
  ROUTES.user = async (id) => {
    const u = await GET("/users/" + id);
    setTitle(`المستخدم ${u.first_name || ""} (${u.id})`);
    let tab = "tx";
    const tabs = h("div", { class: "tabs" });
    const tabBody = h("div");
    const renderTab = () => {
      tabs.replaceChildren(...[["tx", "الحركات المالية"], ["orders", "الطلبات"], ["deposits", "الشحن"]].map(([k, l]) => h("button", { class: tab === k ? "on" : "", onclick: () => { tab = k; renderTab(); } }, l)));
      if (tab === "tx") tabBody.replaceChildren(txTable(u.transactions));
      if (tab === "orders") tabBody.replaceChildren(table(["الطلب", "النوع", "السعر", "الحالة", "التاريخ"], u.orders.map((o) => h("tr", { class: "click", onclick: () => orderModal(o.id, () => ROUTES.user(id)) },
        h("td", { class: "mono" }, o.ref), h("td", null, o.type_snapshot.name), h("td", null, usdt(o.price)), h("td", null, pill(ORDER, o.status)), h("td", null, dt(o.created_at))))));
      if (tab === "deposits") tabBody.replaceChildren(table(["المرجع", "المبلغ", "Order ID", "الحالة", "التاريخ"], u.deposits.map((d) => h("tr", { class: "click", onclick: () => depositModal(d, () => ROUTES.user(id)) },
        h("td", { class: "mono" }, d.ref), h("td", null, usdt(d.amount)), h("td", { class: "mono" }, d.proof_txid || "—"), h("td", null, pill(DEP, d.status)), h("td", null, dt(d.created_at))))));
    };
    renderTab();
    const amount = h("input", { type: "text", inputmode: "decimal", dir: "ltr", placeholder: "مثال: 10 أو -5" });
    const reason = h("input", { type: "text", placeholder: "سبب واضح (إلزامي)" });
    let key = uid();
    const adjust = can("wallet") ? h("div", { class: "card" }, h("div", { class: "card-h" }, h("h3", null, "تعديل الرصيد يدوياً")), h("div", { class: "card-b" },
      h("div", { class: "form-grid" }, field("المبلغ (موجب = إضافة، سالب = خصم)", amount), field("السبب", reason)),
      h("button", { class: "btn primary", onclick: async () => {
        if (!(await confirmBox(`تنفيذ ${amount.value} USDT على رصيد ${u.id}؟`))) return;
        await run(() => POST(`/users/${id}/adjust`, { amount: amount.value, reason: reason.value, idempotency_key: key }), "تمت العملية");
        key = uid(); ROUTES.user(id);
      } }, "تنفيذ"), h("p", { class: "small muted" }, "كل تعديل يُسجل كحركة مالية برقم فريد مع اسمك والسبب، ولا يمكن أن يصبح الرصيد سالباً."))) : null;
    mainEl.replaceChildren(
      h("div", { class: "btn-row" }, h("a", { class: "btn sm", href: "#/users" }, "→ المستخدمون"),
        can("users") ? h("button", { class: "btn sm " + (u.is_banned ? "" : "danger"), onclick: async () => { await run(() => POST(`/users/${id}/ban`, { banned: !u.is_banned }), "تم"); route(); } }, u.is_banned ? "✅ فك الحظر" : "⛔️ حظر المستخدم") : null),
      h("div", { class: "grid kpis" }, kpi("الرصيد", money(u.balance), "USDT"), kpi("Telegram ID", u.id), kpi("اسم المستخدم", u.username ? "@" + u.username : "—"),
        kpi("انضم", dt(u.created_at).split(",")[0]), kpi("الحالة", u.is_banned ? "محظور" : "نشط", "", u.is_banned ? "danger" : "")),
      adjust, h("div", { class: "card" }, h("div", { class: "card-h" }, tabs), tabBody));
  };
  const txTable = (txs) => table(["العملية", "النوع", "المبلغ", "الرصيد بعدها", "بواسطة", "السبب", "الوقت"], txs.map((t) => h("tr", null,
    h("td", { class: "mono" }, t.ref), h("td", null, KIND[t.kind] || t.kind), h("td", null, h("b", { class: "num", style: `color:var(--${+t.amount > 0 ? "ok" : "danger"})` }, (+t.amount > 0 ? "+" : "") + money(t.amount))),
    h("td", null, usdt(t.balance_after)), h("td", { class: "small" }, t.actor || "—"), h("td", { class: "wrap small" }, t.reason || "—"), h("td", null, dt(t.created_at)))), "لا توجد حركات");

  ROUTES.transactions = async () => {
    setTitle("الحركات المالية");
    let page = 0;
    const kind = h("select", null, h("option", { value: "" }, "كل الأنواع"), Object.entries(KIND).map(([k, l]) => h("option", { value: k }, l)));
    const user = h("input", { type: "search", placeholder: "Telegram ID", dir: "ltr", inputmode: "numeric" });
    const body = h("div");
    const recon = h("div");
    const load = async () => {
      const items = await GET("/transactions" + q({ kind: kind.value, user_id: user.value.trim(), page }));
      body.replaceChildren(table(["العملية", "المستخدم", "النوع", "المبلغ", "الرصيد بعدها", "بواسطة", "السبب", "الوقت"], items.map((t) => h("tr", null,
        h("td", { class: "mono" }, t.ref), h("td", null, h("a", { href: "#/user/" + t.user_id, class: "num" }, String(t.user_id))), h("td", null, KIND[t.kind]),
        h("td", null, h("b", { class: "num", style: `color:var(--${+t.amount > 0 ? "ok" : "danger"})` }, (+t.amount > 0 ? "+" : "") + money(t.amount))),
        h("td", null, usdt(t.balance_after)), h("td", { class: "small" }, t.actor || "—"), h("td", { class: "wrap small" }, t.reason || "—"), h("td", null, dt(t.created_at)))), "لا توجد حركات"),
      pager(page, items.length, 50, (p) => { page = p; load(); }));
    };
    kind.addEventListener("change", () => { page = 0; load(); });
    user.addEventListener("input", debounce(() => { page = 0; load(); }, 400));
    mainEl.replaceChildren(recon, h("div", { class: "card" }, h("div", { class: "card-h" }, h("div", { class: "filters", style: "flex:1" }, kind, user),
      can("wallet") ? h("button", { class: "btn sm", onclick: async () => { const r = await run(() => GET("/wallet/reconcile")); recon.replaceChildren(h("div", { class: "notice " + (r.length ? "danger" : "") }, r.length ? `⚠️ ${r.length} رصيد لا يطابق السجل!` : "✅ جميع الأرصدة تطابق السجل المالي تماماً.")); } }, "🧮 مطابقة الأرصدة") : null), body));
    await load();
  };

  // ========================================================== settings
  ROUTES.settings = async () => {
    setTitle("الإعدادات ورسائل البوت");
    const items = await GET("/settings");
    const inputs = {};
    const groups = { "الدفع عبر Binance Pay": ["binance_pay_id", "payment_instructions", "min_deposit", "max_deposit", "require_txid", "auto_verify_enabled"],
      "رسائل البوت والدعم": ["store_name", "welcome_text", "support_text", "support_username"],
      "النصوص باللغة الإنجليزية": ["welcome_text_en", "support_text_en", "payment_instructions_en"],
      "المخزون والشراء": ["hide_out_of_stock", "low_stock_threshold", "max_quantity"],
      "أيقونات أزرار القائمة (Custom Emoji ID)": ["icon_buy", "icon_wallet", "icon_topup", "icon_orders", "icon_support", "icon_lang"] };
    const byKey = Object.fromEntries(items.map((i) => [i.key, i]));
    const cards = Object.entries(groups).map(([title, keys]) => h("div", { class: "card" }, h("div", { class: "card-h" }, h("h2", null, title)), h("div", { class: "card-b" },
      keys.filter((k) => byKey[k]).map((k) => {
        const s = byKey[k];
        let el;
        if (s.kind === "bool") { el = h("input", { type: "checkbox", checked: s.value === "true" }); inputs[k] = el; return h("label", { class: "switch f" }, el, s.label); }
        if (s.kind === "longtext") { el = h("textarea", { dir: k.endsWith("_en") ? "ltr" : "auto" }); el.value = s.value; } else el = h("input", { type: "text", value: s.value, dir: ["binance_pay_id", "support_username", "min_deposit", "max_deposit", "low_stock_threshold", "max_quantity"].includes(k) || s.kind === "icon" ? "ltr" : "auto", placeholder: s.kind === "icon" ? "مثال: 5368324170671202286 — أو استخدم 🛠 ← ⚙️ ← 🎨 في البوت" : "" });
        inputs[k] = el;
        return field(s.label, el);
      }))));
    const save = h("button", { class: "btn primary", onclick: async () => {
      const body = {};
      for (const [k, el] of Object.entries(inputs)) body[k] = el.type === "checkbox" ? el.checked : el.value;
      await run(() => api("PUT", "/settings", body), "تم حفظ الإعدادات — تُطبق فوراً في البوت");
    } }, "💾 حفظ كل الإعدادات");
    mainEl.replaceChildren(h("div", { class: "notice" }, "التحقق الآلي يتطلب ضبط BINANCE_API_KEY و BINANCE_API_SECRET (مفتاح قراءة فقط) في متغيرات البيئة. بدونها تبقى المراجعة يدوية."),
      ...cards, h("div", { class: "btn-row" }, save));
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
      h("div", { class: "notice" }, "الصلاحيات: المالك = كل شيء · المشرف = المخزون والطلبات والشحن والأرصدة والإعدادات · الدعم الفني = عرض ومراجعة الشحن والطلبات فقط. يتم التحقق في البوت عبر Telegram User ID وليس اسم المستخدم."),
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
      h("div", { class: "notice warn" }, "احتفظ بالنسخ مع مفتاح ENCRYPTION_KEY في مكان آمن منفصل — بدون المفتاح لا يمكن فك كلمات مرور الحسابات. تُرسل نسخة تلقائية يومياً إلى المالك عبر تيليجرام."),
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
