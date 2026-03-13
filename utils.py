import copy
import json
import random
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ENCODING = "utf-8"
VALID_CURRENCIES = {"UYU", "ARS"}
VALID_COUNTRIES = {"AR", "UY"}
DEFAULT_DISPLAY_NAME = "Jugador"
MAX_DISPLAY_NAME_LENGTH = 40
MAX_USERNAME_LENGTH = 80
MAX_FULL_NAME_LENGTH = 120
MAX_PRIZE_NAME_LENGTH = 120
MAX_SPIN_MODE_LENGTH = 30
MAX_PURCHASE_ID_LENGTH = 120
MAX_STATUS_LENGTH = 20
MAX_LOG_ITEMS = 10000
PROFILE_VERSION = 3
_FILE_LOCK = threading.RLock()


def _clone_default(value: Any) -> Any:
    return copy.deepcopy(value)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\x00", " ").strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    return text.strip()


def _limit_text(value: Any, max_length: int | None = None, fallback: str = "") -> str:
    text = _clean_text(value)
    if not text:
        text = fallback
    if max_length is not None:
        text = text[:max_length].rstrip()
    return text


def _safe_int(
    value: Any,
    default: int = 0,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default

    if minimum is not None and number < minimum:
        number = minimum
    if maximum is not None and number > maximum:
        number = maximum
    return number


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_amount(amount: int) -> str:
    return f"{amount:,}".replace(",", ".")


def _format_percentage(value: Any) -> str:
    number = _safe_float(value, default=0.0)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    temp_path.write_text(content, encoding=ENCODING)
    temp_path.replace(path)


def _safe_slug(value: Any, fallback: str = "guest") -> str:
    text = _limit_text(value, max_length=80, fallback=fallback).lower()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^a-z0-9_áéíóúñü-]", "", text)
    text = text.strip("_-")
    return text or fallback


def _normalize_username(username: str | None) -> str:
    return _limit_text(username, max_length=MAX_USERNAME_LENGTH).lstrip("@").lower()


def _normalize_country(country: str | None) -> str:
    value = _limit_text(country, max_length=2, fallback="UY").upper()
    return value if value in VALID_COUNTRIES else "UY"


def _normalize_user_id(user_id: str | int | None) -> str:
    return _limit_text(user_id, max_length=64)


def _generate_id(prefix: str) -> str:
    timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    suffix = secrets.randbelow(9000) + 1000
    return f"{prefix}_{timestamp_ms}_{suffix}"


def ensure_json_file(path: Path, default: Any) -> None:
    with _FILE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            _atomic_write_text(path, _json_text(_clone_default(default)))


def read_json(path: Path, default: Any) -> Any:
    ensure_json_file(path, default)
    with _FILE_LOCK:
        try:
            content = path.read_text(encoding=ENCODING).strip()
            if not content:
                data = _clone_default(default)
                _atomic_write_text(path, _json_text(data))
                return data
            return json.loads(content)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            data = _clone_default(default)
            _atomic_write_text(path, _json_text(data))
            return data


def write_json(path: Path, data: Any) -> None:
    with _FILE_LOCK:
        _atomic_write_text(path, _json_text(data))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_currency(currency: str | None, default_currency: str) -> str:
    fallback = _limit_text(default_currency, fallback="UYU").upper()
    if fallback not in VALID_CURRENCIES:
        fallback = "UYU"
    value = _limit_text(currency, fallback=fallback).upper()
    return value if value in VALID_CURRENCIES else fallback


def get_currency_from_language(language_code: str | None, default_currency: str) -> str:
    language = _limit_text(language_code).lower().replace("_", "-")
    if language.startswith("es-ar"):
        return "ARS"
    if language.startswith("es-uy"):
        return "UYU"
    return normalize_currency(default_currency, "UYU")


def sanitize_name(name: str | None) -> str:
    return _limit_text(name, max_length=MAX_DISPLAY_NAME_LENGTH, fallback=DEFAULT_DISPLAY_NAME)


def is_admin(user_id: int, admin_ids: set[int]) -> bool:
    user_number = _safe_int(user_id, default=-1)
    return any(user_number == _safe_int(admin_id, default=-2) for admin_id in admin_ids)


