# Ruleta Jeny PRO — código listo para copiar y pegar

Abajo te dejo una versión completa, más prolija y más estable, con estas mejoras ya integradas:

* nombre del jugador al iniciar
* fichas por usuario
* demo gratis de 1 tirada
* botón para comprar ficha
* dos links de Mercado Pago (Argentina y Uruguay)
* panel admin por comandos de Telegram para acreditar fichas manualmente
* probabilidades corregidas con **💎 Encuentro = 0.1%**
* ruleta visual más premium
* pelotita grande animada
* textos de promo dentro de la captura
* logs JSON sin base de datos
* lista para Render

> Importante: con **links fijos `mpago.la`** no se puede garantizar una acreditación 100% automática por usuario de forma segura, porque ese flujo no identifica de manera confiable quién pagó cada compra dentro de tu app. Por eso esta versión queda **funcional y profesional** con acreditación manual por admin. Más abajo también te dejo cómo pasarla a automático real con webhook cuando quieras.

---

## 1) `app.py`

```python
import json
import logging
import math
import os
import random
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from flask import Flask, jsonify, make_response, redirect, render_template_string, request
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
USERS_FILE = Path(os.environ.get("USERS_FILE", "users_data.json"))
PURCHASES_FILE = Path(os.environ.get("PURCHASES_FILE", "pending_purchases.json"))

# Links directos que vos pasaste
MP_LINK_AR = os.environ.get("MP_LINK_AR", "https://mpago.la/1vUBfHc").strip()
MP_LINK_UY = os.environ.get("MP_LINK_UY", "https://mpago.la/1Zgex99").strip()

RUN_TELEGRAM_BOT = os.environ.get("RUN_TELEGRAM_BOT", "false").strip().lower() == "true"

ADMIN_IDS = {
    int(x.strip())
    for x in os.environ.get("ADMIN_IDS", "8445311801").split(",")
    if x.strip().isdigit()
}

TICKET_PRICE_UYU = int(os.environ.get("TICKET_PRICE_UYU", "250"))
DEMO_SPINS = int(os.environ.get("DEMO_SPINS", "1"))

# Probabilidades pedidas por vos = 100%
# Encuentro queda ultra raro: 0.1%
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

VISIBLE_PRIZES = REAL_PRIZES[:]  # visibles en panel y ruleta

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
_user_lock = threading.Lock()
_purchase_lock = threading.Lock()
_bot_lock = threading.Lock()
_bot_started = False

# =========================================================
# UTILIDADES ARCHIVOS
# =========================================================


def ensure_json_file(path: Path, default: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")



def read_json(path: Path, default: Any) -> Any:
    ensure_json_file(path, default)
    try:
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return default
        return json.loads(content)
    except Exception:
        logger.exception("No se pudo leer %s", path)
        return default



def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# =========================================================
# UTILIDADES LOGS / USUARIOS / COMPRAS
# =========================================================


def load_logs() -> list[dict[str, Any]]:
    with _log_lock:
        data = read_json(LOG_FILE, [])
        return data if isinstance(data, list) else []



def save_logs(logs: list[dict[str, Any]]) -> None:
    with _log_lock:
        write_json(LOG_FILE, logs)



def load_users() -> dict[str, Any]:
    with _user_lock:
        data = read_json(USERS_FILE, {})
        return data if isinstance(data, dict) else {}



def save_users(users: dict[str, Any]) -> None:
    with _user_lock:
        write_json(USERS_FILE, users)



def load_purchases() -> list[dict[str, Any]]:
    with _purchase_lock:
        data = read_json(PURCHASES_FILE, [])
        return data if isinstance(data, list) else []



def save_purchases(items: list[dict[str, Any]]) -> None:
    with _purchase_lock:
        write_json(PURCHASES_FILE, items)



def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")



def normalize_currency(currency: str | None) -> str:
    value = (currency or DEFAULT_CURRENCY).strip().upper()
    return value if value in {"UYU", "ARS"} else DEFAULT_CURRENCY



def get_currency_from_language(language_code: str | None) -> str:
    lang = (language_code or "").lower()
    if lang.startswith("es-ar"):
        return "ARS"
    if lang.startswith("es-uy"):
        return "UYU"
    return DEFAULT_CURRENCY



def convert_price_from_uyu(amount_uyu: int, currency: str) -> str:
    currency = normalize_currency(currency)
    if currency == "ARS":
        return f"${amount_uyu * UYU_TO_ARS} ARS"
    return f"${amount_uyu} UYU"



def ticket_price_text(currency: str) -> str:
    return convert_price_from_uyu(TICKET_PRICE_UYU, currency)



def format_prize(prize: dict[str, Any], currency: str) -> str:
    return f"{prize['name']} — {convert_price_from_uyu(int(prize['uyu_price']), currency)}"



def format_prize_list(currency: str) -> str:
    return "\n".join(
        f"{p['name']} — {convert_price_from_uyu(int(p['uyu_price']), currency)} — {p['chance']}%"
        for p in REAL_PRIZES
    )



def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS



def sanitize_name(name: str | None) -> str:
    raw = (name or "").strip()
    if not raw:
        return "Jugador"
    return raw[:40]



def get_user_key(user_id: str | int | None, username: str | None, full_name: str | None) -> str:
    if user_id not in (None, "", 0, "0"):
        return str(user_id)
    if username:
        return f"user:{username.lower()}"
    return f"guest:{sanitize_name(full_name)}"



def ensure_user_profile(
    user_id: str | int | None,
    username: str | None,
    full_name: str | None,
    currency: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    users = load_users()
    key = get_user_key(user_id, username, full_name)

    if key not in users:
        users[key] = {
            "user_id": user_id,
            "username": username or "",
            "full_name": full_name or "",
            "display_name": sanitize_name(display_name or full_name or username or "Jugador"),
            "currency": normalize_currency(currency),
            "fichas": 0,
            "demo_spins_left": DEMO_SPINS,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "wins": 0,
            "last_prize": "",
        }
    else:
        users[key]["username"] = username or users[key].get("username", "")
        users[key]["full_name"] = full_name or users[key].get("full_name", "")
        if display_name:
            users[key]["display_name"] = sanitize_name(display_name)
        users[key]["currency"] = normalize_currency(currency)
        users[key]["updated_at"] = now_iso()

    save_users(users)
    return users[key]



def get_user_profile(user_id: str | int | None, username: str | None, full_name: str | None) -> tuple[str, dict[str, Any]]:
    users = load_users()
    key = get_user_key(user_id, username, full_name)
    profile = users.get(key)
    if not profile:
        profile = ensure_user_profile(user_id, username, full_name, DEFAULT_CURRENCY)
    return key, profile



def update_user_profile(key: str, profile: dict[str, Any]) -> None:
    users = load_users()
    profile["updated_at"] = now_iso()
    users[key] = profile
    save_users(users)



def add_fichas_to_user(key: str, amount: int) -> dict[str, Any]:
    users = load_users()
    profile = users.get(key)
    if not profile:
        raise ValueError("Usuario no encontrado")
    profile["fichas"] = max(0, int(profile.get("fichas", 0)) + int(amount))
    profile["updated_at"] = now_iso()
    users[key] = profile
    save_users(users)
    return profile



def pick_weighted_prize() -> dict[str, Any]:
    weights = [int(p["weight"]) for p in REAL_PRIZES]
    return random.choices(REAL_PRIZES, weights=weights, k=1)[0]



def log_spin(
    user_id: str | int | None,
    username: str | None,
    full_name: str | None,
    display_name: str | None,
    prize_name: str,
    currency: str,
    spin_mode: str,
) -> None:
    logs = load_logs()
    logs.append(
        {
            "timestamp": now_iso(),
            "user_id": user_id,
            "username": username or "",
            "full_name": full_name or "",
            "display_name": sanitize_name(display_name),
            "currency": currency,
            "prize": prize_name,
            "mode": spin_mode,
        }
    )
    save_logs(logs)



def create_pending_purchase(
    user_id: str | int | None,
    username: str | None,
    full_name: str | None,
    display_name: str | None,
    country: str,
    currency: str,
    qty: int,
) -> dict[str, Any]:
    country = country.upper().strip()
    if country not in {"AR", "UY"}:
        country = "UY"

    items = load_purchases()
    purchase_id = f"buy_{int(datetime.now().timestamp() * 1000)}_{random.randint(1000,9999)}"
    user_key = get_user_key(user_id, username, full_name)

    item = {
        "purchase_id": purchase_id,
        "user_key": user_key,
        "user_id": user_id,
        "username": username or "",
        "full_name": full_name or "",
        "display_name": sanitize_name(display_name or full_name or username),
        "country": country,
        "currency": normalize_currency(currency),
        "qty": max(1, int(qty)),
        "status": "pending",
        "created_at": now_iso(),
        "approved_at": "",
        "approved_by": "",
    }
    items.append(item)
    save_purchases(items)
    return item



def approve_purchase_by_id(purchase_id: str, admin_id: int) -> dict[str, Any] | None:
    items = load_purchases()
    found = None
    for item in items:
        if item.get("purchase_id") == purchase_id and item.get("status") == "pending":
            found = item
            break
    if not found:
        return None

    profile_key = found["user_key"]
    add_fichas_to_user(profile_key, int(found.get("qty", 1)))
    found["status"] = "approved"
    found["approved_at"] = now_iso()
    found["approved_by"] = str(admin_id)
    save_purchases(items)
    return found



def get_country_link(country: str) -> str:
    return MP_LINK_AR if country.upper() == "AR" else MP_LINK_UY



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

    ensure_user_profile(
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        currency=currency,
        display_name=user.first_name,
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=f"🎰 ABRIR RULETA • FICHA {ticket_price_text(currency)}",
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
        f"🎟 Valor de la ficha: {ticket_price_text(currency)}\n"
        f"🆓 Demo gratis: {DEMO_SPINS} tirada\n\n"
        "Abrí la ruleta premium, comprá fichas y girá por premios reales."
    )

    await update.message.reply_text(text, reply_markup=keyboard)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    text = (
        "/start - abrir menú\n"
        "/premios - ver premios\n"
        "/myid - ver tu ID\n"
        "/misfichas - ver fichas\n"
        "/compraspendientes - ver compras pendientes (admin)\n"
        "/aprobarcompra ID_COMPRA - acreditar compra pendiente (admin)\n"
        "/sumarfichas USER_ID CANTIDAD - sumar fichas directo (admin)\n"
        "/stats - estadísticas (admin)"
    )
    await update.message.reply_text(text)


async def premios_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    user = update.effective_user
    currency = get_currency_from_language(user.language_code)
    await update.message.reply_text(
        f"🎁 Premios ({currency}):\n\n{format_prize_list(currency)}\n\n"
        f"🎟 Valor de la ficha: {ticket_price_text(currency)}"
    )


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    await update.message.reply_text(f"Tu ID de Telegram es: {update.effective_user.id}")


async def misfichas_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    user = update.effective_user
    key, profile = get_user_profile(user.id, user.username, user.full_name)
    await update.message.reply_text(
        f"🎟 Tus fichas: {profile.get('fichas', 0)}\n"
        f"🆓 Demo disponible: {profile.get('demo_spins_left', 0)}\n"
        f"👤 Nombre: {profile.get('display_name', 'Jugador')}\n"
        f"🆔 Clave interna: {key}"
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    if not is_admin(update.effective_user.id):
        await update.message.reply_text("No autorizado.")
        return

    logs = load_logs()
    users = load_users()
    purchases = load_purchases()

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
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("No autorizado.")
        return

    items = [x for x in load_purchases() if x.get("status") == "pending"]
    if not items:
        await update.message.reply_text("No hay compras pendientes.")
        return

    lines = ["🧾 Compras pendientes:"]
    for item in items[-20:]:
        lines.append(
            f"\nID: {item['purchase_id']}"
            f"\nUsuario: {item.get('display_name', 'Jugador')}"
            f"\nUser key: {item.get('user_key', '')}"
            f"\nPaís: {item.get('country', '')}"
            f"\nFichas: {item.get('qty', 1)}"
            f"\nFecha: {item.get('created_at', '')}"
        )

    await update.message.reply_text("\n".join(lines))


async def aprobar_compra_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("No autorizado.")
        return

    if not context.args:
        await update.message.reply_text("Uso: /aprobarcompra ID_COMPRA")
        return

    purchase_id = context.args[0].strip()
    approved = approve_purchase_by_id(purchase_id, update.effective_user.id)
    if not approved:
        await update.message.reply_text("Compra no encontrada o ya aprobada.")
        return

    user_key = approved["user_key"]
    users = load_users()
    profile = users.get(user_key, {})
    await update.message.reply_text(
        f"✅ Compra aprobada\n"
        f"ID: {purchase_id}\n"
        f"Usuario: {approved.get('display_name', 'Jugador')}\n"
        f"Fichas acreditadas: {approved.get('qty', 1)}\n"
        f"Saldo actual: {profile.get('fichas', 0)}"
    )


async def sumar_fichas_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not is_admin(update.effective_user.id):
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

    users = load_users()
    key = str(user_id)
    profile = users.get(key)
    if not profile:
        await update.message.reply_text("Usuario no encontrado en users_data.json")
        return

    profile["fichas"] = max(0, int(profile.get("fichas", 0)) + amount)
    profile["updated_at"] = now_iso()
    users[key] = profile
    save_users(users)

    await update.message.reply_text(
        f"✅ Fichas actualizadas\nUsuario: {profile.get('display_name', 'Jugador')}\nSaldo: {profile.get('fichas', 0)}"
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()
    user = query.from_user
    currency = get_currency_from_language(getattr(user, "language_code", None))

    if query.data == "view_prizes" and query.message:
        await query.message.reply_text(
            f"🎁 Premios ({currency}):\n\n{format_prize_list(currency)}\n\n"
            f"🎟 Valor de la ficha: {ticket_price_text(currency)}"
        )
        return

    if query.data == "view_tokens" and query.message:
        _, profile = get_user_profile(user.id, user.username, user.full_name)
        await query.message.reply_text(
            f"🎟 Tus fichas: {profile.get('fichas', 0)}\n"
            f"🆓 Demo disponible: {profile.get('demo_spins_left', 0)}"
        )
        return



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
# HTML TEMPLATE
# =========================================================

HTML_TEMPLATE = r"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>{{ bot_name }}</title>
  <meta name="theme-color" content="#14030b">
  <style>
    *{box-sizing:border-box}
    html,body{min-height:100%}
    :root{
      --bg-1:#100109;
      --bg-2:#1a0410;
      --bg-3:#2a0618;
      --bg-4:#3d0b24;
      --gold-1:#fff7cb;
      --gold-2:#ffe27b;
      --gold-3:#ffc94a;
      --gold-4:#d99711;
      --gold-5:#8f5700;
      --pink-1:#ff7dc5;
      --pink-2:#ff4aa7;
      --pink-3:#d81a6e;
      --violet-1:#c97aff;
      --violet-2:#943eff;
      --white-soft:rgba(255,255,255,.84);
      --white-mid:rgba(255,255,255,.68);
      --white-low:rgba(255,255,255,.46);
      --line:rgba(255,255,255,.10);
      --shadow-xl:0 40px 110px rgba(0,0,0,.58);
      --glass:linear-gradient(180deg, rgba(255,255,255,.10), rgba(255,255,255,.04));
      --btn-text:#2a1500;
      --ok:#66ffb0;
      --warn:#ffd670;
      --danger:#ff799d;
    }

    body{
      margin:0;
      color:#fff;
      font-family:Inter,Segoe UI,Arial,sans-serif;
      background:
        radial-gradient(circle at 50% -12%, rgba(255,222,120,.14), transparent 30%),
        radial-gradient(circle at 15% 12%, rgba(255,89,155,.10), transparent 22%),
        radial-gradient(circle at 82% 16%, rgba(156,74,255,.11), transparent 26%),
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

    .stars,.particles,.confetti-wrap{
      position:fixed;
      inset:0;
      pointer-events:none;
      overflow:hidden;
      z-index:0;
    }

    .star,.particle,.confetti{
      position:absolute;
      border-radius:999px;
    }

    .star{
      width:2px;height:2px;background:#fff;
      box-shadow:0 0 10px rgba(255,255,255,.85);
      animation:twinkle 4s linear infinite;
    }

    .particle{
      width:6px;height:6px;
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
      max-width:1480px;
      margin:0 auto;
      display:grid;
      grid-template-columns:minmax(0,1.18fr) minmax(370px,.82fr);
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
      display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px;flex-wrap:wrap;
    }

    .title-badge,.live-badge,.chip,.winner-badge,.tag-mini,.action-tag{
      border-radius:999px;
      font-size:12px;
      font-weight:900;
      letter-spacing:.16em;
      text-transform:uppercase;
    }

    .title-badge{
      padding:8px 16px;
      color:#ffe8a4;
      border:1px solid rgba(255,216,91,.24);
      background:linear-gradient(180deg, rgba(255,216,91,.14), rgba(255,216,91,.04));
    }

    .live-badge{
      display:inline-flex;align-items:center;gap:8px;
      padding:8px 14px;color:#ffd8e7;
      background:linear-gradient(180deg, rgba(255,86,143,.17), rgba(255,86,143,.06));
      border:1px solid rgba(255,86,143,.22);
    }

    .live-dot{
      width:8px;height:8px;border-radius:50%;background:#ff4f8c;
      box-shadow:0 0 0 0 rgba(255,79,140,.7);animation:pulseDot 1.6s infinite;
    }

    @keyframes pulseDot{
      0%{box-shadow:0 0 0 0 rgba(255,79,140,.7)}
      70%{box-shadow:0 0 0 10px rgba(255,79,140,0)}
      100%{box-shadow:0 0 0 0 rgba(255,79,140,0)}
    }

    .title{
      margin:0;font-size:clamp(34px,4.8vw,62px);line-height:1.02;font-weight:1000;letter-spacing:-.05em;text-align:center;
      text-shadow:0 4px 20px rgba(0,0,0,.45);
    }

    .title .accent{
      background:linear-gradient(180deg, #fff8d4, #ffe27b 58%, #d8950e);
      -webkit-background-clip:text;background-clip:text;color:transparent;
      filter:drop-shadow(0 8px 20px rgba(255,204,84,.18));
    }

    .subtitle{
      margin-top:12px;text-align:center;color:var(--white-mid);font-size:16px;line-height:1.5;max-width:820px;margin-inline:auto;
    }

    .promo-copy{
      margin-top:18px;
      padding:16px 18px;
      border-radius:20px;
      border:1px solid rgba(255,255,255,.09);
      background:linear-gradient(180deg, rgba(255,255,255,.07), rgba(255,255,255,.03));
      text-align:center;
      box-shadow:0 14px 30px rgba(0,0,0,.18);
    }

    .promo-copy strong{
      color:#ffe7a5;
      display:block;
      font-size:18px;
      margin-bottom:6px;
    }

    .mini-stats{margin-top:20px;display:grid;grid-template-columns:repeat(4,1fr);gap:12px}

    .mini-stat{
      position:relative;overflow:hidden;border-radius:18px;padding:14px 14px 12px;border:1px solid rgba(255,255,255,.08);
      background:linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.03));
      box-shadow:0 12px 30px rgba(0,0,0,.18);
    }

    .mini-stat-label{font-size:11px;color:var(--white-low);text-transform:uppercase;letter-spacing:.18em;font-weight:800}
    .mini-stat-value{margin-top:6px;font-size:20px;font-weight:1000;letter-spacing:-.03em}

    .card-body{position:relative;z-index:2;padding:28px}
    .wheel-stage{position:relative;perspective:1400px;transform-style:preserve-3d;max-width:780px;margin:0 auto}
    .wheel-wrap{position:relative;width:min(100%, 740px);margin:0 auto;aspect-ratio:1/1;transform:rotateX(10deg);transform-style:preserve-3d}

    .wheel-floor{
      position:absolute;left:10%;right:10%;bottom:2%;height:18%;border-radius:50%;
      background:radial-gradient(circle, rgba(0,0,0,.5), rgba(0,0,0,.12), transparent 68%);
      filter:blur(24px);transform:translateZ(-80px) scale(1.05);z-index:1;
    }

    .wheel-aura{
      position:absolute;inset:-7%;border-radius:50%;
      background:radial-gradient(circle, rgba(255,228,130,.30), rgba(255,202,88,.14), rgba(255,0,122,.08), transparent 72%);
      filter:blur(34px);animation:auraPulse 2.8s ease-in-out infinite;z-index:1;
    }

    @keyframes auraPulse{0%,100%{transform:scale(1);opacity:.98}50%{transform:scale(1.045);opacity:.8}}

    .halo-ring{position:absolute;inset:-2%;border-radius:50%;border:2px solid rgba(255,224,123,.14);box-shadow:0 0 26px rgba(255,214,104,.16), inset 0 0 24px rgba(255,214,104,.08);animation:ringRotate 14s linear infinite;z-index:2;pointer-events:none}
    .halo-ring.two{inset:3%;border-color:rgba(255,92,168,.10);box-shadow:0 0 26px rgba(255,92,168,.12), inset 0 0 24px rgba(255,92,168,.06);animation-duration:20s;animation-direction:reverse}
    @keyframes ringRotate{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}

    .wheel-reflection{position:absolute;inset:7% 16% auto 16%;height:150px;border-radius:999px;background:linear-gradient(180deg, rgba(255,255,255,.24), rgba(255,255,255,0));transform:rotate(-16deg) translateZ(30px);filter:blur(5px);z-index:9;pointer-events:none}

    .wheel-shell{
      position:absolute;inset:0;border-radius:50%;overflow:hidden;
      background:radial-gradient(circle at 28% 28%, rgba(255,255,255,.16), transparent 24%), radial-gradient(circle at 65% 72%, rgba(0,0,0,.28), transparent 36%), linear-gradient(145deg, #651337, #1a020e 58%, #2f0919);
      border:24px solid var(--gold-3);
      box-shadow:inset 0 0 0 2px rgba(255,255,255,.18), inset 0 0 0 8px rgba(255,255,255,.05), inset 0 0 0 16px rgba(86,30,4,.25), inset 0 0 34px rgba(0,0,0,.55), 0 0 0 2px rgba(255,222,120,.12), 0 0 34px rgba(255,216,91,.34), 0 18px 40px rgba(0,0,0,.34), 0 45px 90px rgba(0,0,0,.5);
      transform:translateZ(24px);z-index:4;
    }

    .wheel-outer-metal{position:absolute;inset:-2.2%;border-radius:50%;background:conic-gradient(from 0deg, rgba(255,240,180,.55), rgba(202,133,20,.45), rgba(255,239,175,.56), rgba(176,105,8,.50), rgba(255,239,175,.56));filter:blur(1px);opacity:.9;z-index:3;box-shadow:0 0 30px rgba(255,216,91,.14)}
    .wheel-inner-ring{position:absolute;inset:18px;border-radius:50%;border:3px solid rgba(255,255,255,.12);box-shadow:inset 0 0 18px rgba(255,255,255,.04), 0 0 18px rgba(255,255,255,.03);z-index:6;pointer-events:none}
    .wheel-depth{position:absolute;inset:7%;border-radius:50%;background:radial-gradient(circle at 50% 50%, rgba(255,255,255,.03), rgba(0,0,0,.24) 78%, rgba(0,0,0,.42) 100%);z-index:5;pointer-events:none}

    .wheel{width:100%;height:100%;border-radius:50%;transform:rotate(0deg);transition:transform 6.8s cubic-bezier(.08,.92,.16,1);filter:drop-shadow(0 22px 40px rgba(0,0,0,.72)) drop-shadow(0 0 15px rgba(255,208,89,.18));will-change:transform}

    .wheel-center{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%) translateZ(55px);width:122px;height:122px;border-radius:50%;z-index:14;background:radial-gradient(circle at 28% 26%, var(--gold-1), var(--gold-2) 36%, var(--gold-4) 78%, var(--gold-5));border:8px solid rgba(255,255,255,.96);box-shadow:0 0 0 10px rgba(72,5,26,.42), 0 16px 36px rgba(0,0,0,.42), 0 0 24px rgba(255,216,91,.26)}
    .wheel-center::before{content:"J";position:absolute;left:50%;top:50%;transform:translate(-50%,-52%);font-size:34px;font-weight:1000;color:rgba(99,20,43,.84);text-shadow:0 1px 0 rgba(255,255,255,.35)}

    .pointer-wrap{position:absolute;left:50%;top:-18px;transform:translateX(-50%) translateZ(80px);width:100px;height:132px;z-index:18;display:flex;justify-content:center;align-items:flex-start;pointer-events:none}
    .pointer-cap{position:absolute;top:4px;width:26px;height:26px;border-radius:50%;background:radial-gradient(circle at 30% 30%, var(--gold-1), var(--gold-2), var(--gold-4));box-shadow:0 0 14px rgba(255,216,91,.52),0 4px 10px rgba(0,0,0,.35);z-index:2}
    .pointer{width:0;height:0;border-left:30px solid transparent;border-right:30px solid transparent;border-top:68px solid var(--gold-3);filter:drop-shadow(0 0 16px rgba(255,214,109,.95)) drop-shadow(0 8px 14px rgba(0,0,0,.55));transform-origin:50% 0%;animation:pointerPulse 1.2s ease-in-out infinite}
    @keyframes pointerPulse{0%,100%{transform:scaleY(1)}50%{transform:scaleY(1.09)}}

    .lights{position:absolute;inset:0;z-index:12;pointer-events:none}
    .lights span{position:absolute;left:50%;top:50%;width:12px;height:12px;margin:-6px 0 0 -6px;border-radius:999px;background:radial-gradient(circle, #fff8cf, #ffd85b 58%, #c6800a);box-shadow:0 0 12px rgba(255,224,123,.98), 0 0 24px rgba(255,224,123,.58), 0 0 34px rgba(255,224,123,.28);animation:blink 1.1s ease-in-out infinite}
    @keyframes blink{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.34;transform:scale(.76)}}

    .wheel-gloss{position:absolute;inset:8% 8%;border-radius:50%;background:linear-gradient(145deg, rgba(255,255,255,.14), rgba(255,255,255,0) 28%), radial-gradient(circle at 50% 0%, rgba(255,255,255,.10), transparent 46%);mix-blend-mode:screen;pointer-events:none;z-index:10}

    .ball-track{position:absolute;inset:4%;border-radius:50%;z-index:13;pointer-events:none}
    .ball{
      position:absolute;left:50%;top:50%;width:28px;height:28px;border-radius:50%;
      background:radial-gradient(circle at 30% 30%, #fff, #f5f5f5 36%, #d7d7d7 72%, #9b9b9b);
      box-shadow:0 0 0 3px rgba(255,255,255,.10), 0 10px 18px rgba(0,0,0,.38), inset -4px -6px 10px rgba(0,0,0,.16), inset 2px 2px 6px rgba(255,255,255,.9);
      transform:translate(-50%, -50%);
      will-change:transform;
    }

    .controls{margin-top:32px;display:flex;flex-direction:column;align-items:center;gap:14px}

    .btn,.btn-secondary,.btn-pay,.btn-demo,.btn-close,.btn-save,.pill{
      position:relative;overflow:hidden;border:0;cursor:pointer;border-radius:20px;font-weight:1000;transition:transform .18s ease, filter .18s ease, opacity .18s ease, box-shadow .18s ease;
    }

    .btn{
      padding:20px 42px;font-size:20px;letter-spacing:.02em;color:var(--btn-text);
      background:linear-gradient(180deg, #fff3b6, #ffd85b 42%, #d89a0e);
      box-shadow:0 16px 28px rgba(0,0,0,.28), 0 0 0 2px rgba(255,255,255,.16) inset, 0 0 0 1px rgba(140,87,0,.36);
      min-width:280px;
    }

    .btn-secondary,.btn-pay,.btn-demo,.btn-save,.btn-close{
      padding:16px 18px;
      color:#fff;
      background:linear-gradient(180deg, rgba(255,255,255,.09), rgba(255,255,255,.04));
      border:1px solid rgba(255,255,255,.10);
      box-shadow:0 12px 24px rgba(0,0,0,.18);
    }

    .btn-pay{background:linear-gradient(180deg, rgba(255,216,91,.18), rgba(255,216,91,.07));color:#ffeeb9}
    .btn-demo{background:linear-gradient(180deg, rgba(166,120,255,.20), rgba(166,120,255,.07));color:#ecd9ff}
    .btn-save{background:linear-gradient(180deg, rgba(76,255,171,.18), rgba(76,255,171,.08));color:#c9ffe3}
    .btn-close{background:linear-gradient(180deg, rgba(255,120,157,.18), rgba(255,120,157,.08));color:#ffdce7}

    .btn:hover,.btn-secondary:hover,.btn-pay:hover,.btn-demo:hover,.btn-save:hover,.btn-close:hover,.pill:hover{transform:translateY(-2px);filter:brightness(1.04)}
    .btn:disabled{opacity:.8;cursor:not-allowed;transform:none;filter:saturate(.85)}

    .btn-row{display:grid;grid-template-columns:1fr 1fr;gap:12px;width:100%;max-width:560px}

    .btn-subline{display:flex;align-items:center;gap:10px;color:var(--white-mid);font-size:13px;text-transform:uppercase;letter-spacing:.16em;font-weight:900;text-align:center}
    .info-label{color:rgba(255,255,255,.58);text-transform:uppercase;letter-spacing:.22em;font-size:12px;font-weight:800}
    .ticket{font-size:40px;font-weight:1000;letter-spacing:-.04em;text-shadow:0 4px 16px rgba(0,0,0,.32);text-align:center}
    .footer-note{text-align:center;color:rgba(255,255,255,.46);font-size:12px;margin-top:2px}

    .panel{display:grid;gap:18px}
    .small-title{font-size:42px;line-height:1;font-weight:1000;letter-spacing:-.045em;margin:0}
    .panel-top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
    .chip{padding:10px 14px;color:#ffe7a5;border:1px solid rgba(255,216,91,.20);background:linear-gradient(180deg, rgba(255,216,91,.11), rgba(255,216,91,.04))}
    .pill-row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    .pill{padding:15px 18px;text-align:center;color:#fff;background:linear-gradient(180deg, rgba(255,255,255,.075), rgba(255,255,255,.03));border:1px solid rgba(255,255,255,.12);box-shadow:0 10px 22px rgba(0,0,0,.14)}
    .pill.active{border-color:rgba(255,216,91,.36);background:linear-gradient(180deg, rgba(255,216,91,.18), rgba(255,216,91,.06));color:#fff2c2;box-shadow:0 0 18px rgba(255,216,91,.12), inset 0 0 0 1px rgba(255,255,255,.05)}

    .winner{min-height:196px;padding:24px;border-radius:24px;border:1px solid rgba(255,255,255,.12);background:radial-gradient(circle at top left, rgba(255,219,110,.14), transparent 30%), radial-gradient(circle at top right, rgba(255,81,145,.12), transparent 20%), linear-gradient(135deg, rgba(255,46,132,.17), rgba(91,34,219,.17));box-shadow:0 18px 38px rgba(0,0,0,.22);position:relative;overflow:hidden}
    .winner::after{content:"";position:absolute;inset:0;background:linear-gradient(115deg, transparent 20%, rgba(255,255,255,.06) 42%, transparent 60%);transform:translateX(-120%);animation:winnerGlow 5s linear infinite}
    @keyframes winnerGlow{0%{transform:translateX(-120%)}100%{transform:translateX(120%)}}
    .winner-main{font-size:clamp(30px,4vw,44px);font-weight:1000;line-height:1.03;margin-top:10px;letter-spacing:-.04em;word-break:break-word}
    .winner-sub{margin-top:8px;color:rgba(255,255,255,.86);font-size:18px;font-weight:700}
    .winner-badge{display:inline-flex;align-items:center;gap:8px;margin-top:14px;padding:8px 12px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.10);color:#ffe9ad}

    .section-head{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
    .prize-list{display:grid;gap:10px;max-height:560px;overflow:auto;padding-right:4px;scrollbar-width:thin;scrollbar-color:rgba(255,216,91,.4) rgba(255,255,255,.04)}
    .prize-list::-webkit-scrollbar{width:9px}
    .prize-list::-webkit-scrollbar-track{background:rgba(255,255,255,.04);border-radius:999px}
    .prize-list::-webkit-scrollbar-thumb{background:linear-gradient(180deg, rgba(255,216,91,.7), rgba(216,154,14,.7));border-radius:999px}

    .prize-item{display:flex;justify-content:space-between;align-items:center;gap:14px;padding:14px 16px;border-radius:16px;background:linear-gradient(180deg, rgba(255,255,255,.058), rgba(255,255,255,.03));border:1px solid rgba(255,255,255,.08);box-shadow:0 10px 22px rgba(0,0,0,.10);transition:transform .16s ease, border-color .16s ease, background .16s ease}
    .prize-item:hover{transform:translateY(-1px);border-color:rgba(255,255,255,.16);background:linear-gradient(180deg, rgba(255,255,255,.072), rgba(255,255,255,.04))}
    .prize-left{display:flex;flex-direction:column;gap:4px;min-width:0}
    .prize-name{font-size:15px;font-weight:800;color:#fff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .prize-meta{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--white-low);font-weight:800}
    .prize-price{font-size:15px;white-space:nowrap;font-weight:1000;color:#ffe6a2}

    .status-row,.profile-row{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
    .status-card{padding:14px 16px;border-radius:18px;border:1px solid rgba(255,255,255,.08);background:linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.03))}
    .status-label{font-size:11px;font-weight:900;text-transform:uppercase;letter-spacing:.16em;color:var(--white-low)}
    .status-value{margin-top:6px;font-size:18px;font-weight:1000;letter-spacing:-.03em}

    .buy-card{
      padding:18px;border-radius:22px;border:1px solid rgba(255,255,255,.08);
      background:linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.03));
      display:grid;gap:12px;
    }

    .buy-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    .buy-box{padding:16px;border-radius:18px;border:1px solid rgba(255,255,255,.10);background:linear-gradient(180deg, rgba(255,255,255,.08), rgba(255,255,255,.03));display:grid;gap:8px}
    .buy-box-title{font-weight:1000;font-size:16px}
    .buy-box-sub{color:var(--white-mid);font-size:14px;line-height:1.4}

    .notice{padding:14px 16px;border-radius:18px;border:1px solid rgba(255,255,255,.09);background:linear-gradient(180deg, rgba(255,255,255,.055), rgba(255,255,255,.03));color:var(--white-mid);font-size:14px;line-height:1.5}

    .spin-glow{position:absolute;inset:0;pointer-events:none;border-radius:inherit;opacity:0;box-shadow:0 0 50px rgba(255,216,91,.14) inset, 0 0 90px rgba(255,63,159,.10) inset;transition:opacity .25s ease}
    .card.spinning .spin-glow{opacity:1}

    .toast{position:fixed;left:50%;bottom:20px;transform:translateX(-50%) translateY(20px);min-width:220px;max-width:calc(100vw - 20px);padding:14px 16px;border-radius:16px;background:linear-gradient(180deg, rgba(29,10,18,.96), rgba(15,5,10,.96));border:1px solid rgba(255,255,255,.12);color:#fff;box-shadow:0 20px 50px rgba(0,0,0,.34);opacity:0;pointer-events:none;z-index:200;transition:all .28s ease;text-align:center;font-weight:800}
    .toast.show{opacity:1;transform:translateX(-50%) translateY(0)}

    .confetti{width:10px;height:16px;opacity:.95;animation:confettiFall linear forwards;transform-origin:center}
    @keyframes confettiFall{0%{transform:translateY(-14vh) rotate(0deg) scale(.9);opacity:0}8%{opacity:1}100%{transform:translateY(110vh) rotate(960deg) scale(1);opacity:.95}}

    .modal-backdrop{
      position:fixed;inset:0;z-index:300;background:rgba(0,0,0,.66);display:flex;align-items:center;justify-content:center;padding:16px;
      backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);
    }

    .modal{
      width:min(100%, 560px);
      border-radius:28px;border:1px solid rgba(255,255,255,.10);
      background:linear-gradient(180deg, rgba(31,9,18,.96), rgba(14,4,9,.96));
      box-shadow:0 30px 90px rgba(0,0,0,.55);
      padding:24px;
      display:grid;gap:16px;
    }

    .modal h3{margin:0;font-size:34px;letter-spacing:-.04em}
    .modal p{margin:0;color:var(--white-mid);line-height:1.55}
    .field{display:grid;gap:8px}
    .field label{font-size:12px;text-transform:uppercase;letter-spacing:.16em;color:var(--white-low);font-weight:900}
    .field input,.field select{
      width:100%;padding:16px 16px;border-radius:16px;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.06);color:#fff;font-size:16px;outline:none;
    }
    .field option{color:#111}
    .modal-actions{display:grid;grid-template-columns:1fr 1fr;gap:12px}

    .hidden{display:none !important}
    .sr-only{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}

    @media (max-width:1180px){.layout{grid-template-columns:1fr}}
    @media (max-width:820px){.mini-stats,.status-row,.profile-row,.buy-grid{grid-template-columns:1fr}}
    @media (max-width:640px){
      body{padding:10px}
      .card{border-radius:24px}
      .card-header{padding:20px 18px}
      .card-body{padding:18px}
      .wheel-shell{border-width:16px}
      .wheel-center{width:88px;height:88px}
      .pointer-wrap{top:-8px;width:80px;height:100px}
      .pointer{border-left-width:22px;border-right-width:22px;border-top-width:50px}
      .btn{width:100%;min-width:0;font-size:18px;padding:16px 18px}
      .btn-row,.pill-row,.modal-actions{grid-template-columns:1fr}
      .ticket{font-size:30px}
      .small-title{font-size:34px}
      .prize-name{white-space:normal}
      .prize-item{align-items:flex-start}
      .prize-price{padding-top:2px}
    }

    @media (prefers-reduced-motion: reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
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

        <h1 class="title"><span class="accent">Ruleta de Premios</span> Jeny</h1>
        <div class="subtitle">
          Diseño premium estilo casino con ruleta 3D, luces LED, pelotita animada, demo gratis, compra de fichas y premios reales.
        </div>

        <div class="promo-copy">
          <strong>🎰 Comprá tu ficha y probá tu suerte</strong>
          Girá por fotos, videos, packs, sexting y hasta un encuentro ultra raro. Cada compra suma 1 ficha. También tenés una demo gratis para probar la ruleta.
        </div>

        <div class="mini-stats">
          <div class="mini-stat">
            <div class="mini-stat-label">Valor ficha</div>
            <div class="mini-stat-value" id="miniTicket"></div>
          </div>
          <div class="mini-stat">
            <div class="mini-stat-label">Premios</div>
            <div class="mini-stat-value" id="realPrizeCount"></div>
          </div>
          <div class="mini-stat">
            <div class="mini-stat-label">Tus fichas</div>
            <div class="mini-stat-value" id="miniFichas">0</div>
          </div>
          <div class="mini-stat">
            <div class="mini-stat-label">Demo</div>
            <div class="mini-stat-value" id="miniDemo">0</div>
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

            <div class="ball-track" id="ballTrack">
              <div class="ball" id="ball"></div>
            </div>

            <div class="wheel-center"></div>
            <div class="lights" id="lights"></div>
          </div>
        </div>

        <div class="controls">
          <button id="spinBtn" class="btn" type="button" aria-label="Girar ruleta">🎰 GIRAR CON FICHA</button>
          <div class="btn-row">
            <button id="demoBtn" class="btn-demo" type="button">🆓 TIRADA DEMO</button>
            <button id="buyBtn" class="btn-pay" type="button">💳 COMPRAR FICHA</button>
          </div>
          <div class="btn-subline">suerte • brillo • premios • casino premium</div>
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
        <div class="profile-row">
          <div class="status-card">
            <div class="status-label">Jugador</div>
            <div class="status-value" id="playerNameText">Jugador</div>
          </div>
          <div class="status-card">
            <div class="status-label">Saldo</div>
            <div class="status-value" id="fichasValue">0 fichas</div>
          </div>
        </div>

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

        <div class="buy-card">
          <div class="section-head">
            <div class="info-label">Comprar fichas</div>
            <div class="chip">1 compra = 1 ficha</div>
          </div>

          <div class="buy-grid">
            <div class="buy-box">
              <div class="buy-box-title">Argentina</div>
              <div class="buy-box-sub">Pagá con Mercado Pago Argentina y luego tocá “Ya pagué” para dejar la compra registrada.</div>
              <button class="btn-pay" id="payArBtn" type="button">🇦🇷 Pagar Argentina</button>
            </div>
            <div class="buy-box">
              <div class="buy-box-title">Uruguay</div>
              <div class="buy-box-sub">Pagá con Mercado Pago Uruguay y luego tocá “Ya pagué” para que el admin te acredite la ficha.</div>
              <button class="btn-pay" id="payUyBtn" type="button">🇺🇾 Pagar Uruguay</button>
            </div>
          </div>

          <div class="btn-row">
            <button class="btn-secondary" id="confirmArPaidBtn" type="button">✅ Ya pagué en Argentina</button>
            <button class="btn-secondary" id="confirmUyPaidBtn" type="button">✅ Ya pagué en Uruguay</button>
          </div>

          <div class="notice">
            Con esta versión tus compras quedan registradas como pendientes y luego el admin las aprueba desde Telegram. La demo sí funciona automática al instante.
          </div>
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

  <div class="modal-backdrop" id="nameModal">
    <div class="modal">
      <h3>Bienvenido</h3>
      <p>Antes de empezar, escribí tu nombre para felicitarte cuando ganes y guardar tu perfil en la ruleta.</p>
      <div class="field">
        <label for="playerNameInput">Tu nombre</label>
        <input id="playerNameInput" type="text" maxlength="40" placeholder="Ej: Gabriel">
      </div>
      <div class="modal-actions">
        <button class="btn-close" id="skipNameBtn" type="button">Seguir sin cambiar</button>
        <button class="btn-save" id="saveNameBtn" type="button">Guardar nombre</button>
      </div>
    </div>
  </div>

  <div class="sr-only" aria-live="polite" id="liveRegion"></div>

<script>
const prizes = {{ prizes|safe }};
let currency = {{ currency|tojson }};
let currentRotation = 0;
let spinning = false;
let audioCtx = null;
let tickInterval = null;
let spinTimeout = null;
let ballAnimFrame = null;
let ballStopTimeout = null;

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
  user_id: {{ user_id|tojson }},
  username: {{ username|tojson }},
  full_name: {{ full_name|tojson }},
  display_name: {{ display_name|tojson }},
  fichas: {{ fichas|tojson }},
  demo_spins_left: {{ demo_spins_left|tojson }},
};

function convertPrice(uyuPrice, curr) {
  if (curr === "ARS") return `$${uyuPrice * {{ uyu_to_ars }}} ARS`;
  return `$${uyuPrice} UYU`;
}

function ticketText() {
  return currency === "ARS" ? `$${{{ ticket_price_uyu|tojson }}} * {{ uyu_to_ars }} ARS` : `$${{{ ticket_price_uyu|tojson }}} UYU`;
}

function fixedTicketText() {
  if (currency === "ARS") return `$${{ ticket_price_uyu|tojson }} * {{ uyu_to_ars }} ARS`.replace("${{ ticket_price_uyu|tojson }}", {{ ticket_price_uyu|tojson }});
  return `$${{ ticket_price_uyu|tojson }} UYU`.replace("${{ ticket_price_uyu|tojson }}", {{ ticket_price_uyu|tojson }});
}

function getTicketLabel() {
  return currency === "ARS"
    ? `$${{ ticket_price_uyu|tojson }} ARS`.replace("${{ ticket_price_uyu|tojson }}", {{ ticket_price_uyu|tojson }} * {{ uyu_to_ars }})
    : `$${{ ticket_price_uyu|tojson }} UYU`.replace("${{ ticket_price_uyu|tojson }}", {{ ticket_price_uyu|tojson }});
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
  if (ballStopTimeout) clearTimeout(ballStopTimeout);
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
  const display_name = (playerNameInput.value || "").trim();
  const data = await apiPost("/api/profile", {
    user_id: state.user_id,
    username: state.username,
    full_name: state.full_name,
    currency,
    display_name,
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
  if (country === "AR") {
    window.open({{ mp_link_ar|tojson }}, "_blank");
  } else {
    window.open({{ mp_link_uy|tojson }}, "_blank");
  }
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
      fireConfetti(140);
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
  buyBtn.addEventListener("click", () => document.getElementById("payUyBtn").scrollIntoView({behavior: "smooth", block: "center"}));
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

    profile = ensure_user_profile(
        user_id=user_id,
        username=username,
        full_name=full_name,
        currency=currency,
        display_name=full_name or username or "Jugador",
    )

    response = make_response(
        render_template_string(
            HTML_TEMPLATE,
            bot_name=BOT_NAME,
            prizes=json.dumps(VISIBLE_PRIZES, ensure_ascii=False),
            currency=currency,
            user_id=user_id,
            username=username,
            full_name=full_name,
            display_name=profile.get("display_name", "Jugador"),
            fichas=int(profile.get("fichas", 0)),
            demo_spins_left=int(profile.get("demo_spins_left", 0)),
            uyu_to_ars=UYU_TO_ARS,
            ticket_price_uyu=TICKET_PRICE_UYU,
            mp_link_ar=MP_LINK_AR,
            mp_link_uy=MP_LINK_UY,
        )
    )
    return response


@app.post("/api/profile")
def api_profile():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    username = data.get("username", "")
    full_name = data.get("full_name", "")
    currency = normalize_currency(data.get("currency", DEFAULT_CURRENCY))
    display_name = sanitize_name(data.get("display_name") or full_name or username or "Jugador")

    key, profile = get_user_profile(user_id, username, full_name)
    profile["display_name"] = display_name
    profile["currency"] = currency
    update_user_profile(key, profile)

    return jsonify({"ok": True, "profile": profile})


@app.post("/api/profile-sync")
def api_profile_sync():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    username = data.get("username", "")
    full_name = data.get("full_name", "")
    currency = normalize_currency(data.get("currency", DEFAULT_CURRENCY))
    display_name = sanitize_name(data.get("display_name") or full_name or username or "Jugador")

    key, profile = get_user_profile(user_id, username, full_name)
    profile["currency"] = currency
    profile["display_name"] = display_name
    update_user_profile(key, profile)

    return jsonify({"ok": True, "profile": profile})


@app.post("/api/create-pending-purchase")
def api_create_pending_purchase():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    username = data.get("username", "")
    full_name = data.get("full_name", "")
    display_name = sanitize_name(data.get("display_name") or full_name or username or "Jugador")
    currency = normalize_currency(data.get("currency", DEFAULT_CURRENCY))
    country = (data.get("country") or "UY").upper().strip()
    qty = max(1, int(data.get("qty", 1)))

    ensure_user_profile(user_id, username, full_name, currency, display_name)
    item = create_pending_purchase(user_id, username, full_name, display_name, country, currency, qty)

    return jsonify(
        {
            "ok": True,
            "purchase_id": item["purchase_id"],
            "payment_url": get_country_link(country),
            "message": "Compra registrada como pendiente. Luego aprobala desde admin o bot.",
        }
    )


@app.post("/api/spin")
def api_spin():
    data = request.get_json(silent=True) or {}

    user_id = data.get("user_id")
    username = data.get("username", "")
    full_name = data.get("full_name", "")
    display_name = sanitize_name(data.get("display_name") or full_name or username or "Jugador")
    currency = normalize_currency(data.get("currency", DEFAULT_CURRENCY))
    mode = (data.get("mode") or "paid").strip().lower()

    key, profile = get_user_profile(user_id, username, full_name)
    profile["display_name"] = display_name
    profile["currency"] = currency

    fichas = int(profile.get("fichas", 0))
    demo_left = int(profile.get("demo_spins_left", 0))

    if mode == "demo":
        if demo_left <= 0:
            return jsonify({"ok": False, "error": "Ya usaste la tirada demo."}), 400
        profile["demo_spins_left"] = demo_left - 1
    else:
        if fichas <= 0:
            return jsonify({"ok": False, "error": "No tenés fichas. Comprá una para seguir jugando."}), 400
        profile["fichas"] = fichas - 1

    prize = pick_weighted_prize()
    profile["wins"] = int(profile.get("wins", 0)) + 1
    profile["last_prize"] = prize["name"]
    update_user_profile(key, profile)

    log_spin(
        user_id=user_id,
        username=username,
        full_name=full_name,
        display_name=display_name,
        prize_name=prize["name"],
        currency=currency,
        spin_mode=mode,
    )

    return jsonify(
        {
            "ok": True,
            "prize": {
                "name": prize["name"],
                "label": convert_price_from_uyu(int(prize["uyu_price"]), currency),
                "chance": prize["chance"],
            },
            "ticket": ticket_price_text(currency),
            "profile": profile,
        }
    )


# =========================================================
# MAIN
# =========================================================

def main() -> None:
    ensure_json_file(LOG_FILE, [])
    ensure_json_file(USERS_FILE, {})
    ensure_json_file(PURCHASES_FILE, [])

    if RUN_TELEGRAM_BOT:
        start_bot_background_once()

    logger.info("%s web iniciada en http://127.0.0.1:%s", BOT_NAME, WEB_PORT)
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False)


if __name__ == "__main__":
    main()
```

