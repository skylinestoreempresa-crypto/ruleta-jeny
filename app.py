import json
import logging
import os
import random
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from flask import Flask, jsonify, make_response, render_template_string, request
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
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
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
    ensure_log_file()
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

        if query.message:
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
# HTML ULTRA PRO
# =========================================================

HTML_TEMPLATE = r"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>{{ bot_name }}</title>
  <meta name="theme-color" content="#2a0417">
  <style>
    *{box-sizing:border-box}
    html,body{min-height:100%}
    :root{
      --bg-1:#11010a;
      --bg-2:#1b0310;
      --bg-3:#2c0618;
      --bg-4:#3e0b26;
      --gold-1:#fff7cb;
      --gold-2:#ffe27b;
      --gold-3:#ffc94a;
      --gold-4:#d99711;
      --gold-5:#8f5700;
      --pink-1:#ff70bd;
      --pink-2:#ff3f9f;
      --pink-3:#d81a6e;
      --violet-1:#bf6bff;
      --violet-2:#8b38ff;
      --violet-3:#5e18dc;
      --white-soft:rgba(255,255,255,.82);
      --white-mid:rgba(255,255,255,.66);
      --white-low:rgba(255,255,255,.45);
      --line:rgba(255,255,255,.09);
      --shadow-xl:0 40px 110px rgba(0,0,0,.58);
      --glass:linear-gradient(180deg, rgba(255,255,255,.10), rgba(255,255,255,.04));
      --btn-text:#2a1500;
    }

    body{
      margin:0;
      color:#fff;
      font-family:Inter,Segoe UI,Arial,sans-serif;
      background:
        radial-gradient(circle at 50% -12%, rgba(255,222,120,.14), transparent 30%),
        radial-gradient(circle at 15% 12%, rgba(255,89,155,.10), transparent 22%),
        radial-gradient(circle at 82% 16%, rgba(156,74,255,.11), transparent 26%),
        radial-gradient(circle at 50% 50%, rgba(255,201,74,.03), transparent 42%),
        linear-gradient(180deg, var(--bg-4), var(--bg-3) 24%, var(--bg-2) 56%, var(--bg-1));
      overflow-x:hidden;
      padding:18px;
      position:relative;
    }

    body::before{
      content:"";
      position:fixed;
      inset:0;
      pointer-events:none;
      background:
        linear-gradient(135deg, rgba(255,255,255,.04), transparent 24%, transparent 76%, rgba(255,255,255,.02)),
        radial-gradient(circle at 50% 50%, rgba(255,255,255,.03), transparent 55%);
      mix-blend-mode:screen;
      opacity:.8;
    }

    .stars,.particles{
      position:fixed;
      inset:0;
      pointer-events:none;
      overflow:hidden;
      z-index:0;
    }

    .star,.particle{
      position:absolute;
      border-radius:999px;
      opacity:.75;
    }

    .star{
      width:2px;
      height:2px;
      background:#fff;
      box-shadow:0 0 10px rgba(255,255,255,.85);
      animation:twinkle 4s linear infinite;
    }

    .particle{
      width:6px;
      height:6px;
      background:radial-gradient(circle, rgba(255,230,138,.95), rgba(255,230,138,0));
      filter:blur(.4px);
      animation:floatUp linear infinite;
    }

    @keyframes twinkle{
      0%,100%{opacity:.22;transform:scale(.7)}
      50%{opacity:.95;transform:scale(1.2)}
    }

    @keyframes floatUp{
      0%{transform:translateY(20px) translateX(0);opacity:0}
      15%{opacity:.8}
      50%{transform:translateY(-40vh) translateX(15px)}
      100%{transform:translateY(-100vh) translateX(-10px);opacity:0}
    }

    .layout{
      position:relative;
      z-index:2;
      width:100%;
      max-width:1440px;
      margin:0 auto;
      display:grid;
      grid-template-columns:minmax(0,1.15fr) minmax(360px,.85fr);
      gap:26px;
      align-items:start;
    }

    .card{
      position:relative;
      overflow:hidden;
      border-radius:34px;
      border:1px solid var(--line);
      background:var(--glass);
      box-shadow:var(--shadow-xl);
      backdrop-filter:blur(18px);
      -webkit-backdrop-filter:blur(18px);
      isolation:isolate;
    }

    .card::before{
      content:"";
      position:absolute;
      inset:0;
      pointer-events:none;
      background:
        radial-gradient(circle at 18% 0%, rgba(255,255,255,.10), transparent 22%),
        radial-gradient(circle at 100% 0%, rgba(255,231,164,.08), transparent 28%);
      opacity:.75;
    }

    .card-header{
      position:relative;
      z-index:2;
      padding:28px 28px 22px;
      border-bottom:1px solid rgba(255,255,255,.07);
      background:linear-gradient(180deg, rgba(255,255,255,.08), rgba(255,255,255,.03));
    }

    .top-meta{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
      margin-bottom:14px;
      flex-wrap:wrap;
    }

    .title-badge{
      width:max-content;
      padding:8px 16px;
      border-radius:999px;
      font-size:12px;
      letter-spacing:.24em;
      text-transform:uppercase;
      font-weight:900;
      color:#ffe8a4;
      border:1px solid rgba(255,216,91,.24);
      background:linear-gradient(180deg, rgba(255,216,91,.14), rgba(255,216,91,.04));
      box-shadow:0 0 0 1px rgba(255,255,255,.03) inset;
    }

    .live-badge{
      display:inline-flex;
      align-items:center;
      gap:8px;
      padding:8px 14px;
      border-radius:999px;
      font-size:12px;
      font-weight:900;
      letter-spacing:.16em;
      text-transform:uppercase;
      color:#ffd8e7;
      background:linear-gradient(180deg, rgba(255,86,143,.17), rgba(255,86,143,.06));
      border:1px solid rgba(255,86,143,.22);
    }

    .live-dot{
      width:8px;
      height:8px;
      border-radius:50%;
      background:#ff4f8c;
      box-shadow:0 0 0 0 rgba(255,79,140,.7);
      animation:pulseDot 1.6s infinite;
    }

    @keyframes pulseDot{
      0%{box-shadow:0 0 0 0 rgba(255,79,140,.7)}
      70%{box-shadow:0 0 0 10px rgba(255,79,140,0)}
      100%{box-shadow:0 0 0 0 rgba(255,79,140,0)}
    }

    .title{
      margin:0;
      font-size:clamp(34px,4.8vw,62px);
      line-height:1.02;
      font-weight:1000;
      letter-spacing:-.05em;
      text-align:center;
      text-shadow:0 4px 20px rgba(0,0,0,.45);
    }

    .title .accent{
      background:linear-gradient(180deg, #fff8d4, #ffe27b 58%, #d8950e);
      -webkit-background-clip:text;
      background-clip:text;
      color:transparent;
      filter:drop-shadow(0 8px 20px rgba(255,204,84,.18));
    }

    .subtitle{
      margin-top:12px;
      text-align:center;
      color:var(--white-mid);
      font-size:16px;
      line-height:1.5;
      max-width:820px;
      margin-inline:auto;
    }

    .mini-stats{
      margin-top:20px;
      display:grid;
      grid-template-columns:repeat(3,1fr);
      gap:12px;
    }

    .mini-stat{
      position:relative;
      overflow:hidden;
      border-radius:18px;
      padding:14px 14px 12px;
      border:1px solid rgba(255,255,255,.08);
      background:linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.03));
      box-shadow:0 12px 30px rgba(0,0,0,.18);
    }

    .mini-stat-label{
      font-size:11px;
      color:var(--white-low);
      text-transform:uppercase;
      letter-spacing:.18em;
      font-weight:800;
    }

    .mini-stat-value{
      margin-top:6px;
      font-size:20px;
      font-weight:1000;
      letter-spacing:-.03em;
    }

    .card-body{
      position:relative;
      z-index:2;
      padding:28px;
    }

    .wheel-stage{
      position:relative;
      perspective:1400px;
      transform-style:preserve-3d;
      max-width:760px;
      margin:0 auto;
    }

    .wheel-wrap{
      position:relative;
      width:min(100%, 720px);
      margin:0 auto;
      aspect-ratio:1/1;
      transform:rotateX(10deg);
      transform-style:preserve-3d;
    }

    .wheel-floor{
      position:absolute;
      left:10%;
      right:10%;
      bottom:2%;
      height:18%;
      border-radius:50%;
      background:radial-gradient(circle, rgba(0,0,0,.5), rgba(0,0,0,.12), transparent 68%);
      filter:blur(24px);
      transform:translateZ(-80px) scale(1.05);
      z-index:1;
    }

    .wheel-aura{
      position:absolute;
      inset:-7%;
      border-radius:50%;
      background:
        radial-gradient(circle, rgba(255,228,130,.30), rgba(255,202,88,.14), rgba(255,0,122,.08), transparent 72%);
      filter:blur(34px);
      animation:auraPulse 2.8s ease-in-out infinite;
      z-index:1;
    }

    @keyframes auraPulse{
      0%,100%{transform:scale(1);opacity:.98}
      50%{transform:scale(1.045);opacity:.8}
    }

    .halo-ring{
      position:absolute;
      inset:-2%;
      border-radius:50%;
      border:2px solid rgba(255,224,123,.14);
      box-shadow:0 0 26px rgba(255,214,104,.16), inset 0 0 24px rgba(255,214,104,.08);
      animation:ringRotate 14s linear infinite;
      z-index:2;
      pointer-events:none;
    }

    .halo-ring.two{
      inset:3%;
      border-color:rgba(255,92,168,.10);
      box-shadow:0 0 26px rgba(255,92,168,.12), inset 0 0 24px rgba(255,92,168,.06);
      animation-duration:20s;
      animation-direction:reverse;
    }

    @keyframes ringRotate{
      from{transform:rotate(0deg)}
      to{transform:rotate(360deg)}
    }

    .wheel-reflection{
      position:absolute;
      inset:7% 16% auto 16%;
      height:150px;
      border-radius:999px;
      background:linear-gradient(180deg, rgba(255,255,255,.24), rgba(255,255,255,0));
      transform:rotate(-16deg) translateZ(30px);
      filter:blur(5px);
      z-index:9;
      pointer-events:none;
    }

    .wheel-shell{
      position:absolute;
      inset:0;
      border-radius:50%;
      overflow:hidden;
      background:
        radial-gradient(circle at 28% 28%, rgba(255,255,255,.16), transparent 24%),
        radial-gradient(circle at 65% 72%, rgba(0,0,0,.28), transparent 36%),
        linear-gradient(145deg, #651337, #1a020e 58%, #2f0919);
      border:24px solid var(--gold-3);
      box-shadow:
        inset 0 0 0 2px rgba(255,255,255,.18),
        inset 0 0 0 8px rgba(255,255,255,.05),
        inset 0 0 0 16px rgba(86,30,4,.25),
        inset 0 0 34px rgba(0,0,0,.55),
        0 0 0 2px rgba(255,222,120,.12),
        0 0 34px rgba(255,216,91,.34),
        0 18px 40px rgba(0,0,0,.34),
        0 45px 90px rgba(0,0,0,.5);
      transform:translateZ(24px);
      z-index:4;
    }

    .wheel-outer-metal{
      position:absolute;
      inset:-2.2%;
      border-radius:50%;
      background:
        conic-gradient(
          from 0deg,
          rgba(255,240,180,.55),
          rgba(202,133,20,.45),
          rgba(255,239,175,.56),
          rgba(176,105,8,.50),
          rgba(255,239,175,.56)
        );
      filter:blur(1px);
      opacity:.9;
      z-index:3;
      box-shadow:0 0 30px rgba(255,216,91,.14);
    }

    .wheel-inner-ring{
      position:absolute;
      inset:18px;
      border-radius:50%;
      border:3px solid rgba(255,255,255,.12);
      box-shadow:inset 0 0 18px rgba(255,255,255,.04), 0 0 18px rgba(255,255,255,.03);
      z-index:6;
      pointer-events:none;
    }

    .wheel-depth{
      position:absolute;
      inset:7%;
      border-radius:50%;
      background:radial-gradient(circle at 50% 50%, rgba(255,255,255,.03), rgba(0,0,0,.24) 78%, rgba(0,0,0,.42) 100%);
      z-index:5;
      pointer-events:none;
    }

    .wheel{
      width:100%;
      height:100%;
      border-radius:50%;
      transform:rotate(0deg);
      transition:transform 6.4s cubic-bezier(.08,.92,.16,1);
      filter:
        drop-shadow(0 22px 40px rgba(0,0,0,.72))
        drop-shadow(0 0 15px rgba(255,208,89,.18));
      will-change:transform;
    }

    .wheel-center{
      position:absolute;
      left:50%;
      top:50%;
      transform:translate(-50%,-50%) translateZ(55px);
      width:110px;
      height:110px;
      border-radius:50%;
      z-index:14;
      background:
        radial-gradient(circle at 28% 26%, var(--gold-1), var(--gold-2) 36%, var(--gold-4) 78%, var(--gold-5));
      border:8px solid rgba(255,255,255,.96);
      box-shadow:
        0 0 0 10px rgba(72,5,26,.42),
        0 16px 36px rgba(0,0,0,.42),
        0 0 24px rgba(255,216,91,.26);
    }

    .wheel-center::before{
      content:"J";
      position:absolute;
      left:50%;
      top:50%;
      transform:translate(-50%,-52%);
      font-size:30px;
      font-weight:1000;
      color:rgba(99,20,43,.84);
      text-shadow:0 1px 0 rgba(255,255,255,.35);
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
      background:#7f0f37;
      box-shadow:inset 0 2px 8px rgba(0,0,0,.35);
      opacity:.18;
    }

    .pointer-wrap{
      position:absolute;
      left:50%;
      top:-18px;
      transform:translateX(-50%) translateZ(80px);
      width:100px;
      height:132px;
      z-index:18;
      display:flex;
      justify-content:center;
      align-items:flex-start;
      pointer-events:none;
    }

    .pointer-cap{
      position:absolute;
      top:4px;
      width:26px;
      height:26px;
      border-radius:50%;
      background:radial-gradient(circle at 30% 30%, var(--gold-1), var(--gold-2), var(--gold-4));
      box-shadow:
        0 0 14px rgba(255,216,91,.52),
        0 4px 10px rgba(0,0,0,.35);
      z-index:2;
    }

    .pointer{
      width:0;
      height:0;
      border-left:30px solid transparent;
      border-right:30px solid transparent;
      border-top:68px solid var(--gold-3);
      filter:
        drop-shadow(0 0 16px rgba(255,214,109,.95))
        drop-shadow(0 8px 14px rgba(0,0,0,.55));
      transform-origin:50% 0%;
      animation:pointerPulse 1.2s ease-in-out infinite;
    }

    .pointer::after{
      content:"";
      position:absolute;
      left:-16px;
      top:-67px;
      width:32px;
      height:20px;
      background:linear-gradient(180deg, rgba(255,255,255,.40), rgba(255,255,255,0));
      filter:blur(2px);
    }

    @keyframes pointerPulse{
      0%,100%{transform:scaleY(1)}
      50%{transform:scaleY(1.09)}
    }

    .lights{
      position:absolute;
      inset:0;
      z-index:12;
      pointer-events:none;
    }

    .lights span{
      position:absolute;
      left:50%;
      top:50%;
      width:12px;
      height:12px;
      margin:-6px 0 0 -6px;
      border-radius:999px;
      background:radial-gradient(circle, #fff8cf, #ffd85b 58%, #c6800a);
      box-shadow:
        0 0 12px rgba(255,224,123,.98),
        0 0 24px rgba(255,224,123,.58),
        0 0 34px rgba(255,224,123,.28);
      animation:blink 1.1s ease-in-out infinite;
    }

    @keyframes blink{
      0%,100%{opacity:1;transform:scale(1)}
      50%{opacity:.34;transform:scale(.76)}
    }

    .wheel-gloss{
      position:absolute;
      inset:8% 8%;
      border-radius:50%;
      background:
        linear-gradient(145deg, rgba(255,255,255,.14), rgba(255,255,255,0) 28%),
        radial-gradient(circle at 50% 0%, rgba(255,255,255,.10), transparent 46%);
      mix-blend-mode:screen;
      pointer-events:none;
      z-index:10;
    }

    .controls{
      margin-top:32px;
      display:flex;
      flex-direction:column;
      align-items:center;
      gap:16px;
    }

    .btn{
      position:relative;
      overflow:hidden;
      border:0;
      cursor:pointer;
      padding:20px 42px;
      border-radius:22px;
      font-size:20px;
      font-weight:1000;
      letter-spacing:.02em;
      color:var(--btn-text);
      background:linear-gradient(180deg, #fff3b6, #ffd85b 42%, #d89a0e);
      box-shadow:
        0 16px 28px rgba(0,0,0,.28),
        0 0 0 2px rgba(255,255,255,.16) inset,
        0 0 0 1px rgba(140,87,0,.36);
      transition:transform .18s ease, filter .18s ease, opacity .18s ease, box-shadow .18s ease;
      min-width:280px;
    }

    .btn::before{
      content:"";
      position:absolute;
      inset:-120% auto -120% -45%;
      width:42%;
      background:linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,.35), rgba(255,255,255,0));
      transform:rotate(18deg);
      animation:shine 3.2s linear infinite;
    }

    @keyframes shine{
      0%{left:-45%}
      100%{left:120%}
    }

    .btn:hover{
      transform:translateY(-2px) scale(1.012);
      filter:brightness(1.04);
      box-shadow:
        0 18px 30px rgba(0,0,0,.30),
        0 0 0 2px rgba(255,255,255,.18) inset,
        0 0 24px rgba(255,216,91,.18);
    }

    .btn:disabled{
      opacity:.8;
      cursor:not-allowed;
      transform:none;
      filter:saturate(.85);
    }

    .btn-subline{
      display:flex;
      align-items:center;
      gap:10px;
      color:var(--white-mid);
      font-size:13px;
      text-transform:uppercase;
      letter-spacing:.16em;
      font-weight:900;
      text-align:center;
    }

    .info-label{
      color:rgba(255,255,255,.58);
      text-transform:uppercase;
      letter-spacing:.22em;
      font-size:12px;
      font-weight:800;
    }

    .ticket{
      font-size:40px;
      font-weight:1000;
      letter-spacing:-.04em;
      text-shadow:0 4px 16px rgba(0,0,0,.32);
      text-align:center;
    }

    .footer-note{
      text-align:center;
      color:rgba(255,255,255,.46);
      font-size:12px;
      margin-top:2px;
    }

    .panel{display:grid;gap:18px}

    .small-title{
      font-size:42px;
      line-height:1;
      font-weight:1000;
      letter-spacing:-.045em;
      margin:0;
    }

    .panel-top{
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:12px;
      flex-wrap:wrap;
    }

    .chip{
      padding:10px 14px;
      border-radius:999px;
      font-size:12px;
      font-weight:900;
      letter-spacing:.16em;
      text-transform:uppercase;
      color:#ffe7a5;
      border:1px solid rgba(255,216,91,.20);
      background:linear-gradient(180deg, rgba(255,216,91,.11), rgba(255,216,91,.04));
    }

    .pill-row{
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:12px;
    }

    .pill{
      position:relative;
      border:1px solid rgba(255,255,255,.12);
      background:linear-gradient(180deg, rgba(255,255,255,.075), rgba(255,255,255,.03));
      color:#fff;
      padding:15px 18px;
      border-radius:18px;
      font-weight:900;
      text-align:center;
      cursor:pointer;
      transition:all .18s ease;
      box-shadow:0 10px 22px rgba(0,0,0,.14);
    }

    .pill:hover{
      transform:translateY(-1px);
      border-color:rgba(255,255,255,.22);
      background:linear-gradient(180deg, rgba(255,255,255,.09), rgba(255,255,255,.05));
    }

    .pill.active{
      border-color:rgba(255,216,91,.36);
      background:linear-gradient(180deg, rgba(255,216,91,.18), rgba(255,216,91,.06));
      color:#fff2c2;
      box-shadow:0 0 18px rgba(255,216,91,.12), inset 0 0 0 1px rgba(255,255,255,.05);
    }

    .winner{
      min-height:176px;
      padding:24px;
      border-radius:24px;
      border:1px solid rgba(255,255,255,.12);
      background:
        radial-gradient(circle at top left, rgba(255,219,110,.14), transparent 30%),
        radial-gradient(circle at top right, rgba(255,81,145,.12), transparent 20%),
        linear-gradient(135deg, rgba(255,46,132,.17), rgba(91,34,219,.17));
      box-shadow:0 18px 38px rgba(0,0,0,.22);
      position:relative;
      overflow:hidden;
    }

    .winner::after{
      content:"";
      position:absolute;
      inset:0;
      background:linear-gradient(115deg, transparent 20%, rgba(255,255,255,.06) 42%, transparent 60%);
      transform:translateX(-120%);
      animation:winnerGlow 5s linear infinite;
    }

    @keyframes winnerGlow{
      0%{transform:translateX(-120%)}
      100%{transform:translateX(120%)}
    }

    .winner-main{
      font-size:clamp(30px,4vw,44px);
      font-weight:1000;
      line-height:1.03;
      margin-top:10px;
      letter-spacing:-.04em;
      word-break:break-word;
    }

    .winner-sub{
      margin-top:8px;
      color:rgba(255,255,255,.86);
      font-size:18px;
      font-weight:700;
    }

    .winner-badge{
      display:inline-flex;
      align-items:center;
      gap:8px;
      margin-top:14px;
      padding:8px 12px;
      border-radius:999px;
      background:rgba(255,255,255,.08);
      border:1px solid rgba(255,255,255,.10);
      color:#ffe9ad;
      font-size:11px;
      font-weight:900;
      letter-spacing:.14em;
      text-transform:uppercase;
    }

    .section-head{
      display:flex;
      justify-content:space-between;
      gap:12px;
      align-items:center;
      margin-bottom:10px;
      flex-wrap:wrap;
    }

    .prize-list{
      display:grid;
      gap:10px;
      max-height:560px;
      overflow:auto;
      padding-right:4px;
      scrollbar-width:thin;
      scrollbar-color:rgba(255,216,91,.4) rgba(255,255,255,.04);
    }

    .prize-list::-webkit-scrollbar{
      width:9px;
    }

    .prize-list::-webkit-scrollbar-track{
      background:rgba(255,255,255,.04);
      border-radius:999px;
    }

    .prize-list::-webkit-scrollbar-thumb{
      background:linear-gradient(180deg, rgba(255,216,91,.7), rgba(216,154,14,.7));
      border-radius:999px;
    }

    .prize-item{
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:14px;
      padding:14px 16px;
      border-radius:16px;
      background:linear-gradient(180deg, rgba(255,255,255,.058), rgba(255,255,255,.03));
      border:1px solid rgba(255,255,255,.08);
      box-shadow:0 10px 22px rgba(0,0,0,.10);
      transition:transform .16s ease, border-color .16s ease, background .16s ease;
    }

    .prize-item:hover{
      transform:translateY(-1px);
      border-color:rgba(255,255,255,.16);
      background:linear-gradient(180deg, rgba(255,255,255,.072), rgba(255,255,255,.04));
    }

    .prize-left{
      display:flex;
      flex-direction:column;
      gap:4px;
      min-width:0;
    }

    .prize-name{
      font-size:15px;
      font-weight:800;
      color:#fff;
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
    }

    .prize-meta{
      font-size:11px;
      letter-spacing:.14em;
      text-transform:uppercase;
      color:var(--white-low);
      font-weight:800;
    }

    .prize-price{
      font-size:15px;
      white-space:nowrap;
      font-weight:1000;
      color:#ffe6a2;
    }

    .status-row{
      display:grid;
      grid-template-columns:repeat(2,1fr);
      gap:12px;
    }

    .status-card{
      padding:14px 16px;
      border-radius:18px;
      border:1px solid rgba(255,255,255,.08);
      background:linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.03));
    }

    .status-label{
      font-size:11px;
      font-weight:900;
      text-transform:uppercase;
      letter-spacing:.16em;
      color:var(--white-low);
    }

    .status-value{
      margin-top:6px;
      font-size:18px;
      font-weight:1000;
      letter-spacing:-.03em;
    }

    .spin-glow{
      position:absolute;
      inset:0;
      pointer-events:none;
      border-radius:inherit;
      opacity:0;
      box-shadow:0 0 50px rgba(255,216,91,.14) inset, 0 0 90px rgba(255,63,159,.10) inset;
      transition:opacity .25s ease;
    }

    .card.spinning .spin-glow{
      opacity:1;
    }

    .toast{
      position:fixed;
      left:50%;
      bottom:20px;
      transform:translateX(-50%) translateY(20px);
      min-width:220px;
      max-width:calc(100vw - 20px);
      padding:14px 16px;
      border-radius:16px;
      background:linear-gradient(180deg, rgba(29,10,18,.96), rgba(15,5,10,.96));
      border:1px solid rgba(255,255,255,.12);
      color:#fff;
      box-shadow:0 20px 50px rgba(0,0,0,.34);
      opacity:0;
      pointer-events:none;
      z-index:200;
      transition:all .28s ease;
      text-align:center;
      font-weight:800;
    }

    .toast.show{
      opacity:1;
      transform:translateX(-50%) translateY(0);
    }

    .confetti-wrap{
      position:fixed;
      inset:0;
      pointer-events:none;
      overflow:hidden;
      z-index:150;
    }

    .confetti{
      position:absolute;
      width:10px;
      height:16px;
      opacity:.95;
      animation:confettiFall linear forwards;
      transform-origin:center;
    }

    @keyframes confettiFall{
      0%{transform:translateY(-14vh) rotate(0deg) scale(.9);opacity:0}
      8%{opacity:1}
      100%{transform:translateY(110vh) rotate(960deg) scale(1);opacity:.95}
    }

    .sr-only{
      position:absolute!important;
      width:1px!important;
      height:1px!important;
      padding:0!important;
      margin:-1px!important;
      overflow:hidden!important;
      clip:rect(0,0,0,0)!important;
      white-space:nowrap!important;
      border:0!important;
    }

    @media (max-width:1180px){
      .layout{grid-template-columns:1fr}
    }

    @media (max-width:820px){
      .mini-stats{grid-template-columns:1fr}
      .status-row{grid-template-columns:1fr}
    }

    @media (max-width:640px){
      body{padding:10px}
      .card{border-radius:24px}
      .card-header{padding:20px 18px}
      .card-body{padding:18px}
      .wheel-wrap{width:100%}
      .wheel-shell{border-width:16px}
      .wheel-center{width:84px;height:84px}
      .pointer-wrap{top:-8px;width:80px;height:100px}
      .pointer{border-left-width:22px;border-right-width:22px;border-top-width:50px}
      .btn{width:100%;min-width:0;font-size:18px;padding:16px 18px}
      .ticket{font-size:30px}
      .pill-row{grid-template-columns:1fr}
      .small-title{font-size:34px}
      .prize-name{white-space:normal}
      .prize-item{align-items:flex-start}
      .prize-price{padding-top:2px}
    }

    @media (prefers-reduced-motion: reduce){
      *,*::before,*::after{
        animation:none!important;
        transition:none!important;
        scroll-behavior:auto!important;
      }
    }
  </style>
