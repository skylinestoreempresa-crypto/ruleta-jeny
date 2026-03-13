const {
  prizes,
  currency: initialCurrency,
  user_id,
  username,
  full_name,
  display_name,
  fichas,
  demo_spins_left,
  uyu_to_ars,
  ticket_price_uyu,
  mp_link_ar,
  mp_link_uy,
} = window.RULETA_CONFIG;

let currency = initialCurrency;
let currentRotation = 0;
let spinning = false;
let audioCtx = null;
let tickInterval = null;
let spinTimeout = null;
let ballAnimFrame = null;

const wheelCard = document.getElementById("wheelCard");
const wheelSvg = document.getElementById("wheelSvg");
const spinBtn = document.getElementById("spinBtn");
const demoBtn = document.getElementById("demoBtn");
const buyBtn = document.getElementById("buyBtn");
const winnerBox = document.getElementById("winnerBox");
const prizeList = document.getElementById("prizeList");
const ticketPrice = document.getElementById("ticketPrice");
const miniTicket = document.getElementById("miniTicket");
const currencyChip = document.getElementById("currencyChip");
const statusValue = document.getElementById("statusValue");
const spinState = document.getElementById("spinState");
const totalItemsChip = document.getElementById("totalItemsChip");
const liveRegion = document.getElementById("liveRegion");
const btnUyu = document.getElementById("btnUyu");
const btnArs = document.getElementById("btnArs");
const ball = document.getElementById("ball");
const playerNameText = document.getElementById("playerNameText");
const fichasValue = document.getElementById("fichasValue");
const miniFichas = document.getElementById("miniFichas");
const miniDemo = document.getElementById("miniDemo");
const nameModal = document.getElementById("nameModal");
const playerNameInput = document.getElementById("playerNameInput");
const saveNameBtn = document.getElementById("saveNameBtn");
const skipNameBtn = document.getElementById("skipNameBtn");

const state = {
  user_id,
  username,
  full_name,
  display_name,
  fichas,
  demo_spins_left,
};

function convertPrice(uyuPrice, curr) {
  if (curr === "ARS") return `$${uyuPrice * uyu_to_ars} ARS`;
  return `$${uyuPrice} UYU`;
}

function getTicketLabel() {
  if (currency === "ARS") return `$${ticket_price_uyu * uyu_to_ars} ARS`;
  return `$${ticket_price_uyu} UYU`;
}

function polarToCartesian(cx, cy, r, angleDeg) {
  const angleRad = ((angleDeg - 90) * Math.PI) / 180;
  return {
    x: cx + r * Math.cos(angleRad),
    y: cy + r * Math.sin(angleRad)
  };
}

function describeWedge(cx, cy, r, startAngle, endAngle) {
  const start = polarToCartesian(cx, cy, r, endAngle);
  const end = polarToCartesian(cx, cy, r, startAngle);
  const largeArcFlag = endAngle - startAngle <= 180 ? "0" : "1";
  return `M ${cx} ${cy} L ${start.x} ${start.y} A ${r} ${r} 0 ${largeArcFlag} 0 ${end.x} ${end.y} Z`;
}

function safeShortLabel(text, maxLen = 17) {
  return text.length > maxLen ? text.slice(0, maxLen) + "…" : text;
}

function renderStars() {
  const wrap = document.getElementById("stars");
  wrap.innerHTML = "";
  const count = window.innerWidth < 700 ? 28 : 54;
  for (let i = 0; i < count; i++) {
    const el = document.createElement("span");
    el.className = "star";
    el.style.left = `${Math.random() * 100}%`;
    el.style.top = `${Math.random() * 100}%`;
    el.style.animationDelay = `${Math.random() * 4}s`;
    el.style.animationDuration = `${3 + Math.random() * 4}s`;
    wrap.appendChild(el);
  }
}