---

## 2) `requirements.txt`

```txt
Flask==3.1.0
python-telegram-bot==21.10
gunicorn==23.0.0
```

---

## 3) `render.yaml` (opcional)

```yaml
services:
  - type: web
    name: ruleta-jeny
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app:app
    autoDeploy: true
```

---

## 4) Variables de entorno para Render

```txt
TELEGRAM_BOT_TOKEN=TU_TOKEN
BOT_NAME=Ruleta Jeny
DEFAULT_CURRENCY=UYU
WEBAPP_BASE_URL=https://TU-APP.onrender.com
PORT=10000
UYU_TO_ARS=25
RUN_TELEGRAM_BOT=true
ADMIN_IDS=8445311801
MP_LINK_AR=https://mpago.la/1vUBfHc
MP_LINK_UY=https://mpago.la/1Zgex99
TICKET_PRICE_UYU=250
DEMO_SPINS=1
```

---

## 5) Cómo usarlo

### Para el jugador

* entra a la ruleta
* pone su nombre
* tiene 1 demo gratis
* si quiere seguir, paga por Argentina o Uruguay
* toca **Ya pagué**
* la compra queda pendiente
* vos desde Telegram la aprobás y se acredita la ficha

### Para vos como admin en Telegram

Ver compras pendientes:

