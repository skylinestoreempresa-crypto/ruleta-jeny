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

DEFAULT_CURRENCY = "UYU"
DEFAULT_COUNTRY = "UY"
DEFAULT_DISPLAY_NAME = "Jugador"

MAX_DISPLAY_NAME_LENGTH = 40
MAX_USERNAME_LENGTH = 80
MAX_FULL_NAME_LENGTH = 120
MAX_PRIZE_NAME_LENGTH = 120
MAX_SPIN_MODE_LENGTH = 30
MAX_PURCHASE_ID_LENGTH = 120
MAX_STATUS_LENGTH = 20
MAX_REASON_LENGTH = 220
MAX_LOG_ITEMS = 10000
MAX_PURCHASE_ITEMS = 50000

PROFILE_VERSION = 4
PURCHASE_VERSION = 2
SPIN_LOG_VERSION = 2

_FILE_LOCK = threading.RLock()


def _clone_default(value: Any) -> Any:
    return copy.deepcopy(value)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return _utc_now().replace(microsecond=0).isoformat()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).replace("\x00", " ")
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
        if isinstance(value, bool):
            number = int(value)
        elif isinstance(value, float):
            number = int(value)
        else:
            number = int(str(value).strip())
    except (TypeError, ValueError):
        number = default

    if minimum is not None and number < minimum:
        number = minimum
    if maximum is not None and number > maximum:
        number = maximum
    return number


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, bool):
            return float(int(value))
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = _clean_text(value).lower()
    if text in {"1", "true", "yes", "y", "si", "sí", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _format_amount(amount: int) -> str:
    return f"{_safe_int(amount, minimum=0):,}".replace(",", ".")


def _format_percentage(value: Any) -> str:
    number = _safe_float(value, default=0.0)
    if float(number).is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    temp_path.write_text(content, encoding=ENCODING)
    temp_path.replace(path)


def _backup_broken_file(path: Path) -> None:
    if not path.exists():
        return
    backup_name = f"{path.name}.broken.{_utc_now().strftime('%Y%m%d%H%M%S')}.{secrets.token_hex(4)}.bak"
    backup_path = path.with_name(backup_name)
    try:
        path.replace(backup_path)
    except OSError:
        pass


def _safe_slug(value: Any, fallback: str = "guest") -> str:
    text = _limit_text(value, max_length=80, fallback=fallback).lower()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^a-z0-9_áéíóúñü-]", "", text)
    text = text.strip("_-")
    return text or fallback


def _normalize_username(username: str | None) -> str:
    return _limit_text(username, max_length=MAX_USERNAME_LENGTH).lstrip("@").lower()


def _normalize_country(country: str | None) -> str:
    value = _limit_text(country, max_length=2, fallback=DEFAULT_COUNTRY).upper()
    return value if value in VALID_COUNTRIES else DEFAULT_COUNTRY


def _normalize_user_id(user_id: str | int | None) -> str:
    return _limit_text(user_id, max_length=64)


def _normalize_status(value: Any, fallback: str = "active") -> str:
    return _limit_text(value, max_length=MAX_STATUS_LENGTH, fallback=fallback).lower()


def _generate_id(prefix: str) -> str:
    timestamp_ms = int(_utc_now().timestamp() * 1000)
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
            _backup_broken_file(path)
            data = _clone_default(default)
            _atomic_write_text(path, _json_text(data))
            return data


def write_json(path: Path, data: Any) -> None:
    with _FILE_LOCK:
        _atomic_write_text(path, _json_text(data))


def normalize_currency(currency: str | None, default_currency: str = DEFAULT_CURRENCY) -> str:
    fallback = _limit_text(default_currency, fallback=DEFAULT_CURRENCY).upper()
    if fallback not in VALID_CURRENCIES:
        fallback = DEFAULT_CURRENCY

    value = _limit_text(currency, fallback=fallback).upper()
    return value if value in VALID_CURRENCIES else fallback


