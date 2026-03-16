import asyncio
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, make_response, render_template, request
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from utils import (
    approve_purchase_by_id,
    build_webapp_url,
    convert_price_from_uyu,
    create_pending_purchase,
    ensure_json_file,
    ensure_user_profile,
    format_prize_list,
    get_country_link,
    get_currency_from_language,
    get_user_profile,
    is_admin,
    load_logs,
    load_purchases,
    load_users,
    log_spin,
    normalize_currency,
    now_iso,
    pick_weighted_prize,
    sanitize_name,
    save_users,
    ticket_price_text,
    update_user_profile,
)

# =========================================================
# CONFIG
# =========================================================

def env_bool(name: str, default: bool = False) -> bool:
    value = str(os.environ.get(name, str(default))).strip().lower()
    return value in {"1", "true", "yes", "y", "on"}

def env_int(name: str, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        value = default

    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value

def safe_int(value: Any, default: int = 0, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError):
        num = default

    if min_value is not None:
        num = max(min_value, num)
    if max_value is not None:
        num = min(max_value, num)
    return num

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
BOT_NAME = os.environ.get("BOT_NAME", "Ruleta Jeny").strip()
APP_SECRET_KEY = os.environ.get("APP_SECRET_KEY", "ruleta_default_secret_key").strip()

DEFAULT_CURRENCY = os.environ.get("DEFAULT_CURRENCY", "UYU").strip().upper()
WEBAPP_BASE_URL = os.environ.get(
    "WEBAPP_BASE_URL",
    "https://ruleta-jeny-2.onrender.com",
).rstrip("/")

WEB_PORT = env_int("PORT", 8080, min_value=1, max_value=65535)
UYU_TO_ARS = env_int("UYU_TO_ARS", 25, min_value=1)

LOG_LEVEL_NAME = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.INFO)

LOG_FILE = Path(os.environ.get("LOG_FILE", "spins_log.json"))
USERS_FILE = Path(os.environ.get("USERS_FILE", "users_data.json"))
PURCHASES_FILE = Path(os.environ.get("PURCHASES_FILE", "pending_purchases.json"))

MP_LINK_AR = os.environ.get("MP_LINK_AR", "https://mpago.la/1vUBfHc").strip()
MP_LINK_UY = os.environ.get("MP_LINK_UY", "https://mpago.la/1Zgex99").strip()

RUN_TELEGRAM_BOT = env_bool("RUN_TELEGRAM_BOT", False)
START_TELEGRAM_WITH_WEB = env_bool("START_TELEGRAM_WITH_WEB", True)

ADMIN_IDS = {
    int(x.strip())
    for x in os.environ.get("ADMIN_IDS", "8445311801").split(",")
    if x.strip().isdigit()
}

TICKET_PRICE_UYU = env_int("TICKET_PRICE_UYU", 250, min_value=1)
DEMO_SPINS = env_int("DEMO_SPINS", 1, min_value=0, max_value=10)
MAX_PURCHASE_QTY = env_int("MAX_PURCHASE_QTY", 100, min_value=1, max_value=1000)

REAL_PRIZES = [
    {"name": "💋 Pose favorita", "chance": 35.9, "uyu_price": 200, "weight": 359},
    {"name": "📷 Pack 8 fotos", "chance": 24.0, "uyu_price": 350, "weight": 240},
    {"name": "🎥 Video personalizado", "chance": 18.0, "uyu_price": 500, "weight": 180},
    {"name": "🔥 3 videos x 3 min", "chance": 10.0, "uyu_price": 700, "weight": 100},
    {"name": "🎬 Video personalizado 3 min", "chance": 6.0, "uyu_price": 750, "weight": 60},
    {"name": "📸 10 fotos personalizadas", "chance": 4.0, "uyu_price": 1000, "weight": 40},
    {"name": "💬 Sexting 1 hora", "chance": 2.0, "uyu_price": 950, "weight": 20},
    {"name": "💎 Encuentro", "chance": 0.1, "uyu_price": 1500, "weight": 1},
]

VISIBLE_PRIZES = REAL_PRIZES[:]

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(BOT_NAME)