function renderParticles() {
  const wrap = document.getElementById("particles");
  wrap.innerHTML = "";
  const count = window.innerWidth < 700 ? 12 : 22;
  for (let i = 0; i < count; i++) {
    const el = document.createElement("span");
    el.className = "particle";
    el.style.left = `${Math.random() * 100}%`;
    el.style.bottom = `${-10 - Math.random() * 30}px`;
    el.style.animationDelay = `${Math.random() * 6}s`;
    el.style.animationDuration = `${8 + Math.random() * 8}s`;
    el.style.width = `${4 + Math.random() * 6}px`;
    el.style.height = el.style.width;
    wrap.appendChild(el);
  }
}

function renderLights() {
  const wrap = document.getElementById("lights");
  wrap.innerHTML = "";
  const count = 36;
  const radius = window.innerWidth < 640 ? 41.5 : 45.5;
  for (let i = 0; i < count; i++) {
    const dot = document.createElement("span");
    const angle = (i / count) * 360;
    dot.style.transform = `translate(-50%, -50%) rotate(${angle}deg) translateY(calc(-1 * ${radius}%))`;
    dot.style.animationDelay = `${i * 0.035}s`;
    wrap.appendChild(dot);
  }
}

function renderWheel() {
  const angle = 360 / prizes.length;
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

  let defs = `
    <filter id="segmentShadow" x="-50%" y="-50%" width="200%" height="200%">
      <feDropShadow dx="0" dy="1.2" stdDeviation="1.2" flood-color="rgba(0,0,0,.35)"/>
    </filter>
    <filter id="textShadow" x="-50%" y="-50%" width="200%" height="200%">
      <feDropShadow dx="0" dy="1.2" stdDeviation=".8" flood-color="rgba(0,0,0,.55)"/>
    </filter>
    <radialGradient id="centerGlow" cx="50%" cy="50%" r="60%">
      <stop offset="0%" stop-color="rgba(255,255,255,.08)"/>
      <stop offset="100%" stop-color="rgba(255,255,255,0)"/>
    </radialGradient>
  `;

  let html = "";
  prizes.forEach((prize, i) => {
    const startAngle = i * angle;
    const endAngle = (i + 1) * angle;
    const midAngle = startAngle + angle / 2;
    const path = describeWedge(50, 50, 47.8, startAngle, endAngle);
    const gradId = `grad${i}`;
    const glossId = `gloss${i}`;
    const text = safeShortLabel(prize.name, 18);

    defs += `
      <linearGradient id="${gradId}" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="${colors[i % colors.length][0]}"/>
        <stop offset="100%" stop-color="${colors[i % colors.length][1]}"/>
      </linearGradient>
      <linearGradient id="${glossId}" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stop-color="rgba(255,255,255,.18)"/>
        <stop offset="45%" stop-color="rgba(255,255,255,.04)"/>
        <stop offset="100%" stop-color="rgba(255,255,255,0)"/>
      </linearGradient>
    `;

    html += `
      <g filter="url(#segmentShadow)">
        <path d="${path}" fill="url(#${gradId})" stroke="rgba(255,255,255,0.24)" stroke-width="0.7"></path>
        <path d="${path}" fill="url(#${glossId})"></path>
        <g transform="rotate(${midAngle} 50 50)">
          <text x="50" y="15.4" text-anchor="middle" fill="white" font-size="3.9" font-weight="1000" filter="url(#textShadow)">${text}</text>
        </g>
      </g>
    `;
  });

  html += `<circle cx="50" cy="50" r="13" fill="url(#centerGlow)" />`;
  wheelSvg.innerHTML = `<defs>${defs}</defs>${html}`;
}

function renderPrizeList() {
  prizeList.innerHTML = "";
  prizes.forEach((p) => {
    const row = document.createElement("div");
    row.className = "prize-item";
    row.innerHTML = `
      <div class="prize-left">
        <div class="prize-name">${p.name}</div>
        <div class="prize-meta">Probabilidad ${p.chance}%</div>
      </div>
      <div class="prize-price">${convertPrice(p.uyu_price, currency)}</div>
    `;
    prizeList.appendChild(row);
  });
  totalItemsChip.textContent = `${prizes.length} premios`;
}

