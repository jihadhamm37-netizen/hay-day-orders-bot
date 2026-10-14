/* HD Agent — customer app (web + Android WebView). Vanilla JS, no external scripts. */
(() => {
  "use strict";
  const root = document.getElementById("root");
  const LS = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
    del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
  };
  const Android = window.HDAndroid || null;   // injected by the APK

  // ------------------------------------------------------------ helpers
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "html") el.innerHTML = v;
      else if (k === "value") el.value = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat(Infinity)) {
      if (c === null || c === undefined || c === false) continue;
      el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  }
  const svg = (d, extra = "") => {
    const s = document.createElement("span");
    s.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
    s.style.display = "contents";
    return s.firstChild;
  };
  const I = {
    send: '<path d="M21 3 10 14"/><path d="m21 3-7 18-4-7-7-4z"/>',
    clip: '<path d="m21 11-8.5 8.5a5 5 0 0 1-7-7L14 4a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.6a1.7 1.7 0 0 1-2.4-2.4L16 7"/>',
    box: '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="m3 8 9 5 9-5"/><path d="M12 13v8"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    bot: '<rect x="4" y="8" width="16" height="12" rx="4"/><path d="M12 8V4"/><circle cx="12" cy="3" r="1"/><circle cx="9" cy="13" r="1.3"/><circle cx="15" cy="13" r="1.3"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
  };
  const botMark = (size) => {
    const s = svg(I.bot); s.setAttribute("width", size); s.setAttribute("height", size); s.style.color = "#123524"; return s;
  };
  function toast(msg, bad) {
    const t = h("div", { class: bad ? "bad" : "" }, msg);
    document.getElementById("toast").append(t);
    setTimeout(() => t.remove(), bad ? 5000 : 2600);
  }
  const fmtTime = (s) => { try { return new Date(s).toLocaleTimeString("ar", { hour: "2-digit", minute: "2-digit" }); } catch { return ""; } };
  async function copy(text, label) {
    try {
      if (Android && Android.copy) Android.copy(text);
      else await navigator.clipboard.writeText(text);
      toast(label || "تم النسخ");
    } catch {
      const ta = h("textarea", { style: "position:fixed;opacity:0" }); ta.value = text; document.body.append(ta); ta.select();
      try { document.execCommand("copy"); toast(label || "تم النسخ"); } catch { toast("انسخ يدوياً", true); }
      ta.remove();
    }
  }

  // ------------------------------------------------------------- device
  function deviceId() {
    if (Android && Android.deviceId) { try { const id = Android.deviceId(); if (id) return "and-" + id; } catch { /* fall back */ } }
    let id = LS.get("hd_dev");
    if (!id) { id = "web-" + (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2)); LS.set("hd_dev", id); }
    return id;
  }
  function deviceLabel() {
    if (Android && Android.deviceName) { try { return Android.deviceName(); } catch { /* ignore */ } }
    const ua = navigator.userAgent;
    const m = ua.match(/Android [\d.]+; ([^;)]+)/) || ua.match(/(iPhone|iPad|Windows NT [\d.]+|Mac OS X [\d_]+)/);
    return (m ? m[1] : "Browser").slice(0, 100);
  }

  // ---------------------------------------------------------------- api
  class ApiError extends Error {}
  async function api(method, path, body, isForm) {
    const headers = {};
    const tok = LS.get("hd_token");
    if (tok) headers.Authorization = "Bearer " + tok;
    const opts = { method, headers };
    if (body !== undefined) {
      if (isForm) opts.body = body;
      else { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    }
    let res;
    try { res = await fetch("/app/api" + path, opts); } catch { throw new ApiError("لا يوجد اتصال بالإنترنت."); }
    let data = {};
    try { data = await res.json(); } catch { /* empty */ }
    if (res.status === 401 && path !== "/login") { LS.del("hd_token"); stopPolling(); renderLogin(data.error); throw new ApiError(data.error || "سجّل الدخول"); }
    if (!res.ok || data.ok === false) throw new ApiError(data.error || `خطأ ${res.status}`);
    return data.data;
  }

  // -------------------------------------------------------------- login
  function renderLogin(msg) {
    const input = h("input", { inputmode: "text", autocomplete: "one-time-code", autocapitalize: "characters", spellcheck: "false",
      maxlength: "20", placeholder: "XXXXXXXX", "aria-label": "كود الدخول" });
    const err = h("div", { class: "err", role: "alert" }, msg || "");
    const btn = h("button", { class: "btn primary block", type: "submit" }, "دخول");
    const form = h("form", { class: "login" },
      h("div", { class: "bot" }, (() => { const s = svg(I.bot); s.setAttribute("width", 52); s.setAttribute("height", 52); s.style.color = "#F2C14E"; return s; })()),
      h("div", null, h("h1", null, "HD Agent"), h("p", null, "مساعدك الذكي لشراء مزارع Hay Day. أدخل الكود الذي استلمته من الإدارة.")),
      h("label", { class: "code-field" }, h("span", null, "HD-"), input),
      err, btn,
      h("p", { class: "hint" }, "الكود يعمل على جهاز واحد فقط، وتبقى مسجّلاً بعد الدخول."));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const raw = input.value.trim().toUpperCase().replace(/^HD-?/, "");
      if (raw.length < 4) { err.textContent = "اكتب الكود كاملاً."; return; }
      btn.disabled = true; err.textContent = "";
      try {
        const r = await api("POST", "/login", { code: "HD-" + raw, device_id: deviceId(), device_label: deviceLabel() });
        LS.set("hd_token", r.token);
        start();
      } catch (ex) { err.textContent = ex.message; btn.disabled = false; }
    });
    root.replaceChildren(form);
    setTimeout(() => input.focus(), 50);
  }

  // --------------------------------------------------------------- chat
  const state = { last: 0, states: {}, nodes: new Map(), busy: false, timer: null, me: null };
  let log, ta, sendBtn, attachBtn, fileIn, typing;

  function stopPolling() { clearTimeout(state.timer); state.timer = null; }

  async function start() {
    let me;
    try { me = await api("GET", "/me"); } catch { return; }
    state.me = me; state.last = 0; state.nodes.clear();
    renderChat();
    await poll(true);
  }

  function renderChat() {
    log = h("main", { class: "log", "aria-live": "polite" });
    typing = h("div", { class: "typing", hidden: true, "aria-label": "يكتب" }, h("i"), h("i"), h("i"));
    ta = h("textarea", { rows: 1, placeholder: "اكتب رسالتك…", "aria-label": "رسالة", dir: "auto" });
    sendBtn = h("button", { class: "round send", "aria-label": "إرسال" }, svg(I.send));
    fileIn = h("input", { type: "file", accept: "image/*", hidden: true });
    attachBtn = h("button", { class: "round attach", "aria-label": "إرسال صورة إثبات التحويل", title: "صورة إثبات التحويل" }, svg(I.clip));
    ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 140) + "px"; });
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && window.matchMedia("(pointer:fine)").matches) { e.preventDefault(); send(); } });
    sendBtn.addEventListener("click", send);
    attachBtn.addEventListener("click", () => fileIn.click());
    fileIn.addEventListener("change", () => { if (fileIn.files[0]) uploadProof(fileIn.files[0]); fileIn.value = ""; });
    root.replaceChildren(
      h("header", { class: "top" },
        h("div", { class: "av" }, botMark(26)),
        h("div", { class: "who" }, h("b", null, "HD Agent"), h("small", null, "متصل الآن")),
        h("button", { class: "icon-btn", "aria-label": "طلباتي", title: "طلباتي", onclick: openOrders }, svg(I.box)),
        h("button", { class: "icon-btn", "aria-label": "خروج", title: "خروج", onclick: logout }, svg(I.logout))),
      log, h("div", { class: "composer" }, attachBtn, ta, sendBtn, fileIn));
    log.append(typing);
  }

  function logout() {
    if (!confirm("تسجيل الخروج؟ يمكنك الدخول مرة أخرى بنفس الكود على هذا الجهاز فقط.")) return;
    LS.del("hd_token"); stopPolling(); renderLogin();
  }

  async function poll(first) {
    stopPolling();
    try {
      const r = await api("GET", "/messages" + (state.last ? "?after=" + state.last : ""));
      state.states = r.states || {};
      const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 140;
      for (const m of r.messages) { addMessage(m); state.last = Math.max(state.last, m.id); }
      refreshCards();
      if (first || r.messages.length && nearBottom) scrollDown();
      else if (r.messages.length) toast("رسالة جديدة");
    } catch { /* retry */ }
    if (LS.get("hd_token")) state.timer = setTimeout(poll, document.hidden ? 15000 : 4000);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && state.me && LS.get("hd_token")) poll(); });

  const scrollDown = () => requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });

  async function send() {
    const text = ta.value.trim();
    if (!text || state.busy) return;
    state.busy = true; sendBtn.disabled = true;
    ta.value = ""; ta.style.height = "auto";
    const pending = h("div", { class: "b me" }, text);
    log.insertBefore(pending, typing); typing.hidden = false; scrollDown();
    try { await api("POST", "/messages", { text }); pending.remove(); }
    catch (ex) { pending.remove(); ta.value = text; toast(ex.message, true); }
    typing.hidden = true; state.busy = false; sendBtn.disabled = false;
    await poll(); scrollDown();
  }

  async function uploadProof(file) {
    if (file.size > 8 * 1024 * 1024) { toast("الصورة أكبر من 8MB.", true); return; }
    const fd = new FormData(); fd.append("file", file);
    attachBtn.disabled = true; typing.hidden = false; scrollDown();
    try { await api("POST", "/proof", fd, true); toast("تم إرسال صورة التحويل"); }
    catch (ex) { toast(ex.message, true); }
    attachBtn.disabled = false; typing.hidden = true;
    await poll(); scrollDown();
  }

  async function act(fn, okMsg) {
    try { await fn(); if (okMsg) toast(okMsg); } catch (ex) { toast(ex.message, true); }
    await poll(); scrollDown();
  }

  // ------------------------------------------------------------ messages
  function addMessage(m) {
    if (state.nodes.has(m.id)) return;
    let node;
    if (m.role === "user") {
      node = m.kind === "proof" ? h("div", { class: "b me" }, "صورة إثبات التحويل للطلب ", h("span", { class: "num" }, (m.payload || {}).ref || ""))
        : h("div", { class: "b me" }, m.text);
    } else if (m.role === "admin") {
      node = h("div", { class: "b staff" }, h("span", { class: "by" }, "فريق الدعم"), m.text);
    } else if (m.role === "assistant") {
      node = h("div", { class: "b bot" }, m.text);
    } else {
      node = card(m) || h("div", { class: "notice" }, m.text);
    }
    if (node.classList.contains("b")) node.append(h("time", null, fmtTime(m.at)));
    node.dataset.kind = m.kind;
    state.nodes.set(m.id, { node, m });
    log.insertBefore(node, typing);
  }

  const orderState = (id) => (state.states[String(id)] || {}).status;

  function card(m) {
    const p = m.payload || {};
    if (m.kind === "order_summary") {
      const t = h("section", { class: "ticket", "aria-label": "ملخص الطلب" },
        h("div", { class: "band" }, "ملخص الطلب", h("span", { class: "ref num" }, p.ref)),
        h("div", { class: "body" },
          h("div", { class: "specs" },
            [["المستوى", p.lvl], ["المخزن", p.barn], ["الصومعة", p.silo], ["الأدوات", p.tools]].map(([k, v]) =>
              h("div", null, h("b", { class: "num" }, v), h("small", null, k)))),
          h("hr", { class: "perf" }),
          h("div", { class: "total" },
            h("div", null, h("div", { class: "big num" }, `${p.total} ${p.currency}`)),
            h("div", { class: "calc" }, h("span", { class: "num" }, `${p.quantity} × ${p.unit_price}`)))),
        h("div", { class: "acts" },
          h("button", { class: "btn green", "data-act": "confirm", onclick: () => act(() => api("POST", `/orders/${p.order_id}/confirm`)) }, "تأكيد الشراء"),
          h("button", { class: "btn danger", "data-act": "cancel", onclick: () => act(() => api("POST", `/orders/${p.order_id}/cancel`)) }, "إلغاء")),
        h("div", { class: "state" }));
      t.dataset.order = p.order_id;
      return t;
    }
    if (m.kind === "methods") {
      const t = h("section", { class: "ticket pay" },
        h("div", { class: "band" }, "اختر وسيلة الدفع", h("span", { class: "ref num" }, p.ref)),
        h("div", { class: "acts", style: "flex-direction:column" }, (p.methods || []).map((x) =>
          h("button", { class: "btn", "data-act": "method", onclick: () => act(() => api("POST", `/orders/${p.order_id}/method`, { method_id: x.id })) }, x.name))),
        h("div", { class: "state" }));
      t.dataset.order = p.order_id;
      return t;
    }
    if (m.kind === "pay_details") {
      const t = h("section", { class: "ticket pay" },
        h("div", { class: "band" }, `الدفع عبر ${p.method}`, h("span", { class: "ref num" }, p.ref)),
        h("div", { class: "body" },
          h("div", { class: "row" }, h("span", { class: "k" }, "المبلغ"),
            h("span", { class: "v" }, h("span", { class: "num" }, `${p.total} ${p.currency}`), h("button", { class: "copy", onclick: () => copy(p.amount, "تم نسخ المبلغ") }, "نسخ"))),
          h("div", { class: "row" }, h("span", { class: "k" }, "المعرّف"),
            h("span", { class: "v" }, h("span", { class: "num" }, p.account), h("button", { class: "copy", onclick: () => copy(p.account, "تم نسخ المعرّف") }, "نسخ"))),
          p.instructions ? h("div", { class: "instr" }, p.instructions) : null,
          h("div", { class: "instr" }, "حوّل المبلغ بالضبط، ثم أرسل صورة التحويل فقط. لا حاجة لرقم العملية.")),
        h("div", { class: "acts" }, h("button", { class: "btn primary", "data-act": "proof", onclick: () => fileIn.click() }, "إرسال صورة التحويل")),
        h("div", { class: "state" }));
      t.dataset.order = p.order_id;
      return t;
    }
    if (m.kind === "delivered") {
      return h("section", { class: "ticket done" },
        h("div", { class: "band" }, "تم التسليم", h("span", { class: "ref num" }, p.ref)),
        h("div", { class: "body" }, h("div", { class: "instr" }, `${p.count} مزرعة — المستوى ${p.lvl}. البيانات محفوظة في طلباتك ويمكنك فتحها في أي وقت.`)),
        h("div", { class: "acts" }, h("button", { class: "btn green", onclick: () => showFarms(p.order_id) }, "عرض بيانات المزارع")));
    }
    return null;
  }

  const LIVE = { pending_confirmation: ["بانتظار تأكيدك", ""], awaiting_payment: ["بانتظار الدفع", "warn"], proof_received: ["استلمنا الإثبات", "warn"],
    payment_review: ["الدفع قيد المراجعة", "warn"], payment_confirmed: ["الدفع مؤكد", "ok"], processing: ["قيد التنفيذ", "ok"],
    delivered: ["تم التسليم", "ok"], cancelled: ["ملغي", "bad"], rejected: ["مرفوض", "bad"] };

  function refreshCards() {
    for (const { node, m } of state.nodes.values()) {
      if (!node.dataset || !node.dataset.order) continue;
      const st = orderState(node.dataset.order);
      const method = (state.states[node.dataset.order] || {}).method;
      const enable = { order_summary: st === "pending_confirmation", methods: st === "awaiting_payment" && !method, pay_details: st === "awaiting_payment" }[m.kind];
      node.querySelectorAll("[data-act]").forEach((b) => { b.disabled = !enable; });
      const acts = node.querySelector(".acts");
      if (acts) acts.hidden = !enable;
      const stEl = node.querySelector(".state");
      if (stEl) stEl.textContent = !enable && st ? "حالة الطلب: " + (LIVE[st] || [st])[0] : "";
    }
  }

  // ------------------------------------------------------------- sheets
  function sheet(title, content) {
    const bg = h("div", { class: "sheet-bg" });
    const close = () => bg.remove();
    bg.addEventListener("click", (e) => { if (e.target === bg) close(); });
    bg.append(h("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-label": title },
      h("header", null, h("h2", null, title), h("button", { class: "btn ghost", "aria-label": "إغلاق", onclick: close }, svg(I.x))),
      h("div", { class: "content" }, content)));
    document.body.append(bg);
    return { close };
  }

  async function openOrders() {
    const box = h("div", { class: "empty" }, "جارٍ التحميل…");
    sheet("طلباتي", box);
    try {
      const items = await api("GET", "/orders");
      if (!items.length) { box.replaceWith(h("div", { class: "empty" }, "لا توجد طلبات بعد. اكتب للمساعد ما تحتاجه وسيجهّز لك الطلب.")); return; }
      box.replaceWith(...items.map((o) => {
        const [lbl, cls] = LIVE[o.status] || [o.status_text, ""];
        return h("div", { class: "order" },
          h("div", { class: "t" }, h("b", null, `${o.quantity} مزرعة — المستوى ${o.offer.lvl}`), h("span", { class: "chip " + cls }, lbl)),
          h("div", { class: "s" }, h("span", { class: "num" }, o.ref), "  ·  ", h("span", { class: "num" }, `${o.total} ${o.currency}`)),
          o.reason ? h("div", { class: "s" }, o.reason) : null,
          o.status === "delivered" ? h("button", { class: "btn green block", onclick: () => showFarms(o.id) }, "عرض بيانات المزارع") : null);
      }));
    } catch (ex) { box.textContent = ex.message; }
  }

  async function showFarms(orderId) {
    try {
      const r = await api("GET", `/orders/${orderId}/farms`);
      const text = r.farms.map((f) => `ID: ${f.id}\nPassword: ${f.password}`).join("\n\n");
      sheet(`بيانات الطلب ${r.ref}`, [
        h("div", { class: "creds" }, text),
        h("button", { class: "btn primary block", onclick: () => copy(text, "تم نسخ البيانات") }, "نسخ الكل"),
        h("p", { class: "hint" }, "احفظ البيانات ولا تشاركها مع أحد.")]);
    } catch (ex) { toast(ex.message, true); }
  }

  // --------------------------------------------------------------- boot
  if ("serviceWorker" in navigator && !Android) navigator.serviceWorker.register("/sw.js").catch(() => {});
  if (LS.get("hd_token")) start(); else renderLogin();
})();