app = Flask(__name__)
app.secret_key = APP_SECRET_KEY
app.config["JSON_AS_ASCII"] = False

_bot_lock = threading.Lock()
_bot_started = False


# =========================================================
# HELPERS
# =========================================================

def is_valid_payment_link(value: str) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("https://") and "mpago.la/" in text

def validate_startup_config() -> None:
    if not BOT_NAME:
        logger.warning("BOT_NAME está vacío. Se usará el nombre por defecto.")
    if not TOKEN and RUN_TELEGRAM_BOT:
        logger.warning("RUN_TELEGRAM_BOT=true pero falta TELEGRAM_BOT_TOKEN.")
    if not ADMIN_IDS:
        logger.warning("No hay ADMIN_IDS configurados.")
    if not is_valid_payment_link(MP_LINK_AR):
        logger.warning("MP_LINK_AR no parece válido: %s", MP_LINK_AR)
    if not is_valid_payment_link(MP_LINK_UY):
        logger.warning("MP_LINK_UY no parece válido: %s", MP_LINK_UY)

def resolve_display_name(raw_display_name: str, full_name: str, username: str) -> str:
    return sanitize_name(raw_display_name or full_name or username or "Jugador")

def normalize_country(value: str) -> str:
    country = str(value or "UY").strip().upper()
    if country in {"AR", "ARG", "ARGENTINA"}:
        return "AR"
    return "UY"

def resolve_currency(value: str) -> str:
    return normalize_currency(value or DEFAULT_CURRENCY, DEFAULT_CURRENCY)

def ensure_profile(
    user_id: Any,
    username: str,
    full_name: str,
    currency: str,
    display_name: str,
):
    return ensure_user_profile(
        user_id=user_id,
        username=username,
        full_name=full_name,
        currency=currency,
        display_name=display_name,
        users_file=USERS_FILE,
        default_demo_spins=DEMO_SPINS,
        default_currency=DEFAULT_CURRENCY,
    )

def profile_payload(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        **profile,
        "fichas": safe_int(profile.get("fichas", 0), 0, 0),
        "demo_spins_left": safe_int(profile.get("demo_spins_left", 0), 0, 0),
        "wins": safe_int(profile.get("wins", 0), 0, 0),
    }

def base_ui_config(profile: dict[str, Any], currency: str) -> dict[str, Any]:
    return {
        "botName": BOT_NAME,
        "currency": currency,
        "defaultCurrency": DEFAULT_CURRENCY,
        "displayName": profile.get("display_name", "Jugador"),
        "fichas": safe_int(profile.get("fichas", 0), 0, 0),
        "demoSpinsLeft": safe_int(profile.get("demo_spins_left", 0), 0, 0),
        "ticketPriceUyu": TICKET_PRICE_UYU,
        "ticketPriceLabel": ticket_price_text(currency, TICKET_PRICE_UYU, UYU_TO_ARS, DEFAULT_CURRENCY),
        "uyuToArs": UYU_TO_ARS,
        "prizes": VISIBLE_PRIZES,
        "mpLinkAr": MP_LINK_AR,
        "mpLinkUy": MP_LINK_UY,
        "visual": {
            "theme": "premium-3d",
            "highContrastText": True,
            "glowText": True,
            "confettiEnabled": True,
            "showWelcomeModal": True,
            "showThankYouMessage": True,
            "enableWinFlash": True,
            "recommendedTextShadow": "0 2px 10px rgba(0,0,0,.55)",
            "recommendedStroke": "rgba(10,10,10,.45)",
        },
        "limits": {
            "maxPurchaseQty": MAX_PURCHASE_QTY,
            "demoSpins": DEMO_SPINS,
        },
        "texts": {
            "welcomeTitle": f"Bienvenido/a a {BOT_NAME}",
            "welcomeSubtitle": "Ingresá tu nombre, girá y descubrí tu premio.",
            "thanks": f"Gracias por jugar en {BOT_NAME}",
            "ticketLabel": ticket_price_text(currency, TICKET_PRICE_UYU, UYU_TO_ARS, DEFAULT_CURRENCY),
            "freeSpinLabel": f"Demo gratis: {DEMO_SPINS} tirada",
        },
    }

