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

# rosextpy.ros_ws_gateway_client (ros2-ws-gateway)
# Author: parasby@gmail.com
"""ros_ws_gateway_client
"""

from __future__ import absolute_import
import asyncio
import logging
import traceback
#from node_manager import NodeManager
from rosextpy.ros_ws_gateway import RosWsGateway
from rosextpy.websocket_utils import ConnectionManager, WebSocketInterface, WebSocketDisconnect, register_ws_route

mlogger = logging.getLogger('ros_ws_gateway_endpoint')

class RosWsGatewayEndpoint:
    """
       ROS Websocket Server to receive the ROS2-web-bridge compliant protocol messages
    """
    def __init__(self, node_manager, 
                 manager : ConnectionManager = None,
                 on_connect=None,
                 on_disconnect=None):
        """
        Args:
            node_manager (NodeManager): ROS2 Node Manager to process ROS2 command
            loop (asyncio.loop) : event loop for running this gateway server
            manager ([ConnectionManager], optional): Connection tracking object. Defaults to None (i.e. new ConnectionManager()).
            on_disconnect (List[coroutine], optional): Callbacks per disconnection 
            on_connect(List[coroutine], optional): Callbacks per connection (Server spins the callbacks as a new task, not waiting on it.)

            usage: 
               # for Sanic
                app = Sanic()
                endpoint = RosWsGatewayEndpoint(node_manager)
                endpoint.register_route(app)

               # for FastAPI
                app = FastAPI()
                endpoint = RosWsGatewayEndpoint(node_manager)
                endpoint.register_route(app)
        """
        # ros node manager
        self.node_manager = node_manager
        # connection manager 
        self.manager = manager if manager is not None else ConnectionManager()        
        # event handlers
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect

    async def serve(self, websocket, request = None, client_id : str = None, **kwargs):
        mlogger.debug("serve")        
        try:
            the_loop = asyncio.get_event_loop()
            wshandle  = WebSocketInterface(websocket, request)            
        except Exception:
            mlogger.error(traceback.format_exc())
        try:
            await self.manager.accept(wshandle)            
            mlogger.debug("Client Connected from %s", wshandle.address)
            gateway = RosWsGateway(wshandle, self.node_manager, the_loop)
            gateway.register_connect_handler(self._on_connect)
            gateway.register_disconnect_handler(self._on_disconnect)
            await gateway.on_connect()
            try:
                while True:
                    data = await wshandle.recv()
                    if not data:
                        raise WebSocketDisconnect
                    await gateway.on_message(data)
            except WebSocketDisconnect:
                mlogger.debug("Client disconnected - %s :: %s", wshandle.address, gateway.bridge_id)
                await self.handle_disconnect(wshandle, gateway)
            except asyncio.exceptions.CancelledError:
                mlogger.debug("Client disconnected - %s :: %s", wshandle.address, gateway.bridge_id)
                await self.handle_disconnect(wshandle, gateway)
            except Exception:
                mlogger.debug(traceback.format_exc())
                mlogger.debug("Client failed - %s :: %s", wshandle.address, gateway.bridge_id)
                await self.handle_disconnect(wshandle, gateway)
        except Exception:
            mlogger.error("Failed to serve %s",wshandle.address)
            self.manager.disconnect(wshandle)

    async def handle_disconnect(self, wshandle:WebSocketInterface, gateway:RosWsGateway):
        mlogger.debug("handle_disconnect")
        self.manager.disconnect(wshandle)
        await gateway.on_disconnect()

    # function for fastapi on connect
    async def on_connect(self, gateway, wshandle):
        mlogger.debug("on_connect")
        if self._on_connect is not None:
            asyncio.create_task(self._on_connect(gateway, wshandle))

    # function for fastapi endpoint
    def register_route(self, router, path="/"):
        register_ws_route(self, router, path)