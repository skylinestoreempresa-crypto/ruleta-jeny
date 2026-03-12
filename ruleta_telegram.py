import json
import logging
import os
import random
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from flask import Flask, jsonify, render_template_string, request
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# =========================================================
# CONFIGURACION
# =========================================================

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
BOT_NAME = os.environ.get("BOT_NAME", "Ruleta Jeny").strip()
DEFAULT_CURRENCY = os.environ.get("DEFAULT_CURRENCY", "UYU").strip().upper()
WEBAPP_BASE_URL = os.environ.get(
    "WEBAPP_BASE_URL",
    "https://ruleta-jeny-2.onrender.com",
).rstrip("/")
WEB_PORT = int(os.environ.get("PORT", "8080"))
UYU_TO_ARS = int(os.environ.get("UYU_TO_ARS", "25"))
LOG_FILE = Path(os.environ.get("LOG_FILE", "spins_log.json"))

ADMIN_IDS = {
    int(x.strip())
    for x in os.environ.get("ADMIN_IDS", "8445311801").split(",")
    if x.strip().isdigit()
}

RUN_TELEGRAM_BOT = os.environ.get("RUN_TELEGRAM_BOT", "false").strip().lower() == "true"

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

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# =========================================================
# APP
# =========================================================

app = Flask(__name__)

_log_lock = threading.Lock()
_bot_lock = threading.Lock()
_bot_started = False

# =========================================================
# UTILIDADES
# =========================================================


def ensure_log_file() -> None:
    if not LOG_FILE.exists():
        LOG_FILE.write_text("[]", encoding="utf-8")


def load_logs() -> list[dict[str, Any]]:
    ensure_log_file()
    with _log_lock:
        try:
            content = LOG_FILE.read_text(encoding="utf-8").strip()
            if not content:
                return []
            data = json.loads(content)
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            logger.exception("No se pudo leer el archivo de logs.")
            return []


def save_logs(logs: list[dict[str, Any]]) -> None:
    with _log_lock:
        LOG_FILE.write_text(
            json.dumps(logs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def log_spin(
    user_id: str | int | None,
    username: str | None,
    full_name: str | None,
    prize_name: str,
    currency: str,
) -> None:
    logs = load_logs()
    logs.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "user_id": user_id,
            "username": username or "",
            "full_name": full_name or "",
            "currency": currency,
            "prize": prize_name,
        }
    )
    save_logs(logs)


def pick_weighted_prize() -> dict[str, Any]:
    weights = [p["weight"] for p in REAL_PRIZES]
    return random.choices(REAL_PRIZES, weights=weights, k=1)[0]


def get_currency_from_language(language_code: str | None) -> str:
    lang = (language_code or "").lower()
    if lang.startswith("es-ar"):
        return "ARS"
    if lang.startswith("es-uy"):
        return "UYU"
    return DEFAULT_CURRENCY


def normalize_currency(currency: str | None) -> str:
    value = (currency or DEFAULT_CURRENCY).strip().upper()
    return value if value in {"UYU", "ARS"} else DEFAULT_CURRENCY


def convert_price_from_uyu(amount_uyu: int, currency: str) -> str:
    currency = normalize_currency(currency)
    if currency == "ARS":
        return f"${amount_uyu * UYU_TO_ARS} ARS"
    return f"${amount_uyu} UYU"


def get_ficha_price_text(currency: str) -> str:
    return convert_price_from_uyu(250, currency)


def format_prize(prize: dict[str, Any], currency: str) -> str:
    return f"{prize['name']} — {convert_price_from_uyu(int(prize['uyu_price']), currency)}"


def format_prize_list(currency: str) -> str:
    lines = [format_prize(p, currency) for p in REAL_PRIZES]
    lines.append(format_prize(VISIBLE_ONLY_PRIZE, currency))
    return "\n".join(lines)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def build_webapp_url(user: Any) -> str:
    currency = get_currency_from_language(getattr(user, "language_code", None))
    params = urlencode(
        {
            "user_id": getattr(user, "id", ""),
            "username": getattr(user, "username", "") or "",
            "full_name": getattr(user, "full_name", "") or "",
            "currency": currency,
        }
    )
    return f"{WEBAPP_BASE_URL}/wheel?{params}"