def get_currency_from_language(language_code: str | None, default_currency: str = DEFAULT_CURRENCY) -> str:
    language = _limit_text(language_code).lower().replace("_", "-")
    if language.startswith("es-ar"):
        return "ARS"
    if language.startswith("es-uy"):
        return "UYU"
    return normalize_currency(default_currency, DEFAULT_CURRENCY)


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


def format_prize_list(
    prizes: list[dict[str, Any]],
    currency: str,
    uyu_to_ars: int,
    default_currency: str,
) -> str:
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
        if weight <= 0:
            continue

        normalized_prize = {
            "name": _limit_text(prize.get("name"), max_length=MAX_PRIZE_NAME_LENGTH, fallback="Premio"),
            "uyu_price": _safe_int(prize.get("uyu_price"), default=0, minimum=0),
            "chance": _safe_float(prize.get("chance"), default=0.0),
            "weight": weight,
        }
        valid_prizes.append({**prize, **normalized_prize})
        weights.append(weight)

    if not valid_prizes:
        raise ValueError("No hay premios con peso válido")

    return copy.deepcopy(random.choices(valid_prizes, weights=weights, k=1)[0])


def get_user_key(user_id: str | int | None, username: str | None, full_name: str | None) -> str:
    user_id_text = _normalize_user_id(user_id)
    if user_id_text not in {"", "0"}:
        return user_id_text

    normalized_username = _normalize_username(username)
    if normalized_username:
        return f"user:{normalized_username}"

    return f"guest:{_safe_slug(full_name, fallback='guest')}"


def _default_user_profile(
    user_id: str | int | None,
    username: str | None,
    full_name: str | None,
    currency: str,
    display_name: str | None,
    default_demo_spins: int,
) -> dict[str, Any]:
    timestamp = now_iso()
    resolved_username = _normalize_username(username)
    resolved_full_name = _limit_text(full_name, max_length=MAX_FULL_NAME_LENGTH)
    resolved_display_name = sanitize_name(display_name or resolved_full_name or resolved_username)

    return {
        "user_id": _normalize_user_id(user_id),
        "username": resolved_username,
        "full_name": resolved_full_name,
        "display_name": resolved_display_name,
        "currency": normalize_currency(currency, DEFAULT_CURRENCY),
        "country": DEFAULT_COUNTRY,
        "fichas": 0,
        "demo_spins_left": _safe_int(default_demo_spins, default=0, minimum=0),
        "created_at": timestamp,
        "updated_at": timestamp,
        "last_seen_at": timestamp,
        "wins": 0,
        "spins_total": 0,
        "paid_spins_total": 0,
        "demo_spins_total": 0,
        "last_prize": "",
        "best_prize": "",
        "total_fichas_added": 0,
        "total_fichas_removed": 0,
        "status": "active",
        "profile_version": PROFILE_VERSION,
    }


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
    base = _default_user_profile(
        user_id=user_id,
        username=username,
        full_name=full_name,
        currency=currency or default_currency,
        display_name=display_name,
        default_demo_spins=default_demo_spins,
    )

    profile = raw_profile if isinstance(raw_profile, dict) else {}
    timestamp = now_iso()

    resolved_username = _normalize_username(
        username if username not in (None, "") else profile.get("username", base["username"])
    )
    resolved_full_name = _limit_text(
        full_name if full_name not in (None, "") else profile.get("full_name", base["full_name"]),
        max_length=MAX_FULL_NAME_LENGTH,
    )
    resolved_display_name = sanitize_name(
        display_name
        or profile.get("display_name")
        or resolved_full_name
        or resolved_username
        or DEFAULT_DISPLAY_NAME
    )
    resolved_currency = normalize_currency(currency or profile.get("currency"), default_currency)
    resolved_country = _normalize_country(profile.get("country"))

    current_fichas = _safe_int(profile.get("fichas"), minimum=0)
    total_added = _safe_int(profile.get("total_fichas_added"), minimum=0)
    total_removed = _safe_int(profile.get("total_fichas_removed"), minimum=0)

    if total_added < current_fichas:
        total_added = current_fichas

    created_at = _limit_text(profile.get("created_at"), fallback=base["created_at"])

    normalized = {
        "user_id": _normalize_user_id(profile.get("user_id") or user_id),
        "username": resolved_username,
        "full_name": resolved_full_name,
        "display_name": resolved_display_name,
        "currency": resolved_currency,
        "country": resolved_country,
        "fichas": current_fichas,
        "demo_spins_left": _safe_int(
            profile.get("demo_spins_left"),
            default=_safe_int(default_demo_spins, minimum=0),
            minimum=0,
        ),
        "created_at": created_at,
        "updated_at": timestamp,
        "last_seen_at": timestamp,
        "wins": _safe_int(profile.get("wins"), minimum=0),
        "spins_total": _safe_int(profile.get("spins_total"), minimum=0),
        "paid_spins_total": _safe_int(profile.get("paid_spins_total"), minimum=0),
        "demo_spins_total": _safe_int(profile.get("demo_spins_total"), minimum=0),
        "last_prize": _limit_text(profile.get("last_prize"), max_length=MAX_PRIZE_NAME_LENGTH),
        "best_prize": _limit_text(profile.get("best_prize"), max_length=MAX_PRIZE_NAME_LENGTH),
        "total_fichas_added": total_added,
        "total_fichas_removed": total_removed,
        "status": _normalize_status(profile.get("status"), fallback="active"),
        "profile_version": max(PROFILE_VERSION, _safe_int(profile.get("profile_version"), default=PROFILE_VERSION)),
    }

    return normalized


