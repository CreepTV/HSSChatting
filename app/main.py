from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import asyncio
import json
from datetime import datetime
from typing import Dict

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# Serve index.html
@app.get("/")
async def index():
    return FileResponse("static/index.html")

class ConnectionManager:
    def __init__(self):
        self.active: Dict[WebSocket, str] = {}
        self.lock = asyncio.Lock()
        # history keys: 'all' for public, or 'dm:userA|userB' for private
        self.history: Dict[str, list] = {"all": []}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self.lock:
            self.active[websocket] = ""  # username filled on join

    async def disconnect(self, websocket: WebSocket):
        async with self.lock:
            if websocket in self.active:
                username = self.active.pop(websocket)
            else:
                username = ""
        return username

    async def set_username(self, websocket: WebSocket, desired: str) -> str:
        """Set username, ensure uniqueness by appending numeric suffix if needed."""
        async with self.lock:
            base = (desired or "Gast")[:32]
            name = base
            existing = set(self.active.values())
            i = 1
            while name in existing and name != "":
                i += 1
                name = f"{base}#{i}"
            self.active[websocket] = name
            return name

    async def broadcast(self, message: dict):
        text = json.dumps(message)
        async with self.lock:
            websockets = list(self.active.keys())
        for ws in websockets:
            try:
                await ws.send_text(text)
            except Exception:
                pass

    async def user_list(self):
        async with self.lock:
            return [name for name in self.active.values() if name]

    async def get_ws_by_username(self, username: str):
        async with self.lock:
            for ws, name in self.active.items():
                if name == username:
                    return ws
        return None

    async def send_to_ws(self, ws: WebSocket, message: dict):
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            pass

    # History helpers
    def _dm_key(self, a: str, b: str) -> str:
        a,b = sorted([a,b])
        return f"dm:{a}|{b}"

    async def store_message(self, channel: str, message: dict):
        async with self.lock:
            lst = self.history.setdefault(channel, [])
            lst.append(message)
            # keep only last 200 messages per channel
            if len(lst) > 200:
                self.history[channel] = lst[-200:]

    async def get_history(self, channel: str):
        async with self.lock:
            return list(self.history.get(channel, []))

    async def get_dm_history_for(self, user_a: str, user_b: str):
        key = self._dm_key(user_a, user_b)
        return await self.get_history(key)

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
            except Exception:
                continue

            typ = payload.get("type")

            if typ == "join":
                desired = payload.get("user", "")[:32]
                username = await manager.set_username(websocket, desired)
                sysmsg = {"type":"message","user":"_system","text":f"{username} hat den Chat betreten.","ts":datetime.utcnow().isoformat()}
                await manager.store_message('all', sysmsg)
                await manager.broadcast(sysmsg)
                users = await manager.user_list()
                await manager.broadcast({"type":"user_list","users":users})
                # notify the joining user of their final username (in case it was modified)
                await manager.send_to_ws(websocket, {"type":"joined","user":username,"ts":datetime.utcnow().isoformat()})
                # send recent public history to the joining user
                hist = await manager.get_history('all')
                await manager.send_to_ws(websocket, {"type":"history","channel":"all","messages":hist})

            elif typ == "message":
                sender = manager.active.get(websocket, "")
                text = payload.get("text", "")
                to = payload.get("to", "all")
                ts = datetime.utcnow().isoformat()
                if (str(to).lower() == "all"):
                    # public message -> broadcast to all and store
                    msg = {"type":"message","user":sender,"text":text,"private":False,"ts":ts}
                    await manager.store_message('all', msg)
                    await manager.broadcast(msg)
                else:
                    # private message -> only send to recipient and sender (do NOT broadcast) and store in DM history
                    target_ws = await manager.get_ws_by_username(to)
                    if target_ws:
                        msg = {"type":"message","user":sender,"text":text,"private":True,"to":to,"ts":ts}
                        # store under dm:<a>|<b>
                        dm_key = manager._dm_key(sender, to)
                        await manager.store_message(dm_key, msg)
                        # send to recipient and to sender
                        await manager.send_to_ws(target_ws, msg)
                        await manager.send_to_ws(websocket, msg)
                    else:
                        await manager.send_to_ws(websocket, {"type":"message","user":"_system","text":f"Benutzer '{to}' nicht gefunden.","private":False,"ts":ts})

            elif typ == "rename":
                desired = payload.get('user', '')[:32]
                old = manager.active.get(websocket, '')
                newname = await manager.set_username(websocket, desired)
                ts = datetime.utcnow().isoformat()
                sysmsg = {"type":"message","user":"_system","text":f"{old} heißt jetzt {newname}","ts":ts}
                await manager.store_message('all', sysmsg)
                await manager.broadcast(sysmsg)
                users = await manager.user_list()
                await manager.broadcast({"type":"user_list","users":users})
                await manager.send_to_ws(websocket, {"type":"renamed","old":old,"user":newname,"ts":ts})

            elif typ == "history":
                channel = payload.get('channel')
                requester = manager.active.get(websocket, '')
                if channel == 'all':
                    hist = await manager.get_history('all')
                    await manager.send_to_ws(websocket, {"type":"history","channel":"all","messages":hist})
                else:
                    # channel is a username -> return dm history between requester and that username
                    other = str(channel)
                    dm = manager._dm_key(requester, other)
                    hist = await manager.get_history(dm)
                    await manager.send_to_ws(websocket, {"type":"history","channel":other,"messages":hist})

            elif typ == "leave":
                user = await manager.disconnect(websocket)
                if user:
                    sysmsg = {"type":"message","user":"_system","text":f"{user} hat den Chat verlassen.","ts":datetime.utcnow().isoformat()}
                    await manager.store_message('all', sysmsg)
                    await manager.broadcast(sysmsg)
                    users = await manager.user_list()
                    await manager.broadcast({"type":"user_list","users":users})

    except WebSocketDisconnect:
        user = await manager.disconnect(websocket)
        if user:
            await manager.broadcast({"type":"message","user":"_system","text":f"{user} hat den Chat verlassen.","ts":datetime.utcnow().isoformat()})
            users = await manager.user_list()
            await manager.broadcast({"type":"user_list","users":users})