</head>
<body>
  <div class="stars" id="stars"></div>
  <div class="particles" id="particles"></div>
  <div class="confetti-wrap" id="confettiWrap"></div>
  <div class="toast" id="toast"></div>

  <div class="layout">
    <div class="card" id="wheelCard">
      <div class="spin-glow"></div>

      <div class="card-header">
        <div class="top-meta">
          <div class="title-badge">CASINO PREMIUM</div>
          <div class="live-badge"><span class="live-dot"></span> Modo en vivo</div>
        </div>

        <h1 class="title"><span class="accent">Ruleta de Premios</span> Jenni</h1>
        <div class="subtitle">
          Experiencia premium estilo casino con iluminación 3D, animación avanzada, giro realista y panel visual mejorado.
        </div>

        <div class="mini-stats">
          <div class="mini-stat">
            <div class="mini-stat-label">Valor ficha</div>
            <div class="mini-stat-value" id="miniTicket"></div>
          </div>
          <div class="mini-stat">
            <div class="mini-stat-label">Premios reales</div>
            <div class="mini-stat-value" id="realPrizeCount"></div>
          </div>
          <div class="mini-stat">
            <div class="mini-stat-label">Modo</div>
            <div class="mini-stat-value">Casino 3D</div>
          </div>
        </div>
      </div>

      <div class="card-body">
        <div class="wheel-stage">
          <div class="wheel-wrap">
            <div class="wheel-floor"></div>
            <div class="wheel-aura"></div>
            <div class="halo-ring"></div>
            <div class="halo-ring two"></div>
            <div class="wheel-outer-metal"></div>
            <div class="wheel-reflection"></div>

            <div class="pointer-wrap">
              <div class="pointer-cap"></div>
              <div class="pointer" id="pointer"></div>
            </div>

            <div class="wheel-shell">
              <div class="wheel-inner-ring"></div>
              <div class="wheel-depth"></div>
              <svg id="wheelSvg" class="wheel" viewBox="0 0 100 100" aria-hidden="true"></svg>
              <div class="wheel-gloss"></div>
            </div>

            <div class="wheel-center"></div>
            <div class="lights" id="lights"></div>
          </div>
        </div>

        <div class="controls">
          <button id="spinBtn" class="btn" type="button" aria-label="Girar ruleta">🎰 GIRAR RULETA</button>
          <div class="btn-subline">Suerte • brillo • casino premium</div>
          <div class="info-label">Valor de la ficha</div>
          <div class="ticket" id="ticketPrice"></div>
          <div class="footer-note">{{ bot_name }} • premium • casino style • 3D</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <div class="panel-top">
          <h2 class="small-title">Panel</h2>
          <div class="chip" id="currencyChip">Moneda {{ currency }}</div>
        </div>
      </div>

      <div class="card-body panel">
        <div class="pill-row">
          <button class="pill" id="btnUyu" type="button">🇺🇾 Mostrar UYU</button>
          <button class="pill" id="btnArs" type="button">🇦🇷 Mostrar ARS</button>
        </div>

        <div class="status-row">
          <div class="status-card">
            <div class="status-label">Estado</div>
            <div class="status-value" id="statusValue">Lista para girar</div>
          </div>
          <div class="status-card">
            <div class="status-label">Última animación</div>
            <div class="status-value" id="spinState">Esperando</div>
          </div>
        </div>

        <div class="winner" id="winnerBox">
          <div class="info-label">Resultado</div>
          <div class="winner-main">Gira la ruleta</div>
          <div class="winner-sub">Tu premio aparecerá aquí</div>
          <div class="winner-badge">Sin resultado todavía</div>
        </div>

        <div>
          <div class="section-head">
            <div class="info-label">Premios visibles</div>
            <div class="chip" id="totalItemsChip"></div>
          </div>
          <div class="prize-list" id="prizeList"></div>
        </div>
      </div>
    </div>
  </div>

  <div class="sr-only" aria-live="polite" id="liveRegion"></div>