def json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status

def require_user_identity(user_id: Any):
    if user_id is None or str(user_id).strip() == "":
        return False
    return True


# =========================================================
# TELEGRAM
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    user = update.effective_user
    currency = get_currency_from_language(user.language_code, DEFAULT_CURRENCY)

    ensure_user_profile(
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        currency=currency,
        display_name=resolve_display_name(user.first_name, user.full_name, user.username),
        users_file=USERS_FILE,
        default_demo_spins=DEMO_SPINS,
        default_currency=DEFAULT_CURRENCY,
    )

    webapp_url = build_webapp_url(user, WEBAPP_BASE_URL, DEFAULT_CURRENCY)

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=f"🎰 ABRIR RULETA • FICHA {ticket_price_text(currency, TICKET_PRICE_UYU, UYU_TO_ARS, DEFAULT_CURRENCY)}",
                    web_app=WebAppInfo(url=webapp_url),
                )
            ],
            [
                InlineKeyboardButton("🎁 Ver premios", callback_data="view_prizes"),
                InlineKeyboardButton("🎟 Mis fichas", callback_data="view_tokens"),
            ],
        ]
    )

    text = (
        f"🎀 Bienvenido/a a {BOT_NAME}\n\n"
        f"💱 Moneda detectada: {currency}\n"
        f"🎟 Valor de la ficha: {ticket_price_text(currency, TICKET_PRICE_UYU, UYU_TO_ARS, DEFAULT_CURRENCY)}\n"
        f"🆓 Demo gratis: {DEMO_SPINS} tirada\n\n"
        "Abrí la ruleta premium, elegí tu nombre, girá y participá por premios reales."
    )

    await update.message.reply_text(text, reply_markup=keyboard)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "/start - abrir menú\n"
        "/premios - ver premios\n"
        "/myid - ver tu ID\n"
        "/misfichas - ver fichas\n"
        "/compraspendientes - ver compras pendientes (admin)\n"
        "/aprobarcompra ID_COMPRA - acreditar compra pendiente (admin)\n"
        "/sumarfichas USER_ID CANTIDAD - sumar fichas directo (admin)\n"
        "/stats - estadísticas (admin)"
    )


async def premios_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    user = update.effective_user
    currency = get_currency_from_language(user.language_code, DEFAULT_CURRENCY)

    await update.message.reply_text(
        f"🎁 Premios ({currency}):\n\n"
        f"{format_prize_list(REAL_PRIZES, currency, UYU_TO_ARS, DEFAULT_CURRENCY)}\n\n"
        f"🎟 Valor de la ficha: {ticket_price_text(currency, TICKET_PRICE_UYU, UYU_TO_ARS, DEFAULT_CURRENCY)}"
    )


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    await update.message.reply_text(f"Tu ID de Telegram es: {update.effective_user.id}")


async def misfichas_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    user = update.effective_user
    key, profile = get_user_profile(
        user.id,
        user.username,
        user.full_name,
        USERS_FILE,
        DEFAULT_CURRENCY,
        DEMO_SPINS,
    )

    await update.message.reply_text(
        f"🎟 Tus fichas: {safe_int(profile.get('fichas', 0), 0, 0)}\n"
        f"🆓 Demo disponible: {safe_int(profile.get('demo_spins_left', 0), 0, 0)}\n"
        f"👤 Nombre: {profile.get('display_name', 'Jugador')}\n"
        f"🆔 Clave interna: {key}"
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    if not is_admin(update.effective_user.id, ADMIN_IDS):
        await update.message.reply_text("No autorizado.")
        return

    logs = load_logs(LOG_FILE)
    users = load_users(USERS_FILE)
    purchases = load_purchases(PURCHASES_FILE)

    total = len(logs)
    pending = len([x for x in purchases if x.get("status") == "pending"])
    approved = len([x for x in purchases if x.get("status") == "approved"])

    counts: dict[str, int] = {}
    for item in logs:
        prize = str(item.get("prize", "Sin premio"))
        counts[prize] = counts.get(prize, 0) + 1

    lines = [
        f"📊 Giros totales: {total}",
        f"👥 Usuarios: {len(users)}",
        f"🧾 Compras pendientes: {pending}",
        f"✅ Compras aprobadas: {approved}",
        "",
        "Premios más salidos:",
    ]

    for prize, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"{prize}: {count}")

    await update.message.reply_text("\n".join(lines))


