"""Run real FastAPI requests over a local process pipe for an isolated synthetic recording."""

import argparse
import asyncio
import base64
import json
import os
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--data-dir", type=Path, required=True)
args = parser.parse_args()
target = args.data_dir.resolve()
with sqlite3.connect((target / "runtime/app.sqlite3").as_uri() + "?mode=ro", uri=True) as connection:
    rows = connection.execute("SELECT source FROM jobs").fetchall()
if len(rows) != 2 or any(row[0] != "synthetic-demo" for row in rows):
    raise SystemExit("Recording bridge requires only the two synthetic demo jobs.")
os.environ["DATA_DIR"] = str(target)
os.environ["DEEPSEEK_API_KEY"] = ""
sys.path.insert(0, str(ROOT / "backend"))
from app.main import app


async def dispatch(item):
    body = item.get("body", "").encode("utf-8")
    events = []
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Future()

    async def send(event):
        events.append(event)

    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1", "method": item["method"], "scheme": "http",
        "path": item["path"], "raw_path": item["path"].encode(),
        "query_string": item.get("query", "").encode(), "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 0), "server": ("demo.local", 80),
    }
    await app(scope, receive, send)
    start = next(event for event in events if event["type"] == "http.response.start")
    payload = b"".join(event.get("body", b"") for event in events if event["type"] == "http.response.body")
    return {"id": item["id"], "status": start["status"],
            "headers": {key.decode("latin-1"): value.decode("latin-1") for key, value in start["headers"]},
            "body": base64.b64encode(payload).decode("ascii")}


for line in sys.stdin:
    item = json.loads(line)
    try:
        response = asyncio.run(dispatch(item))
    except Exception as error:
        response = {"id": item["id"], "error": str(error)}
    print(json.dumps(response), flush=True)