def load_users(users_file: Path) -> dict[str, Any]:
    data = read_json(users_file, {})
    return data if isinstance(data, dict) else {}


def save_users(users: dict[str, Any], users_file: Path) -> None:
    sanitized: dict[str, Any] = {}
    for key, value in users.items():
        if not isinstance(key, str):
            continue
        if not isinstance(value, dict):
            continue
        sanitized[_limit_text(key, max_length=120)] = value
    write_json(users_file, sanitized)


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
            raw_profile=current_profile,
            user_id=user_id,
            username=username,
            full_name=full_name,
            currency=currency,
            display_name=display_name,
            default_demo_spins=default_demo_spins,
            default_currency=default_currency,
        )

        users[key] = profile
        save_users(users, users_file)
        return copy.deepcopy(profile)


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

        normalized_profile = _normalize_user_profile(
            raw_profile=profile if isinstance(profile, dict) else None,
            user_id=user_id,
            username=username,
            full_name=full_name,
            currency=(profile or {}).get("currency", default_currency) if isinstance(profile, dict) else default_currency,
            display_name=(profile or {}).get("display_name") if isinstance(profile, dict) else None,
            default_demo_spins=default_demo_spins,
            default_currency=default_currency,
        )

        users[key] = normalized_profile
        save_users(users, users_file)
        return key, copy.deepcopy(normalized_profile)


def update_user_profile(key: str, profile: dict[str, Any], users_file: Path) -> None:
    with _FILE_LOCK:
        users = load_users(users_file)
        current = users.get(key) if isinstance(users.get(key), dict) else {}
        incoming = profile if isinstance(profile, dict) else {}

        merged = {**current, **incoming}
        currency = normalize_currency(merged.get("currency"), DEFAULT_CURRENCY)

        normalized_profile = _normalize_user_profile(
            raw_profile=merged,
            user_id=merged.get("user_id"),
            username=merged.get("username"),
            full_name=merged.get("full_name"),
            currency=currency,
            display_name=merged.get("display_name"),
            default_demo_spins=_safe_int(merged.get("demo_spins_left"), default=0, minimum=0),
            default_currency=currency,
        )

        users[_limit_text(key, max_length=120)] = normalized_profile
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
        profile["profile_version"] = max(
            PROFILE_VERSION,
            _safe_int(profile.get("profile_version"), default=PROFILE_VERSION),
        )

        users[key] = profile
        save_users(users, users_file)
        return copy.deepcopy(profile)


