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
  const I18N = {"ar": {"copied": "تم النسخ", "copy_manual": "انسخ يدوياً", "offline": "لا يوجد اتصال بالإنترنت.", "sign_in": "سجّل الدخول", "code_label": "كود الدخول", "enter": "دخول", "tagline": "مساعدك الذكي لشراء مزارع Hay Day. أدخل الكود الذي استلمته من الإدارة.", "one_device": "الكود يعمل على جهاز واحد فقط، وتبقى مسجّلاً بعد الدخول.", "full_code": "اكتب الكود كاملاً.", "typing": "يكتب", "type_msg": "اكتب رسالتك…", "message": "رسالة", "send": "إرسال", "send_proof_aria": "إرسال صورة إثبات التحويل", "proof_title": "صورة إثبات التحويل", "online": "متصل الآن", "my_orders": "طلباتي", "logout": "خروج", "logout_q": "تسجيل الخروج؟ يمكنك الدخول مرة أخرى بنفس الكود على هذا الجهاز فقط.", "new_msg": "رسالة جديدة", "too_big": "الصورة أكبر من 8MB.", "proof_sent": "تم إرسال صورة التحويل", "proof_for": "صورة إثبات التحويل للطلب ", "support": "فريق الدعم", "summary": "ملخص الطلب", "lvl": "المستوى", "barn": "المخزن", "silo": "الصومعة", "tools": "الأدوات", "confirm_buy": "تأكيد الشراء", "cancel": "إلغاء", "choose_method": "اختر وسيلة الدفع", "pay_via": "الدفع عبر ", "amount": "المبلغ", "amount_copied": "تم نسخ المبلغ", "copy": "نسخ", "account": "المعرّف", "account_copied": "تم نسخ المعرّف", "pay_note": "حوّل المبلغ بالضبط، ثم أرسل صورة التحويل فقط. لا حاجة لرقم العملية.", "send_proof": "إرسال صورة التحويل", "delivered": "تم التسليم", "show_farms": "عرض بيانات المزارع", "order_state": "حالة الطلب: ", "close": "إغلاق", "loading": "جارٍ التحميل…", "no_orders": "لا توجد طلبات بعد. اكتب للمساعد ما تحتاجه وسيجهّز لك الطلب.", "data_copied": "تم نسخ البيانات", "copy_all": "نسخ الكل", "keep_safe": "احفظ البيانات ولا تشاركها مع أحد.", "st_pending_confirmation": "بانتظار تأكيدك", "st_awaiting_payment": "بانتظار الدفع", "st_proof_received": "استلمنا الإثبات", "st_payment_review": "الدفع قيد المراجعة", "st_payment_confirmed": "الدفع مؤكد", "st_processing": "قيد التجهيز", "st_delivered": "تم التسليم", "st_cancelled": "ملغي", "st_rejected": "مرفوض", "farms_n": "{n} مزرعة — المستوى {lvl}", "delivered_note": "{n} مزرعة — المستوى {lvl}. هذه بيانات حساباتك، وهي محفوظة أيضًا في «طلباتي».", "order_data": "بيانات الطلب ", "language": "اللغة", "err_bad_code": "الكود غير صحيح أو موقوف.", "err_other_device": "هذا الكود مفعّل على جهاز آخر. لا يمكن استخدامه على أكثر من جهاز — تواصل مع الإدارة.", "err_banned": "هذا الحساب موقوف. تواصل مع الإدارة.", "err_session": "انتهت الجلسة. سجّل الدخول من جديد.", "err_many": "محاولات كثيرة، انتظر قليلاً ثم حاول.", "tt_land": "أرض", "tt_barn": "حظيرة", "tt_silo": "صومعة", "type_n": "النوع {n}", "farms_lvl": "{n} × مستوى {lvl}", "total_amount": "المبلغ الإجمالي", "total_farms": "إجمالي المزارع", "confirm_q": "هل تريد تأكيد الطلب والانتقال إلى الدفع؟", "yes_pay": "نعم، ادفع", "edit_order": "تعديل الطلب"}, "en": {"copied": "Copied", "copy_manual": "Copy it manually", "offline": "No internet connection.", "sign_in": "Please sign in", "code_label": "Access code", "enter": "Sign in", "tagline": "Your smart assistant for buying Hay Day farms. Enter the code you received from the store.", "one_device": "The code works on one device only, and you stay signed in.", "full_code": "Enter the full code.", "typing": "Typing", "type_msg": "Type a message…", "message": "Message", "send": "Send", "send_proof_aria": "Send transfer screenshot", "proof_title": "Transfer screenshot", "online": "Online", "my_orders": "My orders", "logout": "Sign out", "logout_q": "Sign out? You can sign in again with the same code on this device only.", "new_msg": "New message", "too_big": "The image is larger than 8MB.", "proof_sent": "Screenshot sent", "proof_for": "Transfer screenshot for order ", "support": "Support team", "summary": "Order summary", "lvl": "Level", "barn": "Barn", "silo": "Silo", "tools": "Tools", "confirm_buy": "Confirm purchase", "cancel": "Cancel", "choose_method": "Choose a payment method", "pay_via": "Pay with ", "amount": "Amount", "amount_copied": "Amount copied", "copy": "Copy", "account": "Account", "account_copied": "Account copied", "pay_note": "Transfer the exact amount, then send only the screenshot. No transaction ID needed.", "send_proof": "Send transfer screenshot", "delivered": "Delivered", "show_farms": "Show farm details", "order_state": "Order status: ", "close": "Close", "loading": "Loading…", "no_orders": "No orders yet. Tell the assistant what you need and it will prepare your order.", "data_copied": "Details copied", "copy_all": "Copy all", "keep_safe": "Keep these details private.", "st_pending_confirmation": "Awaiting your confirmation", "st_awaiting_payment": "Awaiting payment", "st_proof_received": "Proof received", "st_payment_review": "Payment under review", "st_payment_confirmed": "Payment confirmed", "st_processing": "Being prepared", "st_delivered": "Delivered", "st_cancelled": "Cancelled", "st_rejected": "Rejected", "farms_n": "{n} farm(s) — level {lvl}", "delivered_note": "{n} farm(s) — level {lvl}. Here are your account details; they're also saved in “My orders”.", "order_data": "Order details ", "language": "Language", "err_bad_code": "The code is wrong or disabled.", "err_other_device": "This code is already active on another device. It can't be used on more than one device — contact the store.", "err_banned": "This account is suspended. Contact the store.", "err_session": "Session ended. Please sign in again.", "err_many": "Too many attempts, please wait a moment.", "tt_land": "land", "tt_barn": "barn", "tt_silo": "silo", "type_n": "Type {n}", "farms_lvl": "{n} × level {lvl}", "total_amount": "Total amount", "total_farms": "Total farms", "confirm_q": "Confirm the order and go to payment?", "yes_pay": "Yes, pay", "edit_order": "Edit order"}, "vi": {"copied": "Đã sao chép", "copy_manual": "Hãy sao chép thủ công", "offline": "Không có kết nối Internet.", "sign_in": "Vui lòng đăng nhập", "code_label": "Mã truy cập", "enter": "Đăng nhập", "tagline": "Trợ lý thông minh mua nông trại Hay Day. Nhập mã bạn nhận được từ cửa hàng.", "one_device": "Mã chỉ dùng được trên một thiết bị và bạn sẽ luôn được đăng nhập.", "full_code": "Nhập đầy đủ mã.", "typing": "Đang nhập", "type_msg": "Nhập tin nhắn…", "message": "Tin nhắn", "send": "Gửi", "send_proof_aria": "Gửi ảnh chuyển khoản", "proof_title": "Ảnh chuyển khoản", "online": "Đang trực tuyến", "my_orders": "Đơn hàng", "logout": "Đăng xuất", "logout_q": "Đăng xuất? Bạn có thể đăng nhập lại bằng cùng mã trên thiết bị này.", "new_msg": "Tin nhắn mới", "too_big": "Ảnh lớn hơn 8MB.", "proof_sent": "Đã gửi ảnh chuyển khoản", "proof_for": "Ảnh chuyển khoản cho đơn ", "support": "Đội hỗ trợ", "summary": "Tóm tắt đơn hàng", "lvl": "Cấp", "barn": "Kho", "silo": "Silo", "tools": "Công cụ", "confirm_buy": "Xác nhận mua", "cancel": "Hủy", "choose_method": "Chọn phương thức thanh toán", "pay_via": "Thanh toán qua ", "amount": "Số tiền", "amount_copied": "Đã sao chép số tiền", "copy": "Sao chép", "account": "Tài khoản", "account_copied": "Đã sao chép tài khoản", "pay_note": "Chuyển đúng số tiền rồi chỉ cần gửi ảnh chụp. Không cần mã giao dịch.", "send_proof": "Gửi ảnh chuyển khoản", "delivered": "Đã giao", "show_farms": "Xem thông tin nông trại", "order_state": "Trạng thái đơn: ", "close": "Đóng", "loading": "Đang tải…", "no_orders": "Chưa có đơn hàng. Hãy nói với trợ lý bạn cần gì.", "data_copied": "Đã sao chép thông tin", "copy_all": "Sao chép tất cả", "keep_safe": "Hãy giữ thông tin này bí mật.", "st_pending_confirmation": "Chờ bạn xác nhận", "st_awaiting_payment": "Chờ thanh toán", "st_proof_received": "Đã nhận bằng chứng", "st_payment_review": "Đang kiểm tra thanh toán", "st_payment_confirmed": "Đã xác nhận thanh toán", "st_processing": "Đang chuẩn bị", "st_delivered": "Đã giao", "st_cancelled": "Đã hủy", "st_rejected": "Bị từ chối", "farms_n": "{n} nông trại — cấp {lvl}", "delivered_note": "{n} nông trại — cấp {lvl}. Đây là thông tin tài khoản, cũng được lưu trong “Đơn hàng”.", "order_data": "Thông tin đơn ", "language": "Ngôn ngữ", "err_bad_code": "Mã không đúng hoặc đã bị khóa.", "err_other_device": "Mã này đã được dùng trên thiết bị khác. Không thể dùng trên nhiều thiết bị — hãy liên hệ cửa hàng.", "err_banned": "Tài khoản đã bị khóa. Hãy liên hệ cửa hàng.", "err_session": "Phiên đã hết. Vui lòng đăng nhập lại.", "err_many": "Quá nhiều lần thử, vui lòng đợi.", "tt_land": "đất", "tt_barn": "kho", "tt_silo": "silo", "type_n": "Loại {n}", "farms_lvl": "{n} × cấp {lvl}", "total_amount": "Tổng số tiền", "total_farms": "Tổng nông trại", "confirm_q": "Xác nhận đơn và chuyển sang thanh toán?", "yes_pay": "Có, thanh toán", "edit_order": "Sửa đơn"}, "zh": {"copied": "已复制", "copy_manual": "请手动复制", "offline": "没有网络连接。", "sign_in": "请登录", "code_label": "访问码", "enter": "登录", "tagline": "购买 Hay Day 农场的智能助手。请输入商店给您的访问码。", "one_device": "访问码仅限一台设备使用，登录后保持登录状态。", "full_code": "请输入完整的访问码。", "typing": "正在输入", "type_msg": "输入消息…", "message": "消息", "send": "发送", "send_proof_aria": "发送转账截图", "proof_title": "转账截图", "online": "在线", "my_orders": "我的订单", "logout": "退出", "logout_q": "确定退出？之后只能在本设备上用同一访问码再次登录。", "new_msg": "新消息", "too_big": "图片超过 8MB。", "proof_sent": "截图已发送", "proof_for": "转账截图，订单 ", "support": "客服团队", "summary": "订单摘要", "lvl": "等级", "barn": "仓库", "silo": "粮仓", "tools": "工具", "confirm_buy": "确认购买", "cancel": "取消", "choose_method": "选择支付方式", "pay_via": "付款方式：", "amount": "金额", "amount_copied": "已复制金额", "copy": "复制", "account": "账号", "account_copied": "已复制账号", "pay_note": "请转账准确金额，然后只需发送截图，无需交易编号。", "send_proof": "发送转账截图", "delivered": "已交付", "show_farms": "查看农场信息", "order_state": "订单状态：", "close": "关闭", "loading": "加载中…", "no_orders": "还没有订单。告诉助手您需要什么，它会为您准备订单。", "data_copied": "已复制信息", "copy_all": "全部复制", "keep_safe": "请妥善保管，不要分享给他人。", "st_pending_confirmation": "待您确认", "st_awaiting_payment": "待付款", "st_proof_received": "已收到凭证", "st_payment_review": "付款审核中", "st_payment_confirmed": "付款已确认", "st_processing": "准备中", "st_delivered": "已交付", "st_cancelled": "已取消", "st_rejected": "已拒绝", "farms_n": "{n} 个农场 — 等级 {lvl}", "delivered_note": "{n} 个农场 — 等级 {lvl}。以下是账号信息，也保存在“我的订单”中。", "order_data": "订单信息 ", "language": "语言", "err_bad_code": "访问码错误或已停用。", "err_other_device": "此访问码已在另一台设备上使用，不能在多台设备上使用，请联系商店。", "err_banned": "此账号已停用，请联系商店。", "err_session": "会话已结束，请重新登录。", "err_many": "尝试次数过多，请稍后再试。", "tt_land": "土地", "tt_barn": "仓库", "tt_silo": "粮仓", "type_n": "类型 {n}", "farms_lvl": "{n} × 等级 {lvl}", "total_amount": "总金额", "total_farms": "农场总数", "confirm_q": "确认订单并前往付款？", "yes_pay": "是，去付款", "edit_order": "修改订单"}};
  const LANG_NAMES = [["ar", "العربية"], ["en", "English"], ["vi", "Tiếng Việt"], ["zh", "中文"]];
  const I18N_MORE = {
    ar: { notifs: "الإشعارات", no_notifs: "لا توجد إشعارات بعد.", bal_enough: "رصيدك {b} يكفي لهذا الطلب — ادفع منه بضغطة واحدة، أو اختر وسيلة دفع أخرى.", balance: "الرصيد", balance_avail: "رصيدك المتوفر", pay_balance: "الدفع من الرصيد", no_moves: "لا توجد حركات على رصيدك بعد.",
          k_topup: "إضافة رصيد", k_deduct: "خصم", k_order: "دفع طلب", k_refund: "استرجاع", balance_hint: "لإضافة رصيد تواصل مع الإدارة، ويُضاف إلى حسابك عبر كود الدخول.",
          yes: "نعم", no: "إلغاء" },
    en: { notifs: "Notifications", no_notifs: "No notifications yet.", bal_enough: "Your balance {b} covers this order — pay with one tap, or choose another method.", balance: "Balance", balance_avail: "Available balance", pay_balance: "Pay from balance", no_moves: "No balance activity yet.",
          k_topup: "Top-up", k_deduct: "Deduction", k_order: "Order payment", k_refund: "Refund", balance_hint: "To add balance, contact the store; it is added to your account by your access code.",
          yes: "Yes", no: "Cancel" },
    vi: { notifs: "Thông báo", no_notifs: "Chưa có thông báo.", bal_enough: "Số dư {b} đủ cho đơn này — thanh toán bằng một chạm, hoặc chọn phương thức khác.", balance: "Số dư", balance_avail: "Số dư hiện có", pay_balance: "Thanh toán bằng số dư", no_moves: "Chưa có giao dịch số dư.",
          k_topup: "Nạp tiền", k_deduct: "Trừ tiền", k_order: "Thanh toán đơn", k_refund: "Hoàn tiền", balance_hint: "Để nạp số dư, hãy liên hệ cửa hàng; số dư được cộng theo mã truy cập của bạn.",
          yes: "Có", no: "Hủy" },
    zh: { notifs: "通知", no_notifs: "暂无通知。", bal_enough: "您的余额 {b} 足够支付此订单——一键支付，或选择其他方式。", balance: "余额", balance_avail: "可用余额", pay_balance: "用余额支付", no_moves: "暂无余额记录。",
          k_topup: "充值", k_deduct: "扣除", k_order: "订单付款", k_refund: "退款", balance_hint: "如需充值请联系商店，余额会按您的访问码充入账户。",
          yes: "是", no: "取消" },
  };
  for (const [l, v] of Object.entries(I18N_MORE)) Object.assign(I18N[l], v);
  let LANG = LS.get("hd_lang") || "ar";   // Arabic by default; the customer picks on the sign-in screen
  const T = (k, vars) => { let s = (I18N[LANG] || I18N.en)[k] ?? I18N.en[k] ?? k; if (vars) for (const [a, b] of Object.entries(vars)) s = s.replace("{" + a + "}", b); return s; };
  document.documentElement.dataset.theme = "light";   // the app is always the white theme
  function applyLang() {
    document.documentElement.lang = LANG; document.documentElement.dir = LANG === "ar" ? "rtl" : "ltr";
    document.title = "HD Agent";
  }
  applyLang();
  function setLang(code) { LANG = code; LS.set("hd_lang", code); applyLang(); }

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
    bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    wallet: '<path d="M19 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0 0 4h14a2 2 0 0 1 2 2v3"/><path d="M3 5v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-3"/><path d="M21 12h-4a2 2 0 0 0 0 4h4z"/>',
  };
  const botMark = (size) => {
    const s = svg(I.bot); s.setAttribute("width", size); s.setAttribute("height", size); s.style.color = "#123524"; return s;
  };
  function toast(msg, bad) {
    const t = h("div", { class: bad ? "bad" : "" }, msg);
    document.getElementById("toast").append(t);
    setTimeout(() => t.remove(), bad ? 5000 : 2600);
  }
  const fmtTime = (s) => { try { return new Date(s).toLocaleTimeString(LANG === "zh" ? "zh-CN" : LANG, { hour: "2-digit", minute: "2-digit" }); } catch { return ""; } };
  async function copy(text, label) {
    try {
      if (Android && Android.copy) Android.copy(text);
      else await navigator.clipboard.writeText(text);
      toast(label || T("copied"));
    } catch {
      const ta = h("textarea", { style: "position:fixed;opacity:0" }); ta.value = text; document.body.append(ta); ta.select();
      try { document.execCommand("copy"); toast(label || T("copied")); } catch { toast(T("copy_manual"), true); }
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
    try { res = await fetch("/app/api" + path, opts); } catch { throw new ApiError(T("offline")); }
    let data = {};
    try { data = await res.json(); } catch { /* empty */ }
    const msg = ({ bad_code: T("err_bad_code"), other_device: T("err_other_device"), banned: T("err_banned") })[data.code]
      || (res.status === 429 ? T("err_many") : null) || data.error || `Error ${res.status}`;
    if (res.status === 401 && path !== "/login") { LS.del("hd_token"); stopPolling(); renderLogin(T("err_session")); throw new ApiError(T("err_session")); }
    if (!res.ok || data.ok === false) throw new ApiError(msg);
    return data.data;
  }

  // -------------------------------------------------------------- login
  function renderLogin(msg) {
    const input = h("input", { inputmode: "text", autocomplete: "one-time-code", autocapitalize: "characters", spellcheck: "false",
      maxlength: "20", placeholder: "XXXXXXXX", "aria-label": T("code_label") });
    const err = h("div", { class: "err", role: "alert" }, msg || "");
    const btn = h("button", { class: "btn primary block", type: "submit" }, T("enter"));
    const langName = (LANG_NAMES.find(([c]) => c === LANG) || LANG_NAMES[0])[1];
    const langBtn = h("button", { type: "button", class: "login-lang", "aria-label": T("language"),
      onclick: () => openLang((code) => { const keep = input.value; setLang(code); renderLogin(); const i = root.querySelector(".code-field input"); if (i) i.value = keep; }) },
      svg(I.globe), h("span", null, langName));
    const form = h("form", { class: "login" },
      h("div", { class: "login-top" }, langBtn),
      h("div", { class: "login-card" },
        h("div", { class: "bot" }, (() => { const s = svg(I.bot); s.setAttribute("width", 48); s.setAttribute("height", 48); s.style.color = "#F2C14E"; return s; })()),
        h("h1", null, "HD Agent"), h("p", { class: "tag" }, T("tagline")),
        h("label", { class: "code-field" }, h("span", null, "HD-"), input),
        err, btn,
        h("p", { class: "hint" }, T("one_device"))));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const raw = input.value.trim().toUpperCase().replace(/^HD-?/, "");
      if (raw.length < 4) { err.textContent = T("full_code"); return; }
      btn.disabled = true; err.textContent = "";
      try {
        const r = await api("POST", "/login", { code: "HD-" + raw, device_id: deviceId(), device_label: deviceLabel(), lang: LANG });
        LS.set("hd_token", r.token);
        start();
      } catch (ex) { err.textContent = ex.message; btn.disabled = false; }
    });
    root.replaceChildren(form);
    setTimeout(() => input.focus(), 50);
  }

  // --------------------------------------------------------------- chat
  const state = { last: 0, states: {}, nodes: new Map(), busy: false, timer: null, me: null, balance: "0.00" };
  let log, ta, sendBtn, attachBtn, fileIn, typing, balBtn, bellBtn;
  const NOTICE_KINDS = ["notice", "delivered"];
  const seenKey = () => "hd_seen_" + ((state.me && state.me.id) || "");
  function notices() { return [...state.nodes.values()].map((x) => x.m).filter((m) => NOTICE_KINDS.includes(m.kind)); }
  function refreshBell() {
    if (!bellBtn) return;
    const list = notices();
    let seen = Number(LS.get(seenKey()));
    if (!LS.get(seenKey())) { seen = list.reduce((a, m) => Math.max(a, m.id), 0); LS.set(seenKey(), String(seen)); }
    const n = list.filter((m) => m.id > seen).length;
    const badge = bellBtn.querySelector(".badge");
    badge.textContent = n > 9 ? "9+" : String(n); badge.hidden = !n;
    bellBtn.setAttribute("aria-label", T("notifs") + (n ? ` (${n})` : ""));
  }
  function setBalance(b) {
    if (b === undefined || b === null) return;
    state.balance = b;
    if (balBtn) { balBtn.querySelector(".amt").textContent = "$" + b; balBtn.setAttribute("aria-label", T("balance_avail") + " $" + b); }
  }

  function stopPolling() { clearTimeout(state.timer); state.timer = null; }

  async function start() {
    let me;
    try { me = await api("GET", "/me"); } catch { return; }
    state.me = me; state.last = 0; state.nodes.clear();
    renderChat();
    setBalance(me.balance);
    await poll(true);
  }

  function renderChat() {
    log = h("main", { class: "log", "aria-live": "polite" });
    typing = h("div", { class: "typing", hidden: true, "aria-label": T("typing") }, h("i"), h("i"), h("i"));
    ta = h("textarea", { rows: 1, placeholder: T("type_msg"), "aria-label": T("message"), dir: "auto" });
    sendBtn = h("button", { class: "round send", "aria-label": T("send") }, svg(I.send));
    fileIn = h("input", { type: "file", accept: "image/*", hidden: true });
    attachBtn = h("button", { class: "round attach", "aria-label": T("send_proof_aria"), title: T("proof_title") }, svg(I.clip));
    ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 140) + "px"; });
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && window.matchMedia("(pointer:fine)").matches) { e.preventDefault(); send(); } });
    sendBtn.addEventListener("click", send);
    attachBtn.addEventListener("click", () => fileIn.click());
    fileIn.addEventListener("change", () => { if (fileIn.files[0]) uploadProof(fileIn.files[0]); fileIn.value = ""; });
    root.replaceChildren(
      h("header", { class: "top" },
        h("div", { class: "av" }, botMark(26)),
        h("div", { class: "who" }, h("b", null, "HD Agent"), h("small", null, T("online"))),
        balBtn = h("button", { class: "bal-btn", title: T("balance"), onclick: openBalance }, svg(I.wallet), h("span", { class: "amt num" }, "$" + state.balance)),
        bellBtn = h("button", { class: "icon-btn c-bell", "aria-label": T("notifs"), title: T("notifs"), onclick: openNotices }, svg(I.bell), h("span", { class: "badge", hidden: true })),
        h("button", { class: "icon-btn c-lang", "aria-label": T("language"), title: T("language"), onclick: openLang }, svg(I.globe), h("span", { class: "lang-code" }, LANG.toUpperCase())),
        h("button", { class: "icon-btn c-orders", "aria-label": T("my_orders"), title: T("my_orders"), onclick: openOrders }, svg(I.box)),
        h("button", { class: "icon-btn c-out", "aria-label": T("logout"), title: T("logout"), onclick: logout }, svg(I.logout))),
      log, h("div", { class: "composer" }, attachBtn, ta, sendBtn, fileIn));
    log.append(typing);
  }

  async function logout() {
    if (!await ask(T("logout_q"), T("logout"))) return;
    LS.del("hd_token"); stopPolling(); renderLogin();
  }

  // in-app confirmation (the browser's confirm() shows the site address in the Android app)
  function ask(text, yesLabel) {
    return new Promise((resolve) => {
      const done = (v) => { bg.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
      const onKey = (e) => { if (e.key === "Escape") done(false); };
      const yes = h("button", { class: "btn danger-fill", onclick: () => done(true) }, yesLabel || T("yes"));
      const bg = h("div", { class: "dlg-bg", onclick: (e) => { if (e.target === bg) done(false); } },
        h("div", { class: "dlg", role: "alertdialog", "aria-modal": "true" },
          h("div", { class: "dlg-ic" }, svg(I.logout)),
          h("p", null, text),
          h("div", { class: "dlg-acts" }, h("button", { class: "btn", onclick: () => done(false) }, T("no")), yes)));
      document.addEventListener("keydown", onKey);
      document.body.append(bg);
      yes.focus();
    });
  }

  async function poll(first) {
    stopPolling();
    try {
      const r = await api("GET", "/messages" + (state.last ? "?after=" + state.last : ""));
      state.states = r.states || {};
      setBalance(r.balance);
      const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 140;
      for (const m of r.messages) { addMessage(m); state.last = Math.max(state.last, m.id); }
      refreshCards();
      refreshBell();
      if (first || r.messages.length && nearBottom) scrollDown();
      else if (r.messages.length) toast(T("new_msg"));
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
    if (file.size > 8 * 1024 * 1024) { toast(T("too_big"), true); return; }
    const fd = new FormData(); fd.append("file", file);
    attachBtn.disabled = true; typing.hidden = false; scrollDown();
    try { await api("POST", "/proof", fd, true); toast(T("proof_sent")); }
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
      node = m.kind === "proof" ? h("div", { class: "b me" }, T("proof_for"), h("span", { class: "num" }, (m.payload || {}).ref || ""))
        : h("div", { class: "b me" }, m.text);
    } else if (m.role === "admin") {
      node = h("div", { class: "b staff" }, h("span", { class: "by" }, T("support")), m.text);
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

  const ORD_AR = ["النوع الأول", "النوع الثاني", "النوع الثالث", "النوع الرابع", "النوع الخامس", "النوع السادس"];
  const ordinal = (i) => (LANG === "ar" && ORD_AR[i]) || T("type_n", { n: i + 1 });
  function farmsCount(n) {
    if (LANG === "ar") return n === 1 ? "مزرعة واحدة" : n === 2 ? "مزرعتان" : n <= 10 ? `${n} مزارع` : `${n} مزرعة`;
    return { en: `${n} farm${n === 1 ? "" : "s"}`, vi: `${n} nông trại`, zh: `${n} 个农场` }[LANG] || String(n);
  }
  const orderState = (id) => (state.states[String(id)] || {}).status;

  function card(m) {
    const p = m.payload || {};
    if (m.kind === "order_summary") {
      const lines = p.lines || [{ lvl: p.lvl, barn: p.barn, silo: p.silo, tools: p.tools, tool_type: p.tool_type, quantity: p.quantity, unit_price: p.unit_price }];
      const totalQty = p.total_qty || lines.reduce((a, x) => a + x.quantity, 0);
      const t = h("section", { class: "ticket", "aria-label": T("summary") },
        h("div", { class: "band" }, T("summary"), h("span", { class: "ref num" }, p.ref)),
        h("div", { class: "body" },
          lines.map((x, i) => h("div", { class: "line" },
            lines.length > 1 ? h("div", { class: "line-h" }, ordinal(i)) : null,
            h("div", { class: "line-main" }, `${farmsCount(x.quantity)} — ${T("lvl")} ${x.lvl}`),
            h("div", { class: "line-sub" }, `${T("barn")} ${x.barn} · ${T("silo")} ${x.silo} · ${T("tools")} ${T("tt_" + (x.tool_type || "land"))} ${x.tools}`),
            h("div", { class: "line-calc num" }, `${x.quantity} × ${x.unit_price} ${p.currency}`))),
          h("hr", { class: "perf" }),
          h("div", { class: "total" },
            h("div", null, h("div", { class: "calc" }, T("total_amount")), h("div", { class: "big num" }, `${p.total} ${p.currency}`)),
            h("div", { class: "calc" }, T("total_farms"), h("div", null, h("b", { class: "num" }, totalQty))))),
        h("div", { class: "ask" }, T("confirm_q")),
        h("div", { class: "acts" },
          h("button", { class: "btn green", "data-act": "confirm", onclick: () => act(() => api("POST", `/orders/${p.order_id}/confirm`)) }, "✅ " + T("yes_pay")),
          h("button", { class: "btn", "data-act": "edit", onclick: () => act(() => api("POST", `/orders/${p.order_id}/edit`)) }, "✏️ " + T("edit_order"))),
        h("div", { class: "state" }));
      t.dataset.order = p.order_id;
      return t;
    }
    if (m.kind === "methods") {
      const t = h("section", { class: "ticket pay" },
        h("div", { class: "band" }, T("choose_method"), h("span", { class: "ref num" }, p.ref)),
        p.balance ? h("div", { class: "body" }, h("div", { class: "instr" }, T("bal_enough", { b: "$" + p.balance }))) : null,
        h("div", { class: "acts", style: "flex-direction:column" },
          p.balance ? h("button", { class: "btn wallet-pay", "data-act": "balance", onclick: () => act(async () => { const r = await api("POST", `/orders/${p.order_id}/pay-balance`); setBalance(r.balance); }) },
            svg(I.wallet), T("pay_balance") + " — ", h("span", { dir: "ltr" }, "$" + p.total)) : null,
          (p.methods || []).map((x) =>
          h("button", { class: "btn", "data-act": "method", onclick: () => act(() => api("POST", `/orders/${p.order_id}/method`, { method_id: x.id })) }, x.name))),
        h("div", { class: "state" }));
      t.dataset.order = p.order_id;
      return t;
    }
    if (m.kind === "pay_details") {
      const t = h("section", { class: "ticket pay" },
        h("div", { class: "band" }, T("pay_via") + p.method, h("span", { class: "ref num" }, p.ref)),
        h("div", { class: "body" },
          h("div", { class: "row" }, h("span", { class: "k" }, T("amount")),
            h("span", { class: "v" }, h("span", { class: "num" }, `${p.total} ${p.currency}`), h("button", { class: "copy", onclick: () => copy(p.amount, T("amount_copied")) }, T("copy")))),
          h("div", { class: "row" }, h("span", { class: "k" }, T("account")),
            h("span", { class: "v" }, h("span", { class: "num" }, p.account), h("button", { class: "copy", onclick: () => copy(p.account, T("account_copied")) }, T("copy")))),
          p.instructions ? h("div", { class: "instr" }, p.instructions) : null,
          h("div", { class: "instr" }, T("pay_note"))),
        h("div", { class: "acts" }, h("button", { class: "btn primary", "data-act": "proof", onclick: () => fileIn.click() }, T("send_proof"))),
        h("div", { class: "state" }));
      t.dataset.order = p.order_id;
      return t;
    }
    if (m.kind === "delivered") {
      const box = h("div", { class: "creds", hidden: true });
      const copyBtn = h("button", { class: "btn primary", hidden: true }, T("copy_all"));
      const t = h("section", { class: "ticket done" },
        h("div", { class: "band" }, T("delivered"), h("span", { class: "ref num" }, p.ref)),
        h("div", { class: "body" }, h("div", { class: "instr" }, T("delivered_note", { n: p.count, lvl: p.lvl })), box),
        h("div", { class: "acts" }, copyBtn, h("button", { class: "btn green", onclick: () => showFarms(p.order_id) }, T("show_farms"))));
      api("GET", `/orders/${p.order_id}/farms`).then((r) => {
        const text = r.farms.map((f) => `ID: ${f.id}\nPassword: ${f.password}`).join("\n\n");
        box.textContent = text; box.hidden = false;
        copyBtn.hidden = false; copyBtn.onclick = () => copy(text, T("data_copied"));
      }).catch(() => {});
      return t;
    }
    return null;
  }

  const LIVE_CLS = { pending_confirmation: "", awaiting_payment: "warn", proof_received: "warn", payment_review: "warn", payment_confirmed: "ok",
    processing: "ok", delivered: "ok", cancelled: "bad", rejected: "bad" };
  const LIVE = new Proxy({}, { get: (_, st) => (typeof st === "string" && st in LIVE_CLS) ? [T("st_" + st), LIVE_CLS[st]] : undefined });

  function refreshCards() {
    for (const { node, m } of state.nodes.values()) {
      if (!node.dataset || !node.dataset.order) continue;
      const st = orderState(node.dataset.order);
      const method = (state.states[node.dataset.order] || {}).method;
      const enable = { order_summary: st === "pending_confirmation", methods: st === "awaiting_payment" && !method, pay_details: st === "awaiting_payment" }[m.kind];
      node.querySelectorAll("[data-act]").forEach((b) => { b.disabled = !enable; });
      const acts = node.querySelector(".acts");
      if (acts) acts.hidden = !enable;
      const ask = node.querySelector(".ask");
      if (ask) ask.hidden = !enable;
      const stEl = node.querySelector(".state");
      if (stEl) stEl.textContent = !enable && st ? T("order_state") + (LIVE[st] || [st])[0] : "";
    }
  }

  // ------------------------------------------------------------- sheets
  function sheet(title, content) {
    const bg = h("div", { class: "sheet-bg" });
    const close = () => bg.remove();
    bg.addEventListener("click", (e) => { if (e.target === bg) close(); });
    bg.append(h("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-label": title },
      h("header", null, h("h2", null, title), h("button", { class: "btn ghost", "aria-label": T("close"), onclick: close }, svg(I.x))),
      h("div", { class: "content" }, content)));
    document.body.append(bg);
    return { close };
  }

  function openLang(onPick) {
    const sh = sheet(T("language"), h("div", { class: "langs" }, LANG_NAMES.map(([code, name]) =>
      h("button", { type: "button", class: "lang" + (code === LANG ? " on" : ""), lang: code, onclick: async () => {
        sh.close();
        if (typeof onPick === "function") { onPick(code); return; }
        setLang(code);
        try { await api("POST", "/lang", { lang: code }); } catch { /* offline: UI still switches */ }
        start();
      } }, name))));
  }

  function openNotices() {
    const list = notices().slice().reverse();
    LS.set(seenKey(), String(list.reduce((a, m) => Math.max(a, m.id), Number(LS.get(seenKey())) || 0)));
    refreshBell();
    sheet(T("notifs"), list.length ? h("div", { class: "moves" }, list.slice(0, 50).map((m) => h("div", { class: "notif" },
      h("div", { class: "notif-ic" + (m.kind === "delivered" ? " ok" : "") }, svg(m.kind === "delivered" ? I.box : I.bell)),
      h("div", null, h("div", null, m.kind === "delivered" ? `${T("delivered")} — ${(m.payload || {}).ref || ""}` : m.text),
        h("div", { class: "s" }, new Date(m.at).toLocaleString(LANG === "ar" ? "ar-EG" : LANG))))))
      : h("div", { class: "empty" }, T("no_notifs")));
  }

  async function openBalance() {
    const list = h("div", { class: "empty" }, T("loading"));
    const amt = h("div", { class: "bal-big num" }, "$" + state.balance);
    sheet(T("balance"), [h("div", { class: "bal-card" }, h("div", { class: "bal-ic" }, svg(I.wallet)),
      h("div", null, h("small", null, T("balance_avail")), amt)), h("p", { class: "hint" }, T("balance_hint")), list]);
    try {
      const r = await api("GET", "/balance");
      setBalance(r.balance); amt.textContent = "$" + r.balance;
      if (!r.items.length) { list.textContent = T("no_moves"); return; }
      list.replaceWith(h("div", { class: "moves" }, r.items.map((x) => h("div", { class: "move" },
        h("div", null, h("b", null, T("k_" + x.kind)), x.ref ? " " : null, x.ref ? h("small", { class: "num ref-s" }, x.ref) : null,
          h("div", { class: "s" }, new Date(x.at).toLocaleString(LANG === "ar" ? "ar-EG" : LANG))),
        h("span", { class: "num " + (x.delta.startsWith("-") ? "neg" : "pos") }, (x.delta.startsWith("-") ? "−$" + x.delta.slice(1) : "+$" + x.delta))))));
    } catch (ex) { list.textContent = ex.message; }
  }

  async function openOrders() {
    const box = h("div", { class: "empty" }, T("loading"));
    sheet(T("my_orders"), box);
    try {
      const items = await api("GET", "/orders");
      if (!items.length) { box.replaceWith(h("div", { class: "empty" }, T("no_orders"))); return; }
      box.replaceWith(...items.map((o) => {
        const [lbl, cls] = LIVE[o.status] || [o.status_text, ""];
        return h("div", { class: "order" },
          h("div", { class: "t" }, h("b", null, (o.lines && o.lines.length > 1 ? o.lines.map((x) => `${x.quantity} × ${T("lvl")} ${x.offer.lvl} ${T("tt_" + (x.offer.tool_type || "land"))}`).join(" + ") : T("farms_n", { n: o.quantity, lvl: o.offer.lvl }))), h("span", { class: "chip " + cls }, lbl)),
          h("div", { class: "s" }, h("span", { class: "num" }, o.ref), "  ·  ", h("span", { class: "num" }, `${o.total} ${o.currency}`)),
          o.reason ? h("div", { class: "s" }, o.reason) : null,
          o.status === "delivered" ? h("button", { class: "btn green block", onclick: () => showFarms(o.id) }, T("show_farms")) : null);
      }));
    } catch (ex) { box.textContent = ex.message; }
  }

  async function showFarms(orderId) {
    try {
      const r = await api("GET", `/orders/${orderId}/farms`);
      const text = r.farms.map((f) => `ID: ${f.id}\nPassword: ${f.password}`).join("\n\n");
      sheet(T("order_data") + r.ref, [
        h("div", { class: "creds" }, text),
        h("button", { class: "btn primary block", onclick: () => copy(text, T("data_copied")) }, T("copy_all")),
        h("p", { class: "hint" }, T("keep_safe"))]);
    } catch (ex) { toast(ex.message, true); }
  }

  // --------------------------------------------------------------- boot
  if ("serviceWorker" in navigator && !Android) navigator.serviceWorker.register("/sw.js").catch(() => {});
  if (LS.get("hd_token")) start(); else renderLogin();
})();