async def compras_pendientes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    if not is_admin(update.effective_user.id, ADMIN_IDS):
        await update.message.reply_text("No autorizado.")
        return

    items = [x for x in load_purchases(PURCHASES_FILE) if x.get("status") == "pending"]

    if not items:
        await update.message.reply_text("No hay compras pendientes.")
        return

    lines = ["🧾 Compras pendientes:"]

    for item in items[-20:]:
        lines.append(
            f"\nID: {item.get('purchase_id', '')}"
            f"\nUsuario: {item.get('display_name', 'Jugador')}"
            f"\nUser key: {item.get('user_key', '')}"
            f"\nPaís: {item.get('country', '')}"
            f"\nFichas: {safe_int(item.get('qty', 1), 1, 1)}"
            f"\nFecha: {item.get('created_at', '')}"
        )

    await update.message.reply_text("\n".join(lines))


async def aprobar_compra_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    if not is_admin(update.effective_user.id, ADMIN_IDS):
        await update.message.reply_text("No autorizado.")
        return

    if not context.args:
        await update.message.reply_text("Uso: /aprobarcompra ID_COMPRA")
        return

    purchase_id = context.args[0].strip()
    approved = approve_purchase_by_id(
        purchase_id,
        update.effective_user.id,
        PURCHASES_FILE,
        USERS_FILE,
    )

    if not approved:
        await update.message.reply_text("Compra no encontrada o ya aprobada.")
        return

    users = load_users(USERS_FILE)
    profile = users.get(approved["user_key"], {})

    await update.message.reply_text(
        f"✅ Compra aprobada\n"
        f"ID: {purchase_id}\n"
        f"Usuario: {approved.get('display_name', 'Jugador')}\n"
        f"Fichas acreditadas: {safe_int(approved.get('qty', 1), 1, 1)}\n"
        f"Saldo actual: {safe_int(profile.get('fichas', 0), 0, 0)}"
    )