def consume_user_spin(
    key: str,
    users_file: Path,
    mode: str,
) -> dict[str, Any]:
    with _FILE_LOCK:
        users = load_users(users_file)
        profile = users.get(key)

        if not isinstance(profile, dict):
            raise ValueError("Usuario no encontrado")

        current_fichas = _safe_int(profile.get("fichas"), minimum=0)
        current_demo = _safe_int(profile.get("demo_spins_left"), minimum=0)
        normalized_mode = _limit_text(mode, max_length=MAX_SPIN_MODE_LENGTH).lower()

        if normalized_mode == "demo":
            if current_demo <= 0:
                raise ValueError("No quedan giros demo")
            profile["demo_spins_left"] = current_demo - 1
            profile["demo_spins_total"] = _safe_int(profile.get("demo_spins_total"), minimum=0) + 1
        elif normalized_mode in {"paid", "real", "ticket"}:
            if current_fichas <= 0:
                raise ValueError("No hay fichas suficientes")
            profile["fichas"] = current_fichas - 1
            profile["paid_spins_total"] = _safe_int(profile.get("paid_spins_total"), minimum=0) + 1
            profile["total_fichas_removed"] = _safe_int(profile.get("total_fichas_removed"), minimum=0) + 1
        else:
            raise ValueError("Modo de giro inválido")

        profile["spins_total"] = _safe_int(profile.get("spins_total"), minimum=0) + 1
        profile["updated_at"] = now_iso()
        profile["last_seen_at"] = profile["updated_at"]
        profile["profile_version"] = max(PROFILE_VERSION, _safe_int(profile.get("profile_version"), default=PROFILE_VERSION))

        users[key] = profile
        save_users(users, users_file)
        return copy.deepcopy(profile)


def register_user_win(
    key: str,
    prize_name: str,
    users_file: Path,
) -> dict[str, Any]:
    with _FILE_LOCK:
        users = load_users(users_file)
        profile = users.get(key)

        if not isinstance(profile, dict):
            raise ValueError("Usuario no encontrado")

        prize = _limit_text(prize_name, max_length=MAX_PRIZE_NAME_LENGTH, fallback="Premio")

        profile["wins"] = _safe_int(profile.get("wins"), minimum=0) + 1
        profile["last_prize"] = prize
        if not _limit_text(profile.get("best_prize")):
            profile["best_prize"] = prize
        profile["updated_at"] = now_iso()
        profile["last_seen_at"] = profile["updated_at"]
        profile["profile_version"] = max(PROFILE_VERSION, _safe_int(profile.get("profile_version"), default=PROFILE_VERSION))

        users[key] = profile
        save_users(users, users_file)
        return copy.deepcopy(profile)


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
                "version": SPIN_LOG_VERSION,
                "user_key": get_user_key(user_id, username, full_name),
                "user_id": _normalize_user_id(user_id),
                "username": _normalize_username(username),
                "full_name": _limit_text(full_name, max_length=MAX_FULL_NAME_LENGTH),
                "display_name": sanitize_name(display_name or full_name or username),
                "currency": normalize_currency(currency, DEFAULT_CURRENCY),
                "prize": _limit_text(prize_name, max_length=MAX_PRIZE_NAME_LENGTH, fallback="Premio"),
                "mode": _limit_text(spin_mode, max_length=MAX_SPIN_MODE_LENGTH, fallback="unknown").lower(),
            }
        )

        save_logs(logs, log_file)


def load_purchases(purchases_file: Path) -> list[dict[str, Any]]:
    data = read_json(purchases_file, [])
    return data if isinstance(data, list) else []