def convert_price_from_uyu(amount_uyu: int, currency: str, uyu_to_ars: int, default_currency: str) -> str:
    amount = _safe_int(amount_uyu, minimum=0)
    rate = _safe_int(uyu_to_ars, default=1, minimum=1)
    selected_currency = normalize_currency(currency, default_currency)

    if selected_currency == "ARS":
        return f"${_format_amount(amount * rate)} ARS"
    return f"${_format_amount(amount)} UYU"


def ticket_price_text(currency: str, ticket_price_uyu: int, uyu_to_ars: int, default_currency: str) -> str:
    return convert_price_from_uyu(ticket_price_uyu, currency, uyu_to_ars, default_currency)


def format_prize_list(prizes: list[dict[str, Any]], currency: str, uyu_to_ars: int, default_currency: str) -> str:
    if not prizes:
        return "Sin premios configurados"

    lines: list[str] = []
    for prize in prizes:
        if not isinstance(prize, dict):
            continue
        name = _limit_text(prize.get("name"), max_length=MAX_PRIZE_NAME_LENGTH, fallback="Premio")
        price = convert_price_from_uyu(prize.get("uyu_price", 0), currency, uyu_to_ars, default_currency)
        chance = _format_percentage(prize.get("chance", 0))
        lines.append(f"{name} — {price} — {chance}%")

    return "\n".join(lines) if lines else "Sin premios configurados"


def pick_weighted_prize(prizes: list[dict[str, Any]]) -> dict[str, Any]:
    if not prizes:
        raise ValueError("No hay premios configurados")

    valid_prizes: list[dict[str, Any]] = []
    weights: list[int] = []

    for prize in prizes:
        if not isinstance(prize, dict):
            continue
        weight = _safe_int(prize.get("weight"), default=0, minimum=0)
        if weight > 0:
            valid_prizes.append(prize)
            weights.append(weight)

    if not valid_prizes:
        raise ValueError("No hay premios con peso válido")

    return random.choices(valid_prizes, weights=weights, k=1)[0]


def get_user_key(user_id: str | int | None, username: str | None, full_name: str | None) -> str:
    user_id_text = _normalize_user_id(user_id)
    if user_id_text not in {"", "0"}:
        return user_id_text

    normalized_username = _normalize_username(username)
    if normalized_username:
        return f"user:{normalized_username}"

    return f"guest:{_safe_slug(full_name, fallback='guest')}"


def load_users(users_file: Path) -> dict[str, Any]:
    data = read_json(users_file, {})
    return data if isinstance(data, dict) else {}


def save_users(users: dict[str, Any], users_file: Path) -> None:
    write_json(users_file, users)


def _normalize_user_profile(
    raw_profile: dict[str, Any] | None,
    user_id: str | int | None,
    username: str | None,
    full_name: str | None,
    currency: str,
    display_name: str | None,
    default_demo_spins: int,
    default_currency: str,
) -> dict[str, Any]:
    profile = raw_profile if isinstance(raw_profile, dict) else {}
    timestamp = now_iso()
    resolved_username = _normalize_username(username if username not in (None, "") else profile.get("username"))
    resolved_full_name = _limit_text(
        full_name if full_name not in (None, "") else profile.get("full_name"),
        max_length=MAX_FULL_NAME_LENGTH,
    )
    resolved_display_name = sanitize_name(
        display_name or profile.get("display_name") or resolved_full_name or resolved_username
    )
    resolved_currency = normalize_currency(currency or profile.get("currency"), default_currency)
    resolved_created_at = _limit_text(profile.get("created_at"), fallback=timestamp)
    current_fichas = _safe_int(profile.get("fichas"), minimum=0)
    total_added = _safe_int(profile.get("total_fichas_added"), minimum=0)
    total_removed = _safe_int(profile.get("total_fichas_removed"), minimum=0)

    return {
        "user_id": profile.get("user_id", user_id),
        "username": resolved_username,
        "full_name": resolved_full_name,
        "display_name": resolved_display_name,
        "currency": resolved_currency,
        "fichas": current_fichas,
        "demo_spins_left": _safe_int(profile.get("demo_spins_left"), default=default_demo_spins, minimum=0),
        "created_at": resolved_created_at,
        "updated_at": timestamp,
        "last_seen_at": timestamp,
        "wins": _safe_int(profile.get("wins"), minimum=0),
        "last_prize": _limit_text(profile.get("last_prize"), max_length=MAX_PRIZE_NAME_LENGTH),
        "total_fichas_added": max(total_added, current_fichas),
        "total_fichas_removed": total_removed,
        "status": _limit_text(profile.get("status"), max_length=MAX_STATUS_LENGTH, fallback="active"),
        "profile_version": max(PROFILE_VERSION, _safe_int(profile.get("profile_version"), default=PROFILE_VERSION)),
    }


