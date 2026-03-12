import json
import os
import random
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, jsonify, render_template_string, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# =========================
# CONFIGURACION
# =========================

TOKEN = "8705191584:AAG4sXJ7tBRHiMFVxw2THfzEFDtCVzZGYrA"
ADMIN_IDS = {8445311801}
BOT_NAME = "Ruleta Jeny"
DEFAULT_CURRENCY = "UYU"
LOG_FILE = Path("spins_log.json")
UYU_TO_ARS = 25
WEBAPP_BASE_URL = "https://intermural-haematothermal-mai.ngrok-free.dev"
WEB_PORT = int(os.environ.get("PORT", 8080))

REAL_PRIZES = [
    {"name": "📸 Foto personalizada", "weight": 22, "uyu_price": 400},
    {"name": "🎥 Video personalizado", "weight": 18, "uyu_price": 500},
    {"name": "🔥 3 videos x 3 min", "weight": 12, "uyu_price": 700},
    {"name": "📷 Pack 8 fotos", "weight": 20, "uyu_price": 350},
    {"name": "💋 Pose favorita", "weight": 15, "uyu_price": 200},
    {"name": "💬 Sexting 1 hora", "weight": 5, "uyu_price": 950},
    {"name": "📸 10 fotos personalizadas", "weight": 4, "uyu_price": 1000},
    {"name": "🎬 Video personalizado 3 min", "weight": 4, "uyu_price": 750},
]

VISIBLE_ONLY_PRIZE = {"name": "💎 Encuentro", "uyu_price": 1500}

app_flask = Flask(__name__)
app = app_flask  # <- necesario para Render/Gunicorn


# =========================
# UTILIDADES
# =========================

def ensure_log_file() -> None:
    if not LOG_FILE.exists():
        LOG_FILE.write_text("[]", encoding="utf-8")


def load_logs() -> list:
    ensure_log_file()
    try:
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def save_logs(logs: list) -> None:
    LOG_FILE.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")


def log_spin(user_id, username, full_name, prize_name: str, currency: str) -> None:
    logs = load_logs()
    logs.append(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "user_id": user_id,
            "username": username,
            "full_name": full_name,
            "currency": currency,
            "prize": prize_name,
        }
    )
    save_logs(logs)


def pick_weighted_prize() -> dict:
    prizes = [p for p in REAL_PRIZES]
    weights = [p["weight"] for p in REAL_PRIZES]
    return random.choices(prizes, weights=weights, k=1)[0]


def get_currency_from_language(language_code: str | None) -> str:
    lang = (language_code or "").lower()
    if lang == "es-ar":
        return "ARS"
    if lang == "es-uy":
        return "UYU"
    return DEFAULT_CURRENCY


def convert_price_from_uyu(amount_uyu: int, currency: str) -> str:
    if currency == "ARS":
        ars = amount_uyu * UYU_TO_ARS
        return f"${ars} ARS"
    return f"${amount_uyu} UYU"


def get_ficha_price_text(currency: str) -> str:
    return convert_price_from_uyu(250, currency)


def format_prize(prize: dict, currency: str) -> str:
    return f"{prize['name']} — {convert_price_from_uyu(prize['uyu_price'], currency)}"


def format_prize_list(currency: str) -> str:
    lines = []
    for p in REAL_PRIZES:
        lines.append(format_prize(p, currency))
    lines.append(format_prize(VISIBLE_ONLY_PRIZE, currency))
    return "\n".join(lines)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def build_webapp_url(user) -> str:
    currency = get_currency_from_language(getattr(user, "language_code", None))
    params = urlencode(
        {
            "user_id": user.id,
            "username": user.username or "",
            "full_name": user.full_name or "",
            "currency": currency,
        }
    )
    return f"{WEBAPP_BASE_URL}/wheel?{params}"


# =========================
# TELEGRAM BOT
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    currency = get_currency_from_language(user.language_code)
    webapp_url = build_webapp_url(user)

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=f"🎰 ABRIR RULETA VISUAL • FICHA {get_ficha_price_text(currency)}",
                    web_app=WebAppInfo(url=webapp_url),
                )
            ],
            [InlineKeyboardButton("🎁 Ver premios", callback_data="view_prizes")],
        ]
    )

    text = (
        f"🎀 Bienvenido/a a {BOT_NAME}\n\n"
        f"💱 Moneda detectada: {currency}\n"
        f"🎟 Valor de la ficha: {get_ficha_price_text(currency)}\n\n"
        "Ahora la ruleta se abre en modo visual tipo casino premium.\n"
        "Toca el botón para abrir la ruleta animada."
    )

    await update.message.reply_text(text, reply_markup=keyboard)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "/start - abrir menú\n"
        "/premios - ver premios\n"
        "/myid - ver tu ID\n"
        "/stats - estadísticas (solo admin)"
    )