# =========================================================
# TELEGRAM BOT
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    user = update.effective_user
    currency = get_currency_from_language(user.language_code)
    webapp_url = build_webapp_url(user)

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=f"🎰 ABRIR RULETA • FICHA {get_ficha_price_text(currency)}",
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
        "Abrí la ruleta visual premium desde el botón y girala en modo casino."
    )

    await update.message.reply_text(text, reply_markup=keyboard)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "/start - abrir menú\n"
        "/premios - ver premios\n"
        "/myid - ver tu ID\n"
        "/stats - estadísticas (solo admin)"
    )


async def premios_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    user = update.effective_user
    currency = get_currency_from_language(user.language_code)

    await update.message.reply_text(
        f"🎁 Premios ({currency}):\n\n{format_prize_list(currency)}\n\n"
        f"🎟 Valor de la ficha: {get_ficha_price_text(currency)}"
    )


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    await update.message.reply_text(f"Tu ID de Telegram es: {update.effective_user.id}")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("No autorizado.")
        return

    logs = load_logs()
    total = len(logs)

    if total == 0:
        await update.message.reply_text("Todavía no hay giros registrados.")
        return

    counts: dict[str, int] = {}
    for item in logs:
        prize = str(item.get("prize", "Sin premio"))
        counts[prize] = counts.get(prize, 0) + 1

    lines = [f"📊 Giros totales: {total}", ""]
    for prize, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"{prize}: {count}")

    await update.message.reply_text("\n".join(lines))


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()

    if query.data == "view_prizes":
        user = query.from_user
        currency = get_currency_from_language(getattr(user, "language_code", None))

        await query.message.reply_text(
            f"🎁 Premios ({currency}):\n\n{format_prize_list(currency)}\n\n"
            f"🎟 Valor de la ficha: {get_ficha_price_text(currency)}"
        )


