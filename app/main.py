from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import asyncio
import json
from datetime import datetime
from typing import Dict
import os
from uuid import uuid4
from pathlib import Path
import re

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# Serve index.html
@app.get("/")
async def index():
    return FileResponse("static/index.html")

class ConnectionManager:
    def __init__(self):
        # active: websocket -> id
        self.active: Dict[WebSocket, str] = {}
        self.lock = asyncio.Lock()
        # history keys: 'all' for public, or 'dm:<idA>|<idB>' for private
        self.history: Dict[str, list] = {"all": []}
        # avatar mapping: id -> url (served under /static/avatars/)
        self.avatars: Dict[str, str] = {}
        # id->name mapping and ip->id mapping
        self.id_to_name: Dict[str, str] = {}
        self.ip_to_id: Dict[str, str] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        # determine client ip and assign id
        peer = websocket.client
        ip = ''
        try:
            ip = peer[0]
        except Exception:
            ip = ''
        async with self.lock:
            # get or create id for this ip
            uid = self.ip_to_id.get(ip)
            if not uid:
                uid = uuid4().hex[:8]
                self.ip_to_id[ip] = uid
            self.active[websocket] = uid
            # ensure id has a name entry (might be empty until 'join' sets it)
            self.id_to_name.setdefault(uid, '')

    async def disconnect(self, websocket: WebSocket):
        async with self.lock:
            if websocket in self.active:
                uid = self.active.pop(websocket)
            else:
                uid = ""
        # return id
        return uid

    async def set_username(self, websocket: WebSocket, desired: str) -> str:
        """Set username for the id associated with websocket, ensure uniqueness among active names."""
        async with self.lock:
            uid = self.active.get(websocket, '')
            base = (desired or "Gast")[:32]
            name = base
            # existing names (excluding empty)
            existing = set([n for n in self.id_to_name.values() if n])
            i = 1
            while name in existing and name != "":
                i += 1
                name = f"{base}#{i}"
            self.id_to_name[uid] = name
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
            # return list of connected users (id, name, avatar)
            seen = {}
            for uid in set(self.active.values()):
                if not uid: continue
                seen[uid] = {
                    "id": uid,
                    "user": self.id_to_name.get(uid, ''),
                    "avatar": self.avatars.get(uid)
                }
            # return list
            return list(seen.values())

    async def set_avatar(self, uid: str, avatar_url: str):
        async with self.lock:
            self.avatars[uid] = avatar_url

    async def rename_user(self, uid: str, newname: str):
        async with self.lock:
            # set new name for id
            self.id_to_name[uid] = newname

    async def get_ws_by_username(self, username: str):
        """Return first websocket for given username (name)."""
        async with self.lock:
            for ws, uid in self.active.items():
                if self.id_to_name.get(uid) == username:
                    return ws
        return None

    async def get_ws_by_id(self, uid: str):
        """Return all websockets associated with given id."""
        async with self.lock:
            return [ws for ws, idv in self.active.items() if idv == uid]

    async def get_id_by_name(self, name: str):
        async with self.lock:
            for uid, nm in self.id_to_name.items():
                if nm == name:
                    return uid
        return None

    async def get_id_for_ip(self, ip: str):
        async with self.lock:
            return self.ip_to_id.get(ip)

    async def is_id_active(self, uid: str):
        async with self.lock:
            return any(idv == uid for idv in self.active.values())

    async def get_name_for_id(self, uid: str):
        async with self.lock:
            return self.id_to_name.get(uid)

    async def send_to_ws(self, ws: WebSocket, message: dict):
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            pass

    # History helpers
    def _dm_key(self, a: str, b: str) -> str:
        # dm keys are always based on ids
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

# ensure avatars folder exists
Path('static/avatars').mkdir(parents=True, exist_ok=True)

manager = ConnectionManager()

@app.post('/upload-avatar')
async def upload_avatar(file: UploadFile = File(...), request: Request = None):
    # determine client ip
    ip = request.client.host if request and getattr(request, 'client', None) else None
    if not ip:
        raise HTTPException(status_code=400, detail='Cannot determine client IP')
    uid = await manager.get_id_for_ip(ip)
    if not uid:
        raise HTTPException(status_code=404, detail='No ID for this IP (connect via WebSocket first)')

    if file.content_type not in ("image/png","image/jpeg","image/webp","image/gif"):
        raise HTTPException(status_code=415, detail='Unsupported file type')

    data = await file.read()
    if len(data) > 2*1024*1024:
        raise HTTPException(status_code=413, detail='File too large (max 2MB)')

    suffix = {
        'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp', 'image/gif': '.gif'
    }.get(file.content_type, '')
    # sanitize uid for filename
    safe = re.sub(r'[^A-Za-z0-9_-]', '_', uid)[:40] or uuid4().hex[:8]
    filename = f"{safe}_{uuid4().hex}{suffix}"
    out_path = Path('static/avatars') / filename
    with open(out_path, 'wb') as f:
        f.write(data)

    url = f"/static/avatars/{filename}"
    await manager.set_avatar(uid, url)
    users = await manager.user_list()
    await manager.broadcast({"type":"user_list","users":users})
    return {"url": url}