async def premios_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    currency = get_currency_from_language(user.language_code)
    await update.message.reply_text(
        f"🎁 Premios ({currency}):\n\n{format_prize_list(currency)}\n\n"
        f"🎟 Valor de la ficha: {get_ficha_price_text(currency)}"
    )


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Tu ID de Telegram es: {update.effective_user.id}")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("No autorizado.")
        return

    logs = load_logs()
    total = len(logs)
    if total == 0:
        await update.message.reply_text("Todavía no hay giros registrados.")
        return

    counts = {}
    for item in logs:
        prize = item["prize"]
        counts[prize] = counts.get(prize, 0) + 1

    lines = [f"📊 Giros totales: {total}", ""]
    for prize, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"{prize}: {count}")

    await update.message.reply_text("\n".join(lines))


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "view_prizes":
        user = query.from_user
        currency = get_currency_from_language(user.language_code)
        await query.message.reply_text(
            f"🎁 Premios ({currency}):\n\n{format_prize_list(currency)}\n\n"
            f"🎟 Valor de la ficha: {get_ficha_price_text(currency)}"
        )


# =========================
# FLASK WEB APP VISUAL
# =========================

HTML_TEMPLATE = r'''
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ruleta Casino Premium</title>
  <style>
    * { box-sizing: border-box; }
    :root{
      --bg1:#12010e;
      --bg2:#2a0720;
      --gold1:#f7d457;
      --gold2:#d89b13;
      --gold3:#fff0ac;
      --panel:rgba(255,255,255,.05);
      --line:rgba(255,255,255,.11);
      --soft:rgba(255,255,255,.72);
      --shadow:0 24px 60px rgba(0,0,0,.45);
      --pink:#ff3c8f;
      --pink2:#d81b7a;
      --violet:#8b2be2;
      --violet2:#5e1ae3;
      --red:#ff355d;
    }

    body{
      margin:0;
      font-family: Inter, Arial, sans-serif;
      color:#fff;
      min-height:100vh;
      background:
        radial-gradient(circle at 50% -10%, rgba(255,208,84,.18), transparent 30%),
        radial-gradient(circle at 10% 20%, rgba(255,31,143,.16), transparent 24%),
        radial-gradient(circle at 80% 10%, rgba(139,43,226,.14), transparent 28%),
        linear-gradient(180deg,var(--bg2),var(--bg1));
      padding:18px;
    }

    .layout{
      width:100%;
      max-width:1280px;
      margin:0 auto;
      display:grid;
      grid-template-columns: 1.15fr .85fr;
      gap:24px;
      align-items:start;
    }

    .card{
      background:linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.035));
      border:1px solid var(--line);
      border-radius:32px;
      box-shadow:var(--shadow);
      overflow:hidden;
      backdrop-filter: blur(12px);
      position:relative;
    }

    .card::before{
      content:"";
      position:absolute;
      inset:0;
      background:linear-gradient(180deg, rgba(255,255,255,.05), transparent 18%, transparent 82%, rgba(255,255,255,.03));
      pointer-events:none;
    }

    .card-header{
      padding:24px 26px;
      border-bottom:1px solid rgba(255,255,255,.08);
      background:linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.025));
      position:relative;
      z-index:1;
    }

    .title{
      font-size:clamp(28px,4vw,46px);
      line-height:1.06;
      font-weight:900;
      letter-spacing:-.03em;
      text-align:center;
      text-shadow:0 2px 12px rgba(0,0,0,.35);
    }

    .subtitle{
      text-align:center;
      color:var(--soft);
      margin-top:8px;
      font-size:16px;
    }

    .card-body{
      padding:28px;
      position:relative;
      z-index:1;
    }

    .wheel-wrap{
      position:relative;
      max-width:650px;
      margin:0 auto;
      aspect-ratio:1/1;
    }

    .wheel-aura{
      position:absolute;
      inset:-4%;
      border-radius:50%;
      background:
        radial-gradient(circle, rgba(255,231,133,.24), rgba(255,191,0,.12), rgba(255,0,122,.10), transparent 72%);
      filter: blur(22px);
    }

    .wheel-shell{
      position:absolute;
      inset:0;
      border-radius:50%;
      background:
        radial-gradient(circle at 50% 50%, rgba(255,255,255,.08), rgba(255,255,255,.01) 58%, transparent 60%),
        linear-gradient(145deg, #3f0d24, #14040d);
      border:18px solid var(--gold1);
      box-shadow:
        0 0 0 4px rgba(255,255,255,.08) inset,
        0 0 0 10px rgba(76,17,40,.55) inset,
        0 0 30px rgba(247,212,87,.36),
        0 35px 60px rgba(0,0,0,.45);
      overflow:hidden;
    }

    .wheel{
      width:100%;
      height:100%;
      border-radius:50%;
      transition:transform 5.4s cubic-bezier(.08,.86,.22,1);
      transform:rotate(0deg);
      filter: drop-shadow(0 10px 26px rgba(0,0,0,.35));
    }

    .wheel-center{
      position:absolute;
      left:50%;
      top:50%;
      transform:translate(-50%,-50%);
      width:82px;
      height:82px;
      border-radius:50%;
      z-index:9;
      background:
        radial-gradient(circle at 30% 30%, var(--gold3), var(--gold1) 45%, var(--gold2) 80%);
      border:8px solid rgba(255,255,255,.92);
      box-shadow:
        0 0 0 8px rgba(60,0,24,.35),
        0 10px 26px rgba(0,0,0,.4);
    }

    .wheel-center::after{
      content:"";
      position:absolute;
      left:50%;
      top:50%;
      width:26px;
      height:26px;
      transform:translate(-50%,-50%);
      border-radius:50%;
      background:#8a103f;
      box-shadow: inset 0 2px 6px rgba(0,0,0,.35);
    }

    .pointer-wrap{
      position:absolute;
      left:50%;
      top:-14px;
      transform:translateX(-50%);
      z-index:10;
      width:74px;
      height:100px;
      display:flex;
      align-items:flex-start;
      justify-content:center;
      pointer-events:none;
    }

    .pointer{
      width:0;
      height:0;
      border-left:24px solid transparent;
      border-right:24px solid transparent;
      border-top:54px solid var(--gold1);
      filter: drop-shadow(0 0 8px rgba(247,212,87,.9));
      transform-origin:50% 0%;
      animation: pointerPulse 1.3s ease-in-out infinite;
    }

    @keyframes pointerPulse{
      0%,100%{ transform:scaleY(1); }
      50%{ transform:scaleY(1.05); }
    }

    .lights span{
      position:absolute;
      left:50%;
      top:50%;
      width:12px;
      height:12px;
      margin:-6px 0 0 -6px;
      border-radius:999px;
      background:var(--gold1);
      box-shadow:
        0 0 8px rgba(255,219,110,.95),
        0 0 18px rgba(255,219,110,.65);
      z-index:8;
      animation: blink 1.25s ease-in-out infinite;
    }

    @keyframes blink{
      0%,100%{ opacity:1; transform:scale(1); }
      50%{ opacity:.4; transform:scale(.82); }
    }

    .shine{
      position:absolute;
      inset:10% 16% auto 16%;
      height:130px;
      border-radius:999px;
      background:linear-gradient(180deg, rgba(255,255,255,.18), rgba(255,255,255,0));
      transform:rotate(-14deg);
      filter: blur(4px);
      pointer-events:none;
      z-index:8;
    }

    .controls{
      margin-top:28px;
      display:flex;
      flex-direction:column;
      align-items:center;
      gap:16px;
    }

    .btn{
      border:0;
      cursor:pointer;
      padding:18px 34px;
      border-radius:20px;
      font-weight:900;
      font-size:20px;
      letter-spacing:.01em;
      color:#1c0f00;
      background:
        linear-gradient(180deg, #ffe588, #f7d457 45%, #d89b13 100%);
      box-shadow:
        0 10px 24px rgba(0,0,0,.22),
        0 0 0 2px rgba(255,255,255,.16) inset;
      transition:transform .18s ease, filter .18s ease, opacity .18s ease;
    }

    .btn:hover{ transform:translateY(-2px); filter:brightness(1.03); }
    .btn:disabled{ opacity:.7; cursor:not-allowed; transform:none; }

    .info-label{
      color:rgba(255,255,255,.62);
      text-transform:uppercase;
      letter-spacing:.22em;
      font-size:12px;
      font-weight:700;
    }

    .ticket{
      font-size:34px;
      font-weight:900;
      text-shadow:0 4px 16px rgba(0,0,0,.28);
    }

    .panel{
      display:grid;
      gap:18px;
    }

    .small-title{
      font-size:38px;
      font-weight:900;
      letter-spacing:-.03em;
    }

    .pill-row{
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:12px;
    }

    .pill{
      border:1px solid rgba(255,255,255,.12);
      background:linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.035));
      color:white;
      padding:15px 18px;
      border-radius:20px;
      font-weight:800;
      text-align:center;
      cursor:pointer;
      transition:all .18s ease;
      box-shadow: inset 0 1px 0 rgba(255,255,255,.05);
    }

    .pill:hover{
      transform:translateY(-1px);
      border-color:rgba(255,255,255,.22);
      background:linear-gradient(180deg, rgba(255,255,255,.08), rgba(255,255,255,.05));
    }

    .winner{
      padding:22px;
      border-radius:24px;
      background:
        radial-gradient(circle at top left, rgba(255,219,110,.10), transparent 30%),
        linear-gradient(135deg, rgba(255,46,132,.18), rgba(91,34,219,.18));
      border:1px solid rgba(255,255,255,.12);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.06);
      min-height:150px;
    }

    .winner-main{
      font-size:clamp(30px,4vw,40px);
      font-weight:900;
      line-height:1.05;
      margin-top:10px;
    }

    .winner-sub{
      color:rgba(255,255,255,.82);
      margin-top:8px;
      font-size:18px;
      font-weight:700;
    }

    .prize-list{
      display:grid;
      gap:10px;
      max-height:520px;
      overflow:auto;
      padding-right:4px;
    }

    .prize-list::-webkit-scrollbar{ width:8px; }
    .prize-list::-webkit-scrollbar-thumb{
      background:rgba(255,255,255,.15);
      border-radius:999px;
    }

    .prize-item{
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:16px;
      padding:14px 16px;
      border-radius:16px;
      background:linear-gradient(180deg, rgba(255,255,255,.045), rgba(255,255,255,.03));
      border:1px solid rgba(255,255,255,.07);
      font-size:15px;
      box-shadow: inset 0 1px 0 rgba(255,255,255,.03);
    }

    .prize-item strong{
      white-space:nowrap;
      font-size:15px;
    }

    .footer-note{
      text-align:center;
      color:rgba(255,255,255,.48);
      font-size:12px;
      margin-top:8px;
    }

    @media (max-width: 1000px){
      .layout{ grid-template-columns:1fr; }
      .small-title{ font-size:30px; }
      .card-body{ padding:22px; }
    }

    @media (max-width: 640px){
      body{ padding:10px; }
      .card{ border-radius:24px; }
      .card-header{ padding:20px 18px; }
      .card-body{ padding:18px; }
      .wheel-shell{ border-width:14px; }
      .pointer-wrap{ top:-8px; }
      .pointer{
        border-left-width:18px;
        border-right-width:18px;
        border-top-width:42px;
      }
      .btn{
        width:100%;
        font-size:18px;
        padding:16px 20px;
      }
      .ticket{ font-size:28px; }
    }
  </style>
</head>
<body>
  <div class="layout">
    <div class="card">
      <div class="card-header">
        <div class="title">🎰 Ruleta Casino Premium</div>
        <div class="subtitle">Visual más pro, estilo casino, con la misma lógica real de tu bot</div>
      </div>

      <div class="card-body">
        <div class="wheel-wrap">
          <div class="wheel-aura"></div>
          <div class="shine"></div>

          <div class="pointer-wrap">
            <div class="pointer" id="pointer"></div>
          </div>

          <div class="wheel-shell">
            <svg id="wheelSvg" class="wheel" viewBox="0 0 100 100"></svg>
          </div>

          <div class="wheel-center"></div>
          <div class="lights" id="lights"></div>
        </div>

        <div class="controls">
          <button id="spinBtn" class="btn">🎰 GIRAR RULETA</button>
          <div class="info-label">Valor de la ficha</div>
          <div class="ticket" id="ticketPrice"></div>
          <div class="footer-note">Diseño casino premium • Ruleta visual animada</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <div class="small-title">Panel</div>
      </div>

      <div class="card-body panel">
        <div class="pill-row">
          <button class="pill" id="btnUyu">🇺🇾 Mostrar UYU</button>
          <button class="pill" id="btnArs">🇦🇷 Mostrar ARS</button>
        </div>

        <div class="winner" id="winnerBox">
          <div class="info-label">Resultado</div>
          <div class="winner-main">Gira la ruleta</div>
          <div class="winner-sub">Tu premio aparecerá aquí</div>
        </div>

        <div>
          <div class="info-label" style="margin-bottom:10px;">Premios visibles</div>
          <div class="prize-list" id="prizeList"></div>
        </div>
      </div>
    </div>
  </div>

<script>
const prizes = {{ prizes|safe }};
const visibleOnlyPrize = {{ visible_only_prize|safe }};
let currency = {{ currency|tojson }};
let currentRotation = 0;
let spinning = false;

const queryData = {
  user_id: {{ user_id|tojson }},
  username: {{ username|tojson }},
  full_name: {{ full_name|tojson }}
};

function convertPrice(uyuPrice, curr) {
  if (curr === "ARS") return `$${uyuPrice * {{ uyu_to_ars }}} ARS`;
  return `$${uyuPrice} UYU`;
}

function ticketText() {
  return currency === "ARS" ? `$${250 * {{ uyu_to_ars }}} ARS` : "$250 UYU";
}

function polarToCartesian(cx, cy, r, angleDeg) {
  const angleRad = ((angleDeg - 90) * Math.PI) / 180.0;
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

function renderLights() {
  const wrap = document.getElementById("lights");
  wrap.innerHTML = "";
  for (let i = 0; i < 28; i++) {
    const dot = document.createElement("span");
    const angle = (i / 28) * 360;
    dot.style.transform = `translate(-50%, -50%) rotate(${angle}deg) translateY(-305px)`;
    dot.style.animationDelay = `${i * 0.05}s`;
    wrap.appendChild(dot);
  }
}

function renderWheel() {
  const svg = document.getElementById("wheelSvg");
  const angle = 360 / prizes.length;
  const colors = [
    ["#ff4f94", "#d71f7f"],
    ["#8f3dff", "#6225e6"],
    ["#ff4f67", "#e01943"],
    ["#ca41f0", "#9820d4"],
    ["#ff2f7c", "#d91767"],
    ["#9e37f1", "#741fe0"],
    ["#ff5164", "#ea243d"],
    ["#cf47ff", "#8e2be2"]
  ];

  let html = "";
  prizes.forEach((prize, i) => {
    const startAngle = i * angle;
    const endAngle = (i + 1) * angle;
    const midAngle = startAngle + angle / 2;
    const path = describeWedge(50, 50, 48, startAngle, endAngle);
    const label = prize.name.length > 18 ? prize.name.slice(0, 18) + "…" : prize.name;
    const gradId = `grad${i}`;

    html += `
      <defs>
        <linearGradient id="${gradId}" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="${colors[i % colors.length][0]}"/>
          <stop offset="100%" stop-color="${colors[i % colors.length][1]}"/>
        </linearGradient>
      </defs>

      <g>
        <path d="${path}" fill="url(#${gradId})" stroke="rgba(255,255,255,0.26)" stroke-width="0.7"></path>
        <g transform="rotate(${midAngle} 50 50)">
          <text
            x="50"
            y="15.4"
            text-anchor="middle"
            fill="white"
            font-size="4.15"
            font-weight="900"
            style="text-shadow:0 2px 4px rgba(0,0,0,.35);"
          >${label}</text>
        </g>
      </g>
    `;
  });

  svg.innerHTML = html;
}

function renderPrizeList() {
  const box = document.getElementById("prizeList");
  box.innerHTML = "";
  [...prizes, visibleOnlyPrize].forEach((p) => {
    const row = document.createElement("div");
    row.className = "prize-item";
    row.innerHTML = `<span>${p.name}</span><strong>${convertPrice(p.uyu_price, currency)}</strong>`;
    box.appendChild(row);
  });
}

function renderTicket() {
  document.getElementById("ticketPrice").textContent = ticketText();
}

function animatePointerBounce() {
  const pointer = document.getElementById("pointer");
  pointer.animate(
    [
      { transform: "scaleY(1)" },
      { transform: "scaleY(1.12) translateY(2px)" },
      { transform: "scaleY(0.96)" },
      { transform: "scaleY(1)" }
    ],
    {
      duration: 260,
      iterations: 12,
      easing: "ease-in-out"
    }
  );
}

async function spinWheel() {
  if (spinning) return;
  spinning = true;

  const spinBtn = document.getElementById("spinBtn");
  spinBtn.disabled = true;
  spinBtn.textContent = "⏳ GIRANDO...";

  try {
    const response = await fetch("/api/spin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...queryData, currency })
    });

    const data = await response.json();

    const index = prizes.findIndex((p) => p.name === data.prize.name);
    const segmentAngle = 360 / prizes.length;
    const targetSegmentCenter = index * segmentAngle + segmentAngle / 2;
    currentRotation += (7 * 360) + (360 - targetSegmentCenter);

    document.getElementById("wheelSvg").style.transform = `rotate(${currentRotation}deg)`;
    animatePointerBounce();

    setTimeout(() => {
      const box = document.getElementById("winnerBox");
      box.innerHTML = `
        <div class="info-label">Premio ganado</div>
        <div class="winner-main">${data.prize.name}</div>
        <div class="winner-sub">${data.prize.label}</div>
      `;

      spinBtn.disabled = false;
      spinBtn.textContent = "🎰 GIRAR RULETA";
      spinning = false;
    }, 5400);

  } catch (e) {
    alert("Error al girar la ruleta");
    spinBtn.disabled = false;
    spinBtn.textContent = "🎰 GIRAR RULETA";
    spinning = false;
  }
}

renderLights();
renderWheel();
renderPrizeList();
renderTicket();

document.getElementById("spinBtn").addEventListener("click", spinWheel);
document.getElementById("btnUyu").addEventListener("click", () => {
  currency = "UYU";
  renderPrizeList();
  renderTicket();
});
document.getElementById("btnArs").addEventListener("click", () => {
  currency = "ARS";
  renderPrizeList();
  renderTicket();
});
</script>
</body>
</html>
'''


