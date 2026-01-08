import asyncio
import json
import sys

import websockets

async def client(name, actions):
    uri = 'ws://127.0.0.1:8000/ws'
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({'type':'join','user':name}))
        async def receiver():
            try:
                async for msg in ws:
                    data = json.loads(msg)
                    print(f"[{name} RECEIVED] {data}")
            except Exception as e:
                print(f"[{name}] receiver error: {e}")
        task = asyncio.create_task(receiver())
        await asyncio.sleep(0.5)
        for a in actions:
            await ws.send(json.dumps(a))
            await asyncio.sleep(0.3)
        # request history for DM with the other user (if private actions exist)
        await ws.send(json.dumps({'type':'history','channel':'all'}))
        await asyncio.sleep(0.5)
        await ws.send(json.dumps({'type':'leave'}))
        await asyncio.sleep(0.2)
        task.cancel()

async def main():
    alice_actions = [
        {'type':'message','text':'Hallo zusammen','to':'all'},
        {'type':'message','text':'Hi Bob, private hier','to':'Bob'},
    ]
    bob_actions = [
        {'type':'message','text':'Moin Alice','to':'all'},
        {'type':'message','text':'Hallo Alice, privat!','to':'Alice'},
    ]
    await asyncio.gather(client('Alice', alice_actions), client('Bob', bob_actions))

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