async def sumar_fichas_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    if not is_admin(update.effective_user.id, ADMIN_IDS):
        await update.message.reply_text("No autorizado.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Uso: /sumarfichas USER_ID CANTIDAD")
        return

    user_id = context.args[0].strip()

    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Cantidad inválida.")
        return

    users = load_users(USERS_FILE)
    profile = users.get(str(user_id))

    if not profile:
        await update.message.reply_text("Usuario no encontrado en users_data.json")
        return

    profile["fichas"] = max(0, safe_int(profile.get("fichas", 0), 0, 0) + amount)
    profile["updated_at"] = now_iso()
    users[str(user_id)] = profile
    save_users(users, USERS_FILE)

    await update.message.reply_text(
        f"✅ Fichas actualizadas\n"
        f"Usuario: {profile.get('display_name', 'Jugador')}\n"
        f"Saldo: {safe_int(profile.get('fichas', 0), 0, 0)}"
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()
    user = query.from_user
    currency = get_currency_from_language(getattr(user, "language_code", None), DEFAULT_CURRENCY)

    if query.data == "view_prizes" and query.message:
        await query.message.reply_text(
            f"🎁 Premios ({currency}):\n\n"
            f"{format_prize_list(REAL_PRIZES, currency, UYU_TO_ARS, DEFAULT_CURRENCY)}\n\n"
            f"🎟 Valor de la ficha: {ticket_price_text(currency, TICKET_PRICE_UYU, UYU_TO_ARS, DEFAULT_CURRENCY)}"
        )
        return

    if query.data == "view_tokens" and query.message:
        _, profile = get_user_profile(
            user.id,
            user.username,
            user.full_name,
            USERS_FILE,
            DEFAULT_CURRENCY,
            DEMO_SPINS,
        )
        await query.message.reply_text(
            f"🎟 Tus fichas: {safe_int(profile.get('fichas', 0), 0, 0)}\n"
            f"🆓 Demo disponible: {safe_int(profile.get('demo_spins_left', 0), 0, 0)}\n"
            f"👤 Nombre: {profile.get('display_name', 'Jugador')}"
        )


def build_bot_application():
    if not TOKEN:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN en variables de entorno.")

    bot_app = ApplicationBuilder().token(TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(CommandHandler("premios", premios_command))
    bot_app.add_handler(CommandHandler("myid", myid_command))
    bot_app.add_handler(CommandHandler("misfichas", misfichas_command))
    bot_app.add_handler(CommandHandler("stats", stats_command))
    bot_app.add_handler(CommandHandler("compraspendientes", compras_pendientes_command))
    bot_app.add_handler(CommandHandler("aprobarcompra", aprobar_compra_command))
    bot_app.add_handler(CommandHandler("sumarfichas", sumar_fichas_command))
    bot_app.add_handler(CallbackQueryHandler(button_handler))
    return bot_app


def run_bot_polling() -> None:
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        bot_app = build_bot_application()
        logger.info("Bot de Telegram iniciado")
        bot_app.run_polling(drop_pending_updates=True, stop_signals=None)
    except Exception:
        logger.exception("Error al iniciar el bot de Telegram.")


def start_bot_background_once() -> None:
    global _bot_started

    if not RUN_TELEGRAM_BOT:
        return

    if not START_TELEGRAM_WITH_WEB:
        return

    if not TOKEN:
        logger.warning("RUN_TELEGRAM_BOT=true pero falta TELEGRAM_BOT_TOKEN.")
        return

    with _bot_lock:
        if _bot_started:
            return

        _bot_started = True
        thread = threading.Thread(
            target=run_bot_polling,
            name="telegram-bot",
            daemon=True,
        )
        thread.start()
        logger.info("Thread del bot de Telegram lanzado")


# =========================================================
# FLASK LIFECYCLE
# =========================================================

@app.before_request
def boot_bot_once():
    start_bot_background_once()


@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# =========================================================
# RUTAS
# =========================================================

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
            "start_telegram_with_web": START_TELEGRAM_WITH_WEB,
            "default_currency": DEFAULT_CURRENCY,
            "demo_spins": DEMO_SPINS,
            "ticket_price_uyu": TICKET_PRICE_UYU,
            "max_purchase_qty": MAX_PURCHASE_QTY,
            "admin_count": len(ADMIN_IDS),
            "links": {
                "ar_ok": is_valid_payment_link(MP_LINK_AR),
                "uy_ok": is_valid_payment_link(MP_LINK_UY),
            },
        }
    )


@app.get("/wheel")
def wheel_page():
    user_id = request.args.get("user_id", "").strip()
    username = request.args.get("username", "").strip()
    full_name = request.args.get("full_name", "").strip()
    currency = resolve_currency(request.args.get("currency", DEFAULT_CURRENCY))
    display_name = resolve_display_name(request.args.get("display_name", "").strip(), full_name, username)

    profile = ensure_profile(
        user_id=user_id,
        username=username,
        full_name=full_name,
        currency=currency,
        display_name=display_name,
    )

    ui_config = base_ui_config(profile, currency)

    return make_response(
        render_template(
            "wheel.html",
            bot_name=BOT_NAME,
            prizes=json.dumps(VISIBLE_PRIZES, ensure_ascii=False),
            currency=currency,
            default_currency=DEFAULT_CURRENCY,
            user_id=user_id,
            username=username,
            full_name=full_name,
            display_name=profile.get("display_name", "Jugador"),
            fichas=safe_int(profile.get("fichas", 0), 0, 0),
            demo_spins_left=safe_int(profile.get("demo_spins_left", 0), 0, 0),
            uyu_to_ars=UYU_TO_ARS,
            ticket_price_uyu=TICKET_PRICE_UYU,
            ticket_price_label=ticket_price_text(currency, TICKET_PRICE_UYU, UYU_TO_ARS, DEFAULT_CURRENCY),
            mp_link_ar=MP_LINK_AR,
            mp_link_uy=MP_LINK_UY,
            run_telegram_bot=RUN_TELEGRAM_BOT,
            max_purchase_qty=MAX_PURCHASE_QTY,
            demo_spins=DEMO_SPINS,
            ui_config=json.dumps(ui_config, ensure_ascii=False),
        )
    )


