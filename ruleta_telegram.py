import json
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
WEB_PORT = 8080

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
        "Ahora la ruleta se abre en modo visual tipo casino.\n"
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
  <title>Ruleta Visual</title>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Arial, sans-serif;
      background: radial-gradient(circle at top, #5a1039 0%, #180510 48%, #090409 100%);
      color: white;
      min-height: 100vh;
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 18px;
    }
    .layout {
      width: 100%;
      max-width: 1120px;
      display: grid;
      grid-template-columns: 1.2fr .8fr;
      gap: 22px;
    }
    .card {
      background: rgba(255,255,255,.05);
      border: 1px solid rgba(255,255,255,.12);
      border-radius: 28px;
      box-shadow: 0 18px 50px rgba(0,0,0,.35);
      backdrop-filter: blur(12px);
      overflow: hidden;
    }
    .card-header {
      padding: 22px 24px;
      border-bottom: 1px solid rgba(255,255,255,.08);
      background: rgba(255,255,255,.03);
    }
    .title { font-size: 34px; font-weight: 800; text-align: center; }
    .subtitle { text-align: center; color: rgba(255,255,255,.72); margin-top: 8px; }
    .card-body { padding: 28px; }
    .wheel-wrap {
      position: relative;
      max-width: 560px;
      margin: 0 auto;
      aspect-ratio: 1/1;
    }
    .wheel-glow {
      position: absolute; inset: 0;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(255,230,120,.2), rgba(255,0,120,.06), transparent 70%);
      filter: blur(18px);
    }
    .pointer {
      position: absolute;
      left: 50%; top: -6px;
      transform: translateX(-50%);
      width: 0; height: 0;
      border-left: 18px solid transparent;
      border-right: 18px solid transparent;
      border-top: 34px solid #f8d34b;
      z-index: 6;
      filter: drop-shadow(0 0 10px rgba(248,211,75,.95));
    }
    .wheel-shell {
      position: absolute; inset: 0;
      border-radius: 50%;
      border: 14px solid #f8d34b;
      box-shadow: 0 0 28px rgba(248,211,75,.34);
      overflow: hidden;
      background: rgba(0,0,0,.2);
      z-index: 3;
    }
    .wheel {
      width: 100%; height: 100%;
      border-radius: 50%;
      transition: transform 5.2s cubic-bezier(.12,.8,.2,1);
      transform: rotate(0deg);
    }
    .lights span {
      position: absolute;
      left: 50%; top: 50%;
      width: 10px; height: 10px;
      margin: -5px 0 0 -5px;
      border-radius: 999px;
      background: #f8d34b;
      box-shadow: 0 0 10px rgba(248,211,75,.95);
      z-index: 7;
    }
    .controls { margin-top: 26px; display: flex; flex-direction: column; align-items: center; gap: 14px; }
    .btn {
      border: 0; cursor: pointer;
      background: linear-gradient(90deg, #f8d34b, #ffbf00);
      color: #1e1200;
      font-weight: 800;
      font-size: 18px;
      padding: 16px 28px;
      border-radius: 18px;
      box-shadow: 0 10px 24px rgba(0,0,0,.25);
    }
    .btn:disabled { opacity: .65; cursor: not-allowed; }
    .info-label { color: rgba(255,255,255,.65); text-transform: uppercase; letter-spacing: .18em; font-size: 12px; }
    .ticket { font-size: 30px; font-weight: 800; }
    .panel { display: grid; gap: 18px; }
    .small-title { font-size: 28px; font-weight: 800; }
    .pill-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .pill {
      border: 1px solid rgba(255,255,255,.12);
      background: rgba(255,255,255,.06);
      color: white;
      padding: 14px 16px;
      border-radius: 18px;
      font-weight: 700;
      text-align: center;
      cursor: pointer;
    }
    .winner {
      padding: 18px;
      border-radius: 20px;
      background: linear-gradient(135deg, rgba(255,0,128,.18), rgba(120,0,255,.18));
      border: 1px solid rgba(255,255,255,.12);
    }
    .winner-main { font-size: 28px; font-weight: 800; margin-top: 8px; }
    .winner-sub { color: rgba(255,255,255,.8); margin-top: 6px; }
    .prize-list { display: grid; gap: 10px; }
    .prize-item {
      display: flex; justify-content: space-between; gap: 16px;
      padding: 12px 14px; border-radius: 14px;
      background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.06);
      font-size: 14px;
    }
    @media (max-width: 920px) {
      .layout { grid-template-columns: 1fr; }
      .title { font-size: 28px; }
    }
  </style>
