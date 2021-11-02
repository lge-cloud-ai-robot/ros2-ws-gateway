#  MIT License
#
#  Copyright (c) 2021, Electronics and Telecommunications Research Institute (ETRI) All Rights Reserved.
#
#  Permission is hereby granted, free of charge, to any person obtaining a copy
#  of this software and associated documentation files (the "Software"), to deal
#  in the Software without restriction, including without limitation the rights
#  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#  copies of the Software, and to permit persons to whom the Software is
#  furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# rosextpy.websocket_utils (ros2-ws-gateway)
# Author: paraby@gmail.com

"""websocket_util
"""
import logging
from .mod_config import WS_CONFIG

mlogger = logging.getLogger('websocket_utils')

class WebSocketDisconnect(Exception):
    pass

class ConnectionManager:
    def __init__(self):
        self.connections = []

    async def accept(self, websocekt):
        await websocekt.accept()
        self.connections.append(websocekt)
#        print([s.address for s in self.connections])

    def disconnect(self, websocekt):
        self.connections.remove(websocekt)        

# config for sanic
if WS_CONFIG['wsf'] == "sanic":
    mlogger.debug("websocket_util SANIC IMPORTED")
    from sanic import Sanic
    from sanic.response import json
    from sanic.request import Request
    from sanic.websocket import WebSocketProtocol

# At present, sanic does not support uvicorn

    def register_ws_route(cls, router, path):
        @router.websocket(path)
        async def websocket_endpoint(request, websocket):
            await cls.serve(websocket, request)

    class WebSocketInterface:
        def __init__(self, websocket, request=None):
            mlogger.debug("websocket is %s ", type(websocket))
            mlogger.debug("Mod config is %s", WS_CONFIG['wsf'])
            self.websocket = websocket            

        @property
        def send(self): #WebSocketCommonProtocol
            return self.websocket.send

        @property
        def recv(self):  #WebSocketCommonProtocol
            return self.websocket.recv

        async def close(self, code: int = 1000):  
            return await self.websocket.close(code) #WebSocketCommonProtocol

        async def accept(self):  #WebSocketCommonProtocol
            mlogger.debug("accept")
            #await self.websocket.accept()
            await self.websocket.ensure_open()

        def address(self):
            return self.websocket.remote_address  #WebSocketCommonProtocol : remote_address is tuple (ip, port)

elif WS_CONFIG['wsf'] == "fastapi":
    mlogger.debug("websocket_util fastapi IMPORTED")
    # config for fastapi
    from fastapi import WebSocket, WebSocketDisconnect

    def register_ws_route(cls, router, path):
        @router.websocket(path)
        async def websocket_endpoint(websocket):
            await cls.serve(websocket)

    class WebSocketInterface:
        def __init__(self, websocket, request=None):
            self.websocket = websocket
            mlogger.debug("websocket is %s ", type(websocket))
            mlogger.debug("Mod config is %s", WS_CONFIG['wsf'])

        @property
        def send(self):
            return self.websocket.send_text

        @property
        def recv(self):
            return self.websocket.receive_text

        async def close(self, code: int = 1000):
            return await self.websocket.close(code)

        @property
        def accept(self):
            return self.websocket.accept

        @property
        def address(self):
            return self.websocket.client