@app.post("/api/profile")
def api_profile():
    data = request.get_json(silent=True) or {}

    user_id = data.get("user_id")
    if not require_user_identity(user_id):
        return json_error("Falta user_id.")

    username = str(data.get("username", "")).strip()
    full_name = str(data.get("full_name", "")).strip()
    currency = resolve_currency(data.get("currency", DEFAULT_CURRENCY))
    display_name = resolve_display_name(str(data.get("display_name", "")).strip(), full_name, username)

    key, profile = get_user_profile(
        user_id,
        username,
        full_name,
        USERS_FILE,
        DEFAULT_CURRENCY,
        DEMO_SPINS,
    )

    profile["display_name"] = display_name
    profile["currency"] = currency
    profile["updated_at"] = now_iso()

    update_user_profile(key, profile, USERS_FILE)

    return jsonify(
        {
            "ok": True,
            "profile": profile_payload(profile),
            "messages": {
                "welcome": f"Bienvenido/a, {display_name}",
                "saved": "Tu nombre quedó guardado correctamente.",
            },
        }
    )


@app.post("/api/profile-sync")
def api_profile_sync():
    data = request.get_json(silent=True) or {}

    user_id = data.get("user_id")
    if not require_user_identity(user_id):
        return json_error("Falta user_id.")

    username = str(data.get("username", "")).strip()
    full_name = str(data.get("full_name", "")).strip()
    currency = resolve_currency(data.get("currency", DEFAULT_CURRENCY))
    display_name = resolve_display_name(str(data.get("display_name", "")).strip(), full_name, username)

    key, profile = get_user_profile(
        user_id,
        username,
        full_name,
        USERS_FILE,
        DEFAULT_CURRENCY,
        DEMO_SPINS,
    )

    profile["currency"] = currency
    profile["display_name"] = display_name
    profile["updated_at"] = now_iso()

    update_user_profile(key, profile, USERS_FILE)

    return jsonify(
        {
            "ok": True,
            "profile": profile_payload(profile),
        }
    )


@app.post("/api/create-pending-purchase")
def api_create_pending_purchase():
    data = request.get_json(silent=True) or {}

    user_id = data.get("user_id")
    if not require_user_identity(user_id):
        return json_error("Falta user_id.")

    username = str(data.get("username", "")).strip()
    full_name = str(data.get("full_name", "")).strip()
    display_name = resolve_display_name(str(data.get("display_name", "")).strip(), full_name, username)
    currency = resolve_currency(data.get("currency", DEFAULT_CURRENCY))
    country = normalize_country(data.get("country", "UY"))
    qty = safe_int(data.get("qty", 1), default=1, min_value=1, max_value=MAX_PURCHASE_QTY)

    ensure_user_profile(
        user_id=user_id,
        username=username,
        full_name=full_name,
        currency=currency,
        display_name=display_name,
        users_file=USERS_FILE,
        default_demo_spins=DEMO_SPINS,
        default_currency=DEFAULT_CURRENCY,
    )

    item = create_pending_purchase(
        user_id=user_id,
        username=username,
        full_name=full_name,
        display_name=display_name,
        country=country,
        currency=currency,
        qty=qty,
        purchases_file=PURCHASES_FILE,
        default_currency=DEFAULT_CURRENCY,
    )

    payment_url = get_country_link(country, MP_LINK_AR, MP_LINK_UY)

    return jsonify(
        {
            "ok": True,
            "purchase_id": item["purchase_id"],
            "country": country,
            "qty": qty,
            "payment_url": payment_url,
            "message": "Compra registrada como pendiente. Luego aprobala desde admin o bot.",
            "messages": {
                "thanks": f"Gracias {display_name}, tu compra fue registrada.",
                "next": "Completá el pago y luego aprobá la compra desde Telegram.",
            },
        }
    )