def save_purchases(items: list[dict[str, Any]], purchases_file: Path) -> None:
    sanitized_items = [item for item in items if isinstance(item, dict)]
    if len(sanitized_items) > MAX_PURCHASE_ITEMS:
        sanitized_items = sanitized_items[-MAX_PURCHASE_ITEMS:]
    write_json(purchases_file, sanitized_items)


def _normalize_purchase_item(
    raw_item: dict[str, Any] | None,
    user_id: str | int | None = None,
    username: str | None = None,
    full_name: str | None = None,
    display_name: str | None = None,
    country: str | None = None,
    currency: str | None = None,
    qty: int | None = None,
    default_currency: str = DEFAULT_CURRENCY,
) -> dict[str, Any]:
    item = raw_item if isinstance(raw_item, dict) else {}
    timestamp = now_iso()

    normalized_user_id = _normalize_user_id(item.get("user_id") if user_id is None else user_id)
    normalized_username = _normalize_username(item.get("username") if username is None else username)
    normalized_full_name = _limit_text(
        item.get("full_name") if full_name is None else full_name,
        max_length=MAX_FULL_NAME_LENGTH,
    )
    normalized_display_name = sanitize_name(
        display_name
        or item.get("display_name")
        or normalized_full_name
        or normalized_username
        or DEFAULT_DISPLAY_NAME
    )
    normalized_country = _normalize_country(country if country is not None else item.get("country"))
    normalized_currency = normalize_currency(currency if currency is not None else item.get("currency"), default_currency)
    normalized_qty = _safe_int(qty if qty is not None else item.get("qty"), default=1, minimum=1, maximum=100000)

    created_at = _limit_text(item.get("created_at"), fallback=timestamp)

    return {
        "purchase_id": _limit_text(
            item.get("purchase_id"),
            max_length=MAX_PURCHASE_ID_LENGTH,
            fallback=_generate_id("buy"),
        ),
        "user_key": get_user_key(normalized_user_id, normalized_username, normalized_full_name),
        "user_id": normalized_user_id,
        "username": normalized_username,
        "full_name": normalized_full_name,
        "display_name": normalized_display_name,
        "country": normalized_country,
        "currency": normalized_currency,
        "qty": normalized_qty,
        "status": _normalize_status(item.get("status"), fallback="pending"),
        "created_at": created_at,
        "updated_at": _limit_text(item.get("updated_at"), fallback=timestamp),
        "approved_at": _limit_text(item.get("approved_at")),
        "approved_by": _limit_text(item.get("approved_by"), max_length=64),
        "rejected_at": _limit_text(item.get("rejected_at")),
        "rejected_by": _limit_text(item.get("rejected_by"), max_length=64),
        "rejection_reason": _limit_text(item.get("rejection_reason"), max_length=MAX_REASON_LENGTH),
        "version": max(PURCHASE_VERSION, _safe_int(item.get("version"), default=PURCHASE_VERSION)),
    }


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
        items = load_purchases(purchases_file)

        new_item = _normalize_purchase_item(
            raw_item={
                "purchase_id": _generate_id("buy"),
                "status": "pending",
                "created_at": now_iso(),
                "updated_at": now_iso(),
            },
            user_id=user_id,
            username=username,
            full_name=full_name,
            display_name=display_name,
            country=country,
            currency=currency,
            qty=qty,
            default_currency=default_currency,
        )

        items.append(new_item)
        save_purchases(items, purchases_file)
        return copy.deepcopy(new_item)


