"""WebSocket handlers for real-time collaboration."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, Set

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

try:
    from crm import crud
    from crm.schemas import (
        CursorPositionMessage,
        EditEndMessage,
        EditStartMessage,
        EntryUpdateMessage,
        PresenceMessage,
        RealTimeMessage,
    )
except ImportError:
    import crud
    from schemas import (
        CursorPositionMessage,
        EditEndMessage,
        EntryUpdateMessage,
        PresenceMessage,
        RealTimeMessage,
    )


class ConnectionManager:
    """Manage WebSocket connections for real-time collaboration."""

    def __init__(self):
        # Map of entry_id -> set of connected websockets
        self.entry_connections: Dict[str, Set[WebSocket]] = {}
        # Map of websocket -> {username, session_id, entry_id}
        self.connection_info: Dict[WebSocket, dict] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def connect(
        self, websocket: WebSocket, entry_id: str, username: str, session_id: str
    ):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()

        async with self._lock:
            if entry_id not in self.entry_connections:
                self.entry_connections[entry_id] = set()

            self.entry_connections[entry_id].add(websocket)
            self.connection_info[websocket] = {
                "username": username,
                "session_id": session_id,
                "entry_id": entry_id,
                "connected_at": datetime.now(timezone.utc).isoformat(),
            }

        # Notify others that user joined
        await self.broadcast_to_entry(
            entry_id,
            {
                "type": "presence",
                "username": username,
                "session_id": session_id,
                "data": {"status": "online", "action": "joined"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            exclude=websocket,
        )

    async def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        async with self._lock:
            info = self.connection_info.get(websocket)
            if not info:
                return

            entry_id = info["entry_id"]
            username = info["username"]
            session_id = info["session_id"]

            # Remove from entry connections
            if entry_id in self.entry_connections:
                self.entry_connections[entry_id].discard(websocket)
                if not self.entry_connections[entry_id]:
                    del self.entry_connections[entry_id]

            # Remove connection info
            del self.connection_info[websocket]

        # Notify others that user left
        await self.broadcast_to_entry(
            entry_id,
            {
                "type": "presence",
                "username": username,
                "session_id": session_id,
                "data": {"status": "offline", "action": "left"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def broadcast_to_entry(
        self, entry_id: str, message: dict, exclude: WebSocket | None = None
    ):
        """Broadcast a message to all connections for an entry."""
        if entry_id not in self.entry_connections:
            return

        disconnected = []
        for websocket in self.entry_connections[entry_id]:
            if websocket == exclude:
                continue
            try:
                await websocket.send_json(message)
            except Exception:
                disconnected.append(websocket)

        # Clean up disconnected clients
        for websocket in disconnected:
            await self.disconnect(websocket)

    async def send_to_session(self, session_id: str, message: dict):
        """Send a message to a specific session."""
        for websocket, info in self.connection_info.items():
            if info["session_id"] == session_id:
                try:
                    await websocket.send_json(message)
                    return True
                except Exception:
                    return False
        return False

    def get_active_users(self, entry_id: str) -> list[dict]:
        """Get list of active users editing an entry."""
        if entry_id not in self.entry_connections:
            return []

        users = []
        for websocket in self.entry_connections[entry_id]:
            info = self.connection_info.get(websocket)
            if info:
                users.append(
                    {
                        "username": info["username"],
                        "session_id": info["session_id"],
                        "connected_at": info["connected_at"],
                    }
                )
        return users

    def get_connection_count(self, entry_id: str) -> int:
        """Get number of active connections for an entry."""
        return len(self.entry_connections.get(entry_id, set()))


# Global connection manager
manager = ConnectionManager()


async def handle_websocket(
    websocket: WebSocket,
    entry_id: str,
    username: str,
    session_id: str,
    db: Session,
):
    """Handle WebSocket connection for real-time collaboration."""
    await manager.connect(websocket, entry_id, username, session_id)

    # Start edit session in database
    crud.start_edit_session(db, entry_id, session_id, username)

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type == "edit_start":
                    # User started editing
                    crud.start_edit_session(db, entry_id, session_id, username)
                    await manager.broadcast_to_entry(
                        entry_id,
                        {
                            "type": "edit_start",
                            "username": username,
                            "session_id": session_id,
                            "entry_id": entry_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                        exclude=websocket,
                    )

                elif msg_type == "edit_end":
                    # User finished editing
                    crud.end_edit_session(db, entry_id, session_id)
                    await manager.broadcast_to_entry(
                        entry_id,
                        {
                            "type": "edit_end",
                            "username": username,
                            "session_id": session_id,
                            "entry_id": entry_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                        exclude=websocket,
                    )

                elif msg_type == "cursor":
                    # Cursor position update
                    await manager.broadcast_to_entry(
                        entry_id,
                        {
                            "type": "cursor",
                            "username": username,
                            "session_id": session_id,
                            "entry_id": entry_id,
                            "data": message.get("data", {}),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                        exclude=websocket,
                    )

                elif msg_type == "heartbeat":
                    # Extend edit session
                    crud.extend_edit_session(db, entry_id, session_id)
                    await websocket.send_json(
                        {"type": "heartbeat_ack", "timestamp": datetime.now(timezone.utc).isoformat()}
                    )

                elif msg_type == "get_presence":
                    # Return list of active users
                    users = manager.get_active_users(entry_id)
                    await websocket.send_json(
                        {
                            "type": "presence_list",
                            "entry_id": entry_id,
                            "users": users,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )

            except json.JSONDecodeError:
                await websocket.send_json(
                    {"type": "error", "message": "Invalid JSON"}
                )
            except Exception as e:
                await websocket.send_json(
                    {"type": "error", "message": str(e)}
                )

    except WebSocketDisconnect:
        # Clean up on disconnect
        crud.end_edit_session(db, entry_id, session_id)
        await manager.disconnect(websocket)


async def broadcast_entry_update(
    entry_id: str,
    updated_fields: dict,
    version: int,
    edited_by: str,
    exclude_session: str | None = None,
):
    """Broadcast entry update to all connected clients."""
    message = {
        "type": "entry_update",
        "entry_id": entry_id,
        "data": updated_fields,
        "version": version,
        "edited_by": edited_by,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if entry_id in manager.entry_connections:
        for websocket in manager.entry_connections[entry_id]:
            info = manager.connection_info.get(websocket)
            if info and info.get("session_id") == exclude_session:
                continue
            try:
                await websocket.send_json(message)
            except Exception:
                pass


async def notify_conflict(
    entry_id: str,
    session_id: str,
    current_version: int,
    current_data: dict,
):
    """Notify a specific session about a conflict."""
    message = {
        "type": "conflict",
        "entry_id": entry_id,
        "current_version": current_version,
        "current_data": current_data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await manager.send_to_session(session_id, message)
