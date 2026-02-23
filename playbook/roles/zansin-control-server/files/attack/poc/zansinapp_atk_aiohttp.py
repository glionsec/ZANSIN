#!/usr/bin/env python
# coding: UTF-8
import asyncio
import os
import signal
import sys
from aiohttp import web
from pathlib import Path

args = sys.argv
if len(args) != 3:
    print("usage: zansinapp_atk_aiohttp.py <host> <port>")
    sys.exit(1)

host = args[1]
port = args[2]

async def stopserver(request):
    print("======== Stop WebServer ========")
    # Send SIGTERM after a short delay so the response is delivered first.
    # This triggers aiohttp's signal handler (GracefulExit at run_app level),
    # avoiding "Task exception was never retrieved" from raising inside a Task.
    asyncio.get_running_loop().call_later(0.1, os.kill, os.getpid(), signal.SIGTERM)
    return web.Response(text="OK")

app = web.Application()
app.add_routes([
    web.get('/stopserver', stopserver),
    web.static('/', path=str(Path.cwd().joinpath('attack/public')), show_index=False)
    ])

if __name__ == '__main__':
    web.run_app(app, host=host, port=int(port))