def approve_purchase_by_id(
    purchase_id: str,
    admin_id: int,
    purchases_file: Path,
    users_file: Path,
) -> dict[str, Any] | None:
    with _FILE_LOCK:
        target_purchase_id = _limit_text(purchase_id, max_length=MAX_PURCHASE_ID_LENGTH)
        items = load_purchases(purchases_file)
        found_index = -1

        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            if item.get("purchase_id") == target_purchase_id and item.get("status") == "pending":
                found_index = idx
                break

        if found_index < 0:
            return None

        found = _normalize_purchase_item(items[found_index])

        ensure_user_profile(
            user_id=found.get("user_id"),
            username=found.get("username"),
            full_name=found.get("full_name"),
            currency=found.get("currency", DEFAULT_CURRENCY),
            display_name=found.get("display_name"),
            users_file=users_file,
            default_demo_spins=0,
            default_currency=found.get("currency", DEFAULT_CURRENCY),
        )

        add_fichas_to_user(
            key=found["user_key"],
            amount=_safe_int(found.get("qty"), default=1, minimum=1),
            users_file=users_file,
        )

        found["status"] = "approved"
        found["approved_at"] = now_iso()
        found["approved_by"] = str(_safe_int(admin_id))
        found["updated_at"] = found["approved_at"]

        items[found_index] = found
        save_purchases(items, purchases_file)
        return copy.deepcopy(found)


def reject_purchase_by_id(
    purchase_id: str,
    admin_id: int,
    purchases_file: Path,
    reason: str = "",
) -> dict[str, Any] | None:
    with _FILE_LOCK:
        target_purchase_id = _limit_text(purchase_id, max_length=MAX_PURCHASE_ID_LENGTH)
        items = load_purchases(purchases_file)
        found_index = -1

        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            if item.get("purchase_id") == target_purchase_id and item.get("status") == "pending":
                found_index = idx
                break

        if found_index < 0:
            return None

        found = _normalize_purchase_item(items[found_index])
        found["status"] = "rejected"
        found["rejected_at"] = now_iso()
        found["rejected_by"] = str(_safe_int(admin_id))
        found["rejection_reason"] = _limit_text(reason, max_length=MAX_REASON_LENGTH)
        found["updated_at"] = found["rejected_at"]

        items[found_index] = found
        save_purchases(items, purchases_file)
        return copy.deepcopy(found)


def get_pending_purchases(purchases_file: Path) -> list[dict[str, Any]]:
    with _FILE_LOCK:
        items = load_purchases(purchases_file)
        pending = [
            _normalize_purchase_item(item)
            for item in items
            if isinstance(item, dict) and _normalize_status(item.get("status"), fallback="pending") == "pending"
        ]
        return pending


def get_country_link(country: str, mp_link_ar: str, mp_link_uy: str) -> str:
    return _limit_text(mp_link_ar) if _normalize_country(country) == "AR" else _limit_text(mp_link_uy)


def build_webapp_url(user: Any, webapp_base_url: str, default_currency: str) -> str:
    base_url = _limit_text(webapp_base_url).rstrip("/")
    currency = get_currency_from_language(getattr(user, "language_code", None), default_currency)

    full_name = (
        getattr(user, "full_name", None)
        or " ".join(
            part for part in [
                _clean_text(getattr(user, "first_name", "")),
                _clean_text(getattr(user, "last_name", "")),
            ]
            if part
        )
    )

    params = urlencode(
        {
            "user_id": getattr(user, "id", "") or "",
            "username": getattr(user, "username", "") or "",
            "full_name": full_name or "",
            "currency": currency,
        }
    )

    wheel_path = "/wheel"
    prefix = base_url if base_url else ""
    return f"{prefix}{wheel_path}?{params}" if params else f"{prefix}{wheel_path}"


def get_purchase_by_id(purchase_id: str, purchases_file: Path) -> dict[str, Any] | None:
    target_purchase_id = _limit_text(purchase_id, max_length=MAX_PURCHASE_ID_LENGTH)
    items = load_purchases(purchases_file)

    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("purchase_id") == target_purchase_id:
            return _normalize_purchase_item(item)
    return None