<script>
const prizes = {{ prizes|safe }};
const visibleOnlyPrize = {{ visible_only_prize|safe }};
let currency = {{ currency|tojson }};
let currentRotation = 0;
let spinning = false;
let audioCtx = null;
let tickInterval = null;
let spinTimeout = null;

const wheelCard = document.getElementById("wheelCard");
const wheelSvg = document.getElementById("wheelSvg");
const spinBtn = document.getElementById("spinBtn");
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

function safeShortLabel(text, maxLen = 18) {
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
    dot.style.transform =
      `translate(-50%, -50%) rotate(${angle}deg) translateY(calc(-1 * ${radius}%))`;
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
    ["#d757ff", "#8d2be2"]
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
          <text
            x="50"
            y="15.4"
            text-anchor="middle"
            fill="white"
            font-size="3.9"
            font-weight="1000"
            filter="url(#textShadow)"
          >${text}</text>
        </g>
      </g>
    `;
  });

  html += `<circle cx="50" cy="50" r="13" fill="url(#centerGlow)" />`;
  wheelSvg.innerHTML = `<defs>${defs}</defs>${html}`;
}

function renderPrizeList() {
  prizeList.innerHTML = "";
  const allItems = [...prizes, visibleOnlyPrize];

  allItems.forEach((p, index) => {
    const row = document.createElement("div");
    row.className = "prize-item";
    row.innerHTML = `
      <div class="prize-left">
        <div class="prize-name">${p.name}</div>
        <div class="prize-meta">${index < prizes.length ? "Premio disponible" : "Solo visual"}</div>
      </div>
      <div class="prize-price">${convertPrice(p.uyu_price, currency)}</div>
    `;
    prizeList.appendChild(row);
  });

  totalItemsChip.textContent = `${allItems.length} premios`;
}

function renderTicket() {
  const text = ticketText();
  ticketPrice.textContent = text;
  miniTicket.textContent = text;
  currencyChip.textContent = `Moneda ${currency}`;
}

function renderMiniStats() {
  document.getElementById("realPrizeCount").textContent = `${prizes.length} reales`;
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
  el._hideTimer = setTimeout(() => {
    el.classList.remove("show");
  }, 2200);
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
    {
      duration: 220,
      iterations: 16,
      easing: "ease-in-out"
    }
  );
}

function startTicking(durationMs = 5200) {
  stopTicking();
  tickInterval = setInterval(() => {
    playTick();
  }, 95);

  setTimeout(() => {
    stopTicking();
  }, Math.max(300, durationMs - 700));
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

function fireConfetti(count = 120) {
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

  setTimeout(() => {
    wrap.innerHTML = "";
  }, 5200);
}

function buildWinnerHTML(prizeName, prizeLabel) {
  return `
    <div class="info-label">Premio ganado</div>
    <div class="winner-main">${prizeName}</div>
    <div class="winner-sub">${prizeLabel}</div>
    <div class="winner-badge">Resultado confirmado</div>
  `;
}

async function spinWheel() {
  if (spinning) return;

  spinning = true;
  wheelCard.classList.add("spinning");
  spinBtn.disabled = true;
  spinBtn.textContent = "⏳ GIRANDO...";
  setStatus("Girando", "Animación activa");
  announce("La ruleta está girando");

  try {
    initAudio();
    if (audioCtx && audioCtx.state === "suspended") {
      await audioCtx.resume();
    }

    playSpinStart();

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
    if (index === -1) {
      throw new Error("Premio no encontrado en la ruleta.");
    }

    const segmentAngle = 360 / prizes.length;
    const targetSegmentCenter = index * segmentAngle + segmentAngle / 2;

    const fullSpins = 8 + Math.floor(Math.random() * 4);
    const fineOffset = (Math.random() * 8) - 4;

    currentRotation += (fullSpins * 360) + (360 - targetSegmentCenter) + fineOffset;
    wheelSvg.style.transform = `rotate(${currentRotation}deg)`;

    animatePointerBounce();
    startTicking(5600);

    clearTimeout(spinTimeout);
    spinTimeout = setTimeout(() => {
      winnerBox.innerHTML = buildWinnerHTML(data.prize.name, data.prize.label);
      playWinSound();
      fireConfetti(140);
      toast(`¡Ganaste: ${data.prize.name}!`);
      setStatus("Premio entregado", "Animación completada");
      announce(`Premio ganado: ${data.prize.name} por ${data.prize.label}`);

      spinBtn.disabled = false;
      spinBtn.textContent = "🎰 GIRAR RULETA";
      wheelCard.classList.remove("spinning");
      spinning = false;
    }, 6000);
  } catch (e) {
    console.error(e);
    stopTicking();
    toast("Error al girar la ruleta");
    setStatus("Error", "Reintentar");
    announce("Hubo un error al girar la ruleta");
    spinBtn.disabled = false;
    spinBtn.textContent = "🎰 GIRAR RULETA";
    wheelCard.classList.remove("spinning");
    spinning = false;
  }
}

function boot() {
  renderStars();
  renderParticles();
  renderLights();
  renderWheel();
  renderPrizeList();
  renderTicket();
  renderMiniStats();
  updateCurrencyButtons();

  setStatus("Lista para girar", "Esperando");
  winnerBox.innerHTML = `
    <div class="info-label">Resultado</div>
    <div class="winner-main">Gira la ruleta</div>
    <div class="winner-sub">Tu premio aparecerá aquí</div>
    <div class="winner-badge">Sin resultado todavía</div>
  `;

  spinBtn.addEventListener("click", spinWheel);
  btnUyu.addEventListener("click", () => setCurrency("UYU"));
  btnArs.addEventListener("click", () => setCurrency("ARS"));

  window.addEventListener("resize", () => {
    renderLights();
    renderStars();
  });
}

boot();
</script>
</body>
</html>
"""

# =========================================================
# RUTAS
# =========================================================


@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/")
def home():
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
    user_id = request.args.get("user_id", "")
    username = request.args.get("username", "")
    full_name = request.args.get("full_name", "")
    currency = normalize_currency(request.args.get("currency", DEFAULT_CURRENCY))

    response = make_response(
        render_template_string(
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
    )
    return response


@app.post("/api/spin")
def api_spin():
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