```txt
/compraspendientes
```

Aprobar una compra:

```txt
/aprobarcompra buy_XXXXXXXX_1234
```

Sumar fichas manualmente:

```txt
/sumarfichas 8445311801 3
```

Ver stats:

```txt
/stats
```

---

## 6) Cómo dejarlo automático de verdad después

Cuando quieras la siguiente versión, te conviene cambiar el pago fijo por este flujo:

1. crear preferencia de Mercado Pago desde backend
2. mandar `external_reference` con el user_id
3. configurar webhook
4. cuando Mercado Pago confirme el pago, sumar fichas automáticamente al usuario correcto

Eso sí ya permite:

* acreditación automática real
* compra de varias fichas
* validación segura del pago
* evitar falsos “ya pagué”

---

## 7) Corrección importante que te recomiendo hacer ahora mismo

En tu mensaje vino el link de Uruguay como `ttps://mpago.la/1Zgex99`. En el código ya te lo dejé corregido a:

```txt
https://mpago.la/1Zgex99
```

---

## 8) Qué te mejoré de verdad en esta versión

* mejor estructura del backend
* sistema de perfiles por usuario
* fichas persistentes
* demo persistente
* registro de pagos pendientes
* admin por Telegram
* nombre del jugador persistente
* felicitación personalizada al ganar
* probabilidades corregidas
* panel mucho más claro
* CTA publicitaria dentro de la captura
* pelotita grande visual y animada
* menos riesgo de romper en Render

---

## 9) Siguiente paso ideal

Si querés la siguiente iteración, la mejor mejora ya no sería visual sino esta:

**versión con Mercado Pago automático real por webhook y acreditación instantánea de fichas sin aprobación manual**.

Esa es la que te dejaría realmente “nivel pro de producción”.
