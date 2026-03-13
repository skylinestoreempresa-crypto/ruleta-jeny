import logging
import os
import random
import threading
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

from flask import Flask, jsonify, make_response, render_template, render_template_string, request
from jinja2 import TemplateNotFound
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes

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
    sanitize_name,
    ticket_price_text,
    update_user_profile,
)


DEMO_MODE_LABEL = "DEMO"
REAL_MODE_LABEL = "Tirada real"
DEMO_MODE_NOTICE = "Los resultados del demo son ilustrativos y usan probabilidades de vista previa."
VALID_MODES = {"auto", "demo", "ticket"}

# Real: mantiene tus porcentajes actuales
# Demo: muestra todas las opciones, pero el Gran premio tiene el peso más alto
DEFAULT_PRIZES = [
    {"name": "💋 Pose favorita", "chance": 35.9, "uyu_price": 200, "weight": 359, "demo_weight": 130},
    {"name": "📷 Pack digital", "chance": 24.0, "uyu_price": 350, "weight": 240, "demo_weight": 95},
    {"name": "🎥 Video personalizado", "chance": 18.0, "uyu_price": 500, "weight": 180, "demo_weight": 75},
    {"name": "🔥 Pack especial", "chance": 10.0, "uyu_price": 700, "weight": 100, "demo_weight": 55},
    {"name": "🎬 Video exclusivo 3 min", "chance": 6.0, "uyu_price": 750, "weight": 60, "demo_weight": 40},
    {"name": "📸 10 imágenes premium", "chance": 4.0, "uyu_price": 1000, "weight": 40, "demo_weight": 30},
    {"name": "💬 Chat VIP 30 minutos", "chance": 2.0, "uyu_price": 950, "weight": 20, "demo_weight": 20},
    {"name": "💎 Gran premio ENCUENTRO", "chance": 0.1, "uyu_price": 1500, "weight": 1, "demo_weight": 320},
]


def _env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    if minimum is not None and value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on", "si", "sí"}


def _env_admin_ids(name: str, default: str) -> set[int]:
    values: set[int] = set()
    for item in os.environ.get(name, default).split(","):
        item = item.strip()
        if item.lstrip("-").isdigit():
            values.add(int(item))
    return values


@dataclass(frozen=True)
class Settings:
    token: str
    bot_name: str
    default_currency: str
    webapp_base_url: str
    host: str
    web_port: int
    uyu_to_ars: int
    log_file: Path
    users_file: Path
    purchases_file: Path
    mp_link_ar: str
    mp_link_uy: str
    run_telegram_bot: bool
    start_telegram_with_web: bool
    ticket_price_uyu: int
    demo_spins: int
    admin_ids: set[int]
    log_level: str
    max_purchase_qty: int
    max_content_length: int
    admin_api_key: str
    app_secret_key: str


SETTINGS = Settings(
    token=_env_str("TELEGRAM_BOT_TOKEN"),
    bot_name=_env_str("BOT_NAME", "Ruleta Pro"),
    default_currency=normalize_currency(_env_str("DEFAULT_CURRENCY", "UYU").upper(), "UYU"),
    webapp_base_url=_env_str("WEBAPP_BASE_URL", "https://ruleta-jeny-2.onrender.com").rstrip("/"),
    host=_env_str("HOST", "0.0.0.0"),
    web_port=_env_int("PORT", 8080, minimum=1, maximum=65535),
    uyu_to_ars=_env_int("UYU_TO_ARS", 25, minimum=1),
    log_file=Path(_env_str("LOG_FILE", "spins_log.json")),
    users_file=Path(_env_str("USERS_FILE", "users_data.json")),
    purchases_file=Path(_env_str("PURCHASES_FILE", "pending_purchases.json")),
    mp_link_ar=_env_str("MP_LINK_AR", "https://mpago.la/1vUBfHc"),
    mp_link_uy=_env_str("MP_LINK_UY", "https://mpago.la/1Zgex99"),
    run_telegram_bot=_env_bool("RUN_TELEGRAM_BOT", False),
    start_telegram_with_web=_env_bool("START_TELEGRAM_WITH_WEB", False),
    ticket_price_uyu=_env_int("TICKET_PRICE_UYU", 250, minimum=1),
    demo_spins=_env_int("DEMO_SPINS", 1, minimum=0),
    admin_ids=_env_admin_ids("ADMIN_IDS", "8445311801"),
    log_level=_env_str("LOG_LEVEL", "INFO").upper(),
    max_purchase_qty=_env_int("MAX_PURCHASE_QTY", 100, minimum=1),
    max_content_length=_env_int("MAX_CONTENT_LENGTH", 1024 * 1024, minimum=1024),
    admin_api_key=_env_str("ADMIN_API_KEY"),
    app_secret_key=_env_str("APP_SECRET_KEY", "ruleta-pro-secret"),
)


