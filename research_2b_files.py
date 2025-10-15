#!/usr/bin/env python3
"""MCP server that demonstrates durable resource links for price tracking."""

import asyncio
import json
import os
import random
import re
import uuid
import urllib.parse
from pathlib import Path
from typing import Any

import anyio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Resource, ResourceLink, TextContent, TextResourceContents, Tool

try:  
    from pydantic import AnyUrl  
except Exception:  
    AnyUrl = None  
else:  
    if AnyUrl is not None and not hasattr(AnyUrl, "decode"):
        def _anyurl_decode(self, encoding: str = "utf-8", errors: str = "strict") -> str:
            return str(self)

        AnyUrl.decode = _anyurl_decode 

# Allow overriding the storage directory so the demo can run in different environments.
STORE_DIR = Path(os.getenv("DURABILITY_STORE", Path(__file__).parent / "flight_watch_store"))
STORE_DIR.mkdir(parents=True, exist_ok=True)

# DeepAgents instances call into this server to persist snapshots produced by their agents.
server = Server("durable-flight-watch")


def _as_json(model: Any) -> dict[str, Any]:
    """Return a Pydantic model as a plain dict with JSON-serializable values."""
    return json.loads(model.model_dump_json()) if hasattr(model, "model_dump_json") else model


def _resource_uri(file_path: Path) -> str:
    # Use file:// URIs per MCP resource-link recommendations.
    # Use absolute path to ensure compatibility
    absolute_path = file_path.resolve()
    # Convert Windows paths to forward slashes
    path_str = str(absolute_path).replace('\\', '/')
    # Ensure proper file:// URI format
    if not path_str.startswith('/'):
        path_str = '/' + path_str
    return f"file://{path_str}"


def _slugify(*parts: str) -> str:
    tokens: list[str] = []
    for part in parts:
        if not part:
            continue
        token = re.sub(r"[^a-z0-9]+", "-", str(part).lower()).strip("-")
        if token:
            tokens.append(token)
    return "-".join(tokens) or "watch"


def _allocate_watch_file(watch_id: str, origin: str, destination: str, departure_date: str) -> tuple[Path, str, str]:
    base_slug = _slugify(origin, destination, departure_date)
    candidate = f"{base_slug}-{watch_id[:8]}"
    file_name = f"{candidate}.json"
    path = STORE_DIR / file_name
    suffix = 1
    while path.exists():
        candidate = f"{base_slug}-{watch_id[:8]}-{suffix}"
        file_name = f"{candidate}.json"
        path = STORE_DIR / file_name
        suffix += 1
    resource_name = f"flight-watch-{candidate}"
    return path, file_name, resource_name


def _locate_watch_file(watch_id: str) -> Path:
    legacy_path = STORE_DIR / f"{watch_id}.json"
    if legacy_path.exists():
        return legacy_path

    for path in STORE_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if payload.get("watch_id") == watch_id:
            return path

    raise FileNotFoundError(f"Flight watch {watch_id} not found")


def _write_watch_file(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2))


def _parse_watch_id(uri: str | Any) -> str:
    """Parse watch_id from a file:// URI."""
    # Convert to string in case it's a Pydantic AnyUrl object
    uri_str = str(uri)
    
    parsed = urllib.parse.urlparse(uri_str)
    
    # Accept both 'file' and empty scheme (for compatibility)
    if parsed.scheme and parsed.scheme != "file":
        raise ValueError(f"Unsupported resource scheme: {uri_str}")

    # Extract the file path from the URI
    # Handle both file:// and file:/// formats
    file_path_str = urllib.parse.unquote(parsed.path)
    
    # Remove leading slash on Windows if present (e.g., /C:/path)
    if len(file_path_str) > 2 and file_path_str[0] == '/' and file_path_str[2] == ':':
        file_path_str = file_path_str[1:]
    
    # Try to find the file by name in STORE_DIR
    file_name = Path(file_path_str).name
    file_path = STORE_DIR / file_name
    
    if not file_path.exists():
        raise FileNotFoundError(f"Durable resource path not found: {file_path}")

    try:
        payload = json.loads(file_path.read_text())
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid resource payload at {file_path}") from exc

    watch_id = payload.get("watch_id")
    if not watch_id:
        # Fallback: try to extract from filename
        watch_id = file_path.stem.split("-")[-1]
    
    if not watch_id:
        raise ValueError(f"Unable to parse durable resource URI: {uri_str}")

    return str(watch_id)