def build_bot_application():
    if not TOKEN:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN en variables de entorno.")

    bot_app = ApplicationBuilder().token(TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(CommandHandler("premios", premios_command))
    bot_app.add_handler(CommandHandler("myid", myid_command))
    bot_app.add_handler(CommandHandler("stats", stats_command))
    bot_app.add_handler(CallbackQueryHandler(button_handler))

    return bot_app


def run_bot_polling() -> None:
    try:
        bot_app = build_bot_application()
        logger.info("%s iniciado correctamente.", BOT_NAME)
        bot_app.run_polling(drop_pending_updates=True)
    except Exception:
        logger.exception("Error al iniciar el bot de Telegram.")


def start_bot_background_once() -> None:
    global _bot_started

    if not RUN_TELEGRAM_BOT:
        return

    if not TOKEN:
        logger.warning("RUN_TELEGRAM_BOT=true pero falta TELEGRAM_BOT_TOKEN.")
        return

    with _bot_lock:
        if _bot_started:
            return

        _bot_started = True
        thread = threading.Thread(target=run_bot_polling, daemon=True)
        thread.start()
        logger.info("Bot de Telegram lanzado en background.")


# =========================================================
# HTML PREMIUM
# =========================================================

HTML_TEMPLATE = r"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ bot_name }}</title>
  <style>
    *{box-sizing:border-box}
    :root{
      --bg1:#12010c;
      --bg2:#1f0213;
      --bg3:#32071f;
      --gold1:#fff3b5;
      --gold2:#ffd85b;
      --gold3:#d99b0f;
      --gold4:#8e5900;
      --pink1:#ff60ad;
      --pink2:#ff2b83;
      --violet1:#ad4eff;
      --violet2:#6e25e0;
      --soft:rgba(255,255,255,.74);
      --line:rgba(255,255,255,.09);
      --shadow:0 28px 80px rgba(0,0,0,.5);
    }

    html,body{min-height:100%}

    body{
      margin:0;
      color:#fff;
      font-family:Inter,Arial,sans-serif;
      background:
        radial-gradient(circle at 50% -8%, rgba(255,215,92,.16), transparent 28%),
        radial-gradient(circle at 12% 18%, rgba(255,58,140,.13), transparent 24%),
        radial-gradient(circle at 84% 12%, rgba(138,43,226,.12), transparent 26%),
        linear-gradient(180deg, var(--bg3), var(--bg2) 42%, var(--bg1));
      padding:18px;
      overflow-x:hidden;
    }

    .layout{
      width:100%;
      max-width:1360px;
      margin:0 auto;
      display:grid;
      grid-template-columns:1.15fr .85fr;
      gap:26px;
      align-items:start;
    }

    .card{
      position:relative;
      overflow:hidden;
      border-radius:34px;
      border:1px solid var(--line);
      background:linear-gradient(180deg, rgba(255,255,255,.07), rgba(255,255,255,.03));
      box-shadow:var(--shadow);
      backdrop-filter:blur(14px);
    }

    .card-header{
      position:relative;
      z-index:2;
      padding:26px 28px 22px;
      border-bottom:1px solid rgba(255,255,255,.08);
      background:linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.03));
    }

    .title-badge{
      width:max-content;
      margin:0 auto 12px;
      padding:8px 16px;
      border-radius:999px;
      font-size:12px;
      letter-spacing:.24em;
      text-transform:uppercase;
      font-weight:800;
      color:#ffe7a0;
      border:1px solid rgba(255,216,91,.22);
      background:linear-gradient(180deg, rgba(255,216,91,.12), rgba(255,216,91,.04));
    }

    .title{
      margin:0;
      font-size:clamp(32px,4.6vw,58px);
      line-height:1.02;
      font-weight:1000;
      letter-spacing:-.045em;
      text-align:center;
      text-shadow:0 4px 20px rgba(0,0,0,.4);
    }

    .title .accent{
      background:linear-gradient(180deg,#fff8d4,#ffd85b 62%,#d89a0e);
      -webkit-background-clip:text;
      background-clip:text;
      color:transparent;
    }

    .subtitle{
      margin-top:12px;
      text-align:center;
      color:var(--soft);
      font-size:16px;
      line-height:1.45;
    }

    .card-body{
      position:relative;
      z-index:2;
      padding:28px;
    }

    .wheel-wrap{
      position:relative;
      max-width:700px;
      margin:0 auto;
      aspect-ratio:1/1;
    }

    .wheel-aura{
      position:absolute;
      inset:-5%;
      border-radius:50%;
      background:radial-gradient(circle, rgba(255,229,130,.28), rgba(255,202,88,.14), rgba(255,0,122,.08), transparent 72%);
      filter:blur(28px);
      animation:auraPulse 2.5s ease-in-out infinite;
    }

    @keyframes auraPulse{
      0%,100%{transform:scale(1);opacity:.95}
      50%{transform:scale(1.03);opacity:.82}
    }

    .wheel-reflection{
      position:absolute;
      inset:8% 18% auto 18%;
      height:140px;
      border-radius:999px;
      background:linear-gradient(180deg, rgba(255,255,255,.22), rgba(255,255,255,0));
      transform:rotate(-16deg);
      filter:blur(4px);
      z-index:8;
      pointer-events:none;
    }

    .wheel-shell{
      position:absolute;
      inset:0;
      border-radius:50%;
      overflow:hidden;
      background:
        radial-gradient(circle at 50% 50%, rgba(255,255,255,.07), rgba(255,255,255,.02) 58%, transparent 61%),
        linear-gradient(145deg, #53122d, #17030d 58%, #2a0716);
      border:18px solid var(--gold2);
      box-shadow:
        0 0 0 4px rgba(255,255,255,.08) inset,
        0 0 0 10px rgba(87,28,0,.3) inset,
        0 0 28px rgba(255,216,91,.34),
        0 28px 62px rgba(0,0,0,.42);
      z-index:3;
    }

    .wheel-inner-ring{
      position:absolute;
      inset:16px;
      border-radius:50%;
      border:3px solid rgba(255,255,255,.1);
      z-index:4;
      pointer-events:none;
    }

    .wheel{
      width:100%;
      height:100%;
      border-radius:50%;
      transform:rotate(0deg);
      transition:transform 5.6s cubic-bezier(.08,.86,.2,1);
      filter:drop-shadow(0 10px 28px rgba(0,0,0,.32));
    }

    .wheel-center{
      position:absolute;
      left:50%;
      top:50%;
      transform:translate(-50%,-50%);
      width:92px;
      height:92px;
      border-radius:50%;
      z-index:10;
      background:radial-gradient(circle at 28% 28%, var(--gold1), var(--gold2) 42%, var(--gold3) 75%, var(--gold4));
      border:8px solid rgba(255,255,255,.96);
      box-shadow:0 0 0 8px rgba(72,5,26,.4), 0 10px 30px rgba(0,0,0,.42);
    }

    .wheel-center::after{
      content:"";
      position:absolute;
      left:50%;
      top:50%;
      transform:translate(-50%,-50%);
      width:28px;
      height:28px;
      border-radius:50%;
      background:#87103f;
      box-shadow:inset 0 2px 8px rgba(0,0,0,.35);
    }

    .wheel-center::before{
      content:"J";
      position:absolute;
      left:50%;
      top:50%;
      transform:translate(-50%,-50%);
      font-size:24px;
      font-weight:1000;
      color:rgba(255,255,255,.18);
      z-index:1;
    }

    .pointer-wrap{
      position:absolute;
      left:50%;
      top:-14px;
      transform:translateX(-50%);
      width:90px;
      height:118px;
      z-index:12;
      display:flex;
      justify-content:center;
      align-items:flex-start;
      pointer-events:none;
    }

    .pointer{
      width:0;
      height:0;
      border-left:28px solid transparent;
      border-right:28px solid transparent;
      border-top:58px solid var(--gold2);
      filter:drop-shadow(0 0 10px rgba(255,216,91,.92)) drop-shadow(0 4px 8px rgba(0,0,0,.28));
      transform-origin:50% 0%;
      animation:pointerPulse 1.3s ease-in-out infinite;
    }

    .pointer-cap{
      position:absolute;
      top:0;
      width:22px;
      height:22px;
      border-radius:50%;
      background:radial-gradient(circle at 30% 30%, var(--gold1), var(--gold2), var(--gold3));
      box-shadow:0 0 10px rgba(255,216,91,.45);
    }

    @keyframes pointerPulse{
      0%,100%{transform:scaleY(1)}
      50%{transform:scaleY(1.08)}
    }

    .lights span{
      position:absolute;
      left:50%;
      top:50%;
      width:12px;
      height:12px;
      margin:-6px 0 0 -6px;
      border-radius:999px;
      background:var(--gold2);
      box-shadow:0 0 9px rgba(255,221,120,.95), 0 0 18px rgba(255,221,120,.6);
      z-index:9;
      animation:blink 1.15s ease-in-out infinite;
    }

    @keyframes blink{
      0%,100%{opacity:1;transform:scale(1)}
      50%{opacity:.38;transform:scale(.8)}
    }

    .controls{
      margin-top:30px;
      display:flex;
      flex-direction:column;
      align-items:center;
      gap:16px;
    }

    .btn{
      border:0;
      cursor:pointer;
      padding:18px 38px;
      border-radius:22px;
      font-size:20px;
      font-weight:1000;
      letter-spacing:.02em;
      color:#2a1700;
      background:linear-gradient(180deg, #fff0ae, #ffd85b 45%, #d89a0e);
      box-shadow:0 12px 24px rgba(0,0,0,.24), 0 0 0 2px rgba(255,255,255,.15) inset;
      transition:transform .18s ease, filter .18s ease, opacity .18s ease;
    }

    .btn:hover{transform:translateY(-2px) scale(1.01);filter:brightness(1.03)}
    .btn:disabled{opacity:.7;cursor:not-allowed;transform:none}

    .info-label{
      color:rgba(255,255,255,.58);
      text-transform:uppercase;
      letter-spacing:.22em;
      font-size:12px;
      font-weight:800;
    }

    .ticket{
      font-size:36px;
      font-weight:1000;
      letter-spacing:-.03em;
      text-shadow:0 4px 14px rgba(0,0,0,.28);
    }

    .footer-note{
      text-align:center;
      color:rgba(255,255,255,.46);
      font-size:12px;
      margin-top:2px;
    }

    .panel{display:grid;gap:18px}

    .small-title{
      font-size:40px;
      line-height:1;
      font-weight:1000;
      letter-spacing:-.04em;
    }

    .pill-row{
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:12px;
    }

    .pill{
      border:1px solid rgba(255,255,255,.12);
      background:linear-gradient(180deg, rgba(255,255,255,.065), rgba(255,255,255,.03));
      color:#fff;
      padding:15px 18px;
      border-radius:20px;
      font-weight:900;
      text-align:center;
      cursor:pointer;
      transition:all .18s ease;
    }

    .pill:hover{
      transform:translateY(-1px);
      border-color:rgba(255,255,255,.22);
      background:linear-gradient(180deg, rgba(255,255,255,.085), rgba(255,255,255,.045));
    }

    .winner{
      min-height:156px;
      padding:22px;
      border-radius:24px;
      border:1px solid rgba(255,255,255,.12);
      background:radial-gradient(circle at top left, rgba(255,219,110,.10), transparent 30%), linear-gradient(135deg, rgba(255,46,132,.18), rgba(91,34,219,.18));
    }

    .winner-main{
      font-size:clamp(30px,4vw,42px);
      font-weight:1000;
      line-height:1.03;
      margin-top:10px;
    }

    .winner-sub{
      margin-top:8px;
      color:rgba(255,255,255,.84);
      font-size:18px;
      font-weight:700;
    }

    .prize-list{
      display:grid;
      gap:10px;
      max-height:540px;
      overflow:auto;
      padding-right:4px;
    }

    .prize-item{
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:14px;
      padding:14px 16px;
      border-radius:16px;
      background:linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.03));
      border:1px solid rgba(255,255,255,.075);
    }

    .prize-item span{
      font-size:15px;
      font-weight:700;
      color:#fff;
    }

    .prize-item strong{
      font-size:15px;
      white-space:nowrap;
    }

    @media (max-width:1040px){
      .layout{grid-template-columns:1fr}
      .small-title{font-size:30px}
    }

    @media (max-width:640px){
      body{padding:10px}
      .card{border-radius:24px}
      .card-header{padding:20px 18px}
      .card-body{padding:18px}
      .wheel-shell{border-width:14px}
      .wheel-center{width:78px;height:78px}
      .pointer-wrap{top:-8px}
      .pointer{border-left-width:20px;border-right-width:20px;border-top-width:44px}
      .btn{width:100%;font-size:18px;padding:16px 20px}
      .ticket{font-size:28px}
      .pill-row{grid-template-columns:1fr}
    }
  </style>
</head>
<body>
  <div class="layout">
    <div class="card">
      <div class="card-header">
        <div class="title-badge">CASINO PREMIUM</div>
        <h1 class="title"><span class="accent">Ruleta de Premios</span> Jenni</h1>
        <div class="subtitle">Diseño premium, realista y elegante estilo casino</div>
      </div>

      <div class="card-body">
        <div class="wheel-wrap">
          <div class="wheel-aura"></div>
          <div class="wheel-reflection"></div>

          <div class="pointer-wrap">
            <div class="pointer-cap"></div>
            <div class="pointer" id="pointer"></div>
          </div>

          <div class="wheel-shell">
            <div class="wheel-inner-ring"></div>
            <svg id="wheelSvg" class="wheel" viewBox="0 0 100 100"></svg>
          </div>

          <div class="wheel-center"></div>
          <div class="lights" id="lights"></div>
        </div>

        <div class="controls">
          <button id="spinBtn" class="btn">🎰 GIRAR RULETA</button>
          <div class="info-label">Valor de la ficha</div>
          <div class="ticket" id="ticketPrice"></div>
          <div class="footer-note">{{ bot_name }} • premium • casino style</div>
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
  for (let i = 0; i < 30; i++) {
    const dot = document.createElement("span");
    const angle = (i / 30) * 360;
    dot.style.transform = `translate(-50%, -50%) rotate(${angle}deg) translateY(-322px)`;
    dot.style.animationDelay = `${i * 0.04}s`;
    wrap.appendChild(dot);
  }
}

