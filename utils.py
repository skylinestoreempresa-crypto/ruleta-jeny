import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


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
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_currency(currency: str | None, default_currency: str) -> str:
    value = (currency or default_currency).strip().upper()
    return value if value in {"UYU", "ARS"} else default_currency


def get_currency_from_language(language_code: str | None, default_currency: str) -> str:
    lang = (language_code or "").lower()
    if lang.startswith("es-ar"):
        return "ARS"
    if lang.startswith("es-uy"):
        return "UYU"
    return default_currency


def sanitize_name(name: str | None) -> str:
    raw = (name or "").strip()
    return raw[:40] if raw else "Jugador"


def is_admin(user_id: int, admin_ids: set[int]) -> bool:
    return user_id in admin_ids


def convert_price_from_uyu(amount_uyu: int, currency: str, uyu_to_ars: int, default_currency: str) -> str:
    currency = normalize_currency(currency, default_currency)
    if currency == "ARS":
        return f"${amount_uyu * uyu_to_ars} ARS"
    return f"${amount_uyu} UYU"


def ticket_price_text(currency: str, ticket_price_uyu: int, uyu_to_ars: int, default_currency: str) -> str:
    return convert_price_from_uyu(ticket_price_uyu, currency, uyu_to_ars, default_currency)


def format_prize_list(prizes: list[dict[str, Any]], currency: str, uyu_to_ars: int, default_currency: str) -> str:
    return "\n".join(
        f"{p['name']} — {convert_price_from_uyu(int(p['uyu_price']), currency, uyu_to_ars, default_currency)} — {p['chance']}%"
        for p in prizes
    )


def pick_weighted_prize(prizes: list[dict[str, Any]]) -> dict[str, Any]:
    weights = [int(p["weight"]) for p in prizes]
    return random.choices(prizes, weights=weights, k=1)[0]


def get_user_key(user_id: str | int | None, username: str | None, full_name: str | None) -> str:
    if user_id not in (None, "", 0, "0"):
        return str(user_id)
    if username:
        return f"user:{username.lower()}"
    return f"guest:{sanitize_name(full_name)}"


def load_users(users_file: Path) -> dict[str, Any]:
    data = read_json(users_file, {})
    return data if isinstance(data, dict) else {}


def save_users(users: dict[str, Any], users_file: Path) -> None:
    write_json(users_file, users)


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
    users = load_users(users_file)
    key = get_user_key(user_id, username, full_name)

    if key not in users:
        users[key] = {
            "user_id": user_id,
            "username": username or "",
            "full_name": full_name or "",
            "display_name": sanitize_name(display_name or full_name or username),
            "currency": normalize_currency(currency, default_currency),
            "fichas": 0,
            "demo_spins_left": default_demo_spins,
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
        users[key]["currency"] = normalize_currency(currency, default_currency)
        users[key]["updated_at"] = now_iso()

    save_users(users, users_file)
    return users[key]


def get_user_profile(
    user_id: str | int | None,
    username: str | None,
    full_name: str | None,
    users_file: Path,
    default_currency: str,
    default_demo_spins: int,
) -> tuple[str, dict[str, Any]]:
    users = load_users(users_file)
    key = get_user_key(user_id, username, full_name)
    profile = users.get(key)
    if not profile:
        profile = ensure_user_profile(
            user_id,
            username,
            full_name,
            default_currency,
            None,
            users_file,
            default_demo_spins,
            default_currency,
        )
    return key, profile


def update_user_profile(key: str, profile: dict[str, Any], users_file: Path) -> None:
    users = load_users(users_file)
    profile["updated_at"] = now_iso()
    users[key] = profile
    save_users(users, users_file)


def add_fichas_to_user(key: str, amount: int, users_file: Path) -> dict[str, Any]:
    users = load_users(users_file)
    profile = users.get(key)
    if not profile:
        raise ValueError("Usuario no encontrado")
    profile["fichas"] = max(0, int(profile.get("fichas", 0)) + int(amount))
    profile["updated_at"] = now_iso()
    users[key] = profile
    save_users(users, users_file)
    return profile


def load_logs(log_file: Path) -> list[dict[str, Any]]:
    data = read_json(log_file, [])
    return data if isinstance(data, list) else []


def save_logs(logs: list[dict[str, Any]], log_file: Path) -> None:
    write_json(log_file, logs)


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
    logs = load_logs(log_file)
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
    save_logs(logs, log_file)


def load_purchases(purchases_file: Path) -> list[dict[str, Any]]:
    data = read_json(purchases_file, [])
    return data if isinstance(data, list) else []


def save_purchases(items: list[dict[str, Any]], purchases_file: Path) -> None:
    write_json(purchases_file, items)


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
    country = country.upper().strip()
    if country not in {"AR", "UY"}:
        country = "UY"

    items = load_purchases(purchases_file)
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
        "currency": normalize_currency(currency, default_currency),
        "qty": max(1, int(qty)),
        "status": "pending",
        "created_at": now_iso(),
        "approved_at": "",
        "approved_by": "",
    }
    items.append(item)
    save_purchases(items, purchases_file)
    return item


def approve_purchase_by_id(purchase_id: str, admin_id: int, purchases_file: Path, users_file: Path) -> dict[str, Any] | None:
    items = load_purchases(purchases_file)
    found = None
    for item in items:
        if item.get("purchase_id") == purchase_id and item.get("status") == "pending":
            found = item
            break
    if not found:
        return None

    add_fichas_to_user(found["user_key"], int(found.get("qty", 1)), users_file)
    found["status"] = "approved"
    found["approved_at"] = now_iso()
    found["approved_by"] = str(admin_id)
    save_purchases(items, purchases_file)
    return found


def get_country_link(country: str, mp_link_ar: str, mp_link_uy: str) -> str:
    return mp_link_ar if country.upper() == "AR" else mp_link_uy


def build_webapp_url(user: Any, webapp_base_url: str, default_currency: str) -> str:
    currency = get_currency_from_language(getattr(user, "language_code", None), default_currency)
    params = urlencode(
        {
            "user_id": getattr(user, "id", ""),
            "username": getattr(user, "username", "") or "",
            "full_name": getattr(user, "full_name", "") or "",
            "currency": currency,
        }
    )
    return f"{webapp_base_url}/wheel?{params}"