def get_recent_spins(log_file: Path, limit: int = 20) -> list[dict[str, Any]]:
    logs = load_logs(log_file)
    safe_limit = _safe_int(limit, default=20, minimum=1, maximum=200)
    recent = [item for item in logs if isinstance(item, dict)][-safe_limit:]
    return recent[::-1]


def get_user_stats(
    user_id: str | int | None,
    username: str | None,
    full_name: str | None,
    users_file: Path,
    default_currency: str,
    default_demo_spins: int,
) -> dict[str, Any]:
    key, profile = get_user_profile(
        user_id=user_id,
        username=username,
        full_name=full_name,
        users_file=users_file,
        default_currency=default_currency,
        default_demo_spins=default_demo_spins,
    )
    return {
        "user_key": key,
        "display_name": profile.get("display_name", DEFAULT_DISPLAY_NAME),
        "fichas": _safe_int(profile.get("fichas"), minimum=0),
        "demo_spins_left": _safe_int(profile.get("demo_spins_left"), minimum=0),
        "wins": _safe_int(profile.get("wins"), minimum=0),
        "spins_total": _safe_int(profile.get("spins_total"), minimum=0),
        "last_prize": _limit_text(profile.get("last_prize")),
        "currency": normalize_currency(profile.get("currency"), default_currency),
        "status": _normalize_status(profile.get("status"), fallback="active"),
    }


def migrate_users_file(users_file: Path, default_currency: str = DEFAULT_CURRENCY, default_demo_spins: int = 0) -> dict[str, Any]:
    with _FILE_LOCK:
        users = load_users(users_file)
        migrated: dict[str, Any] = {}

        for key, raw_profile in users.items():
            if not isinstance(raw_profile, dict):
                continue
            safe_key = _limit_text(key, max_length=120)
            migrated[safe_key] = _normalize_user_profile(
                raw_profile=raw_profile,
                user_id=raw_profile.get("user_id"),
                username=raw_profile.get("username"),
                full_name=raw_profile.get("full_name"),
                currency=raw_profile.get("currency", default_currency),
                display_name=raw_profile.get("display_name"),
                default_demo_spins=default_demo_spins,
                default_currency=default_currency,
            )

        save_users(migrated, users_file)
        return migrated


def migrate_purchases_file(purchases_file: Path, default_currency: str = DEFAULT_CURRENCY) -> list[dict[str, Any]]:
    with _FILE_LOCK:
        items = load_purchases(purchases_file)
        migrated = [
            _normalize_purchase_item(item, default_currency=default_currency)
            for item in items
            if isinstance(item, dict)
        ]
        save_purchases(migrated, purchases_file)
        return migrated


def migrate_logs_file(log_file: Path) -> list[dict[str, Any]]:
    with _FILE_LOCK:
        logs = load_logs(log_file)
        migrated: list[dict[str, Any]] = []

        for item in logs:
            if not isinstance(item, dict):
                continue

            migrated.append(
                {
                    "spin_id": _limit_text(item.get("spin_id"), max_length=120, fallback=_generate_id("spin")),
                    "timestamp": _limit_text(item.get("timestamp"), fallback=now_iso()),
                    "version": SPIN_LOG_VERSION,
                    "user_key": _limit_text(item.get("user_key"), max_length=120),
                    "user_id": _normalize_user_id(item.get("user_id")),
                    "username": _normalize_username(item.get("username")),
                    "full_name": _limit_text(item.get("full_name"), max_length=MAX_FULL_NAME_LENGTH),
                    "display_name": sanitize_name(item.get("display_name")),
                    "currency": normalize_currency(item.get("currency"), DEFAULT_CURRENCY),
                    "prize": _limit_text(item.get("prize"), max_length=MAX_PRIZE_NAME_LENGTH, fallback="Premio"),
                    "mode": _limit_text(item.get("mode"), max_length=MAX_SPIN_MODE_LENGTH, fallback="unknown").lower(),
                }
            )

        save_logs(migrated, log_file)
        return migrated