@app.post('/remove-avatar')
async def remove_avatar(request: Request = None):
    ip = request.client.host if request and getattr(request, 'client', None) else None
    if not ip:
        raise HTTPException(status_code=400, detail='Cannot determine client IP')
    uid = await manager.get_id_for_ip(ip)
    if not uid:
        raise HTTPException(status_code=404, detail='No ID for this IP')
    avatar = manager.avatars.get(uid)
    if avatar and avatar.startswith('/static/avatars/'):
        fname = avatar.split('/')[-1]
        fpath = Path('static/avatars') / fname
        try:
            if fpath.exists():
                fpath.unlink()
        except Exception:
            pass
    await manager.set_avatar(uid, None)
    users = await manager.user_list()
    await manager.broadcast({"type":"user_list","users":users})
    return {"ok": True}


@app.websocket('/ws')
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
                uid = manager.active.get(websocket, '')
                sysmsg = {"type":"message","user":"_system","text":f"{username} hat den Chat betreten.","ts":datetime.utcnow().isoformat()}
                await manager.store_message('all', sysmsg)
                await manager.broadcast(sysmsg)
                users = await manager.user_list()
                await manager.broadcast({"type":"user_list","users":users})
                # notify the joining user of their final username and id
                await manager.send_to_ws(websocket, {"type":"joined","user":username,"id":uid,"ts":datetime.utcnow().isoformat()})
                # send recent public history to the joining user
                hist = await manager.get_history('all')
                await manager.send_to_ws(websocket, {"type":"history","channel":"all","messages":hist})

            elif typ == "message":
                sender_id = manager.active.get(websocket, "")
                sender_name = await manager.get_name_for_id(sender_id) or ''
                text = payload.get("text", "")
                to_raw = payload.get("to", "all")
                ts = datetime.utcnow().isoformat()
                if (str(to_raw).lower() == "all"):
                    # public message -> broadcast to all and store
                    msg = {"type":"message","user":sender_name,"user_id":sender_id,"text":text,"private":False,"ts":ts}
                    await manager.store_message('all', msg)
                    await manager.broadcast(msg)
                else:
                    # private message -> resolve target (id or name)
                    target_id = await manager.get_id_by_name(str(to_raw))
                    if not target_id:
                        # maybe it was an id already
                        if await manager.get_name_for_id(str(to_raw)):
                            target_id = str(to_raw)
                    if target_id:
                        target_name = await manager.get_name_for_id(target_id) or ''
                        msg = {"type":"message","user":sender_name,"user_id":sender_id,"text":text,"private":True,"to":target_id,"to_user":target_name,"ts":ts}
                        # store under dm:<id>|<id>
                        dm_key = manager._dm_key(sender_id, target_id)
                        await manager.store_message(dm_key, msg)
                        # send to recipient sockets and to sender
                        target_ws_list = await manager.get_ws_by_id(target_id)
                        for tws in target_ws_list:
                            await manager.send_to_ws(tws, msg)
                        await manager.send_to_ws(websocket, msg)
                    else:
                        await manager.send_to_ws(websocket, {"type":"message","user":"_system","text":f"Benutzer '{to_raw}' nicht gefunden.","private":False,"ts":ts})

            elif typ == "rename":
                desired = payload.get('user', '')[:32]
                uid = manager.active.get(websocket, '')
                oldname = await manager.get_name_for_id(uid) or uid
                newname = await manager.set_username(websocket, desired)
                # update name mapping
                await manager.rename_user(uid, newname)
                ts = datetime.utcnow().isoformat()
                sysmsg = {"type":"message","user":"_system","text":f"{oldname} heißt jetzt {newname}","ts":ts}
                await manager.store_message('all', sysmsg)
                await manager.broadcast(sysmsg)
                users = await manager.user_list()
                await manager.broadcast({"type":"user_list","users":users})
                await manager.send_to_ws(websocket, {"type":"renamed","old":oldname,"user":newname,"ts":ts})

            elif typ == "history":
                channel = payload.get('channel')
                requester = manager.active.get(websocket, '')
                if channel == 'all':
                    hist = await manager.get_history('all')
                    await manager.send_to_ws(websocket, {"type":"history","channel":"all","messages":hist})
                else:
                    # channel is an id or a name -> resolve to id
                    other = str(channel)
                    other_id = await manager.get_id_by_name(other)
                    if not other_id and await manager.get_name_for_id(other):
                        other_id = other
                    if other_id:
                        dm = manager._dm_key(requester, other_id)
                        hist = await manager.get_history(dm)
                        await manager.send_to_ws(websocket, {"type":"history","channel":other_id,"messages":hist})
                    else:
                        await manager.send_to_ws(websocket, {"type":"message","user":"_system","text":f"Benutzer '{other}' nicht gefunden.","private":False,"ts":datetime.utcnow().isoformat()})

            elif typ == "leave":
                uid = await manager.disconnect(websocket)
                if uid:
                    # announce leave only if this id has no more active sockets
                    still = await manager.is_id_active(uid)
                    if not still:
                        name = await manager.get_name_for_id(uid) or uid
                        sysmsg = {"type":"message","user":"_system","text":f"{name} hat den Chat verlassen.","ts":datetime.utcnow().isoformat()}
                        await manager.store_message('all', sysmsg)
                        await manager.broadcast(sysmsg)
                        users = await manager.user_list()
                        await manager.broadcast({"type":"user_list","users":users})

    except WebSocketDisconnect:
        uid = await manager.disconnect(websocket)
        if uid:
            still = await manager.is_id_active(uid)
            if not still:
                name = await manager.get_name_for_id(uid) or uid
                await manager.broadcast({"type":"message","user":"_system","text":f"{name} hat den Chat verlassen.","ts":datetime.utcnow().isoformat()})
                users = await manager.user_list()
                await manager.broadcast({"type":"user_list","users":users})
