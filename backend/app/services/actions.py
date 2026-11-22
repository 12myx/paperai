"""Persistent, user-bound confirmations for agent write actions.

Atomic claim is implemented as a conditional UPDATE on a unique action row.
This guarantees at-most-once *claim* per action in SQLite and PostgreSQL; it
does not magically make arbitrary external side effects exactly-once. The
execution status is persisted and reconciled after a restart.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ActionRequest, User, utcnow

ACTION_TTL_SECONDS = 10 * 60


class ActionError(RuntimeError):
    pass


def canonical_args(args: dict[str, Any]) -> str:
    return json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def args_digest(args: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_args(args).encode("utf-8")).hexdigest()[:16]


def _secret() -> bytes:
    return (settings.secret_key or "development-secret").encode("utf-8")


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_action(user_id: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    expires = int(time.time()) + ACTION_TTL_SECONDS
    payload = json.dumps(
        {"u": user_id, "t": tool, "d": args_digest(args), "e": expires},
        separators=(",", ":"), sort_keys=True,
    )
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    token = encoded + "." + _sign(payload)
    return {"action_id": token, "expires_at": expires, "args_digest": args_digest(args)}


def _decode(action_id: str) -> dict[str, Any]:
    try:
        encoded, signature = action_id.rsplit(".", 1)
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise ActionError("确认令牌格式无效") from exc
    if not hmac.compare_digest(_sign(payload), signature):
        raise ActionError("确认令牌签名无效")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ActionError("确认令牌内容无效") from exc
    return data


def _expiry_datetime(expires: int) -> datetime:
    return datetime.fromtimestamp(expires, tz=timezone.utc).replace(tzinfo=None)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_action(db: Session, user: User, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    token = issue_action(user.id, tool, args)
    row = ActionRequest(
        id=token["action_id"],
        user_id=user.id,
        tool_name=tool,
        args_json=canonical_args(args),
        args_digest=token["args_digest"],
        status="pending",
        expires_at=_expiry_datetime(int(token["expires_at"])),
    )
    db.add(row)
    db.commit()
    return token


def _verify_row(row: ActionRequest, user_id: str, tool: str, args: dict[str, Any]) -> None:
    if row.user_id != user_id:
        raise ActionError("确认令牌不属于当前用户")
    if row.tool_name != tool:
        raise ActionError("确认令牌与操作类型不匹配")
    if row.args_digest != args_digest(args):
        raise ActionError("确认参数与待确认内容不一致")
    if row.expires_at < _utcnow():
        raise ActionError("确认令牌已过期，请重新发起操作")
    if row.status in {"succeeded", "failed", "expired", "rejected", "executing"}:
        raise ActionError(f"该确认令牌当前状态为 {row.status}，不能重复执行")


def claim_action(db: Session, user_id: str, tool: str, args: dict[str, Any], action_id: str) -> ActionRequest:
    """Atomically change pending -> executing. Only one caller can win."""
    data = _decode(action_id)
    if data.get("u") != user_id or data.get("t") != tool or data.get("d") != args_digest(args):
        raise ActionError("确认令牌与当前用户、工具或参数不匹配")
    if int(data.get("e", 0)) < int(time.time()):
        raise ActionError("确认令牌已过期，请重新发起操作")

    now = _utcnow()
    result = db.execute(
        update(ActionRequest)
        .where(
            ActionRequest.id == action_id,
            ActionRequest.user_id == user_id,
            ActionRequest.tool_name == tool,
            ActionRequest.args_digest == args_digest(args),
            ActionRequest.status == "pending",
            ActionRequest.expires_at > now,
        )
        .values(status="executing", confirmed_at=now, started_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if result.rowcount != 1:
        row = db.get(ActionRequest, action_id)
        if row is None:
            raise ActionError("确认记录不存在，可能已被清理")
        _verify_row(row, user_id, tool, args)
        raise ActionError(f"该确认令牌当前状态为 {row.status}，不能重复执行")
    row = db.get(ActionRequest, action_id)
    if row is None:
        raise ActionError("确认记录不存在")
    return row


def finish_action(db: Session, action_id: str, *, status: str, summary: str | None = None, error: str | None = None) -> None:
    db.execute(
        update(ActionRequest)
        .where(ActionRequest.id == action_id)
        .values(status=status, finished_at=_utcnow(), result_summary=(summary or "")[:2000] or None, error=(error or "")[:2000] or None)
        .execution_options(synchronize_session=False)
    )
    db.commit()


def expire_actions(db: Session, *, limit: int = 500) -> int:
    """Mark pending expired actions; never delete executing or completed rows."""
    now = _utcnow()
    result = db.execute(
        update(ActionRequest)
        .where(ActionRequest.status == "pending", ActionRequest.expires_at <= now)
        .values(status="expired", finished_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return int(result.rowcount or 0)


def reconcile_stale_actions(db: Session, *, older_than_seconds: int = 300) -> int:
    """After a crash, an executing row may be stale. Mark it failed, not retryable."""
    cutoff = _utcnow() - timedelta(seconds=older_than_seconds)
    result = db.execute(
        update(ActionRequest)
        .where(ActionRequest.status == "executing", ActionRequest.started_at < cutoff)
        .values(status="failed", finished_at=_utcnow(), error="服务重启后未完成，状态已标记失败；请重新发起操作")
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return int(result.rowcount or 0)


def action_status(db: Session, user_id: str, action_id: str) -> dict | None:
    row = db.get(ActionRequest, action_id)
    if row is None or row.user_id != user_id:
        return None
    return {
        "action_id": row.id,
        "tool": row.tool_name,
        "status": row.status,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "error": row.error,
        "result_summary": row.result_summary,
    }