function renderTicket() {
  const text = getTicketLabel();
  ticketPrice.textContent = text;
  miniTicket.textContent = text;
  currencyChip.textContent = `Moneda ${currency}`;
}

function renderMiniStats() {
  document.getElementById("realPrizeCount").textContent = `${prizes.length} visibles`;
  miniFichas.textContent = String(state.fichas || 0);
  miniDemo.textContent = String(state.demo_spins_left || 0);
}

function renderProfile() {
  const name = state.display_name || state.full_name || state.username || "Jugador";
  playerNameText.textContent = name;
  fichasValue.textContent = `${state.fichas || 0} fichas`;
  renderMiniStats();
}

function setCurrency(curr) {
  currency = curr;
  renderPrizeList();
  renderTicket();
  updateCurrencyButtons();
  toast(`Moneda cambiada a ${currency}`);
}

function updateCurrencyButtons() {
  btnUyu.classList.toggle("active", currency === "UYU");
  btnArs.classList.toggle("active", currency === "ARS");
}

function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(() => el.classList.remove("show"), 2200);
}

function setStatus(main, secondary) {
  statusValue.textContent = main;
  spinState.textContent = secondary;
}

function announce(text) {
  liveRegion.textContent = text;
}

function animatePointerBounce() {
  const pointer = document.getElementById("pointer");
  pointer.animate(
    [
      { transform: "scaleY(1) translateY(0)" },
      { transform: "scaleY(1.14) translateY(3px)" },
      { transform: "scaleY(0.93) translateY(-1px)" },
      { transform: "scaleY(1) translateY(0)" }
    ],
    { duration: 220, iterations: 16, easing: "ease-in-out" }
  );
}

function startTicking(durationMs = 5200) {
  stopTicking();
  tickInterval = setInterval(() => playTick(), 95);
  setTimeout(() => stopTicking(), Math.max(300, durationMs - 700));
}

function stopTicking() {
  if (tickInterval) {
    clearInterval(tickInterval);
    tickInterval = null;
  }
}

function initAudio() {
  if (!audioCtx) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (AudioContextClass) {
      audioCtx = new AudioContextClass();
    }
  }
}

function playTone(type, frequency, duration, gainValue, when = 0) {
  if (!audioCtx) return;
  const now = audioCtx.currentTime + when;
  const osc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(frequency, now);
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(gainValue, now + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);
  osc.connect(gain);
  gain.connect(audioCtx.destination);
  osc.start(now);
  osc.stop(now + duration + 0.03);
}

function playTick() {
  initAudio();
  playTone("square", 950 + Math.random() * 180, 0.05, 0.017);
}

function playSpinStart() {
  initAudio();
  playTone("triangle", 420, 0.12, 0.025, 0);
  playTone("triangle", 560, 0.18, 0.018, 0.05);
}

function playWinSound() {
  initAudio();
  playTone("triangle", 740, 0.12, 0.03, 0);
  playTone("triangle", 920, 0.12, 0.03, 0.11);
  playTone("triangle", 1160, 0.2, 0.028, 0.22);
}

function fireConfetti(count = 180) {
  const wrap = document.getElementById("confettiWrap");
  wrap.innerHTML = "";
  const colors = ["#ffd85b", "#ff5c91", "#c56eff", "#ffffff", "#ff9cc0"];
  for (let i = 0; i < count; i++) {
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
    wrap.appendChild(el);
  }
  setTimeout(() => { wrap.innerHTML = ""; }, 5200);
}

function buildWinnerHTML(prizeName, prizeLabel, playerName) {
  return `
    <div class="info-label">Premio ganado</div>
    <div class="winner-main">${playerName}, ganaste ${prizeName}</div>
    <div class="winner-sub">${prizeLabel}</div>
    <div class="winner-badge">Resultado confirmado</div>
  `;
}

function setBallPosition(angleDeg, radiusPercent = 42) {
  const rad = (angleDeg - 90) * Math.PI / 180;
  const x = Math.cos(rad) * radiusPercent;
  const y = Math.sin(rad) * radiusPercent;
  ball.style.transform = `translate(calc(-50% + ${x}%), calc(-50% + ${y}%))`;
}

