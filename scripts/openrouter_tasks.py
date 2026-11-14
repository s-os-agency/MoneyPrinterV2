#!/usr/bin/env python3
"""Produce text artifacts from an owner-maintained JSON task queue."""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from classes.OpenRouter import OpenRouterClient, OpenRouterError  # noqa: E402


def load_tasks(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        tasks = json.load(handle)
    if not isinstance(tasks, list) or len(tasks) > 1000:
        raise ValueError("The task queue must be an array of at most 1000 tasks.")
    ids = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("Every queue entry must be a task object.")
        task_id = task.get("id", "")
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", task_id):
            raise ValueError("Task IDs must contain 1-100 letters, digits, underscores or hyphens.")
        if task_id in ids:
            raise ValueError("Task IDs must be unique.")
        ids.add(task_id)
        if task.get("repeat", "once") not in {"once", "hourly", "daily"}:
            raise ValueError("Task repeat must be once, hourly or daily.")
        if not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
            raise ValueError("Every task needs a non-empty prompt.")
        if not isinstance(task.get("enabled", True), bool):
            raise ValueError("Task enabled must be a JSON boolean.")
        for field in ("model", "kind"):
            if field in task and not isinstance(task[field], str):
                raise ValueError("Task model and kind must be strings.")
    return tasks


def run_key(task: dict, now: datetime) -> str:
    repeat = task.get("repeat", "once")
    slot = "once" if repeat == "once" else now.strftime("%Y-%m-%dT%H%z" if repeat == "hourly" else "%Y-%m-%d")
    return task["id"] + ":" + slot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=ROOT / "tasks" / "openrouter_tasks.json")
    parser.add_argument("--state-dir", type=Path, default=ROOT / ".mp" / "openrouter")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--list-models", action="store_true", help="Print the currently eligible text model IDs and catalog prices.")
    parser.add_argument("--account-status", action="store_true", help="Read key authorization and numeric limits without generating text.")
    args = parser.parse_args()
    if not 1 <= args.limit <= 20:
        parser.error("--limit must be between 1 and 20")
    client = OpenRouterClient()
    if args.account_status:
        print(json.dumps({"key_present": bool(client.key),
                          "key_has_outer_whitespace": client.key != client.key.strip(),
                          "key_has_bearer_prefix": client.key.lower().startswith("bearer "),
                          "key_has_expected_prefix": client.key.startswith("sk-or-")}))
        data = client._request("/key").get("data", {})
        status = {"key_authorized": True, "is_free_tier": data.get("is_free_tier") is True}
        for field in ("limit", "limit_remaining", "usage_monthly"):
            value = data.get(field)
            status[field] = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        print(json.dumps(status))
        return 0
    if args.list_models:
        for model in client.eligible_models():
            print(json.dumps({"id": model["id"], "pricing": model["pricing"]}))
        return 0
    if not client.key:
        print("No tasks executed: add the OPENROUTER_API_KEY runtime secret.")
        return 0
    tasks = load_tasks(args.queue)
    args.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_dir = args.state_dir / "outputs"
    output_dir.mkdir(mode=0o700, exist_ok=True)
    db_path = args.state_dir / "runs.sqlite3"
    connection = sqlite3.connect(db_path, timeout=30)
    os.chmod(db_path, 0o600)
    connection.execute("""CREATE TABLE IF NOT EXISTS task_runs (
        run_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, task_id TEXT NOT NULL,
        status TEXT NOT NULL, started_at TEXT NOT NULL, output_file TEXT,
        receipt_json TEXT, error TEXT
    )""")
    connection.commit()
    now = datetime.now(ZoneInfo(os.environ.get("TASK_TIMEZONE", "Asia/Dubai")))
    started = 0
    try:
        for task in tasks:
            if not task.get("enabled", True) or started >= args.limit:
                continue
            key = run_key(task, now)
            fingerprint = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT fingerprint, status FROM task_runs WHERE run_key = ?", (key,)).fetchone()
            if existing:
                connection.rollback()
                # In-flight or failed calls are not silently retried: their billing may be uncertain.
                print(json.dumps({"task_id": task["id"], "state": existing[1], "action": "skipped_existing", "same_input": existing[0] == fingerprint}))
                continue
            connection.execute("INSERT INTO task_runs(run_key,fingerprint,task_id,status,started_at) VALUES(?,?,?,?,?)",
                               (key, fingerprint, task["id"], "in_flight", now.isoformat()))
            connection.commit()
            started += 1
            client.last_receipt = None
            try:
                text = client.generate(task["prompt"], task.get("model", "auto"), task.get("kind", "routine"))
                output_path = output_dir / (hashlib.sha256(key.encode()).hexdigest() + ".md")
                with output_path.open("w", encoding="utf-8") as handle:
                    os.chmod(output_path, 0o600)
                    handle.write(text + "\n")
                connection.execute("UPDATE task_runs SET status=?, output_file=?, receipt_json=? WHERE run_key=?",
                                   ("completed", str(output_path), json.dumps(client.last_receipt), key))
                connection.commit()
                # Public logs deliberately omit prompts, generated text and private key-budget data.
                print(json.dumps({"task_id": task["id"], "state": "completed", "model": client.last_receipt.get("model")}))
            except OpenRouterError as error:
                connection.execute("UPDATE task_runs SET status=?, receipt_json=?, error=? WHERE run_key=?",
                                   ("stopped", json.dumps(client.last_receipt), str(error), key))
                connection.commit()
                print(json.dumps({"task_id": task["id"], "state": "stopped", "reason": str(error)}))
                return 1
            except Exception:
                connection.execute("UPDATE task_runs SET status=?, receipt_json=?, error=? WHERE run_key=?",
                                   ("stopped", json.dumps(client.last_receipt), "Local artifact operation failed; no automatic retry.", key))
                connection.commit()
                print(json.dumps({"task_id": task["id"], "state": "stopped", "reason": "Local artifact operation failed; no automatic retry."}))
                return 1
    finally:
        connection.close()
    print(json.dumps({"tasks_started": started, "outbound_business_actions": 0}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OpenRouterError as error:
        print(str(error))
        raise SystemExit(1)
    except (ValueError, OSError):
        print("Worker stopped because its queue, configuration or connection is unavailable. No automatic retry.")
        raise SystemExit(1)