</head>
<body>
  <div class="layout">
    <div class="card">
      <div class="card-header">
        <div class="title">🎰 Ruleta Casino Visual</div>
        <div class="subtitle">La misma lógica de tu bot, ahora con ruleta animada real</div>
      </div>
      <div class="card-body">
        <div class="wheel-wrap">
          <div class="wheel-glow"></div>
          <div class="pointer"></div>
          <div class="wheel-shell">
            <svg id="wheelSvg" class="wheel" viewBox="0 0 100 100"></svg>
          </div>
          <div class="lights" id="lights"></div>
        </div>

        <div class="controls">
          <button id="spinBtn" class="btn">🎰 GIRAR RULETA</button>
          <div class="info-label">Ficha</div>
          <div class="ticket" id="ticketPrice"></div>
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
  for (let i = 0; i < 24; i++) {
    const dot = document.createElement("span");
    const angle = (i / 24) * 360;
    dot.style.transform = `translate(-50%, -50%) rotate(${angle}deg) translateY(-270px)`;
    wrap.appendChild(dot);
  }
}

function renderWheel() {
  const svg = document.getElementById("wheelSvg");
  const angle = 360 / prizes.length;
  const colors = ["#ec4899", "#a21caf", "#f43f5e", "#d946ef", "#e11d48", "#c026d3", "#db2777", "#9333ea"];

  let html = "";
  prizes.forEach((prize, i) => {
    const startAngle = i * angle;
    const endAngle = (i + 1) * angle;
    const midAngle = startAngle + angle / 2;
    const path = describeWedge(50, 50, 48, startAngle, endAngle);
    const label = prize.name.length > 18 ? prize.name.slice(0, 18) + "…" : prize.name;
    html += `
      <g>
        <path d="${path}" fill="${colors[i % colors.length]}" stroke="rgba(255,255,255,0.3)" stroke-width="0.7"></path>
        <g transform="rotate(${midAngle} 50 50)">
          <text x="50" y="16" text-anchor="middle" fill="white" font-size="4" font-weight="700">${label}</text>
        </g>
      </g>
    `;
  });
  html += '<circle cx="50" cy="50" r="7" fill="#f8d34b" stroke="#fff" stroke-width="1.5"></circle>';
  html += '<circle cx="50" cy="50" r="2" fill="#7a1038"></circle>';
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

async function spinWheel() {
  if (spinning) return;
  spinning = true;
  const spinBtn = document.getElementById("spinBtn");
  spinBtn.disabled = true;
  spinBtn.textContent = "⏳ Girando...";

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
    currentRotation += (6 * 360) + (360 - targetSegmentCenter);
    document.getElementById("wheelSvg").style.transform = `rotate(${currentRotation}deg)`;

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
    }, 5200);
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
document.getElementById("btnUyu").addEventListener("click", () => { currency = "UYU"; renderPrizeList(); renderTicket(); });
document.getElementById("btnArs").addEventListener("click", () => { currency = "ARS"; renderPrizeList(); renderTicket(); });
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

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("premios", premios_command))
    app.add_handler(CommandHandler("myid", myid_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    print(f"{BOT_NAME} iniciado correctamente...")
    print(f"Web visual disponible en http://127.0.0.1:{WEB_PORT}/wheel")
    app.run_polling()


if __name__ == "__main__":
    main()
