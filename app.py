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
    add_fichas_to_user,
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
MP_LINK_AR = os.environ.get("MP_LINK_AR", "https://mpago.la/1vUBfHc").strip()
MP_LINK_UY = os.environ.get("MP_LINK_UY", "https://mpago.la/1Zgex99").strip()
RUN_TELEGRAM_BOT = os.environ.get("RUN_TELEGRAM_BOT", "false").strip().lower() == "true"
TICKET_PRICE_UYU = int(os.environ.get("TICKET_PRICE_UYU", "250"))
DEMO_SPINS = int(os.environ.get("DEMO_SPINS", "1"))

ADMIN_IDS = {
    int(x.strip())
    for x in os.environ.get("ADMIN_IDS", "8445311801").split(",")
    if x.strip().isdigit()
}

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
    main()