function stopBallAnimation() {
  if (ballAnimFrame) cancelAnimationFrame(ballAnimFrame);
  ballAnimFrame = null;
}

function animateBallSpin(finalAngle, duration = 5800) {
  stopBallAnimation();
  const start = performance.now();
  const baseTurns = 1440 + Math.random() * 540;
  const wobble = () => (Math.random() * 2.4) - 1.2;

  function frame(now) {
    const elapsed = now - start;
    const t = Math.min(1, elapsed / duration);
    const ease = 1 - Math.pow(1 - t, 3);
    const angle = (baseTurns * (1 - ease)) + (finalAngle * ease) + wobble();
    const radius = 43 - (ease * 4.5);
    setBallPosition(angle, radius);
    if (t < 1) {
      ballAnimFrame = requestAnimationFrame(frame);
    } else {
      setBallPosition(finalAngle, 38.5);
    }
  }

  ballAnimFrame = requestAnimationFrame(frame);
}

async function apiPost(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok || !data.ok) {
    throw new Error(data.error || "Error en la solicitud");
  }
  return data;
}

async function savePlayerName() {
  const newDisplayName = (playerNameInput.value || "").trim();
  const data = await apiPost("/api/profile", {
    user_id: state.user_id,
    username: state.username,
    full_name: state.full_name,
    currency,
    display_name: newDisplayName,
  });
  state.display_name = data.profile.display_name;
  state.fichas = data.profile.fichas;
  state.demo_spins_left = data.profile.demo_spins_left;
  renderProfile();
  nameModal.classList.add("hidden");
  toast(`Hola ${state.display_name}`);
}

async function createPendingPayment(country) {
  const data = await apiPost("/api/create-pending-purchase", {
    user_id: state.user_id,
    username: state.username,
    full_name: state.full_name,
    display_name: state.display_name,
    currency,
    country,
    qty: 1,
  });
  toast(`Compra registrada: ${data.purchase_id}`);
  setStatus("Pago pendiente", "Esperando aprobación");
}

function openPayment(country) {
  window.open(country === "AR" ? mp_link_ar : mp_link_uy, "_blank");
}

async function refreshProfile() {
  const data = await apiPost("/api/profile-sync", {
    user_id: state.user_id,
    username: state.username,
    full_name: state.full_name,
    currency,
    display_name: state.display_name,
  });
  state.display_name = data.profile.display_name;
  state.fichas = data.profile.fichas;
  state.demo_spins_left = data.profile.demo_spins_left;
  renderProfile();
}