@app.post("/api/spin")
def api_spin():
    data = request.get_json(silent=True) or {}

    user_id = data.get("user_id")
    if not require_user_identity(user_id):
        return json_error("Falta user_id.")

    username = str(data.get("username", "")).strip()
    full_name = str(data.get("full_name", "")).strip()
    display_name = resolve_display_name(str(data.get("display_name", "")).strip(), full_name, username)
    currency = resolve_currency(data.get("currency", DEFAULT_CURRENCY))
    mode = str(data.get("mode", "paid")).strip().lower()

    if mode not in {"demo", "paid"}:
        mode = "paid"

    key, profile = get_user_profile(
        user_id,
        username,
        full_name,
        USERS_FILE,
        DEFAULT_CURRENCY,
        DEMO_SPINS,
    )

    profile["display_name"] = display_name
    profile["currency"] = currency

    fichas = safe_int(profile.get("fichas", 0), 0, 0)
    demo_left = safe_int(profile.get("demo_spins_left", 0), 0, 0)

    if mode == "demo":
        if demo_left <= 0:
            return json_error("Ya usaste la tirada demo.")
        profile["demo_spins_left"] = demo_left - 1
    else:
        if fichas <= 0:
            return json_error("No tenés fichas. Comprá una para seguir jugando.")
        profile["fichas"] = fichas - 1

    prize = pick_weighted_prize(REAL_PRIZES)

    profile["wins"] = safe_int(profile.get("wins", 0), 0, 0) + 1
    profile["last_prize"] = prize["name"]
    profile["updated_at"] = now_iso()

    update_user_profile(key, profile, USERS_FILE)

    log_spin(
        user_id=user_id,
        username=username,
        full_name=full_name,
        display_name=display_name,
        prize_name=prize["name"],
        currency=currency,
        spin_mode=mode,
        log_file=LOG_FILE,
    )

    prize_label = convert_price_from_uyu(
        safe_int(prize["uyu_price"], 0, 0),
        currency,
        UYU_TO_ARS,
        DEFAULT_CURRENCY,
    )

    return jsonify(
        {
            "ok": True,
            "mode": mode,
            "prize": {
                "name": prize["name"],
                "label": prize_label,
                "chance": prize["chance"],
                "uyu_price": safe_int(prize["uyu_price"], 0, 0),
            },
            "ticket": ticket_price_text(currency, TICKET_PRICE_UYU, UYU_TO_ARS, DEFAULT_CURRENCY),
            "profile": profile_payload(profile),
            "messages": {
                "welcome": f"Bienvenido/a, {display_name}",
                "thanks": f"Gracias por jugar en {BOT_NAME}",
                "result": f"{display_name}, tu premio es {prize['name']}",
                "subtitle": f"Premio valorizado en {prize_label}",
            },
            "fx": {
                "confetti": True,
                "show_result_modal": True,
                "play_win_sound": True,
                "enable_3d_flash": True,
                "highlight_text": True,
                "high_contrast_text": True,
            },
        }
    )


# =========================================================
# MAIN
# =========================================================

def main() -> None:
    ensure_json_file(LOG_FILE, [])
    ensure_json_file(USERS_FILE, {})
    ensure_json_file(PURCHASES_FILE, [])

    validate_startup_config()

    logger.info("%s web iniciada en http://127.0.0.1:%s", BOT_NAME, WEB_PORT)
    logger.info(
        "Config activa | moneda=%s | demo=%s | ficha=%s UYU | max_purchase_qty=%s | bot=%s | start_with_web=%s",
        DEFAULT_CURRENCY,
        DEMO_SPINS,
        TICKET_PRICE_UYU,
        MAX_PURCHASE_QTY,
        RUN_TELEGRAM_BOT,
        START_TELEGRAM_WITH_WEB,
    )

    app.run(host="0.0.0.0", port=WEB_PORT, debug=False)


if __name__ == "__main__":
    main()