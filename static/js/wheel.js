(() => {
  "use strict";

  const APP_VERSION = "2.0.0";
  const DEFAULTS = Object.freeze({
    currency: "UYU",
    displayName: "Jugador",
    botName: "Ruleta Premium",
    ticketPriceUyu: 250,
    uyuToArs: 25,
    spinDurationMs: 6200,
    reducedSpinDurationMs: 1400,
    requestTimeoutMs: 12000,
    toastDurationMs: 2400,
    errorToastDurationMs: 3200,
    wheelRadius: 47.8,
    wheelCenter: 50,
    idleBallRadius: 42,
    finalBallRadius: 38.4,
    touchBallRadius: 41.4,
    confettiCount: 180,
    reducedConfettiCount: 36,
  });

  const API_PATHS = Object.freeze({
    spin: ["/api/spin"],
    profile: ["/api/user/sync", "/api/profile-sync", "/api/profile"],
    purchase: ["/api/purchase", "/api/create-pending-purchase"],
  });

  const rawConfig = window.RULETA_CONFIG || {};
  const doc = document;
  const root = doc.documentElement;
  const body = doc.body;

  const clampInt = (value, fallback = 0, min = Number.NEGATIVE_INFINITY, max = Number.POSITIVE_INFINITY) => {
    const parsed = Number.parseInt(value, 10);
    const safe = Number.isFinite(parsed) ? parsed : fallback;
    return Math.min(max, Math.max(min, safe));
  };

  const clampFloat = (value, fallback = 0, min = Number.NEGATIVE_INFINITY, max = Number.POSITIVE_INFINITY) => {
    const parsed = Number.parseFloat(value);
    const safe = Number.isFinite(parsed) ? parsed : fallback;
    return Math.min(max, Math.max(min, safe));
  };

  const normalizeText = (value, fallback = "") => {
    const text = String(value ?? "").replace(/\s+/g, " ").trim();
    return text || fallback;
  };

  const normalizeLoose = (value) =>
    normalizeText(value)
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase();

  const normalizeCurrency = (value) => {
    const normalized = normalizeText(value, DEFAULTS.currency).toUpperCase();
    return normalized === "ARS" ? "ARS" : "UYU";
  };

  const normalizeDisplayName = (value) => normalizeText(value, DEFAULTS.displayName).slice(0, 40);

  const safeJsonParse = (value, fallback = null) => {
    try {
      return JSON.parse(value);
    } catch {
      return fallback;
    }
  };

  const escapeHtml = (value) =>
    String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  const splitName = (value) => {
    const clean = normalizeText(value);
    if (!clean) return { first_name: "", last_name: "" };
    const parts = clean.split(" ");
    return {
      first_name: parts.shift() || "",
      last_name: parts.join(" "),
    };
  };

  const cssEscape = (value) => {
    const text = String(value ?? "");
    if (window.CSS && typeof window.CSS.escape === "function") {
      return window.CSS.escape(text);
    }
    return text.replace(/[^a-zA-Z0-9_-]/g, (char) => `\\${char}`);
  };

  const rafThrottle = (fn) => {
    let frame = 0;
    return (...args) => {
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        frame = 0;
        fn(...args);
      });
    };
  };

  const debounce = (fn, delay = 120) => {
    let timer = 0;
    return (...args) => {
      clearTimeout(timer);
      timer = window.setTimeout(() => fn(...args), delay);
    };
  };

  const storage = {
    get(key) {
      try {
        return window.localStorage.getItem(key);
      } catch {
        return null;
      }
    },
    set(key, value) {
      try {
        window.localStorage.setItem(key, value);
      } catch {}
    },
    remove(key) {
      try {
        window.localStorage.removeItem(key);
      } catch {}
    },
  };

  const freezeDeep = (obj) => {
    if (!obj || typeof obj !== "object" || Object.isFrozen(obj)) return obj;
    Object.freeze(obj);
    Object.values(obj).forEach((value) => {
      if (value && typeof value === "object") freezeDeep(value);
    });
    return obj;
  };

  const normalizePrize = (item, index) => {
    const name = normalizeText(item?.name, `Premio ${index + 1}`);
    const chance = clampFloat(item?.chance, 0, 0, 100);
    const uyuPrice = clampInt(item?.uyu_price ?? item?.price_uyu ?? item?.price_value ?? 0, 0, 0);
    const weight = clampInt(item?.weight ?? Math.round(Math.max(1, chance * 10)), 1, 1);

    return {
      id: `prize-${index}-${normalizeLoose(name).replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "item"}`,
      name,
      chance,
      uyu_price: uyuPrice,
      weight,
    };
  };

  const fallbackPrizes = [
    { name: "🎁 Premio sorpresa", chance: 35.9, uyu_price: 200, weight: 359 },
    { name: "🎟️ Cupón especial", chance: 24, uyu_price: 350, weight: 240 },
    { name: "🏷️ Descuento premium", chance: 18, uyu_price: 500, weight: 180 },
    { name: "💎 Gran premio", chance: 0.1, uyu_price: 1500, weight: 1 },
  ];

  const normalizedPrizes = (Array.isArray(rawConfig.prizes) && rawConfig.prizes.length ? rawConfig.prizes : fallbackPrizes)
    .map(normalizePrize)
    .filter((item) => item.name);

  const config = freezeDeep({
    version: APP_VERSION,
    prizes: normalizedPrizes,
    currency: normalizeCurrency(rawConfig.currency),
    user_id: normalizeText(rawConfig.user_id),
    username: normalizeText(rawConfig.username),
    full_name: normalizeText(rawConfig.full_name),
    display_name: normalizeDisplayName(rawConfig.display_name || rawConfig.full_name || rawConfig.username || DEFAULTS.displayName),
    fichas: clampInt(rawConfig.fichas, 0, 0),
    demo_spins_left: clampInt(rawConfig.demo_spins_left, 0, 0),
    uyu_to_ars: clampInt(rawConfig.uyu_to_ars, DEFAULTS.uyuToArs, 1),
    ticket_price_uyu: clampInt(rawConfig.ticket_price_uyu, DEFAULTS.ticketPriceUyu, 1),
    mp_link_ar: normalizeText(rawConfig.mp_link_ar),
    mp_link_uy: normalizeText(rawConfig.mp_link_uy),
    bot_name: normalizeText(rawConfig.bot_name, DEFAULTS.botName),
    language_code: normalizeText(root.lang || rawConfig.language_code || "es", "es"),
  });

  const $ = (id) => doc.getElementById(id);
  const metaCsrf = doc.querySelector('meta[name="csrf-token"], meta[name="csrf"]');

  const els = {
    wheelCard: $("wheelCard"),
    wheelSvg: $("wheelSvg"),
    wheelLayer: $("wheelLayer") || $("wheelSvg"),
    spinBtn: $("spinBtn"),
    demoBtn: $("demoBtn"),
    buyBtn: $("buyBtn"),
    winnerBox: $("winnerBox"),
    prizeList: $("prizeList"),
    ticketPrice: $("ticketPrice"),
    miniTicket: $("miniTicket"),
    currencyChip: $("currencyChip"),
    statusValue: $("statusValue"),
    spinState: $("spinState"),
    totalItemsChip: $("totalItemsChip"),
    liveRegion: $("liveRegion"),
    btnUyu: $("btnUyu"),
    btnArs: $("btnArs"),
    ball: $("ball"),
    playerNameText: $("playerNameText"),
    fichasValue: $("fichasValue"),
    miniFichas: $("miniFichas"),
    miniDemo: $("miniDemo"),
    realPrizeCount: $("realPrizeCount"),
    nameModal: $("nameModal"),
    playerNameInput: $("playerNameInput"),
    saveNameBtn: $("saveNameBtn"),
    skipNameBtn: $("skipNameBtn"),
    toast: $("toast"),
    stars: $("stars"),
    particles: $("particles"),
    confettiWrap: $("confettiWrap"),
    lights: $("lights"),
    payArBtn: $("payArBtn"),
    payUyBtn: $("payUyBtn"),
    confirmArPaidBtn: $("confirmArPaidBtn"),
    confirmUyPaidBtn: $("confirmUyPaidBtn"),
    pointer: $("pointer"),
  };

  if (!els.wheelSvg || !els.spinBtn || !els.demoBtn || !els.winnerBox || !els.prizeList) {
    return;
  }

  const storageKeyBase = `ruleta:${config.user_id || config.username || "guest"}:v2`;
  const media = {
    reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)"),
    contrast: window.matchMedia("(prefers-contrast: more)"),
    hoverNone: window.matchMedia("(hover: none)"),
  };

  const state = {
    currency: normalizeCurrency(storage.get(`${storageKeyBase}:currency`) || config.currency),
    spinning: false,
    spinSource: "paid",
    currentRotation: 0,
    pendingPurchase: false,
    syncingProfile: false,
    liveTimer: 0,
    toastTimer: 0,
    confettiTimer: 0,
    spinTimer: 0,
    tickTimer: 0,
    ballFrame: 0,
    wheelAnimation: null,
    pointerAnimation: null,
    modalFocusedBeforeOpen: null,
    audio: {
      ctx: null,
      compressor: null,
      gain: null,
      ready: false,
    },
    user: {
      user_id: config.user_id,
      username: config.username,
      full_name: config.full_name,
      display_name: normalizeDisplayName(storage.get(`${storageKeyBase}:display_name`) || config.display_name),
      fichas: config.fichas,
      demo_spins_left: config.demo_spins_left,
    },
    lastResult: safeJsonParse(storage.get(`${storageKeyBase}:last_result`), null),
  };

  const isReducedMotion = () => media.reducedMotion.matches;
  const isTouchDevice = () => media.hoverNone.matches;
  const getSpinDuration = () => (isReducedMotion() ? DEFAULTS.reducedSpinDurationMs : DEFAULTS.spinDurationMs);
  const getConfettiCount = () => (isReducedMotion() ? DEFAULTS.reducedConfettiCount : DEFAULTS.confettiCount);
  const getIdleBallRadius = () => (isTouchDevice() ? DEFAULTS.touchBallRadius : DEFAULTS.idleBallRadius);

  const persistUiState = () => {
    storage.set(`${storageKeyBase}:currency`, state.currency);
    storage.set(`${storageKeyBase}:display_name`, state.user.display_name);
    if (state.lastResult) {
      storage.set(`${storageKeyBase}:last_result`, JSON.stringify(state.lastResult));
    } else {
      storage.remove(`${storageKeyBase}:last_result`);
    }
  };

  const formatMoneyValueFromUyu = (uyuPrice, curr = state.currency) => {
    const safeUyu = clampInt(uyuPrice, 0, 0);
    const numeric = curr === "ARS" ? safeUyu * config.uyu_to_ars : safeUyu;
    const formatter = new Intl.NumberFormat(curr === "ARS" ? "es-AR" : "es-UY", {
      maximumFractionDigits: 0,
    });

    return {
      value: numeric,
      label: `$${formatter.format(numeric)} ${curr}`,
    };
  };

  const getTicketLabel = (curr = state.currency) => formatMoneyValueFromUyu(config.ticket_price_uyu, curr).label;

  const chanceLabel = (value) => {
    const safe = clampFloat(value, 0, 0, 100);
    return Number.isInteger(safe) ? `${safe}%` : `${safe.toFixed(2).replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1")}%`;
  };

  const shortLabel = (value, maxLen = 18) => {
    const chars = Array.from(normalizeText(value));
    return chars.length > maxLen ? `${chars.slice(0, maxLen).join("")}…` : chars.join("");
  };

  const setText = (el, value) => {
    if (el) el.textContent = String(value ?? "");
  };

  const setStatus = (main, secondary) => {
    setText(els.statusValue, main);
    setText(els.spinState, secondary);
    if (els.statusValue) els.statusValue.dataset.state = normalizeLoose(main);
  };

  const announce = (text) => {
    if (!els.liveRegion) return;
    els.liveRegion.textContent = "";
    clearTimeout(state.liveTimer);
    state.liveTimer = window.setTimeout(() => {
      els.liveRegion.textContent = text;
    }, 25);
  };

  const toast = (message, type = "info") => {
    if (!els.toast) return;
    els.toast.dataset.type = type;
    els.toast.textContent = message;
    els.toast.classList.add("show");
    clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(() => {
      els.toast.classList.remove("show");
    }, type === "error" ? DEFAULTS.errorToastDurationMs : DEFAULTS.toastDurationMs);
  };

  const currentPlayerName = () => normalizeDisplayName(state.user.display_name || state.user.full_name || state.user.username || DEFAULTS.displayName);

  const setBusy = (el, busy, busyLabel = "Procesando...") => {
    if (!el) return;
    if (busy) {
      if (!el.dataset.originalLabel) el.dataset.originalLabel = el.textContent || "";
      el.disabled = true;
      el.setAttribute("aria-busy", "true");
      el.textContent = busyLabel;
      return;
    }

    el.removeAttribute("aria-busy");
    if (el.dataset.originalLabel) {
      el.textContent = el.dataset.originalLabel;
    }
  };

  const renderMiniStats = () => {
    setText(els.realPrizeCount, `${config.prizes.length} visibles`);
    setText(els.miniFichas, String(state.user.fichas || 0));
    setText(els.miniDemo, String(state.user.demo_spins_left || 0));
  };

  const renderTicket = () => {
    const label = getTicketLabel(state.currency);
    setText(els.ticketPrice, label);
    setText(els.miniTicket, label);
    setText(els.currencyChip, `Moneda ${state.currency}`);
  };

  const updateCurrencyButtons = () => {
    if (els.btnUyu) {
      els.btnUyu.classList.toggle("active", state.currency === "UYU");
      els.btnUyu.setAttribute("aria-pressed", String(state.currency === "UYU"));
    }
    if (els.btnArs) {
      els.btnArs.classList.toggle("active", state.currency === "ARS");
      els.btnArs.setAttribute("aria-pressed", String(state.currency === "ARS"));
    }
  };

  const renderProfile = () => {
    setText(els.playerNameText, currentPlayerName());
    setText(els.fichasValue, `${state.user.fichas || 0} fichas`);
    renderMiniStats();
    updateActionButtons();
    persistUiState();
  };

  const renderIdleWinner = () => {
    els.winnerBox.innerHTML = `
      <div class="info-label">Resultado</div>
      <div class="winner-main">Gira la ruleta</div>
      <div class="winner-sub">Tu premio aparecerá aquí</div>
      <div class="winner-badge">Sin resultado todavía</div>
    `;
  };

  const renderWinner = (result) => {
    const player = escapeHtml(currentPlayerName());
    const prizeName = escapeHtml(result?.name || "Premio");
    const prizeLabel = escapeHtml(result?.label || "");
    const chance = result?.chance != null ? `<div class="winner-badge">Probabilidad ${escapeHtml(chanceLabel(result.chance))}</div>` : `<div class="winner-badge">Resultado confirmado</div>`;

    els.winnerBox.innerHTML = `
      <div class="info-label">Premio ganado</div>
      <div class="winner-main">${player}, ganaste ${prizeName}</div>
      <div class="winner-sub">${prizeLabel}</div>
      ${chance}
    `;
  };

  const renderPersistedWinner = () => {
    if (state.lastResult?.name) {
      renderWinner(state.lastResult);
      return;
    }
    renderIdleWinner();
  };

  const resolvePrizeByName = (prizeName) => {
    const target = normalizeLoose(prizeName);
    if (!target) return null;

    return (
      config.prizes.find((item) => normalizeLoose(item.name) === target) ||
      config.prizes.find((item) => normalizeLoose(item.name).includes(target) || target.includes(normalizeLoose(item.name))) ||
      null
    );
  };

  const renderPrizeList = () => {
    const fragment = doc.createDocumentFragment();

    config.prizes.forEach((prize, index) => {
      const row = doc.createElement("div");
      row.className = "prize-item";
      row.dataset.prizeId = prize.id;
      row.dataset.index = String(index);

      const left = doc.createElement("div");
      left.className = "prize-left";

      const name = doc.createElement("div");
      name.className = "prize-name";
      name.textContent = prize.name;

      const meta = doc.createElement("div");
      meta.className = "prize-meta";
      meta.textContent = `Probabilidad ${chanceLabel(prize.chance)}`;

      const price = doc.createElement("div");
      price.className = "prize-price";
      price.textContent = formatMoneyValueFromUyu(prize.uyu_price, state.currency).label;

      left.appendChild(name);
      left.appendChild(meta);
      row.appendChild(left);
      row.appendChild(price);
      fragment.appendChild(row);
    });

    els.prizeList.replaceChildren(fragment);
    setText(els.totalItemsChip, `${config.prizes.length} premios`);
  };

  const polarToCartesian = (cx, cy, r, angleDeg) => {
    const angleRad = ((angleDeg - 90) * Math.PI) / 180;
    return {
      x: cx + r * Math.cos(angleRad),
      y: cy + r * Math.sin(angleRad),
    };
  };

  const describeWedge = (cx, cy, r, startAngle, endAngle) => {
    const start = polarToCartesian(cx, cy, r, endAngle);
    const end = polarToCartesian(cx, cy, r, startAngle);
    const largeArcFlag = endAngle - startAngle <= 180 ? "0" : "1";
    return `M ${cx} ${cy} L ${start.x} ${start.y} A ${r} ${r} 0 ${largeArcFlag} 0 ${end.x} ${end.y} Z`;
  };

  const renderWheel = () => {
    const colors = [
      ["#ff88c6", "#d51b71"],
      ["#d28cff", "#6d25df"],
      ["#ff7b8e", "#e32052"],
      ["#f38bff", "#8f29df"],
      ["#ff64a8", "#cf1b67"],
      ["#ae79ff", "#5e26da"],
      ["#ff8d73", "#e74834"],
      ["#d86cff", "#822ce0"],
    ];

    const total = Math.max(1, config.prizes.length);
    const angle = 360 / total;

    let defs = `
      <filter id="segmentShadow" x="-50%" y="-50%" width="200%" height="200%">
        <feDropShadow dx="0" dy="1.4" stdDeviation="1.2" flood-color="rgba(0,0,0,.35)"></feDropShadow>
      </filter>
      <filter id="textShadow" x="-50%" y="-50%" width="200%" height="200%">
        <feDropShadow dx="0" dy="1.1" stdDeviation=".9" flood-color="rgba(0,0,0,.5)"></feDropShadow>
      </filter>
      <radialGradient id="centerGlow" cx="50%" cy="50%" r="60%">
        <stop offset="0%" stop-color="rgba(255,255,255,.14)"></stop>
        <stop offset="70%" stop-color="rgba(255,255,255,.04)"></stop>
        <stop offset="100%" stop-color="rgba(255,255,255,0)"></stop>
      </radialGradient>
      <radialGradient id="outerRing" cx="50%" cy="50%" r="65%">
        <stop offset="70%" stop-color="rgba(255,255,255,0)"></stop>
        <stop offset="100%" stop-color="rgba(255,255,255,.12)"></stop>
      </radialGradient>
    `;

    let html = "";

    config.prizes.forEach((prize, index) => {
      const startAngle = index * angle;
      const endAngle = (index + 1) * angle;
      const midAngle = startAngle + angle / 2;
      const path = describeWedge(DEFAULTS.wheelCenter, DEFAULTS.wheelCenter, DEFAULTS.wheelRadius, startAngle, endAngle);
      const gradientId = `seg-grad-${index}`;
      const glossId = `seg-gloss-${index}`;
      const label = escapeHtml(shortLabel(prize.name, total >= 10 ? 13 : 18));
      const fill = colors[index % colors.length];
      const fontSize = total >= 12 ? 2.7 : total >= 10 ? 3.1 : total >= 8 ? 3.6 : 4;
      const labelY = total >= 10 ? 14.6 : 15.4;

      defs += `
        <linearGradient id="${gradientId}" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="${fill[0]}"></stop>
          <stop offset="100%" stop-color="${fill[1]}"></stop>
        </linearGradient>
        <linearGradient id="${glossId}" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="rgba(255,255,255,.22)"></stop>
          <stop offset="40%" stop-color="rgba(255,255,255,.05)"></stop>
          <stop offset="100%" stop-color="rgba(255,255,255,0)"></stop>
        </linearGradient>
      `;

      html += `
        <g filter="url(#segmentShadow)" data-prize-index="${index}">
          <path d="${path}" fill="url(#${gradientId})" stroke="rgba(255,255,255,.25)" stroke-width="0.7"></path>
          <path d="${path}" fill="url(#${glossId})"></path>
          <g transform="rotate(${midAngle} 50 50)">
            <text x="50" y="${labelY}" text-anchor="middle" font-size="${fontSize}" font-weight="1000" letter-spacing=".06em" filter="url(#textShadow)">${label}</text>
          </g>
        </g>
      `;
    });

    html += `
      <circle cx="50" cy="50" r="13" fill="url(#centerGlow)"></circle>
      <circle cx="50" cy="50" r="47.1" fill="none" stroke="url(#outerRing)" stroke-width="1"></circle>
    `;

    els.wheelSvg.innerHTML = `<defs>${defs}</defs>${html}`;
    els.wheelSvg.setAttribute("aria-label", `${config.prizes.length} premios disponibles`);
  };

  const renderStars = () => {
    if (!els.stars) return;
    const count = isReducedMotion() ? 12 : window.innerWidth < 700 ? 30 : 58;
    const fragment = doc.createDocumentFragment();

    for (let i = 0; i < count; i += 1) {
      const star = doc.createElement("span");
      star.className = "star";
      star.style.left = `${Math.random() * 100}%`;
      star.style.top = `${Math.random() * 100}%`;
      star.style.animationDelay = `${Math.random() * 4.2}s`;
      star.style.animationDuration = `${3 + Math.random() * 4.3}s`;
      fragment.appendChild(star);
    }

    els.stars.replaceChildren(fragment);
  };

  const renderParticles = () => {
    if (!els.particles) return;
    const count = isReducedMotion() ? 6 : window.innerWidth < 700 ? 12 : 24;
    const fragment = doc.createDocumentFragment();

    for (let i = 0; i < count; i += 1) {
      const p = doc.createElement("span");
      p.className = "particle";
      p.style.left = `${Math.random() * 100}%`;
      p.style.bottom = `${-10 - Math.random() * 35}px`;
      p.style.animationDelay = `${Math.random() * 6}s`;
      p.style.animationDuration = `${8 + Math.random() * 9}s`;
      const size = `${4 + Math.random() * 7}px`;
      p.style.width = size;
      p.style.height = size;
      fragment.appendChild(p);
    }

    els.particles.replaceChildren(fragment);
  };

  const renderLights = () => {
    if (!els.lights) return;
    const count = isReducedMotion() ? 18 : 38;
    const radius = window.innerWidth < 640 ? 41.3 : 45.2;
    const fragment = doc.createDocumentFragment();

    for (let i = 0; i < count; i += 1) {
      const dot = doc.createElement("span");
      const angle = (i / count) * 360;
      dot.style.transform = `translate(-50%, -50%) rotate(${angle}deg) translateY(calc(-1 * ${radius}%))`;
      dot.style.animationDelay = `${i * 0.035}s`;
      fragment.appendChild(dot);
    }

    els.lights.replaceChildren(fragment);
  };

  const setBallPosition = (angleDeg, radiusPercent = getIdleBallRadius()) => {
    if (!els.ball) return;
    const radians = ((angleDeg - 90) * Math.PI) / 180;
    const x = Math.cos(radians) * radiusPercent;
    const y = Math.sin(radians) * radiusPercent;
    els.ball.style.transform = `translate(calc(-50% + ${x}%), calc(-50% + ${y}%))`;
  };

  const stopBallAnimation = () => {
    if (state.ballFrame) {
      cancelAnimationFrame(state.ballFrame);
      state.ballFrame = 0;
    }
  };

  const animateBallSpin = (finalAngle, duration = getSpinDuration() - 80) => {
    stopBallAnimation();
    const start = performance.now();
    const initialTurns = isReducedMotion() ? 360 : 1440 + Math.random() * 720;

    const frame = (now) => {
      const elapsed = now - start;
      const t = Math.min(1, elapsed / duration);
      const ease = 1 - Math.pow(1 - t, 3);
      const wobble = isReducedMotion() ? 0 : Math.sin(t * Math.PI * 18) * (1 - t) * 1.5;
      const angle = initialTurns * (1 - ease) + finalAngle * ease + wobble;
      const radius = isReducedMotion() ? DEFAULTS.finalBallRadius + 1.2 : getIdleBallRadius() - ease * 4.9;
      setBallPosition(angle, radius);

      if (t < 1) {
        state.ballFrame = requestAnimationFrame(frame);
      } else {
        setBallPosition(finalAngle, DEFAULTS.finalBallRadius);
        state.ballFrame = 0;
      }
    };

    state.ballFrame = requestAnimationFrame(frame);
  };

  const stopWheelAnimation = () => {
    if (state.wheelAnimation && typeof state.wheelAnimation.cancel === "function") {
      try {
        state.wheelAnimation.cancel();
      } catch {}
    }
    state.wheelAnimation = null;
  };

  const animateWheelRotation = (targetRotation, duration = getSpinDuration()) => {
    if (!els.wheelSvg) return;
    stopWheelAnimation();

    if (typeof els.wheelSvg.animate === "function") {
      state.wheelAnimation = els.wheelSvg.animate(
        [
          { transform: `rotate(${state.currentRotation}deg)` },
          { transform: `rotate(${targetRotation}deg)` },
        ],
        {
          duration,
          easing: isReducedMotion() ? "cubic-bezier(.22,.61,.36,1)" : "cubic-bezier(.08,.85,.15,1)",
          fill: "forwards",
        }
      );

      state.wheelAnimation.onfinish = () => {
        els.wheelSvg.style.transform = `rotate(${targetRotation}deg)`;
        state.wheelAnimation = null;
      };

      return;
    }

    els.wheelSvg.style.transition = `transform ${duration}ms cubic-bezier(.08,.85,.15,1)`;
    requestAnimationFrame(() => {
      els.wheelSvg.style.transform = `rotate(${targetRotation}deg)`;
    });
    window.setTimeout(() => {
      els.wheelSvg.style.transition = "";
    }, duration + 40);
  };

  const stopPointerKick = () => {
    if (state.pointerAnimation && typeof state.pointerAnimation.cancel === "function") {
      try {
        state.pointerAnimation.cancel();
      } catch {}
    }
    state.pointerAnimation = null;
  };

  const triggerPointerKick = (totalDuration = getSpinDuration() - 1200) => {
    if (!els.pointer || typeof els.pointer.animate !== "function" || isReducedMotion()) return;
    stopPointerKick();

    const beats = Math.max(8, Math.floor(totalDuration / 210));
    state.pointerAnimation = els.pointer.animate(
      [
        { transform: "scaleY(1) translateY(0)" },
        { transform: "scaleY(1.14) translateY(3px)" },
        { transform: "scaleY(.95) translateY(-1px)" },
        { transform: "scaleY(1) translateY(0)" },
      ],
      {
        duration: 190,
        iterations: beats,
        easing: "ease-in-out",
      }
    );
  };

  const initAudio = () => {
    if (state.audio.ctx) return;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;

    const ctx = new AudioContextClass();
    const compressor = ctx.createDynamicsCompressor();
    const gain = ctx.createGain();

    compressor.threshold.value = -20;
    compressor.knee.value = 20;
    compressor.ratio.value = 8;
    compressor.attack.value = 0.003;
    compressor.release.value = 0.25;
    gain.gain.value = isReducedMotion() ? 0.11 : 0.17;

    compressor.connect(gain);
    gain.connect(ctx.destination);

    state.audio.ctx = ctx;
    state.audio.compressor = compressor;
    state.audio.gain = gain;
  };

  const ensureAudioReady = async () => {
    initAudio();
    if (!state.audio.ctx) return;
    if (state.audio.ctx.state === "suspended") {
      try {
        await state.audio.ctx.resume();
      } catch {}
    }
    state.audio.ready = state.audio.ctx.state === "running";
  };

  const playTone = (type, frequency, duration, gainValue, when = 0, glideTo = null) => {
    if (!state.audio.ctx || !state.audio.compressor || !state.audio.ready) return;

    const now = state.audio.ctx.currentTime + when;
    const osc = state.audio.ctx.createOscillator();
    const gain = state.audio.ctx.createGain();

    osc.type = type;
    osc.frequency.setValueAtTime(frequency, now);
    if (glideTo) {
      osc.frequency.exponentialRampToValueAtTime(glideTo, now + duration);
    }

    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(gainValue, now + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);

    osc.connect(gain);
    gain.connect(state.audio.compressor);

    osc.start(now);
    osc.stop(now + duration + 0.04);
  };

  const playTick = () => playTone("square", 940 + Math.random() * 180, 0.05, 0.015);

  const playSpinStart = () => {
    playTone("triangle", 380, 0.12, 0.021, 0, 520);
    playTone("triangle", 540, 0.17, 0.016, 0.05, 760);
  };

  const playWinSound = () => {
    playTone("triangle", 740, 0.12, 0.028, 0);
    playTone("triangle", 920, 0.12, 0.028, 0.11);
    playTone("triangle", 1160, 0.2, 0.028, 0.22);
    playTone("sine", 1480, 0.28, 0.018, 0.18, 1720);
  };

  const stopTicking = () => {
    if (state.tickTimer) {
      clearTimeout(state.tickTimer);
      state.tickTimer = 0;
    }
  };

  const startTicking = (totalDuration = getSpinDuration() - 450) => {
    stopTicking();
    if (isReducedMotion()) return;
    const startedAt = performance.now();

    const schedule = () => {
      const elapsed = performance.now() - startedAt;
      if (elapsed >= totalDuration) {
        stopTicking();
        return;
      }
      const progress = elapsed / totalDuration;
      const interval = 65 + progress * 125 + Math.random() * 10;
      playTick();
      state.tickTimer = window.setTimeout(schedule, interval);
    };

    schedule();
  };

  const fireConfetti = (count = getConfettiCount()) => {
    if (!els.confettiWrap) return;
    const colors = ["#ffd85b", "#ff5c91", "#c56eff", "#ffffff", "#ff9cc0", "#ffe9a8"];
    const fragment = doc.createDocumentFragment();

    for (let i = 0; i < count; i += 1) {
      const confetti = doc.createElement("span");
      confetti.className = "confetti";
      confetti.style.left = `${Math.random() * 100}%`;
      confetti.style.top = `${-10 - Math.random() * 25}%`;
      confetti.style.background = colors[Math.floor(Math.random() * colors.length)];
      confetti.style.width = `${7 + Math.random() * 7}px`;
      confetti.style.height = `${10 + Math.random() * 12}px`;
      confetti.style.borderRadius = Math.random() > 0.65 ? "50%" : "2px";
      confetti.style.animationDuration = `${2.8 + Math.random() * 2.5}s`;
      confetti.style.animationDelay = `${Math.random() * 0.18}s`;
      confetti.style.transform = `rotate(${Math.random() * 360}deg)`;
      fragment.appendChild(confetti);
    }

    els.confettiWrap.replaceChildren(fragment);
    clearTimeout(state.confettiTimer);
    state.confettiTimer = window.setTimeout(() => {
      els.confettiWrap.innerHTML = "";
    }, 5300);
  };

  const updateActionButtons = () => {
    const canPaidSpin = state.user.fichas > 0;
    const canDemoSpin = state.user.demo_spins_left > 0;

    if (els.spinBtn) {
      els.spinBtn.disabled = state.spinning || !canPaidSpin;
      els.spinBtn.setAttribute("aria-disabled", String(state.spinning || !canPaidSpin));
      els.spinBtn.textContent = state.spinning
        ? state.spinSource === "demo"
          ? "⏳ GIRANDO DEMO..."
          : "⏳ GIRANDO..."
        : canPaidSpin
          ? `🎰 GIRAR CON FICHA (${state.user.fichas})`
          : "🎰 SIN FICHAS";
    }

    if (els.demoBtn) {
      els.demoBtn.disabled = state.spinning || !canDemoSpin;
      els.demoBtn.setAttribute("aria-disabled", String(state.spinning || !canDemoSpin));
      els.demoBtn.textContent = canDemoSpin ? `🆓 TIRADA DEMO (${state.user.demo_spins_left})` : "🆓 DEMO AGOTADA";
    }

    if (els.buyBtn) {
      els.buyBtn.disabled = state.spinning;
      els.buyBtn.setAttribute("aria-disabled", String(state.spinning));
    }

    if (els.confirmArPaidBtn) els.confirmArPaidBtn.disabled = state.pendingPurchase || state.spinning;
    if (els.confirmUyPaidBtn) els.confirmUyPaidBtn.disabled = state.pendingPurchase || state.spinning;
  };

  const applyProfile = (profile) => {
    if (!profile || typeof profile !== "object") return;
    state.user.display_name = normalizeDisplayName(profile.display_name || state.user.display_name);
    state.user.fichas = clampInt(profile.fichas, state.user.fichas, 0);
    state.user.demo_spins_left = clampInt(profile.demo_spins_left, state.user.demo_spins_left, 0);
    persistUiState();
    renderProfile();
  };

  const normalizeProfileShape = (data) => {
    const source = data?.profile || data?.user || data || {};
    return {
      display_name: normalizeDisplayName(source.display_name || source.full_name || source.username || state.user.display_name || DEFAULTS.displayName),
      fichas: clampInt(source.fichas, state.user.fichas, 0),
      demo_spins_left: clampInt(source.demo_spins_left, state.user.demo_spins_left, 0),
    };
  };

  const normalizePurchaseShape = (data, country) => {
    const purchase = data?.purchase || data || {};
    return {
      purchase_id: normalizeText(purchase.purchase_id || purchase.id || data?.purchase_id || `pending-${Date.now()}`),
      payment_link: normalizeText(purchase.payment_link || (country === "AR" ? config.mp_link_ar : config.mp_link_uy)),
      status: normalizeText(purchase.status, "pending"),
      qty: clampInt(purchase.qty, 1, 1),
    };
  };

  const normalizeSpinShape = (data, requestedMode) => {
    const result = data?.result || data?.prize || {};
    const profile = normalizeProfileShape(data);
    const prizeName = normalizeText(result.name || result.prize || data?.prize?.name || "");
    const matched = resolvePrizeByName(prizeName) || config.prizes[0];
    const label = normalizeText(
      result.label ||
      result.price_label ||
      data?.prize?.label ||
      formatMoneyValueFromUyu(matched.uyu_price, state.currency).label
    );

    return {
      profile,
      prize: {
        id: matched.id,
        name: prizeName || matched.name,
        label,
        chance: clampFloat(result.chance || matched.chance, matched.chance, 0, 100),
        uyu_price: clampInt(result.uyu_price || matched.uyu_price, matched.uyu_price, 0),
        source: normalizeText(result.source || requestedMode || "paid"),
      },
    };
  };

  const getHeaders = () => {
    const headers = {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-Requested-With": "XMLHttpRequest",
    };

    if (metaCsrf?.content) {
      headers["X-CSRF-Token"] = metaCsrf.content;
    }

    return headers;
  };

  const fetchJson = async (path, payload, timeoutMs = DEFAULTS.requestTimeoutMs) => {
    if (!navigator.onLine) {
      throw new Error("No hay conexión a internet.");
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(path, {
        method: "POST",
        headers: getHeaders(),
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
        body: JSON.stringify(payload),
      });

      const text = await response.text();
      const data = safeJsonParse(text, null);

      if (!response.ok) {
        throw new Error(data?.error || `Error ${response.status}`);
      }
      if (!data || data.ok === false) {
        throw new Error(data?.error || "Respuesta inválida del servidor");
      }

      return data;
    } catch (error) {
      if (error?.name === "AbortError") {
        throw new Error("La solicitud tardó demasiado. Intentá de nuevo.");
      }
      throw error;
    } finally {
      clearTimeout(timeoutId);
    }
  };

  const apiPost = async (paths, payload) => {
    const candidates = Array.isArray(paths) ? paths : [paths];
    let lastError = null;

    for (const path of candidates) {
      try {
        return await fetchJson(path, payload);
      } catch (error) {
        lastError = error;
      }
    }

    throw lastError || new Error("No se pudo completar la solicitud.");
  };

  const profilePayload = (extra = {}) => {
    const nameParts = splitName(state.user.full_name || config.full_name || state.user.display_name);
    return {
      user_id: state.user.user_id,
      username: state.user.username,
      full_name: state.user.full_name,
      first_name: nameParts.first_name || normalizeDisplayName(state.user.display_name),
      last_name: nameParts.last_name || "",
      display_name: state.user.display_name,
      currency: state.currency,
      language_code: config.language_code,
      version: APP_VERSION,
      ...extra,
    };
  };

  const syncProfile = async (extra = {}) => {
    if (state.syncingProfile) return normalizeProfileShape(state.user);
    state.syncingProfile = true;
    try {
      const data = await apiPost(API_PATHS.profile, profilePayload(extra));
      const profile = normalizeProfileShape(data);
      applyProfile(profile);
      return profile;
    } finally {
      state.syncingProfile = false;
    }
  };

  const savePlayerName = async () => {
    const newDisplayName = normalizeDisplayName(els.playerNameInput?.value || "");
    if (!newDisplayName) {
      toast("Escribí un nombre válido", "error");
      els.playerNameInput?.focus();
      return;
    }

    setBusy(els.saveNameBtn, true, "Guardando...");
    try {
      const profile = await syncProfile({ display_name: newDisplayName });
      state.user.display_name = profile.display_name;
      persistUiState();
      closeNameModal();
      toast(`Hola ${state.user.display_name}`, "success");
      announce(`Nombre guardado como ${state.user.display_name}`);
    } finally {
      setBusy(els.saveNameBtn, false);
    }
  };

  const createPendingPayment = async (country) => {
    state.pendingPurchase = true;
    updateActionButtons();

    const actionButton = country === "AR" ? els.confirmArPaidBtn : els.confirmUyPaidBtn;
    setBusy(actionButton, true, "Registrando...");

    try {
      const payload = {
        ...profilePayload(),
        country,
        qty: 1,
      };

      const data = await apiPost(API_PATHS.purchase, payload);
      const purchase = normalizePurchaseShape(data, country);
      setStatus("Pago pendiente", "Esperando aprobación");
      toast(`Compra registrada: ${purchase.purchase_id}`, "success");
      announce(`Pago pendiente registrado con referencia ${purchase.purchase_id}`);
      return purchase;
    } finally {
      state.pendingPurchase = false;
      setBusy(actionButton, false);
      updateActionButtons();
    }
  };

  const openPayment = (country) => {
    const url = country === "AR" ? config.mp_link_ar : config.mp_link_uy;
    if (!url) {
      toast("No hay link de pago configurado", "error");
      return;
    }

    const telegramWebApp = window.Telegram?.WebApp;
    if (telegramWebApp?.openLink) {
      telegramWebApp.openLink(url);
      return;
    }

    const newWindow = window.open(url, "_blank", "noopener,noreferrer");
    if (!newWindow) {
      window.location.assign(url);
    }
  };

  const refreshProfile = async () => {
    await syncProfile();
  };

  const clearRuntimeTimers = () => {
    stopTicking();
    stopBallAnimation();
    stopWheelAnimation();
    stopPointerKick();
    clearTimeout(state.spinTimer);
    clearTimeout(state.toastTimer);
    clearTimeout(state.confettiTimer);
    clearTimeout(state.liveTimer);
  };

  const highlightPrizeItem = (prizeId) => {
    if (!els.prizeList) return;
    const items = els.prizeList.querySelectorAll(".prize-item");
    items.forEach((item) => item.classList.remove("active", "winner"));

    if (!prizeId) return;
    const current = els.prizeList.querySelector(`[data-prize-id="${cssEscape(prizeId)}"]`);
    if (current) {
      current.classList.add("active", "winner");
      current.scrollIntoView({
        behavior: isReducedMotion() ? "auto" : "smooth",
        block: "nearest",
      });
    }
  };

  const beginSpinUi = (mode) => {
    state.spinning = true;
    state.spinSource = mode;
    els.wheelCard?.classList.add("spinning");
    body?.classList.add("is-spinning");
    updateActionButtons();
    setStatus(mode === "demo" ? "Girando demo" : "Girando", "Animación activa");
    announce("La ruleta está girando");
    highlightPrizeItem(null);
  };

  const endSpinUi = () => {
    state.spinning = false;
    state.spinSource = "paid";
    els.wheelCard?.classList.remove("spinning");
    body?.classList.remove("is-spinning");
    updateActionButtons();
  };

  const calculateTargetRotation = (index) => {
    const segmentAngle = 360 / config.prizes.length;
    const segmentCenter = index * segmentAngle + segmentAngle / 2;
    const fullSpins = isReducedMotion() ? 3 : 8 + Math.floor(Math.random() * 4);
    const fineOffset = isReducedMotion() ? 0 : Math.random() * 7 - 3.5;
    const rotation = state.currentRotation + fullSpins * 360 + (360 - segmentCenter) + fineOffset;
    return { segmentCenter, rotation };
  };

  const spinWheel = async (mode) => {
    if (state.spinning) return;

    if (mode === "paid" && state.user.fichas <= 0) {
      toast("No tenés fichas disponibles", "error");
      setStatus("Sin fichas", "Comprá una ficha");
      return;
    }

    if (mode === "demo" && state.user.demo_spins_left <= 0) {
      toast("La demo ya fue usada", "error");
      setStatus("Demo agotada", "Comprá una ficha");
      return;
    }

    clearRuntimeTimers();
    beginSpinUi(mode);

    try {
      await ensureAudioReady();
      playSpinStart();

      const data = await apiPost(API_PATHS.spin, {
        ...profilePayload(),
        mode,
      });

      const normalized = normalizeSpinShape(data, mode);
      applyProfile(normalized.profile);

      const prizeIndex = config.prizes.findIndex((item) => item.id === normalized.prize.id || normalizeLoose(item.name) === normalizeLoose(normalized.prize.name));
      if (prizeIndex < 0) {
        throw new Error("Premio no encontrado en la ruleta.");
      }

      const target = calculateTargetRotation(prizeIndex);
      const spinDuration = getSpinDuration();
      const ballFinalAngle = 360 - target.segmentCenter + 360;

      animateWheelRotation(target.rotation, spinDuration);
      animateBallSpin(ballFinalAngle, spinDuration - 80);
      triggerPointerKick(spinDuration - 1000);
      startTicking(spinDuration - 450);

      state.currentRotation = target.rotation;
      clearTimeout(state.spinTimer);
      state.spinTimer = window.setTimeout(() => {
        const result = {
          id: normalized.prize.id,
          name: normalized.prize.name,
          label: normalized.prize.label,
          chance: normalized.prize.chance,
          source: normalized.prize.source,
        };

        state.lastResult = result;
        persistUiState();
        renderWinner(result);
        highlightPrizeItem(normalized.prize.id);
        playWinSound();
        fireConfetti();
        toast(`¡Ganaste: ${normalized.prize.name}!`, "success");
        setStatus("Premio entregado", mode === "demo" ? "Demo completada" : "Animación completada");
        announce(`Premio ganado: ${normalized.prize.name} por ${normalized.prize.label}`);
        endSpinUi();
      }, spinDuration);
    } catch (error) {
      clearRuntimeTimers();
      toast(error?.message || "Error al girar la ruleta", "error");
      setStatus("Error", "Reintentar");
      announce("Hubo un error al girar la ruleta");
      endSpinUi();
    }
  };

  const openNameModal = () => {
    if (!els.nameModal) return;
    state.modalFocusedBeforeOpen = doc.activeElement;
    els.nameModal.classList.remove("hidden");
    els.nameModal.setAttribute("aria-hidden", "false");
    root.style.overflow = "hidden";
    window.setTimeout(() => {
      els.playerNameInput?.focus();
      els.playerNameInput?.select();
    }, 25);
  };

  const closeNameModal = () => {
    if (!els.nameModal) return;
    els.nameModal.classList.add("hidden");
    els.nameModal.setAttribute("aria-hidden", "true");
    root.style.overflow = "";
    if (state.modalFocusedBeforeOpen && typeof state.modalFocusedBeforeOpen.focus === "function") {
      state.modalFocusedBeforeOpen.focus();
    }
  };

  const maybeOpenNameModal = () => {
    if (!els.nameModal || !els.playerNameInput) return;
    const current = normalizeDisplayName(state.user.display_name);
    els.playerNameInput.value = current && current !== DEFAULTS.displayName ? current : "";
    if (!current || current === DEFAULTS.displayName) {
      openNameModal();
      return;
    }
    closeNameModal();
  };

  const trapModalFocus = (event) => {
    if (!els.nameModal || els.nameModal.classList.contains("hidden")) return;

    if (event.key === "Escape") {
      closeNameModal();
      return;
    }

    if (event.key !== "Tab") return;

    const focusable = Array.from(
      els.nameModal.querySelectorAll('button, input, [href], select, textarea, [tabindex]:not([tabindex="-1"])')
    ).filter((el) => !el.hasAttribute("disabled") && !el.getAttribute("aria-hidden"));

    if (!focusable.length) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (event.shiftKey && doc.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && doc.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const scrollToPayment = () => {
    const target = state.currency === "ARS" ? els.payArBtn : els.payUyBtn;
    if (!target) return;
    target.scrollIntoView({
      behavior: isReducedMotion() ? "auto" : "smooth",
      block: "center",
    });
  };

  const onResize = debounce(
    rafThrottle(() => {
      renderStars();
      renderParticles();
      renderLights();
      setBallPosition(0, getIdleBallRadius());
    }),
    100
  );

  const onVisibilityChange = () => {
    if (!doc.hidden) return;
    stopTicking();
    if (state.audio.ctx?.state === "running") {
      state.audio.ctx.suspend().catch(() => {});
    }
  };

  const onFirstInteraction = () => {
    ensureAudioReady();
    window.removeEventListener("pointerdown", onFirstInteraction);
    window.removeEventListener("keydown", onFirstInteraction);
    window.removeEventListener("touchstart", onFirstInteraction);
  };

  const bindEvent = (el, eventName, handler, options) => {
    if (el) el.addEventListener(eventName, handler, options);
  };

  const bindMediaListener = (mq, handler) => {
    if (!mq) return;
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", handler);
      return;
    }
    if (typeof mq.addListener === "function") {
      mq.addListener(handler);
    }
  };

  const handleCurrencyChange = (nextCurrency) => {
    const safeCurrency = normalizeCurrency(nextCurrency);
    if (state.currency === safeCurrency) return;
    state.currency = safeCurrency;
    renderTicket();
    renderPrizeList();
    updateCurrencyButtons();
    persistUiState();
    toast(`Moneda cambiada a ${safeCurrency}`);
    announce(`Moneda cambiada a ${safeCurrency === "ARS" ? "pesos argentinos" : "pesos uruguayos"}`);

    if (state.lastResult?.id) {
      const match = config.prizes.find((item) => item.id === state.lastResult.id);
      if (match) {
        state.lastResult.label = formatMoneyValueFromUyu(match.uyu_price, state.currency).label;
        renderWinner(state.lastResult);
        persistUiState();
      }
    }
  };

  const bindEvents = () => {
    bindEvent(els.spinBtn, "click", () => spinWheel("paid"));
    bindEvent(els.demoBtn, "click", () => spinWheel("demo"));
    bindEvent(els.buyBtn, "click", scrollToPayment);

    bindEvent(els.btnUyu, "click", () => handleCurrencyChange("UYU"));
    bindEvent(els.btnArs, "click", () => handleCurrencyChange("ARS"));

    bindEvent(els.payArBtn, "click", () => openPayment("AR"));
    bindEvent(els.payUyBtn, "click", () => openPayment("UY"));

    bindEvent(els.confirmArPaidBtn, "click", async () => {
      try {
        await createPendingPayment("AR");
        await refreshProfile();
      } catch (error) {
        toast(error?.message || "No se pudo registrar la compra", "error");
      }
    });

    bindEvent(els.confirmUyPaidBtn, "click", async () => {
      try {
        await createPendingPayment("UY");
        await refreshProfile();
      } catch (error) {
        toast(error?.message || "No se pudo registrar la compra", "error");
      }
    });

    bindEvent(els.saveNameBtn, "click", async () => {
      try {
        await savePlayerName();
      } catch (error) {
        toast(error?.message || "No se pudo guardar el nombre", "error");
      }
    });

    bindEvent(els.skipNameBtn, "click", closeNameModal);

    bindEvent(els.playerNameInput, "input", () => {
      if (!els.playerNameInput) return;
      const safeName = normalizeDisplayName(els.playerNameInput.value);
      if (safeName !== els.playerNameInput.value) {
        els.playerNameInput.value = safeName;
      }
    });

    bindEvent(els.playerNameInput, "keydown", async (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        try {
          await savePlayerName();
        } catch (error) {
          toast(error?.message || "No se pudo guardar el nombre", "error");
        }
      }
    });

    bindEvent(window, "resize", onResize, { passive: true });
    bindEvent(window, "orientationchange", onResize, { passive: true });
    bindEvent(doc, "keydown", trapModalFocus);
    bindEvent(doc, "visibilitychange", onVisibilityChange);
    bindEvent(window, "online", () => {
      toast("Conexión restaurada", "success");
      announce("Conexión restaurada");
    });
    bindEvent(window, "offline", () => {
      toast("Sin conexión a internet", "error");
      announce("Sin conexión a internet");
    });
    bindEvent(window, "pointerdown", onFirstInteraction, { passive: true });
    bindEvent(window, "keydown", onFirstInteraction, { passive: true });
    bindEvent(window, "touchstart", onFirstInteraction, { passive: true });

    bindMediaListener(media.reducedMotion, () => {
      renderStars();
      renderParticles();
      renderLights();
      updateActionButtons();
      setBallPosition(0, getIdleBallRadius());
    });

    bindMediaListener(media.contrast, () => {
      renderPrizeList();
      renderProfile();
      renderPersistedWinner();
    });

    bindEvent(window, "pagehide", clearRuntimeTimers);
    bindEvent(window, "beforeunload", clearRuntimeTimers);
  };

  const boot = () => {
    root.dataset.ruletaVersion = APP_VERSION;
    renderStars();
    renderParticles();
    renderLights();
    renderWheel();
    renderPrizeList();
    renderTicket();
    renderProfile();
    renderPersistedWinner();
    updateCurrencyButtons();
    setStatus("Lista para girar", "Esperando");
    setBallPosition(0, getIdleBallRadius());
    bindEvents();
    maybeOpenNameModal();

    if (state.lastResult?.name) {
      announce(`Último premio: ${state.lastResult.name}`);
      highlightPrizeItem(state.lastResult.id || resolvePrizeByName(state.lastResult.name)?.id || null);
    }

    if (isTouchDevice()) {
      body?.classList.add("is-touch");
    }
  };

  if (doc.readyState === "loading") {
    doc.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();