def ensure_user_profile(
    user_id: str | int | None,
    username: str | None,
    full_name: str | None,
    currency: str,
    display_name: str | None,
    users_file: Path,
    default_demo_spins: int,
    default_currency: str,
) -> dict[str, Any]:
    with _FILE_LOCK:
        users = load_users(users_file)
        key = get_user_key(user_id, username, full_name)
        current_profile = users.get(key)

        profile = _normalize_user_profile(
            current_profile,
            user_id,
            username,
            full_name,
            currency,
            display_name,
            default_demo_spins,
            default_currency,
        )

        users[key] = profile
        save_users(users, users_file)
        return profile


def get_user_profile(
    user_id: str | int | None,
    username: str | None,
    full_name: str | None,
    users_file: Path,
    default_currency: str,
    default_demo_spins: int,
) -> tuple[str, dict[str, Any]]:
    with _FILE_LOCK:
        users = load_users(users_file)
        key = get_user_key(user_id, username, full_name)
        profile = users.get(key)

        if not isinstance(profile, dict):
            profile = _normalize_user_profile(
                None,
                user_id,
                username,
                full_name,
                default_currency,
                None,
                default_demo_spins,
                default_currency,
            )
            users[key] = profile
            save_users(users, users_file)
        else:
            profile = _normalize_user_profile(
                profile,
                user_id,
                username,
                full_name,
                profile.get("currency", default_currency),
                profile.get("display_name"),
                default_demo_spins,
                default_currency,
            )
            users[key] = profile
            save_users(users, users_file)

        return key, profile


def update_user_profile(key: str, profile: dict[str, Any], users_file: Path) -> None:
    with _FILE_LOCK:
        users = load_users(users_file)
        current = users.get(key) if isinstance(users.get(key), dict) else {}
        merged = {**current, **(profile if isinstance(profile, dict) else {})}
        currency = normalize_currency(merged.get("currency"), "UYU")
        demo_spins = _safe_int(merged.get("demo_spins_left"), default=0, minimum=0)

        normalized_profile = _normalize_user_profile(
            merged,
            merged.get("user_id"),
            merged.get("username"),
            merged.get("full_name"),
            currency,
            merged.get("display_name"),
            demo_spins,
            currency,
        )

        users[key] = normalized_profile
        save_users(users, users_file)


def add_fichas_to_user(key: str, amount: int, users_file: Path) -> dict[str, Any]:
    with _FILE_LOCK:
        users = load_users(users_file)
        profile = users.get(key)

        if not isinstance(profile, dict):
            raise ValueError("Usuario no encontrado")

        timestamp = now_iso()
        current_fichas = _safe_int(profile.get("fichas"), minimum=0)
        requested_delta = _safe_int(amount)
        new_fichas = max(0, current_fichas + requested_delta)
        applied_delta = new_fichas - current_fichas

        total_added = _safe_int(profile.get("total_fichas_added"), minimum=0)
        total_removed = _safe_int(profile.get("total_fichas_removed"), minimum=0)

        if applied_delta > 0:
            total_added += applied_delta
        elif applied_delta < 0:
            total_removed += abs(applied_delta)

        profile["fichas"] = new_fichas
        profile["updated_at"] = timestamp
        profile["last_seen_at"] = timestamp
        profile["total_fichas_added"] = total_added
        profile["total_fichas_removed"] = total_removed
        profile["profile_version"] = max(PROFILE_VERSION, _safe_int(profile.get("profile_version"), default=PROFILE_VERSION))

        users[key] = profile
        save_users(users, users_file)
        return profile


def load_logs(log_file: Path) -> list[dict[str, Any]]:
    data = read_json(log_file, [])
    return data if isinstance(data, list) else []


def save_logs(logs: list[dict[str, Any]], log_file: Path) -> None:
    sanitized_logs = [item for item in logs if isinstance(item, dict)]
    if len(sanitized_logs) > MAX_LOG_ITEMS:
        sanitized_logs = sanitized_logs[-MAX_LOG_ITEMS:]
    write_json(log_file, sanitized_logs)