function renderWheel() {
  const svg = document.getElementById("wheelSvg");
  const angle = 360 / prizes.length;
  const colors = [
    ["#ff5aa7", "#cc1f76"],
    ["#a74dff", "#6d27e0"],
    ["#ff5b75", "#e01e50"],
    ["#d24dff", "#9227d6"],
    ["#ff3f8d", "#d61d6c"],
    ["#8f49ff", "#6224dd"],
    ["#ff6272", "#ea2341"],
    ["#d54fff", "#8b28e2"]
  ];

  let defs = "";
  let html = "";

  prizes.forEach((prize, i) => {
    const startAngle = i * angle;
    const endAngle = (i + 1) * angle;
    const midAngle = startAngle + angle / 2;
    const path = describeWedge(50, 50, 48, startAngle, endAngle);
    const label = prize.name.length > 18 ? prize.name.slice(0, 18) + "…" : prize.name;
    const gradId = `grad${i}`;

    defs += `
      <linearGradient id="${gradId}" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="${colors[i % colors.length][0]}"/>
        <stop offset="100%" stop-color="${colors[i % colors.length][1]}"/>
      </linearGradient>
    `;

    html += `
      <g>
        <path d="${path}" fill="url(#${gradId})" stroke="rgba(255,255,255,0.26)" stroke-width="0.7"></path>
        <g transform="rotate(${midAngle} 50 50)">
          <text x="50" y="15.3" text-anchor="middle" fill="white" font-size="4" font-weight="1000">${label}</text>
        </g>
      </g>
    `;
  });

  svg.innerHTML = `<defs>${defs}</defs>${html}`;
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
      { transform: "scaleY(1.14) translateY(3px)" },
      { transform: "scaleY(0.94)" },
      { transform: "scaleY(1)" }
    ],
    {
      duration: 240,
      iterations: 14,
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

    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Error al girar");
    }

    const index = prizes.findIndex((p) => p.name === data.prize.name);
    const segmentAngle = 360 / prizes.length;
    const targetSegmentCenter = index * segmentAngle + segmentAngle / 2;

    currentRotation += (8 * 360) + (360 - targetSegmentCenter);

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
    }, 5500);
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
"""

# =========================================================
# RUTAS
# =========================================================


@app.get("/")
def home():
    start_bot_background_once()
    return wheel_page()


@app.get("/health")
def health():
    return jsonify(
        {
            "ok": True,
            "service": BOT_NAME,
            "bot_running": RUN_TELEGRAM_BOT,
        }
    )


@app.get("/wheel")
def wheel_page():
    start_bot_background_once()

    user_id = request.args.get("user_id", "")
    username = request.args.get("username", "")
    full_name = request.args.get("full_name", "")
    currency = normalize_currency(request.args.get("currency", DEFAULT_CURRENCY))

    return render_template_string(
        HTML_TEMPLATE,
        bot_name=BOT_NAME,
        prizes=json.dumps(REAL_PRIZES, ensure_ascii=False),
        visible_only_prize=json.dumps(VISIBLE_ONLY_PRIZE, ensure_ascii=False),
        currency=currency,
        user_id=user_id,
        username=username,
        full_name=full_name,
        uyu_to_ars=UYU_TO_ARS,
    )


@app.post("/api/spin")
def api_spin():
    start_bot_background_once()

    data = request.get_json(silent=True) or {}

    user_id = data.get("user_id")
    username = data.get("username", "")
    full_name = data.get("full_name", "")
    currency = normalize_currency(data.get("currency", DEFAULT_CURRENCY))

    prize = pick_weighted_prize()

    log_spin(
        user_id=user_id,
        username=username,
        full_name=full_name,
        prize_name=prize["name"],
        currency=currency,
    )

    return jsonify(
        {
            "ok": True,
            "prize": {
                "name": prize["name"],
                "label": convert_price_from_uyu(int(prize["uyu_price"]), currency),
            },
            "ticket": get_ficha_price_text(currency),
        }
    )


# =========================================================
# MAIN
# =========================================================

def main() -> None:
    ensure_log_file()

    if RUN_TELEGRAM_BOT:
        start_bot_background_once()

    logger.info("%s web iniciada en http://127.0.0.1:%s", BOT_NAME, WEB_PORT)
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False)


if __name__ == "__main__":
    main()