async function spinWheel(mode) {
  if (spinning) return;

  spinning = true;
  wheelCard.classList.add("spinning");
  spinBtn.disabled = true;
  demoBtn.disabled = true;
  spinBtn.textContent = mode === "demo" ? "⏳ GIRANDO DEMO..." : "⏳ GIRANDO...";
  setStatus(mode === "demo" ? "Girando demo" : "Girando", "Animación activa");
  announce("La ruleta está girando");

  try {
    initAudio();
    if (audioCtx && audioCtx.state === "suspended") {
      await audioCtx.resume();
    }

    playSpinStart();

    const data = await apiPost("/api/spin", {
      user_id: state.user_id,
      username: state.username,
      full_name: state.full_name,
      display_name: state.display_name,
      currency,
      mode,
    });

    state.fichas = data.profile.fichas;
    state.demo_spins_left = data.profile.demo_spins_left;
    state.display_name = data.profile.display_name;
    renderProfile();

    const index = prizes.findIndex((p) => p.name === data.prize.name);
    if (index === -1) {
      throw new Error("Premio no encontrado en la ruleta.");
    }

    const segmentAngle = 360 / prizes.length;
    const targetSegmentCenter = index * segmentAngle + segmentAngle / 2;
    const fullSpins = 8 + Math.floor(Math.random() * 4);
    const fineOffset = (Math.random() * 8) - 4;

    currentRotation += (fullSpins * 360) + (360 - targetSegmentCenter) + fineOffset;
    wheelSvg.style.transform = `rotate(${currentRotation}deg)`;

    const ballFinalAngle = (360 - targetSegmentCenter) + 360;
    animateBallSpin(ballFinalAngle, 5900);
    animatePointerBounce();
    startTicking(5600);

    clearTimeout(spinTimeout);
    spinTimeout = setTimeout(() => {
      winnerBox.innerHTML = buildWinnerHTML(data.prize.name, data.prize.label, data.profile.display_name || "Jugador");
      playWinSound();
      fireConfetti(180);
      toast(`¡Ganaste: ${data.prize.name}!`);
      setStatus("Premio entregado", mode === "demo" ? "Demo completada" : "Animación completada");
      announce(`Premio ganado: ${data.prize.name} por ${data.prize.label}`);
      spinBtn.disabled = false;
      demoBtn.disabled = false;
      spinBtn.textContent = "🎰 GIRAR CON FICHA";
      wheelCard.classList.remove("spinning");
      spinning = false;
    }, 6000);
  } catch (e) {
    console.error(e);
    stopTicking();
    stopBallAnimation();
    toast(e.message || "Error al girar la ruleta");
    setStatus("Error", "Reintentar");
    announce("Hubo un error al girar la ruleta");
    spinBtn.disabled = false;
    demoBtn.disabled = false;
    spinBtn.textContent = "🎰 GIRAR CON FICHA";
    wheelCard.classList.remove("spinning");
    spinning = false;
  }
}

function maybeOpenNameModal() {
  const current = (state.display_name || "").trim();
  playerNameInput.value = current && current !== "Jugador" ? current : "";
  if (!current || current === "Jugador") {
    nameModal.classList.remove("hidden");
  } else {
    nameModal.classList.add("hidden");
  }
}

function boot() {
  renderStars();
  renderParticles();
  renderLights();
  renderWheel();
  renderPrizeList();
  renderTicket();
  renderProfile();
  updateCurrencyButtons();
  setStatus("Lista para girar", "Esperando");
  setBallPosition(0, 42);

  winnerBox.innerHTML = `
    <div class="info-label">Resultado</div>
    <div class="winner-main">Gira la ruleta</div>
    <div class="winner-sub">Tu premio aparecerá aquí</div>
    <div class="winner-badge">Sin resultado todavía</div>
  `;

  spinBtn.addEventListener("click", () => spinWheel("paid"));
  demoBtn.addEventListener("click", () => spinWheel("demo"));
  buyBtn.addEventListener("click", () =>
    document.getElementById("payUyBtn").scrollIntoView({ behavior: "smooth", block: "center" })
  );

  btnUyu.addEventListener("click", () => setCurrency("UYU"));
  btnArs.addEventListener("click", () => setCurrency("ARS"));

  document.getElementById("payArBtn").addEventListener("click", () => openPayment("AR"));
  document.getElementById("payUyBtn").addEventListener("click", () => openPayment("UY"));

  document.getElementById("confirmArPaidBtn").addEventListener("click", async () => {
    try {
      await createPendingPayment("AR");
      await refreshProfile();
    } catch (e) {
      toast(e.message || "No se pudo registrar la compra");
    }
  });

  document.getElementById("confirmUyPaidBtn").addEventListener("click", async () => {
    try {
      await createPendingPayment("UY");
      await refreshProfile();
    } catch (e) {
      toast(e.message || "No se pudo registrar la compra");
    }
  });

  saveNameBtn.addEventListener("click", async () => {
    try {
      await savePlayerName();
    } catch (e) {
      toast(e.message || "No se pudo guardar el nombre");
    }
  });

  skipNameBtn.addEventListener("click", () => nameModal.classList.add("hidden"));

  playerNameInput.addEventListener("keydown", async (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      try {
        await savePlayerName();
      } catch (err) {
        toast(err.message || "No se pudo guardar el nombre");
      }
    }
  });

  window.addEventListener("resize", () => {
    renderLights();
    renderStars();
  });

  maybeOpenNameModal();
}

boot();