logging.basicConfig(
    level=getattr(logging, SETTINGS.log_level, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(SETTINGS.bot_name)

_OPERATION_LOCK = threading.RLock()
_BOT_THREAD_STARTED = False


def _normalize_mode(value: str | None, fallback: str = "auto") -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "": fallback,
        "auto": "auto",
        "demo": "demo",
        "preview": "demo",
        "gratis": "demo",
        "free": "demo",
        "ticket": "ticket",
        "paid": "ticket",
        "real": "ticket",
        "paga": "ticket",
    }
    normalized = aliases.get(raw, fallback)
    return normalized if normalized in VALID_MODES else fallback


def _mode_label(mode: str) -> str:
    return DEMO_MODE_LABEL if mode == "demo" else REAL_MODE_LABEL


def _weight_key_for_mode(mode: str) -> str:
    return "demo_weight" if mode == "demo" else "weight"


def _validate_prizes(prizes: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    normalized: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    total_weight = 0
    total_demo_weight = 0
    total_chance = 0.0

    for item in prizes:
        if not isinstance(item, dict):
            raise ValueError("Todos los premios deben ser diccionarios")

        name = sanitize_name(str(item.get("name", "")))[:120]
        weight = int(item.get("weight", 0))
        demo_weight = int(item.get("demo_weight", item.get("weight", 0)))
        chance = round(float(item.get("chance", 0.0)), 4)
        uyu_price = int(item.get("uyu_price", 0))

        if not name or name in seen_names:
            raise ValueError("La lista de premios contiene nombres vacíos o repetidos")
        if weight <= 0:
            raise ValueError(f"Peso real inválido para {name}")
        if demo_weight <= 0:
            raise ValueError(f"Peso demo inválido para {name}")
        if chance <= 0 or chance > 100:
            raise ValueError(f"Chance inválida para {name}")
        if uyu_price < 0:
            raise ValueError(f"Precio inválido para {name}")

        normalized.append(
            {
                "name": name,
                "chance": chance,
                "uyu_price": uyu_price,
                "weight": weight,
                "demo_weight": demo_weight,
            }
        )
        seen_names.add(name)
        total_weight += weight
        total_demo_weight += demo_weight
        total_chance += chance

    if not normalized:
        raise ValueError("Debe existir al menos un premio")
    if total_weight <= 0:
        raise ValueError("La suma de pesos reales debe ser mayor a cero")
    if total_demo_weight <= 0:
        raise ValueError("La suma de pesos demo debe ser mayor a cero")
    if total_chance > 100.5:
        raise ValueError("La suma de chances reales no puede superar 100.5")

    return tuple(normalized)


PRIZES = _validate_prizes(DEFAULT_PRIZES)


def _ensure_storage() -> None:
    ensure_json_file(SETTINGS.users_file, {})
    ensure_json_file(SETTINGS.log_file, [])
    ensure_json_file(SETTINGS.purchases_file, [])


def _now() -> str:
    return now_iso()


def _currency_code(value: str | None) -> str:
    return normalize_currency(value, SETTINGS.default_currency)


def _country_code(value: str | None = None, currency: str | None = None) -> str:
    raw = str(value or "").strip().upper()
    if raw in {"AR", "UY"}:
        return raw
    return "AR" if _currency_code(currency) == "ARS" else "UY"


def _sanitize_display_name(value: str | None) -> str:
    return sanitize_name(value)


def _full_name(first_name: str | None = None, last_name: str | None = None, username: str | None = None) -> str:
    parts = [str(first_name or "").strip(), str(last_name or "").strip()]
    full_name = " ".join(part for part in parts if part).strip()
    if full_name:
        return full_name[:120]
    if username:
        return str(username).strip()[:120]
    return "Jugador"


def _display_name(first_name: str | None = None, username: str | None = None, full_name: str | None = None) -> str:
    return _sanitize_display_name(first_name or full_name or username or "Jugador")


def _numeric_price_from_uyu(amount_uyu: int, currency: str) -> int:
    amount = max(int(amount_uyu), 0)
    currency_code = _currency_code(currency)
    return amount * SETTINGS.uyu_to_ars if currency_code == "ARS" else amount


def _money_label_from_uyu(amount_uyu: int, currency: str) -> str:
    return convert_price_from_uyu(amount_uyu, currency, SETTINGS.uyu_to_ars, SETTINGS.default_currency)


def _ticket_price_label(currency: str) -> str:
    return ticket_price_text(currency, SETTINGS.ticket_price_uyu, SETTINGS.uyu_to_ars, SETTINGS.default_currency)


def _display_chances_for_mode(mode: str) -> dict[str, float]:
    resolved_mode = "demo" if mode == "demo" else "ticket"
    key = _weight_key_for_mode(resolved_mode)
    total = sum(int(prize[key]) for prize in PRIZES if int(prize.get(key, 0)) > 0)

    if total <= 0:
        return {prize["name"]: 0.0 for prize in PRIZES}

    chance_map: dict[str, float] = {}
    for prize in PRIZES:
        chance_map[prize["name"]] = round((int(prize[key]) / total) * 100, 2)
    return chance_map


def _prizes_payload(currency: str, mode: str = "ticket") -> list[dict[str, Any]]:
    currency_code = _currency_code(currency)
    resolved_mode = "demo" if mode == "demo" else "ticket"
    display_chances = _display_chances_for_mode(resolved_mode)

    return [
        {
            "name": prize["name"],
            "chance": display_chances[prize["name"]],
            "display_chance": display_chances[prize["name"]],
            "real_chance": prize["chance"],
            "weight": prize["weight"],
            "demo_weight": prize["demo_weight"],
            "uyu_price": prize["uyu_price"],
            "price_value": _numeric_price_from_uyu(prize["uyu_price"], currency_code),
            "price_label": _money_label_from_uyu(prize["uyu_price"], currency_code),
            "currency": currency_code,
            "mode": resolved_mode,
        }
        for prize in PRIZES
    ]


def _prizes_text(currency: str, mode: str = "ticket") -> str:
    display_chances = _display_chances_for_mode(mode)
    display_prizes = [
        {
            "name": prize["name"],
            "chance": display_chances[prize["name"]],
            "uyu_price": prize["uyu_price"],
            "weight": prize["weight"] if mode != "demo" else prize["demo_weight"],
        }
        for prize in PRIZES
    ]
    return format_prize_list(display_prizes, _currency_code(currency), SETTINGS.uyu_to_ars, SETTINGS.default_currency)


def _load_users_data() -> dict[str, Any]:
    data = load_users(SETTINGS.users_file)
    return data if isinstance(data, dict) else {}


def _load_logs_data() -> list[dict[str, Any]]:
    data = load_logs(SETTINGS.log_file)
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _load_purchases_data() -> list[dict[str, Any]]:
    data = load_purchases(SETTINGS.purchases_file)
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _count_user_spins(user_key: str) -> int:
    return sum(1 for item in _load_logs_data() if item.get("user_key") == user_key)


def _sync_user_profile(
    user_id: int,
    username: str = "",
    first_name: str = "",
    last_name: str = "",
    language_code: str = "",
    currency: str | None = None,
    display_name: str | None = None,
    full_name: str | None = None,
) -> tuple[str, dict[str, Any]]:
    resolved_full_name = _full_name(first_name, last_name, username) if not full_name else str(full_name).strip()[:120]
    resolved_display_name = _display_name(first_name, username, resolved_full_name) if not display_name else _sanitize_display_name(display_name)
    resolved_currency = _currency_code(currency or get_currency_from_language(language_code, SETTINGS.default_currency))

    ensure_user_profile(
        user_id,
        username,
        resolved_full_name,
        resolved_currency,
        resolved_display_name,
        SETTINGS.users_file,
        SETTINGS.demo_spins,
        SETTINGS.default_currency,
    )

    key, profile = get_user_profile(
        user_id,
        username,
        resolved_full_name,
        SETTINGS.users_file,
        SETTINGS.default_currency,
        SETTINGS.demo_spins,
    )

    profile["currency"] = resolved_currency
    if resolved_display_name:
        profile["display_name"] = resolved_display_name
    profile["updated_at"] = _now()
    profile["last_seen_at"] = _now()
    update_user_profile(key, profile, SETTINGS.users_file)

    key, profile = get_user_profile(
        user_id,
        username,
        resolved_full_name,
        SETTINGS.users_file,
        SETTINGS.default_currency,
        SETTINGS.demo_spins,
    )

    return key, profile


def _get_profile_by_user_id(user_id: int) -> tuple[str, dict[str, Any]]:
    users = _load_users_data()
    key = str(user_id)
    profile = users.get(key)
    if isinstance(profile, dict):
        return key, profile
    return _sync_user_profile(user_id=user_id)


def _save_profile(key: str, profile: dict[str, Any]) -> dict[str, Any]:
    profile["updated_at"] = _now()
    profile["last_seen_at"] = _now()
    update_user_profile(key, profile, SETTINGS.users_file)
    users = _load_users_data()
    saved = users.get(key)
    return saved if isinstance(saved, dict) else profile


def _public_user_view(key: str, profile: dict[str, Any]) -> dict[str, Any]:
    currency = _currency_code(profile.get("currency", SETTINGS.default_currency))
    return {
        "user_key": key,
        "user_id": profile.get("user_id"),
        "username": profile.get("username", ""),
        "full_name": profile.get("full_name", ""),
        "display_name": profile.get("display_name", "Jugador"),
        "currency": currency,
        "fichas": int(profile.get("fichas", 0)),
        "demo_spins_left": int(profile.get("demo_spins_left", SETTINGS.demo_spins)),
        "wins": int(profile.get("wins", 0)),
        "last_prize": profile.get("last_prize", ""),
        "spins_total": _count_user_spins(key),
        "created_at": profile.get("created_at", ""),
        "updated_at": profile.get("updated_at", ""),
        "last_seen_at": profile.get("last_seen_at", ""),
    }


def _purchase_payment_link(country: str) -> str:
    return get_country_link(country, SETTINGS.mp_link_ar, SETTINGS.mp_link_uy)


def _purchase_view(purchase: dict[str, Any]) -> dict[str, Any]:
    currency = _currency_code(purchase.get("currency", SETTINGS.default_currency))
    country = _country_code(purchase.get("country"), currency)
    qty = max(int(purchase.get("qty", 1)), 1)
    return {
        "purchase_id": purchase.get("purchase_id", ""),
        "id": purchase.get("purchase_id", ""),
        "user_key": purchase.get("user_key", ""),
        "user_id": purchase.get("user_id"),
        "username": purchase.get("username", ""),
        "full_name": purchase.get("full_name", ""),
        "display_name": purchase.get("display_name", "Jugador"),
        "country": country,
        "currency": currency,
        "qty": qty,
        "status": purchase.get("status", "pending"),
        "payment_link": _purchase_payment_link(country),
        "ticket_price_each": _ticket_price_label(currency),
        "ticket_price_total_value": _numeric_price_from_uyu(SETTINGS.ticket_price_uyu * qty, currency),
        "ticket_price_total_label": _money_label_from_uyu(SETTINGS.ticket_price_uyu * qty, currency),
        "created_at": purchase.get("created_at", ""),
        "approved_at": purchase.get("approved_at", ""),
        "approved_by": purchase.get("approved_by", ""),
    }


def _create_purchase(
    user_id: int,
    username: str = "",
    first_name: str = "",
    last_name: str = "",
    language_code: str = "",
    currency: str | None = None,
    country: str | None = None,
    qty: int = 1,
    display_name: str | None = None,
    full_name: str | None = None,
) -> dict[str, Any]:
    resolved_currency = _currency_code(currency or get_currency_from_language(language_code, SETTINGS.default_currency))
    resolved_country = _country_code(country, resolved_currency)
    resolved_full_name = _full_name(first_name, last_name, username) if not full_name else str(full_name).strip()[:120]
    resolved_display_name = _display_name(first_name, username, resolved_full_name) if not display_name else _sanitize_display_name(display_name)

    _sync_user_profile(
        user_id=user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        language_code=language_code,
        currency=resolved_currency,
        display_name=resolved_display_name,
        full_name=resolved_full_name,
    )

    purchase = create_pending_purchase(
        user_id,
        username,
        resolved_full_name,
        resolved_display_name,
        resolved_country,
        resolved_currency,
        max(1, min(int(qty), SETTINGS.max_purchase_qty)),
        SETTINGS.purchases_file,
        SETTINGS.default_currency,
    )

    return _purchase_view(purchase)


def _approve_purchase(purchase_id: str, admin_id: int) -> dict[str, Any] | None:
    with _OPERATION_LOCK:
        approved = approve_purchase_by_id(
            purchase_id,
            admin_id,
            SETTINGS.purchases_file,
            SETTINGS.users_file,
        )
        if not isinstance(approved, dict):
            return None
        return _purchase_view(approved)


def _pick_weighted_prize(mode: str = "ticket") -> dict[str, Any]:
    resolved_mode = "demo" if mode == "demo" else "ticket"
    weight_key = _weight_key_for_mode(resolved_mode)
    valid_prizes = [dict(prize) for prize in PRIZES if int(prize.get(weight_key, 0)) > 0]

    if not valid_prizes:
        raise ValueError(f"No hay premios disponibles para el modo {resolved_mode}")

    weights = [int(prize[weight_key]) for prize in valid_prizes]
    selected = random.choices(valid_prizes, weights=weights, k=1)[0]
    selected["selected_mode"] = resolved_mode
    return selected


def _serialize_prize_view(prize: dict[str, Any], currency: str, spin_mode: str) -> dict[str, Any]:
    current_currency = _currency_code(currency)
    display_chances = _display_chances_for_mode(spin_mode)
    return {
        "name": prize["name"],
        "prize": prize["name"],
        "chance": display_chances[prize["name"]],
        "real_chance": prize["chance"],
        "uyu_price": int(prize["uyu_price"]),
        "price_value": _numeric_price_from_uyu(int(prize["uyu_price"]), current_currency),
        "price_label": _money_label_from_uyu(int(prize["uyu_price"]), current_currency),
        "label": _money_label_from_uyu(int(prize["uyu_price"]), current_currency),
        "currency": current_currency,
        "source": spin_mode,
        "mode_label": _mode_label(spin_mode),
        "demo_preview": spin_mode == "demo",
    }


def _spin_for_user(
    user_id: int,
    username: str = "",
    first_name: str = "",
    last_name: str = "",
    language_code: str = "",
    currency: str | None = None,
    display_name: str | None = None,
    full_name: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    with _OPERATION_LOCK:
        key, profile = _sync_user_profile(
            user_id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language_code=language_code,
            currency=currency,
            display_name=display_name,
            full_name=full_name,
        )

        current_currency = _currency_code(currency or profile.get("currency", SETTINGS.default_currency))
        profile["currency"] = current_currency

        fichas = max(int(profile.get("fichas", 0)), 0)
        demo_spins_left = max(int(profile.get("demo_spins_left", SETTINGS.demo_spins)), 0)
        requested_mode = _normalize_mode(mode, fallback="auto")

        if requested_mode == "demo":
            if demo_spins_left <= 0:
                raise ValueError("Sin tiradas demo disponibles")
            profile["demo_spins_left"] = demo_spins_left - 1
            spin_mode = "demo"
        elif requested_mode == "ticket":
            if fichas <= 0:
                raise ValueError("Sin fichas disponibles")
            profile["fichas"] = fichas - 1
            spin_mode = "ticket"
        else:
            if fichas > 0:
                profile["fichas"] = fichas - 1
                spin_mode = "ticket"
            elif demo_spins_left > 0:
                profile["demo_spins_left"] = demo_spins_left - 1
                spin_mode = "demo"
            else:
                raise ValueError("Sin fichas disponibles ni demos disponibles")

        prize = _pick_weighted_prize(spin_mode)
        profile["wins"] = max(int(profile.get("wins", 0)), 0) + 1
        profile["last_prize"] = prize["name"]
        saved_profile = _save_profile(key, profile)
        user_view = _public_user_view(key, saved_profile)

        resolved_full_name = _full_name(first_name, last_name, username) if not full_name else full_name
        resolved_display_name = display_name or _display_name(first_name, username, full_name)

        log_spin(
            user_id=user_id,
            username=username,
            full_name=resolved_full_name,
            display_name=resolved_display_name,
            prize_name=prize["name"],
            currency=current_currency,
            spin_mode=spin_mode,
            log_file=SETTINGS.log_file,
        )

        prize_view = _serialize_prize_view(prize, current_currency, spin_mode)

        return {
            "result": {
                "prize": prize_view["name"],
                "name": prize_view["name"],
                "chance": prize_view["chance"],
                "real_chance": prize_view["real_chance"],
                "price_value": prize_view["price_value"],
                "price_label": prize_view["price_label"],
                "label": prize_view["label"],
                "currency": current_currency,
                "source": spin_mode,
                "mode_label": prize_view["mode_label"],
                "demo_preview": prize_view["demo_preview"],
            },
            "prize": prize_view,
            "user": user_view,
            "profile": user_view,
            "spin": {
                "requested_mode": requested_mode,
                "served_mode": spin_mode,
                "served_mode_label": _mode_label(spin_mode),
                "transparent_demo": spin_mode == "demo",
                "notice": DEMO_MODE_NOTICE if spin_mode == "demo" else "",
            },
        }


def _build_webapp(
    user_id: int,
    username: str = "",
    first_name: str = "",
    last_name: str = "",
    language_code: str = "",
    currency: str | None = None,
    full_name: str | None = None,
) -> str:
    resolved_full_name = _full_name(first_name, last_name, username) if not full_name else str(full_name).strip()
    user = SimpleNamespace(
        id=user_id,
        username=username or "",
        full_name=resolved_full_name,
        language_code=language_code or "es",
    )
    base_url = build_webapp_url(user, SETTINGS.webapp_base_url, _currency_code(currency or SETTINGS.default_currency))
    forced_currency = _currency_code(currency or SETTINGS.default_currency)

    prefix = base_url.split("?", 1)[0]
    params = {
        "user_id": user_id,
        "username": username or "",
        "full_name": resolved_full_name,
        "currency": forced_currency,
    }
    return f"{prefix}?{urlencode(params)}"


def _admin_request_allowed() -> bool:
    header_key = request.headers.get("X-Admin-Key", "").strip()
    if SETTINGS.admin_api_key and header_key == SETTINGS.admin_api_key:
        return True

    admin_id_raw = str(request.headers.get("X-Admin-Id", "")).strip()
    if admin_id_raw.isdigit() and is_admin(int(admin_id_raw), SETTINGS.admin_ids):
        return True

    return False


def _parse_int(value: Any, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None and result < minimum:
        result = minimum
    if maximum is not None and result > maximum:
        result = maximum
    return result


def _json_ok(payload: dict[str, Any], status: int = 200) -> Any:
    return jsonify({"ok": True, **payload}), status


def _json_error(message: str, status: int = 400) -> Any:
    return jsonify({"ok": False, "error": message}), status


def _template_context(
    currency: str,
    user_id: str | int | None = "",
    username: str = "",
    full_name: str = "",
    display_name: str = "Jugador",
    fichas: int = 0,
    demo_spins_left: int = 0,
    preview_mode: str = "ticket",
) -> dict[str, Any]:
    resolved_preview_mode = "demo" if preview_mode == "demo" else "ticket"
    return {
        "bot_name": SETTINGS.bot_name,
        "currency": _currency_code(currency),
        "default_currency": SETTINGS.default_currency,
        "ticket_price": _ticket_price_label(currency),
        "prizes": _prizes_payload(currency, resolved_preview_mode),
        "user_id": user_id,
        "username": username,
        "full_name": full_name,
        "display_name": display_name,
        "fichas": fichas,
        "demo_spins_left": demo_spins_left,
        "uyu_to_ars": SETTINGS.uyu_to_ars,
        "ticket_price_uyu": SETTINGS.ticket_price_uyu,
        "mp_link_ar": SETTINGS.mp_link_ar,
        "mp_link_uy": SETTINGS.mp_link_uy,
        "preview_mode": resolved_preview_mode,
        "preview_label": _mode_label(resolved_preview_mode),
        "preview_notice": DEMO_MODE_NOTICE if resolved_preview_mode == "demo" else "",
    }


def _inline_home_html(context: dict[str, Any]) -> str:
    return render_template_string(
        """
        <!doctype html>
        <html lang="es">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width,initial-scale=1">
          <title>{{ bot_name }}</title>
          <style>
            :root { color-scheme: dark; }
            * { box-sizing: border-box; }
            body {
              margin: 0;
              font-family: Arial, Helvetica, sans-serif;
              background: radial-gradient(circle at top, #2a1b59 0%, #120b28 45%, #090611 100%);
              color: #fff;
              min-height: 100vh;
              display: grid;
              place-items: center;
              padding: 24px;
            }
            .wrap {
              width: min(980px, 100%);
              background: rgba(255,255,255,.08);
              backdrop-filter: blur(18px);
              border: 1px solid rgba(255,255,255,.12);
              border-radius: 28px;
              padding: 32px;
              box-shadow: 0 20px 70px rgba(0,0,0,.35);
            }
            .row {
              display: flex;
              flex-wrap: wrap;
              gap: 10px;
              margin-bottom: 18px;
            }
            .badge {
              display: inline-block;
              padding: 8px 14px;
              border-radius: 999px;
              background: rgba(255,255,255,.12);
              font-size: 13px;
            }
            .badge-demo {
              background: rgba(255, 214, 10, 0.18);
              border: 1px solid rgba(255, 214, 10, 0.28);
            }
            h1 {
              margin: 0 0 10px;
              font-size: 42px;
              line-height: 1.05;
            }
            p {
              margin: 0 0 22px;
              color: rgba(255,255,255,.82);
              font-size: 18px;
            }
            .notice {
              margin-top: -8px;
              margin-bottom: 22px;
              font-size: 14px;
              color: rgba(255,255,255,.72);
            }
            .grid {
              display: grid;
              grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
              gap: 16px;
              margin-top: 24px;
            }
            .card {
              background: rgba(255,255,255,.08);
              border: 1px solid rgba(255,255,255,.10);
              border-radius: 20px;
              padding: 18px;
            }
            .small {
              font-size: 13px;
              color: rgba(255,255,255,.65);
              margin-bottom: 8px;
            }
            .big {
              font-size: 20px;
              font-weight: 700;
            }
            ul {
              margin: 18px 0 0;
              padding-left: 20px;
              color: rgba(255,255,255,.9);
            }
            li { margin-bottom: 8px; }
          </style>
        </head>
        <body>
          <main class="wrap">
            <div class="row">
              <span class="badge">Ruleta premium</span>
              <span class="badge {% if preview_mode == 'demo' %}badge-demo{% endif %}">{{ preview_label }}</span>
            </div>
            <h1>{{ bot_name }}</h1>
            <p>Valor por ficha: {{ ticket_price }}</p>
            {% if preview_notice %}
            <div class="notice">{{ preview_notice }}</div>
            {% endif %}
            <div class="grid">
              {% for prize in prizes[:4] %}
              <section class="card">
                <div class="small">{{ prize.display_chance }}%</div>
                <div class="big">{{ prize.name }}</div>
                <div class="small">{{ prize.price_label }}</div>
              </section>
              {% endfor %}
            </div>
            <ul>
              <li>API de premios: <strong>/api/prizes</strong></li>
              <li>API de configuración: <strong>/api/config</strong></li>
              <li>WebApp: <strong>/wheel</strong></li>
            </ul>
          </main>
        </body>
        </html>
        """,
        **context,
    )


def create_flask_app() -> Flask:
    _ensure_storage()
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["MAX_CONTENT_LENGTH"] = SETTINGS.max_content_length
    app.secret_key = SETTINGS.app_secret_key

    @app.after_request
    def add_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(404)
    def not_found(_: Exception) -> Any:
        return _json_error("Ruta no encontrada", 404)

    @app.errorhandler(405)
    def method_not_allowed(_: Exception) -> Any:
        return _json_error("Método no permitido", 405)

    @app.errorhandler(413)
    def payload_too_large(_: Exception) -> Any:
        return _json_error("Payload demasiado grande", 413)

    @app.errorhandler(Exception)
    def internal_error(error: Exception) -> Any:
        logger.exception("Error no controlado: %s", error)
        return _json_error("Error interno del servidor", 500)

    @app.get("/")
    @app.get("/wheel")
    def home() -> Any:
        request_user_id = request.args.get("user_id", "").strip()
        request_username = request.args.get("username", "").strip()
        request_full_name = request.args.get("full_name", "").strip()
        request_display_name = request.args.get("display_name", "").strip()
        request_currency = _currency_code(request.args.get("currency", SETTINGS.default_currency))
        request_mode = request.args.get("mode", "").strip()
        request_demo = request.args.get("demo", "").strip()

        preview_mode = "demo" if request_demo == "1" else _normalize_mode(request_mode, fallback="ticket")
        if preview_mode == "auto":
            preview_mode = "ticket"

        context = _template_context(
            currency=request_currency,
            user_id="",
            username=request_username,
            full_name=request_full_name,
            display_name=request_display_name or "Jugador",
            fichas=0,
            demo_spins_left=SETTINGS.demo_spins,
            preview_mode=preview_mode,
        )

        if request_user_id.isdigit():
            user_id = int(request_user_id)
            first_name = request_display_name or (request_full_name.split(" ")[0] if request_full_name else "")
            last_name = ""
            if request_full_name and " " in request_full_name:
                parts = request_full_name.split(" ", 1)
                first_name = parts[0]
                last_name = parts[1]

            key, profile = _sync_user_profile(
                user_id=user_id,
                username=request_username,
                first_name=first_name,
                last_name=last_name,
                language_code="es",
                currency=request_currency,
                display_name=request_display_name or None,
                full_name=request_full_name or None,
            )
            user_view = _public_user_view(key, profile)
            context = _template_context(
                currency=user_view["currency"],
                user_id=user_view["user_id"],
                username=user_view["username"],
                full_name=user_view["full_name"],
                display_name=user_view["display_name"],
                fichas=user_view["fichas"],
                demo_spins_left=user_view["demo_spins_left"],
                preview_mode=preview_mode,
            )

        try:
            return make_response(render_template("wheel.html", **context))
        except TemplateNotFound:
            return make_response(_inline_home_html(context))
        except Exception:
            logger.exception("Fallo renderizando wheel.html")
            return make_response(_inline_home_html(context))

    @app.get("/health")
    def health() -> Any:
        return _json_ok(
            {
                "bot_name": SETTINGS.bot_name,
                "default_currency": SETTINGS.default_currency,
                "telegram_enabled": SETTINGS.run_telegram_bot,
                "storage": {
                    "users_file": str(SETTINGS.users_file),
                    "log_file": str(SETTINGS.log_file),
                    "purchases_file": str(SETTINGS.purchases_file),
                },
                "totals": {
                    "prizes": len(PRIZES),
                    "users": len(_load_users_data()),
                    "purchases": len(_load_purchases_data()),
                    "logs": len(_load_logs_data()),
                },
            }
        )

    @app.get("/api/config")
    def api_config() -> Any:
        currency = _currency_code(request.args.get("currency", SETTINGS.default_currency))
        country = _country_code(request.args.get("country"), currency)
        mode = _normalize_mode(request.args.get("mode", ""), fallback="ticket")
        if mode == "auto":
            mode = "ticket"

        return _json_ok(
            {
                "bot_name": SETTINGS.bot_name,
                "currency": currency,
                "country": country,
                "ticket_price": {
                    "value": _numeric_price_from_uyu(SETTINGS.ticket_price_uyu, currency),
                    "label": _ticket_price_label(currency),
                    "uyu": SETTINGS.ticket_price_uyu,
                },
                "payment_link": _purchase_payment_link(country),
                "demo_spins": SETTINGS.demo_spins,
                "webapp_base_url": SETTINGS.webapp_base_url,
                "preview": {
                    "mode": mode,
                    "label": _mode_label(mode),
                    "transparent_demo": mode == "demo",
                    "notice": DEMO_MODE_NOTICE if mode == "demo" else "",
                },
            }
        )

    @app.get("/api/prizes")
    def api_prizes() -> Any:
        currency = _currency_code(request.args.get("currency", SETTINGS.default_currency))
        mode = _normalize_mode(request.args.get("mode", ""), fallback="ticket")
        if mode == "auto":
            mode = "ticket"

        return _json_ok(
            {
                "currency": currency,
                "mode": mode,
                "mode_label": _mode_label(mode),
                "transparent_demo": mode == "demo",
                "notice": DEMO_MODE_NOTICE if mode == "demo" else "",
                "items": _prizes_payload(currency, mode),
                "text": _prizes_text(currency, mode),
            }
        )

    @app.get("/api/user/<int:user_id>")
    def api_user(user_id: int) -> Any:
        key, profile = _get_profile_by_user_id(user_id)
        user_view = _public_user_view(key, profile)
        return _json_ok({"user": user_view, "profile": user_view})

    @app.post("/api/user/sync")
    @app.post("/api/profile-sync")
    @app.post("/api/profile")
    def api_user_sync() -> Any:
        payload = request.get_json(silent=True) or {}
        user_id = _parse_int(payload.get("user_id"), minimum=1)
        if user_id <= 0:
            return _json_error("user_id inválido", 400)

        full_name = str(payload.get("full_name", "")).strip()
        first_name = str(payload.get("first_name", "")).strip()
        last_name = str(payload.get("last_name", "")).strip()

        if full_name and not first_name:
            if " " in full_name:
                first_name, last_name = full_name.split(" ", 1)
            else:
                first_name = full_name

        key, profile = _sync_user_profile(
            user_id=user_id,
            username=str(payload.get("username", "")).strip(),
            first_name=first_name,
            last_name=last_name,
            language_code=str(payload.get("language_code", "es")).strip(),
            currency=str(payload.get("currency", SETTINGS.default_currency)).strip(),
            display_name=str(payload.get("display_name", "")).strip() or None,
            full_name=full_name or None,
        )
        user_view = _public_user_view(key, profile)
        return _json_ok({"user": user_view, "profile": user_view})

    @app.post("/api/purchase")
    @app.post("/api/create-pending-purchase")
    def api_purchase() -> Any:
        payload = request.get_json(silent=True) or {}
        user_id = _parse_int(payload.get("user_id"), minimum=1)
        if user_id <= 0:
            return _json_error("user_id inválido", 400)

        full_name = str(payload.get("full_name", "")).strip()
        first_name = str(payload.get("first_name", "")).strip()
        last_name = str(payload.get("last_name", "")).strip()

        if full_name and not first_name:
            if " " in full_name:
                first_name, last_name = full_name.split(" ", 1)
            else:
                first_name = full_name

        purchase = _create_purchase(
            user_id=user_id,
            username=str(payload.get("username", "")).strip(),
            first_name=first_name,
            last_name=last_name,
            language_code=str(payload.get("language_code", "es")).strip(),
            currency=str(payload.get("currency", SETTINGS.default_currency)).strip(),
            country=str(payload.get("country", "")).strip(),
            qty=_parse_int(payload.get("qty"), default=1, minimum=1, maximum=SETTINGS.max_purchase_qty),
            display_name=str(payload.get("display_name", "")).strip() or None,
            full_name=full_name or None,
        )
        return _json_ok(
            {
                "purchase": purchase,
                "purchase_id": purchase["purchase_id"],
                "payment_link": purchase["payment_link"],
            }
        )

    @app.post("/api/purchase/approve")
    def api_purchase_approve() -> Any:
        payload = request.get_json(silent=True) or {}
        purchase_id = str(payload.get("purchase_id", "")).strip()
        admin_id = _parse_int(payload.get("admin_id"), default=0)

        if not purchase_id:
            return _json_error("purchase_id requerido", 400)
        if not (_admin_request_allowed() or is_admin(admin_id, SETTINGS.admin_ids)):
            return _json_error("No autorizado", 403)

        approved = _approve_purchase(purchase_id, admin_id)
        if not approved:
            return _json_error("Compra no encontrada o ya aprobada", 404)

        user_key = str(approved.get("user_key", ""))
        users = _load_users_data()
        profile = users.get(user_key) if user_key else None
        user_view = _public_user_view(user_key, profile) if isinstance(profile, dict) else None

        return _json_ok({"purchase": approved, "user": user_view, "profile": user_view})

    @app.get("/api/admin/purchases")
    def api_admin_purchases() -> Any:
        if not _admin_request_allowed():
            return _json_error("No autorizado", 403)

        status_filter = str(request.args.get("status", "")).strip().lower()
        limit = _parse_int(request.args.get("limit"), default=50, minimum=1, maximum=500)
        items: list[dict[str, Any]] = []

        for purchase in reversed(_load_purchases_data()):
            status = str(purchase.get("status", "")).strip().lower()
            if status_filter and status != status_filter:
                continue
            items.append(_purchase_view(purchase))
            if len(items) >= limit:
                break

        return _json_ok({"count": len(items), "items": items})

    @app.get("/api/admin/stats")
    def api_admin_stats() -> Any:
        if not _admin_request_allowed():
            return _json_error("No autorizado", 403)

        users = _load_users_data()
        purchases = _load_purchases_data()
        logs = _load_logs_data()

        pending = sum(1 for purchase in purchases if purchase.get("status") == "pending")
        approved = sum(1 for purchase in purchases if purchase.get("status") == "approved")
        fichas_total = sum(int(profile.get("fichas", 0)) for profile in users.values() if isinstance(profile, dict))
        wins_total = sum(int(profile.get("wins", 0)) for profile in users.values() if isinstance(profile, dict))
        demo_spins_total = sum(int(profile.get("demo_spins_left", 0)) for profile in users.values() if isinstance(profile, dict))

        return _json_ok(
            {
                "stats": {
                    "users_total": len(users),
                    "purchases_total": len(purchases),
                    "purchases_pending": pending,
                    "purchases_approved": approved,
                    "spins_total": len(logs),
                    "wins_total": wins_total,
                    "fichas_total": fichas_total,
                    "demo_spins_total": demo_spins_total,
                }
            }
        )

    @app.post("/api/spin")
    def api_spin() -> Any:
        payload = request.get_json(silent=True) or {}
        user_id = _parse_int(payload.get("user_id"), minimum=1)
        if user_id <= 0:
            return _json_error("user_id inválido", 400)

        full_name = str(payload.get("full_name", "")).strip()
        first_name = str(payload.get("first_name", "")).strip()
        last_name = str(payload.get("last_name", "")).strip()

        if full_name and not first_name:
            if " " in full_name:
                first_name, last_name = full_name.split(" ", 1)
            else:
                first_name = full_name

        try:
            result = _spin_for_user(
                user_id=user_id,
                username=str(payload.get("username", "")).strip(),
                first_name=first_name,
                last_name=last_name,
                language_code=str(payload.get("language_code", "es")).strip(),
                currency=str(payload.get("currency", SETTINGS.default_currency)).strip(),
                display_name=str(payload.get("display_name", "")).strip() or None,
                full_name=full_name or None,
                mode=str(payload.get("mode", "")).strip(),
            )
            return _json_ok(result)
        except ValueError as error:
            return _json_error(str(error), 402)

    return app


def _telegram_keyboard(webapp_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Abrir ruleta", web_app=WebAppInfo(url=webapp_url))],
            [InlineKeyboardButton("Comprar ficha", callback_data="buy_ticket")],
            [InlineKeyboardButton("Mi saldo", callback_data="my_status")],
            [InlineKeyboardButton("Premios", callback_data="prize_list")],
        ]
    )


def _telegram_start_text(user_key: str, profile: dict[str, Any]) -> str:
    currency = _currency_code(profile.get("currency", SETTINGS.default_currency))
    return (
        f"Hola, {_sanitize_display_name(profile.get('display_name', 'Jugador'))}.\n"
        f"Moneda: {currency}\n"
        f"Fichas: {int(profile.get('fichas', 0))}\n"
        f"Demo: {int(profile.get('demo_spins_left', SETTINGS.demo_spins))}\n"
        f"Premios ganados: {int(profile.get('wins', 0))}\n"
        f"Giros realizados: {_count_user_spins(user_key)}\n"
        f"Valor por ficha: {_ticket_price_label(currency)}"
    )


def _telegram_balance_text(user_key: str, profile: dict[str, Any]) -> str:
    currency = _currency_code(profile.get("currency", SETTINGS.default_currency))
    return (
        f"Fichas: {int(profile.get('fichas', 0))}\n"
        f"Demo: {int(profile.get('demo_spins_left', SETTINGS.demo_spins))}\n"
        f"Premios ganados: {int(profile.get('wins', 0))}\n"
        f"Giros realizados: {_count_user_spins(user_key)}\n"
        f"Último premio: {profile.get('last_prize', '—') or '—'}\n"
        f"Valor por ficha: {_ticket_price_label(currency)}"
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    user_key, profile = _sync_user_profile(
        user_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        language_code=user.language_code or "es",
    )

    webapp_url = _build_webapp(
        user_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        language_code=user.language_code or "es",
        currency=profile.get("currency", SETTINGS.default_currency),
        full_name=profile.get("full_name", ""),
    )

    await message.reply_text(_telegram_start_text(user_key, profile), reply_markup=_telegram_keyboard(webapp_url))


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    user_key, profile = _get_profile_by_user_id(user.id)
    await message.reply_text(_telegram_balance_text(user_key, profile))


async def prizes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    _, profile = _get_profile_by_user_id(user.id)
    await message.reply_text(_prizes_text(profile.get("currency", SETTINGS.default_currency), mode="ticket"))


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    _, profile = _get_profile_by_user_id(user.id)
    purchase = _create_purchase(
        user_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        language_code=user.language_code or "es",
        currency=profile.get("currency", SETTINGS.default_currency),
        country="AR" if _currency_code(profile.get("currency")) == "ARS" else "UY",
        qty=1,
        display_name=profile.get("display_name", ""),
        full_name=profile.get("full_name", ""),
    )

    await message.reply_text(
        f"Valor: {purchase['ticket_price_each']}\n"
        f"Pago: {purchase['payment_link']}\n"
        f"Referencia: {purchase['purchase_id']}"
    )


async def web_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    _, profile = _get_profile_by_user_id(user.id)
    webapp_url = _build_webapp(
        user_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        language_code=user.language_code or "es",
        currency=profile.get("currency", SETTINGS.default_currency),
        full_name=profile.get("full_name", ""),
    )

    await message.reply_text(webapp_url)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None:
        return

    await query.answer()
    user = query.from_user
    user_key, profile = _get_profile_by_user_id(user.id)
    currency = _currency_code(profile.get("currency", SETTINGS.default_currency))

    if query.data == "buy_ticket":
        purchase = _create_purchase(
            user_id=user.id,
            username=user.username or "",
            first_name=user.first_name or "",
            last_name=user.last_name or "",
            language_code=user.language_code or "es",
            currency=currency,
            country="AR" if currency == "ARS" else "UY",
            qty=1,
            display_name=profile.get("display_name", ""),
            full_name=profile.get("full_name", ""),
        )
        if query.message:
            await query.message.reply_text(
                f"Valor: {purchase['ticket_price_each']}\n"
                f"Pago: {purchase['payment_link']}\n"
                f"Referencia: {purchase['purchase_id']}"
            )
        return

    if query.data == "my_status":
        if query.message:
            await query.message.reply_text(_telegram_balance_text(user_key, profile))
        return

    if query.data == "prize_list":
        if query.message:
            await query.message.reply_text(_prizes_text(currency, mode="ticket"))


def run_telegram_bot() -> None:
    if not SETTINGS.run_telegram_bot:
        logger.info("Bot de Telegram desactivado por configuración")
        return
    if not SETTINGS.token:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN y RUN_TELEGRAM_BOT está activo")

    application = ApplicationBuilder().token(SETTINGS.token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("saldo", balance_command))
    application.add_handler(CommandHandler("premios", prizes_command))
    application.add_handler(CommandHandler("comprar", buy_command))
    application.add_handler(CommandHandler("web", web_command))
    application.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Bot de Telegram iniciado")
    application.run_polling(drop_pending_updates=True, stop_signals=None)


def maybe_start_bot_thread() -> None:
    global _BOT_THREAD_STARTED

    if _BOT_THREAD_STARTED or not SETTINGS.run_telegram_bot or not SETTINGS.start_telegram_with_web:
        return

    with _OPERATION_LOCK:
        if _BOT_THREAD_STARTED:
            return
        bot_thread = threading.Thread(target=run_telegram_bot, name="telegram-bot", daemon=True)
        bot_thread.start()
        _BOT_THREAD_STARTED = True
        logger.info("Thread del bot de Telegram lanzado")


app = create_flask_app()
maybe_start_bot_thread()


def main() -> None:
    logger.info("Servidor web iniciado en %s:%s", SETTINGS.host, SETTINGS.web_port)
    if SETTINGS.run_telegram_bot and not SETTINGS.start_telegram_with_web:
        bot_thread = threading.Thread(target=run_telegram_bot, name="telegram-bot", daemon=True)
        bot_thread.start()
    app.run(host=SETTINGS.host, port=SETTINGS.web_port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()