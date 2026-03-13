(() => {
  "use strict";

  const rawConfig = window.RULETA_CONFIG || {};

  const clampInt = (value, fallback = 0, min = Number.NEGATIVE_INFINITY, max = Number.POSITIVE_INFINITY) => {
    const num = Number.parseInt(value, 10);
    const safe = Number.isFinite(num) ? num : fallback;
    return Math.min(max, Math.max(min, safe));
  };

  const clampFloat = (value, fallback = 0, min = Number.NEGATIVE_INFINITY, max = Number.POSITIVE_INFINITY) => {
    const num = Number.parseFloat(value);
    const safe = Number.isFinite(num) ? num : fallback;
    return Math.min(max, Math.max(min, safe));
  };

  const normalizeText = (value, fallback = "") => {
    const text = String(value ?? "").replace(/\s+/g, " ").trim();
    return text || fallback;
  };

  const normalizeCurrency = (value) => {
    const curr = normalizeText(value, "UYU").toUpperCase();
    return curr === "ARS" ? "ARS" : "UYU";
  };

  const normalizeDisplayName = (value) => normalizeText(value, "Jugador").slice(0, 40);

  const escapeHtml = (value) =>
    String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  const shortLabel = (value, maxLen = 18) => {
    const chars = Array.from(normalizeText(value));
    return chars.length > maxLen ? `${chars.slice(0, maxLen).join("")}…` : chars.join("");
  };

  const splitName = (value) => {
    const clean = normalizeText(value);
    if (!clean) return { first_name: "", last_name: "" };
    const parts = clean.split(" ");
    return {
      first_name: parts.shift() || "",
      last_name: parts.join(" "),
    };
  };

  const deepFreeze = (obj) => {
    if (!obj || typeof obj !== "object") return obj;
    Object.freeze(obj);
    Object.values(obj).forEach((value) => {
      if (value && typeof value === "object" && !Object.isFrozen(value)) {
        deepFreeze(value);
      }
    });
    return obj;
  };

  const normalizePrize = (item, index) => {
    const name = normalizeText(item?.name, `Premio ${index + 1}`);
    const chance = clampFloat(item?.chance, 0, 0, 100);
    const uyuPrice = clampInt(item?.uyu_price ?? item?.price_uyu ?? item?.price_value ?? 0, 0, 0);
    const weight = clampInt(item?.weight, 1, 1);
    return {
      name,
      chance,
      uyu_price: uyuPrice,
      weight,
    };
  };

  const normalizedPrizes = Array.isArray(rawConfig.prizes) && rawConfig.prizes.length
    ? rawConfig.prizes.map(normalizePrize)
    : [
        { name: "🎁 Premio sorpresa", chance: 35.9, uyu_price: 200, weight: 359 },
        { name: "🎟️ Cupón especial", chance: 24, uyu_price: 350, weight: 240 },
        { name: "🏷️ Descuento premium", chance: 18, uyu_price: 500, weight: 180 },
        { name: "💎 Gran premio", chance: 0.1, uyu_price: 1500, weight: 1 },
      ];

  const config = deepFreeze({
    prizes: normalizedPrizes,
    currency: normalizeCurrency(rawConfig.currency),
    user_id: normalizeText(rawConfig.user_id),
    username: normalizeText(rawConfig.username),
    full_name: normalizeText(rawConfig.full_name),
    display_name: normalizeDisplayName(rawConfig.display_name),
    fichas: clampInt(rawConfig.fichas, 0, 0),
    demo_spins_left: clampInt(rawConfig.demo_spins_left, 0, 0),
    uyu_to_ars: clampInt(rawConfig.uyu_to_ars, 25, 1),
    ticket_price_uyu: clampInt(rawConfig.ticket_price_uyu, 250, 1),
    mp_link_ar: normalizeText(rawConfig.mp_link_ar),
    mp_link_uy: normalizeText(rawConfig.mp_link_uy),
    bot_name: normalizeText(rawConfig.bot_name, "Ruleta Premium"),
    language_code: document.documentElement.lang || "es",
  });

  const $ = (id) => document.getElementById(id);

  const els = {
    wheelCard: $("wheelCard"),
    wheelSvg: $("wheelSvg"),
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

  const storageKeyBase = `ruleta:${config.user_id || config.username || "guest"}`;
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const prefersContrast = window.matchMedia("(prefers-contrast: more)");
  const isTouchDevice = window.matchMedia("(hover: none)").matches;

  const state = {
    currency: normalizeCurrency(localStorageSafeGet(`${storageKeyBase}:currency`) || config.currency),
    currentRotation: 0,
    spinning: false,
    spinSource: "paid",
    audioCtx: null,
    masterGain: null,
    compressor: null,
    tickTimer: 0,
    spinTimer: 0,
    ballFrame: 0,
    toastTimer: 0,
    resizeTimer: 0,
    confettiTimer: 0,
    liveTimer: 0,
    modalFocusedBeforeOpen: null,
    user: {
      user_id: config.user_id,
      username: config.username,
      full_name: config.full_name,
      display_name: normalizeDisplayName(localStorageSafeGet(`${storageKeyBase}:display_name`) || config.display_name || config.full_name || config.username || "Jugador"),
      fichas: config.fichas,
      demo_spins_left: config.demo_spins_left,
    },
    lastResult: localStorageSafeGet(`${storageKeyBase}:last_result`) ? safeJsonParse(localStorageSafeGet(`${storageKeyBase}:last_result`), null) : null,
  };

  function localStorageSafeGet(key) {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  function localStorageSafeSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch {}
  }

  function safeJsonParse(value, fallback) {
    try {
      return JSON.parse(value);
    } catch {
      return fallback;
    }
  }

  function persistUiState() {
    localStorageSafeSet(`${storageKeyBase}:currency`, state.currency);
    localStorageSafeSet(`${storageKeyBase}:display_name`, state.user.display_name);
    if (state.lastResult) {
      localStorageSafeSet(`${storageKeyBase}:last_result`, JSON.stringify(state.lastResult));
    }
  }

  function formatMoneyValueFromUyu(uyuPrice, curr = state.currency) {
    const numeric = curr === "ARS"
      ? clampInt(uyuPrice, 0, 0) * config.uyu_to_ars
      : clampInt(uyuPrice, 0, 0);

    const formatter = new Intl.NumberFormat(curr === "ARS" ? "es-AR" : "es-UY", {
      maximumFractionDigits: 0,
    });

    return {
      value: numeric,
      label: `$${formatter.format(numeric)} ${curr}`,
    };
  }

  function getTicketLabel(curr = state.currency) {
    return formatMoneyValueFromUyu(config.ticket_price_uyu, curr).label;
  }

  function chanceLabel(value) {
    const num = clampFloat(value, 0, 0, 100);
    return Number.isInteger(num) ? `${num}%` : `${num.toFixed(2).replace(/\.?0+$/, "")}%`;
  }

  function setText(el, value) {
    if (el) el.textContent = String(value ?? "");
  }

  function setStatus(main, secondary) {
    setText(els.statusValue, main);
    setText(els.spinState, secondary);
  }

  function announce(text) {
    if (!els.liveRegion) return;
    els.liveRegion.textContent = "";
    window.clearTimeout(state.liveTimer);
    state.liveTimer = window.setTimeout(() => {
      els.liveRegion.textContent = text;
    }, 20);
  }

  function toast(message, type = "info") {
    if (!els.toast) return;
    els.toast.dataset.type = type;
    els.toast.textContent = message;
    els.toast.classList.add("show");
    window.clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(() => {
      els.toast.classList.remove("show");
    }, type === "error" ? 2800 : 2200);
  }

  function updateCurrencyButtons() {
    if (els.btnUyu) els.btnUyu.classList.toggle("active", state.currency === "UYU");
    if (els.btnArs) els.btnArs.classList.toggle("active", state.currency === "ARS");
  }

  function currentPlayerName() {
    return normalizeDisplayName(state.user.display_name || state.user.full_name || state.user.username || "Jugador");
  }

  function renderMiniStats() {
    setText(els.realPrizeCount, `${config.prizes.length} visibles`);
    setText(els.miniFichas, String(state.user.fichas || 0));
    setText(els.miniDemo, String(state.user.demo_spins_left || 0));
  }

  function renderTicket() {
    const label = getTicketLabel(state.currency);
    setText(els.ticketPrice, label);
    setText(els.miniTicket, label);
    setText(els.currencyChip, `Moneda ${state.currency}`);
  }

  function renderProfile() {
    setText(els.playerNameText, currentPlayerName());
    setText(els.fichasValue, `${state.user.fichas || 0} fichas`);
    renderMiniStats();
    updateActionButtons();
    persistUiState();
  }

  function renderIdleWinner() {
    els.winnerBox.innerHTML = `
      <div class="info-label">Resultado</div>
      <div class="winner-main">Gira la ruleta</div>
      <div class="winner-sub">Tu premio aparecerá aquí</div>
      <div class="winner-badge">Sin resultado todavía</div>
    `;
  }

  function renderWinner(result) {
    const player = escapeHtml(currentPlayerName());
    const prizeName = escapeHtml(result?.name || "Premio");
    const prizeLabel = escapeHtml(result?.label || "");
    els.winnerBox.innerHTML = `
      <div class="info-label">Premio ganado</div>
      <div class="winner-main">${player}, ganaste ${prizeName}</div>
      <div class="winner-sub">${prizeLabel}</div>
      <div class="winner-badge">Resultado confirmado</div>
    `;
  }

  function renderPersistedWinner() {
    if (state.lastResult && state.lastResult.name) {
      renderWinner(state.lastResult);
    } else {
      renderIdleWinner();
    }
  }

  function renderPrizeList() {
    const fragment = document.createDocumentFragment();

    config.prizes.forEach((prize) => {
      const row = document.createElement("div");
      row.className = "prize-item";

      const left = document.createElement("div");
      left.className = "prize-left";

      const name = document.createElement("div");
      name.className = "prize-name";
      name.textContent = prize.name;

      const meta = document.createElement("div");
      meta.className = "prize-meta";
      meta.textContent = `Probabilidad ${chanceLabel(prize.chance)}`;

      const price = document.createElement("div");
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
  }

  function polarToCartesian(cx, cy, r, angleDeg) {
    const angleRad = ((angleDeg - 90) * Math.PI) / 180;
    return {
      x: cx + r * Math.cos(angleRad),
      y: cy + r * Math.sin(angleRad),
    };
  }

  function describeWedge(cx, cy, r, startAngle, endAngle) {
    const start = polarToCartesian(cx, cy, r, endAngle);
    const end = polarToCartesian(cx, cy, r, startAngle);
    const largeArcFlag = endAngle - startAngle <= 180 ? "0" : "1";
    return `M ${cx} ${cy} L ${start.x} ${start.y} A ${r} ${r} 0 ${largeArcFlag} 0 ${end.x} ${end.y} Z`;
  }

  function renderWheel() {
    const colors = [
      ["#ff73bd", "#d41b70"],
      ["#bf6bff", "#6d26e0"],
      ["#ff6f89", "#e1224f"],
      ["#db69ff", "#932bda"],
      ["#ff4c99", "#d21c68"],
      ["#9a56ff", "#6427de"],
      ["#ff7280", "#ea2847"],
      ["#d757ff", "#8d2be2"],
    ];

    const total = config.prizes.length;
    const angle = 360 / total;

    let defs = `
      <filter id="segmentShadow" x="-50%" y="-50%" width="200%" height="200%">
        <feDropShadow dx="0" dy="1.2" stdDeviation="1.2" flood-color="rgba(0,0,0,.35)"></feDropShadow>
      </filter>
      <filter id="textShadow" x="-50%" y="-50%" width="200%" height="200%">
        <feDropShadow dx="0" dy="1.2" stdDeviation=".8" flood-color="rgba(0,0,0,.55)"></feDropShadow>
      </filter>
      <radialGradient id="centerGlow" cx="50%" cy="50%" r="60%">
        <stop offset="0%" stop-color="rgba(255,255,255,.08)"></stop>
        <stop offset="100%" stop-color="rgba(255,255,255,0)"></stop>
      </radialGradient>
    `;

    let html = "";

    config.prizes.forEach((prize, i) => {
      const startAngle = i * angle;
      const endAngle = (i + 1) * angle;
      const midAngle = startAngle + angle / 2;
      const path = describeWedge(50, 50, 47.8, startAngle, endAngle);
      const gradId = `seg-grad-${i}`;
      const glossId = `seg-gloss-${i}`;
      const label = escapeHtml(shortLabel(prize.name, 18));
      const fill = colors[i % colors.length];

      defs += `
        <linearGradient id="${gradId}" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="${fill[0]}"></stop>
          <stop offset="100%" stop-color="${fill[1]}"></stop>
        </linearGradient>
        <linearGradient id="${glossId}" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="rgba(255,255,255,.18)"></stop>
          <stop offset="45%" stop-color="rgba(255,255,255,.04)"></stop>
          <stop offset="100%" stop-color="rgba(255,255,255,0)"></stop>
        </linearGradient>
      `;

      html += `
        <g filter="url(#segmentShadow)">
          <path d="${path}" fill="url(#${gradId})" stroke="rgba(255,255,255,0.24)" stroke-width="0.7"></path>
          <path d="${path}" fill="url(#${glossId})"></path>
          <g transform="rotate(${midAngle} 50 50)">
            <text x="50" y="15.4" text-anchor="middle" font-size="3.9" font-weight="1000" filter="url(#textShadow)">${label}</text>
          </g>
        </g>
      `;
    });

    html += `<circle cx="50" cy="50" r="13" fill="url(#centerGlow)"></circle>`;
    els.wheelSvg.innerHTML = `<defs>${defs}</defs>${html}`;
  }

  function renderStars() {
    if (!els.stars) return;
    const wrap = els.stars;
    const count = prefersReducedMotion.matches ? 12 : window.innerWidth < 700 ? 28 : 54;
    const fragment = document.createDocumentFragment();

    for (let i = 0; i < count; i += 1) {
      const el = document.createElement("span");
      el.className = "star";
      el.style.left = `${Math.random() * 100}%`;
      el.style.top = `${Math.random() * 100}%`;
      el.style.animationDelay = `${Math.random() * 4}s`;
      el.style.animationDuration = `${3 + Math.random() * 4}s`;
      fragment.appendChild(el);
    }

    wrap.replaceChildren(fragment);
  }

  function renderParticles() {
    if (!els.particles) return;
    const wrap = els.particles;
    const count = prefersReducedMotion.matches ? 6 : window.innerWidth < 700 ? 12 : 22;
    const fragment = document.createDocumentFragment();

    for (let i = 0; i < count; i += 1) {
      const el = document.createElement("span");
      el.className = "particle";
      el.style.left = `${Math.random() * 100}%`;
      el.style.bottom = `${-10 - Math.random() * 30}px`;
      el.style.animationDelay = `${Math.random() * 6}s`;
      el.style.animationDuration = `${8 + Math.random() * 8}s`;
      const size = `${4 + Math.random() * 6}px`;
      el.style.width = size;
      el.style.height = size;
      fragment.appendChild(el);
    }

    wrap.replaceChildren(fragment);
  }

  function renderLights() {
    if (!els.lights) return;
    const wrap = els.lights;
    const count = prefersReducedMotion.matches ? 18 : 36;
    const radius = window.innerWidth < 640 ? 41.5 : 45.5;
    const fragment = document.createDocumentFragment();

    for (let i = 0; i < count; i += 1) {
      const dot = document.createElement("span");
      const angle = (i / count) * 360;
      dot.style.transform = `translate(-50%, -50%) rotate(${angle}deg) translateY(calc(-1 * ${radius}%))`;
      dot.style.animationDelay = `${i * 0.035}s`;
      fragment.appendChild(dot);
    }

    wrap.replaceChildren(fragment);
  }

  function setBallPosition(angleDeg, radiusPercent = 42) {
    if (!els.ball) return;
    const rad = ((angleDeg - 90) * Math.PI) / 180;
    const x = Math.cos(rad) * radiusPercent;
    const y = Math.sin(rad) * radiusPercent;
    els.ball.style.transform = `translate(calc(-50% + ${x}%), calc(-50% + ${y}%))`;
  }

  function stopBallAnimation() {
    if (state.ballFrame) {
      cancelAnimationFrame(state.ballFrame);
      state.ballFrame = 0;
    }
  }

  function animateBallSpin(finalAngle, duration = prefersReducedMotion.matches ? 1200 : 5900) {
    stopBallAnimation();
    const start = performance.now();
    const initialTurns = prefersReducedMotion.matches ? 360 : 1440 + Math.random() * 540;

    const frame = (now) => {
      const elapsed = now - start;
      const t = Math.min(1, elapsed / duration);
      const easeOut = 1 - Math.pow(1 - t, 3);
      const wobble = prefersReducedMotion.matches ? 0 : Math.sin(t * Math.PI * 18) * (1 - t) * 1.4;
      const angle = (initialTurns * (1 - easeOut)) + (finalAngle * easeOut) + wobble;
      const radius = prefersReducedMotion.matches ? 39 : 43 - easeOut * 4.5;
      setBallPosition(angle, radius);

      if (t < 1) {
        state.ballFrame = requestAnimationFrame(frame);
      } else {
        setBallPosition(finalAngle, 38.5);
        state.ballFrame = 0;
      }
    };

    state.ballFrame = requestAnimationFrame(frame);
  }

  function triggerPointerKick(totalDuration = prefersReducedMotion.matches ? 800 : 4600) {
    if (!els.pointer || typeof els.pointer.animate !== "function" || prefersReducedMotion.matches) return;

    const beats = Math.max(8, Math.floor(totalDuration / 220));
    els.pointer.animate(
      [
        { transform: "scaleY(1) translateY(0)" },
        { transform: "scaleY(1.12) translateY(3px)" },
        { transform: "scaleY(.94) translateY(-1px)" },
        { transform: "scaleY(1) translateY(0)" },
      ],
      {
        duration: 200,
        iterations: beats,
        easing: "ease-in-out",
      }
    );
  }

  function initAudio() {
    if (state.audioCtx) return;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;

    const ctx = new AudioContextClass();
    const compressor = ctx.createDynamicsCompressor();
    const masterGain = ctx.createGain();

    compressor.threshold.value = -20;
    compressor.knee.value = 20;
    compressor.ratio.value = 8;
    compressor.attack.value = 0.003;
    compressor.release.value = 0.25;

    masterGain.gain.value = prefersReducedMotion.matches ? 0.12 : 0.18;
    compressor.connect(masterGain);
    masterGain.connect(ctx.destination);

    state.audioCtx = ctx;
    state.compressor = compressor;
    state.masterGain = masterGain;
  }

  async function ensureAudioReady() {
    initAudio();
    if (state.audioCtx && state.audioCtx.state === "suspended") {
      try {
        await state.audioCtx.resume();
      } catch {}
    }
  }

  function playTone(type, frequency, duration, gainValue, when = 0, glideTo = null) {
    if (!state.audioCtx || !state.compressor) return;

    const now = state.audioCtx.currentTime + when;
    const osc = state.audioCtx.createOscillator();
    const gain = state.audioCtx.createGain();

    osc.type = type;
    osc.frequency.setValueAtTime(frequency, now);
    if (glideTo) {
      osc.frequency.exponentialRampToValueAtTime(glideTo, now + duration);
    }

    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(gainValue, now + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);

    osc.connect(gain);
    gain.connect(state.compressor);

    osc.start(now);
    osc.stop(now + duration + 0.03);
  }

  function playTick() {
    playTone("square", 950 + Math.random() * 180, 0.05, 0.015);
  }

  function playSpinStart() {
    playTone("triangle", 380, 0.11, 0.022, 0, 520);
    playTone("triangle", 540, 0.16, 0.016, 0.04, 720);
  }

  function playWinSound() {
    playTone("triangle", 740, 0.12, 0.028, 0);
    playTone("triangle", 920, 0.12, 0.028, 0.11);
    playTone("triangle", 1160, 0.2, 0.028, 0.22);
    playTone("sine", 1480, 0.28, 0.018, 0.18, 1720);
  }

  function stopTicking() {
    if (state.tickTimer) {
      clearTimeout(state.tickTimer);
      state.tickTimer = 0;
    }
  }

  function startTicking(totalDuration = prefersReducedMotion.matches ? 900 : 5200) {
    stopTicking();
    if (prefersReducedMotion.matches) return;

    const startedAt = performance.now();

    const schedule = () => {
      const elapsed = performance.now() - startedAt;
      if (elapsed >= totalDuration) {
        stopTicking();
        return;
      }

      const progress = elapsed / totalDuration;
      const interval = 65 + progress * 120 + Math.random() * 12;
      playTick();
      state.tickTimer = window.setTimeout(schedule, interval);
    };

    schedule();
  }

  function fireConfetti(count = prefersReducedMotion.matches ? 32 : 180) {
    if (!els.confettiWrap) return;

    const wrap = els.confettiWrap;
    const colors = ["#ffd85b", "#ff5c91", "#c56eff", "#ffffff", "#ff9cc0", "#ffe9a8"];
    const fragment = document.createDocumentFragment();

    for (let i = 0; i < count; i += 1) {
      const el = document.createElement("span");
      el.className = "confetti";
      el.style.left = `${Math.random() * 100}%`;
      el.style.top = `${-10 - Math.random() * 25}%`;
      el.style.background = colors[Math.floor(Math.random() * colors.length)];
      el.style.width = `${7 + Math.random() * 7}px`;
      el.style.height = `${10 + Math.random() * 12}px`;
      el.style.borderRadius = Math.random() > 0.65 ? "50%" : "2px";
      el.style.animationDuration = `${2.8 + Math.random() * 2.4}s`;
      el.style.animationDelay = `${Math.random() * 0.2}s`;
      el.style.transform = `rotate(${Math.random() * 360}deg)`;
      fragment.appendChild(el);
    }

    wrap.replaceChildren(fragment);
    clearTimeout(state.confettiTimer);
    state.confettiTimer = window.setTimeout(() => {
      wrap.innerHTML = "";
    }, 5200);
  }

  function updateActionButtons() {
    const canPaidSpin = state.user.fichas > 0;
    const canDemoSpin = state.user.demo_spins_left > 0;

    if (els.spinBtn) {
      els.spinBtn.disabled = state.spinning || !canPaidSpin;
      els.spinBtn.textContent = state.spinning
        ? state.spinSource === "demo"
          ? "⏳ GIRANDO DEMO..."
          : "⏳ GIRANDO..."
        : canPaidSpin
          ? "🎰 GIRAR CON FICHA"
          : "🎰 SIN FICHAS";
    }

    if (els.demoBtn) {
      els.demoBtn.disabled = state.spinning || !canDemoSpin;
      els.demoBtn.textContent = canDemoSpin ? "🆓 TIRADA DEMO" : "🆓 DEMO AGOTADA";
    }

    if (els.buyBtn) {
      els.buyBtn.disabled = state.spinning;
    }
  }

  function applyProfile(profile) {
    if (!profile || typeof profile !== "object") return;

    state.user.display_name = normalizeDisplayName(profile.display_name || state.user.display_name || state.user.full_name || state.user.username || "Jugador");
    state.user.fichas = clampInt(profile.fichas, state.user.fichas, 0);
    state.user.demo_spins_left = clampInt(profile.demo_spins_left, state.user.demo_spins_left, 0);
    persistUiState();
    renderProfile();
  }

  function normalizeProfileShape(data) {
    const source = data?.profile || data?.user || data || {};
    return {
      display_name: normalizeDisplayName(source.display_name || source.full_name || source.username || state.user.display_name || "Jugador"),
      fichas: clampInt(source.fichas, state.user.fichas, 0),
      demo_spins_left: clampInt(source.demo_spins_left, state.user.demo_spins_left, 0),
    };
  }

  function normalizePurchaseShape(data, country) {
    const purchase = data?.purchase || data || {};
    return {
      purchase_id: normalizeText(purchase.purchase_id || purchase.id || data?.purchase_id || `pending-${Date.now()}`),
      payment_link: normalizeText(purchase.payment_link || (country === "AR" ? config.mp_link_ar : config.mp_link_uy)),
      status: normalizeText(purchase.status, "pending"),
      qty: clampInt(purchase.qty, 1, 1),
    };
  }

  function resolvePrizeByName(prizeName) {
    const clean = normalizeText(prizeName).toLowerCase();
    return config.prizes.find((item) => normalizeText(item.name).toLowerCase() === clean) || null;
  }

  function normalizeSpinShape(data, requestedMode) {
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
        name: prizeName || matched.name,
        label,
        chance: clampFloat(result.chance || matched.chance, matched.chance, 0, 100),
        uyu_price: clampInt(result.uyu_price || matched.uyu_price, matched.uyu_price, 0),
        source: normalizeText(result.source || requestedMode || "paid"),
      },
    };
  }

  async function fetchJson(path, payload, timeoutMs = 12000) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
        },
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
        body: JSON.stringify(payload),
      });

      const text = await response.text();
      const data = safeJsonParse(text, null);

      if (!response.ok) {
        const message = data?.error || `Error ${response.status}`;
        throw new Error(message);
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
  }

  async function apiPost(paths, payload) {
    const list = Array.isArray(paths) ? paths : [paths];
    let lastError = null;

    for (const path of list) {
      try {
        return await fetchJson(path, payload);
      } catch (error) {
        lastError = error;
      }
    }

    throw lastError || new Error("No se pudo completar la solicitud");
  }

  function profilePayload(extra = {}) {
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
      ...extra,
    };
  }

  async function syncProfile(extra = {}) {
    const data = await apiPost(
      ["/api/user/sync", "/api/profile-sync", "/api/profile"],
      profilePayload(extra)
    );
    const profile = normalizeProfileShape(data);
    applyProfile(profile);
    return profile;
  }

  async function savePlayerName() {
    const newDisplayName = normalizeDisplayName(els.playerNameInput?.value || "");
    if (!newDisplayName) {
      toast("Escribí un nombre válido", "error");
      els.playerNameInput?.focus();
      return;
    }

    const profile = await syncProfile({ display_name: newDisplayName });
    state.user.display_name = profile.display_name;
    closeNameModal();
    toast(`Hola ${state.user.display_name}`, "success");
    announce(`Nombre guardado como ${state.user.display_name}`);
  }

  async function createPendingPayment(country) {
    const payload = {
      ...profilePayload(),
      country,
      qty: 1,
    };

    const data = await apiPost(
      ["/api/purchase", "/api/create-pending-purchase"],
      payload
    );

    const purchase = normalizePurchaseShape(data, country);
    setStatus("Pago pendiente", "Esperando aprobación");
    toast(`Compra registrada: ${purchase.purchase_id}`, "success");
    announce(`Pago pendiente registrado con referencia ${purchase.purchase_id}`);
    return purchase;
  }

  function openPayment(country) {
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
      window.location.href = url;
    }
  }

  async function refreshProfile() {
    await syncProfile();
  }

  function beginSpinUi(mode) {
    state.spinning = true;
    state.spinSource = mode;
    els.wheelCard?.classList.add("spinning");
    updateActionButtons();
    setStatus(mode === "demo" ? "Girando demo" : "Girando", "Animación activa");
    announce("La ruleta está girando");
  }

  function endSpinUi() {
    state.spinning = false;
    state.spinSource = "paid";
    els.wheelCard?.classList.remove("spinning");
    updateActionButtons();
  }

  function calculateTargetRotation(index) {
    const segmentAngle = 360 / config.prizes.length;
    const segmentCenter = index * segmentAngle + segmentAngle / 2;
    const fullSpins = prefersReducedMotion.matches ? 3 : 8 + Math.floor(Math.random() * 4);
    const fineOffset = prefersReducedMotion.matches ? 0 : (Math.random() * 8) - 4;
    state.currentRotation += (fullSpins * 360) + (360 - segmentCenter) + fineOffset;
    return {
      segmentCenter,
      rotation: state.currentRotation,
    };
  }

  async function spinWheel(mode) {
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

    beginSpinUi(mode);

    try {
      await ensureAudioReady();
      playSpinStart();

      const data = await apiPost("/api/spin", {
        ...profilePayload(),
        mode,
      });

      const normalized = normalizeSpinShape(data, mode);
      applyProfile(normalized.profile);

      const prizeIndex = config.prizes.findIndex((item) => item.name === normalized.prize.name);
      if (prizeIndex < 0) {
        throw new Error("Premio no encontrado en la ruleta.");
      }

      const target = calculateTargetRotation(prizeIndex);
      els.wheelSvg.style.transform = `rotate(${target.rotation}deg)`;

      const ballFinalAngle = (360 - target.segmentCenter) + 360;
      const spinDuration = prefersReducedMotion.matches ? 1200 : 6000;

      animateBallSpin(ballFinalAngle, spinDuration - 100);
      triggerPointerKick(spinDuration - 1200);
      startTicking(spinDuration - 500);

      clearTimeout(state.spinTimer);
      state.spinTimer = window.setTimeout(() => {
        const result = {
          name: normalized.prize.name,
          label: normalized.prize.label,
          chance: normalized.prize.chance,
          source: normalized.prize.source,
        };

        state.lastResult = result;
        persistUiState();
        renderWinner(result);
        playWinSound();
        fireConfetti();
        toast(`¡Ganaste: ${normalized.prize.name}!`, "success");
        setStatus("Premio entregado", mode === "demo" ? "Demo completada" : "Animación completada");
        announce(`Premio ganado: ${normalized.prize.name} por ${normalized.prize.label}`);
        endSpinUi();
      }, spinDuration);
    } catch (error) {
      stopTicking();
      stopBallAnimation();
      toast(error?.message || "Error al girar la ruleta", "error");
      setStatus("Error", "Reintentar");
      announce("Hubo un error al girar la ruleta");
      endSpinUi();
    }
  }

  function openNameModal() {
    if (!els.nameModal) return;
    state.modalFocusedBeforeOpen = document.activeElement;
    els.nameModal.classList.remove("hidden");
    els.nameModal.setAttribute("aria-hidden", "false");
    document.documentElement.style.overflow = "hidden";
    window.setTimeout(() => {
      els.playerNameInput?.focus();
      els.playerNameInput?.select();
    }, 20);
  }

  function closeNameModal() {
    if (!els.nameModal) return;
    els.nameModal.classList.add("hidden");
    els.nameModal.setAttribute("aria-hidden", "true");
    document.documentElement.style.overflow = "";
    if (state.modalFocusedBeforeOpen && typeof state.modalFocusedBeforeOpen.focus === "function") {
      state.modalFocusedBeforeOpen.focus();
    }
  }

  function maybeOpenNameModal() {
    if (!els.nameModal || !els.playerNameInput) return;
    const current = normalizeDisplayName(state.user.display_name);
    els.playerNameInput.value = current && current !== "Jugador" ? current : "";
    if (!current || current === "Jugador") {
      openNameModal();
    } else {
      closeNameModal();
    }
  }

  function trapModalFocus(event) {
    if (!els.nameModal || els.nameModal.classList.contains("hidden")) return;

    if (event.key === "Escape") {
      closeNameModal();
      return;
    }

    if (event.key !== "Tab") return;

    const focusable = Array.from(
      els.nameModal.querySelectorAll('button, input, [href], select, textarea, [tabindex]:not([tabindex="-1"])')
    ).filter((el) => !el.hasAttribute("disabled"));

    if (!focusable.length) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function scrollToPayment() {
    const target = state.currency === "ARS" ? els.payArBtn : els.payUyBtn;
    if (!target) return;
    target.scrollIntoView({
      behavior: prefersReducedMotion.matches ? "auto" : "smooth",
      block: "center",
    });
  }

  function onResize() {
    clearTimeout(state.resizeTimer);
    state.resizeTimer = window.setTimeout(() => {
      renderStars();
      renderParticles();
      renderLights();
    }, 120);
  }

  function onVisibilityChange() {
    if (document.hidden) {
      stopTicking();
      if (state.audioCtx?.state === "running") {
        state.audioCtx.suspend().catch(() => {});
      }
    }
  }

  function onFirstInteraction() {
    ensureAudioReady();
    window.removeEventListener("pointerdown", onFirstInteraction);
    window.removeEventListener("keydown", onFirstInteraction);
    window.removeEventListener("touchstart", onFirstInteraction);
  }

  function bindEvent(el, eventName, handler, options) {
    if (el) el.addEventListener(eventName, handler, options);
  }

  function bindEvents() {
    bindEvent(els.spinBtn, "click", () => spinWheel("paid"));
    bindEvent(els.demoBtn, "click", () => spinWheel("demo"));
    bindEvent(els.buyBtn, "click", scrollToPayment);

    bindEvent(els.btnUyu, "click", () => {
      state.currency = "UYU";
      renderTicket();
      renderPrizeList();
      updateCurrencyButtons();
      persistUiState();
      toast("Moneda cambiada a UYU");
      announce("Moneda cambiada a pesos uruguayos");
    });

    bindEvent(els.btnArs, "click", () => {
      state.currency = "ARS";
      renderTicket();
      renderPrizeList();
      updateCurrencyButtons();
      persistUiState();
      toast("Moneda cambiada a ARS");
      announce("Moneda cambiada a pesos argentinos");
    });

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
    bindEvent(document, "keydown", trapModalFocus);
    bindEvent(document, "visibilitychange", onVisibilityChange);
    bindEvent(window, "pointerdown", onFirstInteraction, { passive: true, once: false });
    bindEvent(window, "keydown", onFirstInteraction, { passive: true, once: false });
    bindEvent(window, "touchstart", onFirstInteraction, { passive: true, once: false });

    if (typeof prefersReducedMotion.addEventListener === "function") {
      prefersReducedMotion.addEventListener("change", () => {
        renderStars();
        renderParticles();
        renderLights();
        updateActionButtons();
      });
    }

    if (typeof prefersContrast.addEventListener === "function") {
      prefersContrast.addEventListener("change", () => {
        renderPrizeList();
        renderProfile();
      });
    }

    bindEvent(window, "pagehide", () => {
      stopTicking();
      stopBallAnimation();
      clearTimeout(state.spinTimer);
      clearTimeout(state.toastTimer);
      clearTimeout(state.resizeTimer);
      clearTimeout(state.confettiTimer);
    });
  }

  function boot() {
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
    setBallPosition(0, 42);
    bindEvents();
    maybeOpenNameModal();

    if (state.lastResult?.name) {
      announce(`Último premio: ${state.lastResult.name}`);
    }

    if (isTouchDevice) {
      document.body.classList.add("is-touch");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