@app_flask.get("/wheel")
def wheel_page():
    user_id = request.args.get("user_id", "")
    username = request.args.get("username", "")
    full_name = request.args.get("full_name", "")
    currency = request.args.get("currency", DEFAULT_CURRENCY)
    return render_template_string(
        HTML_TEMPLATE,
        prizes=json.dumps(REAL_PRIZES, ensure_ascii=False),
        visible_only_prize=json.dumps(VISIBLE_ONLY_PRIZE, ensure_ascii=False),
        currency=currency,
        user_id=user_id,
        username=username,
        full_name=full_name,
        uyu_to_ars=UYU_TO_ARS,
    )


@app_flask.post("/api/spin")
def api_spin():
    data = request.get_json(force=True)
    user_id = data.get("user_id")
    username = data.get("username")
    full_name = data.get("full_name")
    currency = data.get("currency", DEFAULT_CURRENCY)

    prize = pick_weighted_prize()
    prize_label = format_prize(prize, currency)
    log_spin(user_id, username, full_name, prize_label, currency)

    return jsonify(
        {
            "ok": True,
            "prize": {
                "name": prize["name"],
                "label": convert_price_from_uyu(prize["uyu_price"], currency),
            },
            "ticket": get_ficha_price_text(currency),
        }
    )


# =========================
# INICIO
# =========================

def run_flask():
    app_flask.run(host="0.0.0.0", port=WEB_PORT, debug=False)


def main() -> None:
    ensure_log_file()

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    bot_app = ApplicationBuilder().token(TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(CommandHandler("premios", premios_command))
    bot_app.add_handler(CommandHandler("myid", myid_command))
    bot_app.add_handler(CommandHandler("stats", stats_command))
    bot_app.add_handler(CallbackQueryHandler(button_handler))

    print(f"{BOT_NAME} iniciado correctamente...")
    print(f"Web visual disponible en http://127.0.0.1:{WEB_PORT}/wheel")
    bot_app.run_polling()


if __name__ == "__main__":
    main()