def _load_watch(watch_id: str) -> dict[str, Any]:
    path = _locate_watch_file(watch_id)
    payload = json.loads(path.read_text())
    payload.setdefault("file_name", path.name)
    payload.setdefault("resource_name", f"flight-watch-{path.stem}")
    return payload


def _save_watch(watch_id: str, payload: dict[str, Any]) -> None:
    file_name = payload.get("file_name")
    if file_name:
        path = STORE_DIR / file_name
    else:
        path = _locate_watch_file(watch_id)
        payload["file_name"] = path.name
    _write_watch_file(path, payload)


async def _simulate_price_updates(
    watch_id: str,
    *,
    session,
    uri: str,
    target_price: float | None,
    jitter_seed: int,
    progress_token: Any | None = None,
) -> None:
    """Simulate a fare watcher that emits resource updates when prices change."""
    rng = random.Random(jitter_seed)
    while True:
        await anyio.sleep(rng.uniform(1.0, 2.0))
        payload = _load_watch(watch_id)
        if payload.get("status") in {"notified", "cancelled"}:
            break

        current_price = payload["history"][-1]["price"]
        delta = rng.randint(-40, 20)
        new_price = max(current_price + delta, 50)
        stage = {
            "sequence": len(payload["history"]),
            "status": "price_update",
            "price": new_price,
            "note": "Received new quote from fare service.",
        }
        payload["history"].append(stage)

        if target_price is not None and new_price <= target_price:
            payload["status"] = "notified"
            payload["summary"] = (
                f"🎉 PRICE ALERT! Flight {payload['origin']} → {payload['destination']} "
                f"dropped to ${new_price} (target was ${target_price})"
            )
            print(f"⚠️  PRICE ALERT: {payload['summary']}", flush=True)
        else:
            payload["status"] = "watching"
            print(f"📊 Price update: {payload['origin']} → {payload['destination']} "
                  f"now ${new_price} (was ${current_price})", flush=True)

        _save_watch(watch_id, payload)
        
        try:
            await session.send_resource_updated(uri=uri)
            print(f"✅ Sent resource update notification for {uri}", flush=True)
            
            # Send progress notification to VS Code
            if progress_token:
                history_len = len(payload["history"])
                status_emoji = "🚨" if payload["status"] == "notified" else "📊"
                
                if payload["status"] == "notified":
                    message = (
                        f"{status_emoji} PRICE ALERT!\n"
                        f"Flight: {payload['origin']} → {payload['destination']}\n"
                        f"Price dropped to ${new_price} (target: ${target_price})\n"
                        f"Book now!"
                    )
                else:
                    price_change = new_price - current_price
                    change_indicator = "📈" if price_change > 0 else "📉"
                    message = (
                        f"{status_emoji} Price Update #{history_len}\n"
                        f"Flight: {payload['origin']} → {payload['destination']}\n"
                        f"Current price: ${new_price} {change_indicator}\n"
                        f"Target: ${target_price if target_price else 'Not set'}"
                    )
                
                await session.send_progress_notification(
                    progress_token=progress_token,
                    progress=history_len,
                    total=history_len + 1,  # We don't know total updates in advance
                    message=message,
                )
                print("✅ Sent progress notification for price update", flush=True)
        except Exception as e:
            print(f"❌ Failed to send notification: {e}", flush=True)

        if payload["status"] == "notified":
            break


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(
            name="track_flight_price",
            description=(
                "Persist an itinerary snapshot and obtain a durable resource link "
                "that streams fare updates for out-of-band monitoring."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "origin": {
                        "type": "string",
                        "description": "IATA code or city for departure (e.g., LHR).",
                    },
                    "destination": {
                        "type": "string",
                        "description": "IATA code or city for arrival (e.g., LIS).",
                    },
                    "departure_date": {
                        "type": "string",
                        "description": "ISO date string for the desired travel date.",
                    },
                    "initial_price": {
                        "type": "number",
                        "description": "The latest fare quote captured by the agent.",
                    },
                    "target_price": {
                        "type": "number",
                        "description": "Optional alert threshold for the traveler.",
                    },
                    "context_file": {
                        "type": "string",
                        "description": "Optional DeepAgents virtual file name for provenance.",
                    },
                },
                "required": ["origin", "destination", "departure_date", "initial_price"],
            },
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any] | None):
    ctx = server.request_context
    if arguments is None:
        arguments = {}

    if name != "track_flight_price":
        raise ValueError(f"Unknown tool: {name}")

    origin = arguments.get("origin")
    destination = arguments.get("destination")
    departure_date = arguments.get("departure_date")
    initial_price = arguments.get("initial_price")
    target_price = arguments.get("target_price")
    context_file = arguments.get("context_file")

    if None in {origin, destination, departure_date, initial_price}:
        raise ValueError(
            "Missing required arguments: origin, destination, departure_date, initial_price"
        )

    origin_str = str(origin)
    destination_str = str(destination)
    departure_date_str = str(departure_date)

    watch_id = uuid.uuid4().hex

    payload = {
        "watch_id": watch_id,
        "origin": origin_str,
        "destination": destination_str,
        "departure_date": departure_date_str,
        "status": "watching",
        "target_price": target_price,
        "context_file": context_file,
        "history": [
            {
                "sequence": 0,
                "status": "snapshot",
                "price": float(initial_price) if initial_price is not None else 0.0,
                "note": "Initial fare captured by DeepAgents research step.",
            }
        ],
    }
    file_path, file_name, resource_name = _allocate_watch_file(
        watch_id, origin_str, destination_str, departure_date_str
    )
    payload["file_name"] = file_name
    payload["resource_name"] = resource_name
    _write_watch_file(file_path, payload)

    uri = _resource_uri(file_path)

    # Extract progress token from request metadata
    progress_token = None
    if ctx and ctx.meta:
        progress_token = ctx.meta.progressToken

    session = ctx.session if ctx else None
    if session is not None:
        asyncio.create_task(
            _simulate_price_updates(
                watch_id,
                session=session,
                uri=uri,
                target_price=float(target_price) if target_price is not None else None,
                jitter_seed=random.randint(0, 2**32 - 1),
                progress_token=progress_token,
            )
        )

    link_meta = {
        "origin": origin_str,
        "destination": destination_str,
        "departure_date": departure_date_str,
        "status": payload["status"],
        "file_name": file_name,
        "resource_name": resource_name,
        "watch_id": watch_id,
    }

    return [
        _as_json(
            TextContent(
                type="text",
                text=(
                    f"✅ Fare watch registered for {origin_str} → {destination_str} on {departure_date_str}.\n\n"
                    f"Initial price: ${initial_price}\n"
                    f"Target alert price: ${target_price if target_price else 'Not set'}\n\n"
                    "I'll monitor this flight and notify you when the price changes. "
                    "The tracking data is saved in a persistent resource that you can check anytime. "
                    "To ensure you receive notifications, please subscribe to this resource in VS Code."
                ),
            )
        ),
        _as_json(
            ResourceLink(
                type="resource_link",
                name=resource_name,
                uri=uri,
                description=f"Flight watch: {origin_str} → {destination_str} ({departure_date_str})",
                mimeType="application/json",
                meta=link_meta,
            )
        ),
    ]


@server.list_resources()
async def handle_list_resources() -> list[Resource]:
    resources: list[Resource] = []
    for path in sorted(STORE_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
            
        watch_id = str(payload.get("watch_id") or path.stem)
        file_name = payload.get("file_name") or path.name
        resource_name = payload.get("resource_name") or f"flight-watch-{Path(file_name).stem}"
        description = "Flight watch: {origin} → {destination}".format(
            origin=payload.get("origin", "?"),
            destination=payload.get("destination", "?"),
        )
        resources.append(
            Resource(
                name=resource_name,
                uri=_resource_uri(path),
                description=description,
                mimeType="application/json",
            )
        )
    return resources


@server.read_resource()
async def handle_read_resource(uri: str) -> str:
    watch_id = _parse_watch_id(uri)
    payload = _load_watch(watch_id)
    return json.dumps(payload, indent=2)


@server.subscribe_resource()
async def handle_subscribe_resource(uri: str) -> None:
    """Handle resource subscription requests from VS Code."""
    # Validate that the resource exists
    watch_id = _parse_watch_id(uri)
    _load_watch(watch_id)  # This will raise if watch doesn't exist
    # VS Code is now subscribed and will receive send_resource_updated notifications


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__": 
    asyncio.run(main())