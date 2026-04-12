#!/usr/bin/env python3
"""Telephony helper for the Henio optional telephony skill."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01/Accounts"
VAPI_API_BASE = "https://api.vapi.ai"
BLAND_DEFAULT_VOICE = "mason"
VAPI_DEFAULT_VOICE_PROVIDER = "11labs"
VAPI_DEFAULT_VOICE_ID = "cjVigY5qzO86Huf0OWal"
VAPI_DEFAULT_MODEL = "gpt-4o"
DEFAULT_AI_PROVIDER = "bland"
STATE_VERSION = 1


class TelephonyError(RuntimeError):
    """Domain-specific failure surfaced to the skill/user."""


@dataclass
class OwnedTwilioNumber:
    sid: str
    phone_number: str
    friendly_name: str
    capabilities: dict[str, Any]


def _henio_home() -> Path:
    return Path(os.environ.get("HENIO_HOME", "~/.henio")).expanduser()


def _env_path() -> Path:
    return _henio_home() / ".env"


def _state_path() -> Path:
    return _henio_home() / "telephony_state.json"


def _load_dotenv_values(path: Path | None = None) -> dict[str, str]:
    env_file = path or _env_path()
    if not env_file.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = raw_line.partition("=")
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1].replace('\\"', '"').replace('\\\\', '\\')
        values[key] = value
    return values


def _env_or_config(env_key: str, default: str = "") -> str:
    value = os.environ.get(env_key, "")
    if value:
        return value
    return _load_dotenv_values().get(env_key, default)


def _load_state(path: Path | None = None) -> dict[str, Any]:
    state_file = path or _state_path()
    if not state_file.exists():
        return {"version": STATE_VERSION}
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("version", STATE_VERSION)
            return data
    except Exception:
        pass
    return {"version": STATE_VERSION}


def _save_state(state: dict[str, Any], path: Path | None = None) -> Path:
    state_file = path or _state_path()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state_file


def _quote_env_value(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:+@-]+", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _upsert_env_file(updates: dict[str, str], env_path: Path | None = None) -> Path:
    path = env_path or _env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        key, _, _rest = line.partition("=")
        key = key.strip()
        if key in updates:
            new_lines.append(f"{key}={_quote_env_value(str(updates[key]))}")
            seen.add(key)
        else:
            new_lines.append(line)
    if new_lines and new_lines[-1].strip():
        new_lines.append("")
    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={_quote_env_value(str(value))}")
    path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
    return path


def _normalize_phone(number: str) -> str:
    if not number:
        raise TelephonyError("Phone number is required")
    trimmed = number.strip()
    if not trimmed.startswith("+"):
        raise TelephonyError(
            f"Phone number must be E.164 format (for example +15551234567), got: {number}"
        )
    digits = "+" + re.sub(r"\D", "", trimmed)
    if len(digits) < 8:
        raise TelephonyError(f"Phone number looks too short: {number}")
    return digits


def _mask_phone(number: str) -> str:
    digits = re.sub(r"\D", "", number or "")
    if len(digits) < 4:
        return "***"
    return f"***-***-{digits[-4:]}"


def _json_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    form: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"
    request_headers = dict(headers or {})
    body: bytes | None = None
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    elif form is not None:
        body = urllib.parse.urlencode(form, doseq=True).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, headers=request_headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            parsed = json.loads(body_text) if body_text else {}
        except Exception:
            parsed = {"raw": body_text}
        raise TelephonyError(f"HTTP {exc.code} from {url}: {parsed or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise TelephonyError(f"Connection error for {url}: {exc.reason}") from exc


def _twilio_creds() -> tuple[str, str]:
    sid = _env_or_config("TWILIO_ACCOUNT_SID")
    token = _env_or_config("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        raise TelephonyError(
            "Twilio credentials are not configured. Use 'save-twilio' or set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in ~/.henio/.env."
        )
    return sid, token


def _twilio_request(method: str, path: str, *, params=None, form=None) -> dict[str, Any]:
    sid, _token = _twilio_creds()
    return _json_request(method, f"{TWILIO_API_BASE}/{sid}/{path.lstrip('/')}" , params=params, form=form)


def _twilio_owned_numbers(limit: int = 50) -> list[OwnedTwilioNumber]:
    payload = _twilio_request("GET", "IncomingPhoneNumbers.json", params={"PageSize": limit})
    items = payload.get("incoming_phone_numbers", []) or []
    results: list[OwnedTwilioNumber] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        caps = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
        results.append(OwnedTwilioNumber(
            sid=str(item.get("sid", "")),
            phone_number=str(item.get("phone_number", "")),
            friendly_name=str(item.get("friendly_name", "")),
            capabilities=caps,
        ))
    return results


def _remember_twilio_number(*, phone_number: str, phone_sid: str = "", save_env: bool = False, state_path: Path | None = None, env_path: Path | None = None) -> dict[str, Any]:
    state = _load_state(state_path)
    twilio_state = state.setdefault("twilio", {})
    twilio_state["default_phone_number"] = phone_number
    if phone_sid:
        twilio_state["default_phone_sid"] = phone_sid
    _save_state(state, state_path)
    saved_env_keys: list[str] = []
    if save_env:
        updates = {"TWILIO_PHONE_NUMBER": phone_number}
        if phone_sid:
            updates["TWILIO_PHONE_NUMBER_SID"] = phone_sid
        _upsert_env_file(updates, env_path)
        saved_env_keys = sorted(updates)
    return {"state_path": str(state_path or _state_path()), "saved_env_keys": saved_env_keys}


def _remember_vapi_number(*, phone_number_id: str, save_env: bool = False, state_path: Path | None = None, env_path: Path | None = None) -> dict[str, Any]:
    state = _load_state(state_path)
    vapi_state = state.setdefault("vapi", {})
    vapi_state["phone_number_id"] = phone_number_id
    _save_state(state, state_path)
    saved_env_keys: list[str] = []
    if save_env:
        _upsert_env_file({"VAPI_PHONE_NUMBER_ID": phone_number_id}, env_path)
        saved_env_keys = ["VAPI_PHONE_NUMBER_ID"]
    return {"state_path": str(state_path or _state_path()), "saved_env_keys": saved_env_keys}


def _resolve_twilio_number(identifier: str | None = None) -> OwnedTwilioNumber:
    if identifier:
        wanted = identifier.strip()
        normalized = _normalize_phone(wanted) if wanted.startswith("+") else None
        for item in _twilio_owned_numbers(limit=100):
            if item.sid == wanted or item.phone_number == normalized:
                return item
        raise TelephonyError(f"Could not find an owned Twilio number matching {identifier}")

    env_number = _env_or_config("TWILIO_PHONE_NUMBER")
    env_sid = _env_or_config("TWILIO_PHONE_NUMBER_SID")
    state = _load_state()
    twilio_state = state.get("twilio", {}) if isinstance(state.get("twilio"), dict) else {}
    preferred_number = env_number or str(twilio_state.get("default_phone_number", ""))
    preferred_sid = env_sid or str(twilio_state.get("default_phone_sid", ""))
    owned = _twilio_owned_numbers(limit=100)
    if preferred_sid:
        for item in owned:
            if item.sid == preferred_sid:
                return item
    if preferred_number:
        normalized = _normalize_phone(preferred_number)
        for item in owned:
            if item.phone_number == normalized:
                return item
    if len(owned) == 1:
        return owned[0]
    raise TelephonyError(
        "No default Twilio phone number is set. Use 'twilio-buy --save-env', 'twilio-set-default', or set TWILIO_PHONE_NUMBER in ~/.henio/.env."
    )


def _vapi_api_key() -> str:
    return _env_or_config("VAPI_API_KEY")


def _bland_api_key() -> str:
    return _env_or_config("BLAND_API_KEY")


def _ai_provider(default: str = DEFAULT_AI_PROVIDER) -> str:
    return _env_or_config("PHONE_PROVIDER", default=default).lower().strip()


def _twilio_buy_number(phone_number: str, *, save_env: bool = False, state_path: Path | None = None, env_path: Path | None = None) -> dict[str, Any]:
    normalized = _normalize_phone(phone_number)
    payload = _twilio_request("POST", "IncomingPhoneNumbers.json", form={"PhoneNumber": normalized})
    purchased = {
        "success": True,
        "provider": "twilio",
        "phone_number": payload.get("phone_number", normalized),
        "phone_sid": payload.get("sid"),
        "friendly_name": payload.get("friendly_name"),
        "capabilities": payload.get("capabilities", {}),
        "message": "Twilio number purchased successfully.",
    }
    purchased.update(_remember_twilio_number(
        phone_number=str(purchased["phone_number"]),
        phone_sid=str(purchased.get("phone_sid") or ""),
        save_env=save_env,
        state_path=state_path,
        env_path=env_path,
    ))
    return purchased


def _checkpoint_for_messages(messages: list[dict[str, Any]]) -> tuple[str, str]:
    if not messages:
        return "", ""
    newest = messages[0]
    return str(newest.get("sid") or ""), str(newest.get("date_sent") or newest.get("date_created") or "")


def _messages_after_checkpoint(messages: list[dict[str, Any]], last_sid: str) -> list[dict[str, Any]]:
    if not last_sid:
        return messages
    filtered: list[dict[str, Any]] = []
    for message in messages:
        if str(message.get("sid") or "") == last_sid:
            break
        filtered.append(message)
    return filtered


def _twilio_inbox(*, limit: int = 20, since_last: bool = False, mark_seen: bool = False, phone_identifier: str | None = None, state_path: Path | None = None) -> dict[str, Any]:
    owned = _resolve_twilio_number(phone_identifier)
    payload = _twilio_request("GET", "Messages.json", params={"To": owned.phone_number, "PageSize": max(1, min(limit, 100))})
    raw_messages = payload.get("messages", []) or []
    messages = [m for m in raw_messages if isinstance(m, dict)]
    state = _load_state(state_path)
    twilio_state = state.setdefault("twilio", {})
    last_sid = str(twilio_state.get("last_inbound_message_sid", ""))
    if since_last:
        messages = _messages_after_checkpoint(messages, last_sid)
    message_rows = [{
        "sid": msg.get("sid"),
        "direction": msg.get("direction"),
        "status": msg.get("status"),
        "from_phone_number": msg.get("from"),
        "to_phone_number": msg.get("to"),
        "date_sent": msg.get("date_sent"),
        "body": msg.get("body"),
        "num_media": msg.get("num_media"),
    } for msg in messages]
    if mark_seen and message_rows:
        last_seen_sid, last_seen_date = _checkpoint_for_messages(message_rows)
        twilio_state["last_inbound_message_sid"] = last_seen_sid
        twilio_state["last_inbound_message_date"] = last_seen_date
        _save_state(state, state_path)
    return {
        "success": True,
        "provider": "twilio",
        "phone_number": owned.phone_number,
        "count": len(message_rows),
        "messages": message_rows,
        "since_last": since_last,
        "marked_seen": bool(mark_seen and message_rows),
        "state_path": str(state_path or _state_path()),
        "last_seen_message_sid": twilio_state.get("last_inbound_message_sid", ""),
    }


def _vapi_import_twilio_number(*, phone_identifier: str | None = None, save_env: bool = False, state_path: Path | None = None, env_path: Path | None = None) -> dict[str, Any]:
    api_key = _vapi_api_key()
    if not api_key:
        raise TelephonyError(
            "Vapi is not configured. Use 'save-vapi' or set VAPI_API_KEY in ~/.henio/.env first."
        )
    owned = _resolve_twilio_number(phone_identifier)
    sid, token = _twilio_creds()
    payload = _json_request(
        "POST",
        f"{VAPI_API_BASE}/phone-number",
        headers={"Authorization": f"Bearer {api_key}"},
        json_body={
            "provider": "twilio",
            "number": owned.phone_number,
            "twilioAccountSid": sid,
            "twilioAuthToken": token,
        },
    )
    phone_number_id = str(payload.get("id") or "")
    if not phone_number_id:
        raise TelephonyError(f"Vapi did not return a phone number id: {payload}")
    result = {
        "success": True,
        "provider": "vapi",
        "phone_number_id": phone_number_id,
        "phone_number": owned.phone_number,
        "message": "Twilio number imported into Vapi.",
    }
    result.update(_remember_vapi_number(
        phone_number_id=phone_number_id,
        save_env=save_env,
        state_path=state_path,
        env_path=env_path,
    ))
    return result


def _provider_decision_tree() -> list[dict[str, str]]:
    return [
        {
            "need": "I want the agent to own a real number for SMS, inbound polling, or future telephony identity.",
            "use": "Twilio",
            "why": "Twilio is the clearest path to provisioning numbers, sending SMS/MMS, polling inbound texts, and later webhook-based inbound telephony.",
        },
        {
            "need": "I only want the easiest outbound AI voice calls right now.",
            "use": "Bland.ai",
            "why": "Bland is the simplest outbound AI calling setup: one API key, no separate number import flow.",
        },
        {
            "need": "I want premium conversational voice quality for AI calls, ideally on my own number.",
            "use": "Twilio + Vapi",
            "why": "Buy/import the number with Twilio, then import it into Vapi for better voices and more flexible assistants.",
        },
    ]


def diagnose() -> dict[str, Any]:
    state = _load_state()
    twilio_state = state.get("twilio", {}) if isinstance(state.get("twilio"), dict) else {}
    vapi_state = state.get("vapi", {}) if isinstance(state.get("vapi"), dict) else {}
    provider = _ai_provider()
    twilio_sid = _env_or_config("TWILIO_ACCOUNT_SID")
    twilio_token = _env_or_config("TWILIO_AUTH_TOKEN")
    twilio_phone = _env_or_config("TWILIO_PHONE_NUMBER", default=str(twilio_state.get("default_phone_number", "")))
    bland_key = _bland_api_key()
    vapi_key = _vapi_api_key()
    vapi_phone_id = _env_or_config("VAPI_PHONE_NUMBER_ID", default=str(vapi_state.get("phone_number_id", "")))
    return {
        "success": True,
        "state_path": str(_state_path()),
        "env_path": str(_env_path()),
        "ai_call_provider": provider,
        "providers": {
            "twilio": {
                "account_sid_configured": bool(twilio_sid),
                "auth_token_configured": bool(twilio_token),
                "default_phone_number": twilio_phone,
                "default_phone_sid": twilio_state.get("default_phone_sid", ""),
                "last_inbound_message_sid": twilio_state.get("last_inbound_message_sid", ""),
                "last_inbound_message_date": twilio_state.get("last_inbound_message_date", ""),
            },
            "bland": {
                "configured": bool(bland_key),
                "default_voice": _env_or_config("BLAND_DEFAULT_VOICE", default=BLAND_DEFAULT_VOICE),
            },
            "vapi": {
                "configured": bool(vapi_key),
                "phone_number_id": vapi_phone_id,
                "voice_provider": _env_or_config("VAPI_VOICE_PROVIDER", default=VAPI_DEFAULT_VOICE_PROVIDER),
                "voice_id": _env_or_config("VAPI_VOICE_ID", default=VAPI_DEFAULT_VOICE_ID),
                "model": _env_or_config("VAPI_MODEL", default=VAPI_DEFAULT_MODEL),
            },
        },
        "decision_tree": _provider_decision_tree(),
        "notes": [
            "Twilio is the best path for owning a durable phone number, texting, and polling inbound SMS.",
            "Bland is the easiest path for outbound AI calls only.",
            "Vapi is best when you want better AI voice quality, usually backed by a Twilio-owned number.",
            "VoIP numbers are not guaranteed to work for every third-party 2FA flow.",
        ],
    }


def save_twilio(account_sid: str, auth_token: str, phone_number: str = "", phone_sid: str = "") -> dict[str, Any]:
    updates = {
        "TWILIO_ACCOUNT_SID": account_sid.strip(),
        "TWILIO_AUTH_TOKEN": auth_token.strip(),
    }
    normalized_phone = ""
    if phone_number:
        normalized_phone = _normalize_phone(phone_number)
        updates["TWILIO_PHONE_NUMBER"] = normalized_phone
    if phone_sid:
        updates["TWILIO_PHONE_NUMBER_SID"] = phone_sid.strip()
    env_file = _upsert_env_file(updates)
    result = {
        "success": True,
        "provider": "twilio",
        "saved_env_keys": sorted(updates),
        "env_path": str(env_file),
        "message": "Twilio credentials saved to ~/.henio/.env.",
    }
    if normalized_phone:
        result.update(_remember_twilio_number(
            phone_number=normalized_phone,
            phone_sid=phone_sid.strip(),
            save_env=False,
        ))
    return result