def log_spin(
    user_id: str | int | None,
    username: str | None,
    full_name: str | None,
    display_name: str | None,
    prize_name: str,
    currency: str,
    spin_mode: str,
    log_file: Path,
) -> None:
    with _FILE_LOCK:
        logs = load_logs(log_file)
        logs.append(
            {
                "spin_id": _generate_id("spin"),
                "timestamp": now_iso(),
                "user_key": get_user_key(user_id, username, full_name),
                "user_id": user_id,
                "username": _normalize_username(username),
                "full_name": _limit_text(full_name, max_length=MAX_FULL_NAME_LENGTH),
                "display_name": sanitize_name(display_name or full_name or username),
                "currency": normalize_currency(currency, "UYU"),
                "prize": _limit_text(prize_name, max_length=MAX_PRIZE_NAME_LENGTH, fallback="Premio"),
                "mode": _limit_text(spin_mode, max_length=MAX_SPIN_MODE_LENGTH, fallback="unknown"),
            }
        )
        save_logs(logs, log_file)


def load_purchases(purchases_file: Path) -> list[dict[str, Any]]:
    data = read_json(purchases_file, [])
    return data if isinstance(data, list) else []


def save_purchases(items: list[dict[str, Any]], purchases_file: Path) -> None:
    sanitized_items = [item for item in items if isinstance(item, dict)]
    write_json(purchases_file, sanitized_items)


def create_pending_purchase(
    user_id: str | int | None,
    username: str | None,
    full_name: str | None,
    display_name: str | None,
    country: str,
    currency: str,
    qty: int,
    purchases_file: Path,
    default_currency: str,
) -> dict[str, Any]:
    with _FILE_LOCK:
        selected_country = _normalize_country(country)
        items = load_purchases(purchases_file)
        purchase_id = _generate_id("buy")
        user_key = get_user_key(user_id, username, full_name)
        normalized_qty = _safe_int(qty, default=1, minimum=1, maximum=100000)
        timestamp = now_iso()

        item = {
            "purchase_id": purchase_id,
            "user_key": user_key,
            "user_id": user_id,
            "username": _normalize_username(username),
            "full_name": _limit_text(full_name, max_length=MAX_FULL_NAME_LENGTH),
            "display_name": sanitize_name(display_name or full_name or username),
            "country": selected_country,
            "currency": normalize_currency(currency, default_currency),
            "qty": normalized_qty,
            "status": "pending",
            "created_at": timestamp,
            "updated_at": timestamp,
            "approved_at": "",
            "approved_by": "",
        }

        items.append(item)
        save_purchases(items, purchases_file)
        return item


def approve_purchase_by_id(
    purchase_id: str,
    admin_id: int,
    purchases_file: Path,
    users_file: Path,
) -> dict[str, Any] | None:
    with _FILE_LOCK:
        target_purchase_id = _limit_text(purchase_id, max_length=MAX_PURCHASE_ID_LENGTH)
        items = load_purchases(purchases_file)
        found: dict[str, Any] | None = None

        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("purchase_id") == target_purchase_id and item.get("status") == "pending":
                found = item
                break

        if not found:
            return None

        ensure_user_profile(
            found.get("user_id"),
            found.get("username"),
            found.get("full_name"),
            found.get("currency", "UYU"),
            found.get("display_name"),
            users_file,
            0,
            found.get("currency", "UYU"),
        )

        add_fichas_to_user(
            found["user_key"],
            _safe_int(found.get("qty"), default=1, minimum=1),
            users_file,
        )

        found["status"] = "approved"
        found["approved_at"] = now_iso()
        found["approved_by"] = str(_safe_int(admin_id))
        found["updated_at"] = now_iso()
        save_purchases(items, purchases_file)
        return found


def get_country_link(country: str, mp_link_ar: str, mp_link_uy: str) -> str:
    return _limit_text(mp_link_ar) if _normalize_country(country) == "AR" else _limit_text(mp_link_uy)


def build_webapp_url(user: Any, webapp_base_url: str, default_currency: str) -> str:
    base_url = _limit_text(webapp_base_url).rstrip("/")
    currency = get_currency_from_language(getattr(user, "language_code", None), default_currency)
    params = urlencode(
        {
            "user_id": getattr(user, "id", "") or "",
            "username": getattr(user, "username", "") or "",
            "full_name": getattr(user, "full_name", "") or "",
            "currency": currency,
        }
    )
    wheel_path = "/wheel"
    prefix = base_url if base_url else ""
    return f"{prefix}{wheel_path}?{params}" if params else f"{prefix}{wheel_path}"