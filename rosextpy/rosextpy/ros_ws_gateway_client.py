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

## based on fastapi_websocket_rpc
import sys
import asyncio
import logging
from typing import List
from tenacity import retry, wait
import tenacity
from tenacity.retry import retry_if_exception
import websockets
import websockets.exceptions
from websockets.exceptions import InvalidStatusCode, WebSocketException, ConnectionClosedError, ConnectionClosedOK 
#from node_manager import NodeManager
from rosextpy.ros_ws_gateway import RosWsGateway

mlogger = logging.getLogger('ros_ws_gateway_client')

stopflag = False

def setStop(state: bool):
    global stopflag
    stopflag = state

def isNotInvalidStatusCode(value):
    return not isinstance(value, InvalidStatusCode)

def isNotForbbiden(value) -> bool:
    """
    Returns:
        bool: Returns True as long as the given exception value is not InvalidStatusCode with 401 or 403
    """
    return not (isinstance(value, InvalidStatusCode) and (value.status_code == 401 or value.status_code == 403))

def logerror(retry_state: tenacity.RetryCallState):
    mlogger.exception(retry_state.outcome.exception())

def OnRequestAdvertiseCallbck(topicName, topicTypeStr, israw):
    pass

def OnRequestUnadvertiseCallbck(topicName):
    pass

def OnRequestSubscribeCallbck(topicName, topicTypeStr, israw):
    pass

def OnRequestUnsubscribeCallbck(topicName):
    pass

def OnRequestExposeServiceCallbck(srvName, srvTypeStr, israw):
    pass

def OnRequestHideServiceCallbck(srvName):
    pass

def OnRequestExposeActionCallbck(actionName, actionTypeStr, israw):
    pass

def OnRequestHideActionCallbck(actionName):
    pass

class WebSocketClientInterface:
    def __init__(self, websocket):
        self.websocket = websocket            

    @property
    def send(self): #WebSocketClientProtocol
        return self.websocket.send

    @property
    def recv(self):  #WebSocketClientProtocol
        return self.websocket.recv

    async def close(self, code: int = 1000):  
        return await self.websocket.close(code) #WebSocketClientProtocol

    async def accept(self):  #WebSocketClientProtocol
        mlogger.debug("accept")
            #await self.websocket.accept()
        await self.websocket.ensure_open()
    
    #@property
    def address(self):        
        return self.websocket.remote_address #self.websocket.remote_address  #WebSocketClientProtocol


class RosWsGatewayClient:
    """
       ROS Websocket client to connect to an ROS2-web-bridge compliant service
    """

    DEFAULT_RETRY_CONFIG = {
        'wait': wait.wait_random_exponential(min=0.1, max=120),
        'retry': retry_if_exception(isNotForbbiden),
        'reraise': True,
        "retry_error_callback": logerror
    }

    WAIT_FOR_INITIAL_CONNECTION = 1

    MAX_CONNECTION_ATTEMPTS = 5

    def __init__(self, uri: str, node_manager, loop=None,
                 retry_config=None,                 
                 default_timeout: float = None,
                 on_connect=None,
                 on_disconnect=None,
                 **kwargs):
        """
        Args:
            uri (str): server uri to connect to (e.g. 'ws://localhost:2000')
            node_manager (NodeManager): ROS2 Node Manager to process ROS2 command
            retry_config (dict): Tenacity.retry config (@see https://tenacity.readthedocs.io/en/latest/api.html#retry-main-api)
                                Default: False(no retry), When retry_config is None, it uses default config
            default_timeout (float): default time in seconds
            on_connect (List[Coroutine]): callbacks on connection being established (each callback is called with the gateway)
                                          @note exceptions thrown in on_connect callbacks propagate to the client and will cause connection restart!
            on_disconnect (List[Coroutine]): callbacks on connection termination (each callback is called with the gateway)
            **kwargs: Additional args passed to connect (@see class Connect at websockets/client.py)
                      https://websockets.readthedocs.io/en/stable/api.html#websockets.client.connect
            usage:
                async with  RosWsGatewayClient(uri, node_manager) as client:
                   await client.wait_on_reader()

        """

        # ros node manager
        self.node_manager = node_manager

        if node_manager is None:
            mlogger.warn("node_manager is None")

        self.connect_kwargs = kwargs

        # Websocket connection
        self.conn = None
        # Websocket object
        self.ws = None

        # ros ws bridge uri : target gateway/bridge URI
        self.uri = uri

        # reader worker
        self._read_task = None

        # timeout
        self.default_timeout = default_timeout

        # Ros WS Gateway
        self.gateway: RosWsGateway = None

        # retry config for Tenacity.retry
        
        self.retry_config = retry_config if retry_config is not None else self.DEFAULT_RETRY_CONFIG


        # event handlers
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect

        self._req_advertise_handlers: List[OnRequestAdvertiseCallbck] = []
        self._req_unadvertise_handlers: List[OnRequestUnadvertiseCallbck] = []
        self._req_subscribe_handlers: List[OnRequestSubscribeCallbck] = []
        self._req_unsubscribe_handlers: List[OnRequestUnsubscribeCallbck] = []       

        self._req_expose_service_handlers : List[OnRequestExposeServiceCallbck] = []
        self._req_hide_service_handlers: List[OnRequestHideServiceCallbck] = []
        self._req_expose_action_handlers: List[OnRequestExposeActionCallbck] = []
        self._req_hide_action_handlers: List[OnRequestHideActionCallbck] = []

        # event loop for multi threading event loop
        self.loop = loop if loop is not None else asyncio.get_event_loop()

    def register_req_advertise_handler(self, callbacks: List[OnRequestAdvertiseCallbck] = None):
        """
        Register a request advertise handler callback that will be called

        Args:
            callbacks (List[function]): callback
        """
        if callbacks is not None:
            self._req_advertise_handlers.extend(callbacks)

    def register_req_unadvertise_handler(self, callbacks: List[OnRequestUnadvertiseCallbck] = None):
        """
        Register a request unadvertise handler callback that will be called

        Args:
            callbacks (List[function]): callback
        """
        if callbacks is not None:
            self._req_unadvertise_handlers.extend(callbacks)

    def register_req_subscribe_handler(self, callbacks: List[OnRequestSubscribeCallbck] = None):
        """
        Register a request subscribe handler callback that will be called

        Args:
            callbacks (List[function]): callback
        """
        if callbacks is not None:
            self._req_subscribe_handlers.extend(callbacks)

    def register_req_unsubscribe_handler(self, callbacks: List[OnRequestUnsubscribeCallbck] = None):
        """
        Register a request unsubscribe handler callback that will be called
        
        Args:
            callbacks (List[function]): callback
        """
        if callbacks is not None:
            self._req_unsubscribe_handlers.extend(callbacks)


    def register_req_expose_service_handler(self, callbacks: List[OnRequestExposeServiceCallbck] = None):
        """
        Register a request expose service handler callback that will be called
        
        Args:
            callbacks (List[function]): callback
        """
        if callbacks is not None:
            self._req_expose_service_handlers.extend(callbacks)        

    def register_req_hide_service_handler(self, callbacks: List[OnRequestHideServiceCallbck] = None):
        """
        Register a request hide service handler callback that will be called
        
        Args:
            callbacks (List[function]): callback
        """
        if callbacks is not None:
            self._req_hide_service_handlers.extend(callbacks)

    def register_expose_action_handler(self, callbacks: List[OnRequestExposeActionCallbck] = None):
        """
        Register a request expose action handler callback that will be called
        
        Args:
            callbacks (List[function]): callback
        """
        if callbacks is not None:
            self._req_expose_action_handlers.extend(callbacks)

    def register_req_hide_action_handler(self, callbacks: List[OnRequestHideActionCallbck] = None):
        """
        Register a request hide action handler callback that will be called
        
        Args:
            callbacks (List[function]): callback
        """
        if callbacks is not None:
            self._req_hide_action_handlers.extend(callbacks)

    def on_handler_event(self, handlers, *args, **kwargs):
        for callback in handlers:
            callback(*args, **kwargs)
    
    def add_publish(self, topic_name, topic_type, israw=False):
        mlogger.debug("add_publish %s:%s:%s",topic_name, topic_type, israw)        
        if self.gateway:
            self.gateway.add_publish(topic_name, topic_type, israw)        
        self.on_handler_event(self._req_advertise_handlers, topic_name, topic_type, israw)        

    def remove_publish(self, topic_name):
        mlogger.debug("remove_publish %s",topic_name)
        if self.gateway:
            self.gateway.remove_publish(topic_name)
        self.on_handler_event(self._req_unadvertise_handlers, topic_name)

    def add_subscribe(self, topic_name, topic_type, israw=False):
        mlogger.debug("add_subscribe %s:%s:%s",topic_name, topic_type, israw)
        if self.gateway:            
            self.gateway.add_subscribe(topic_name, topic_type, israw)
        self.on_handler_event(self._req_subscribe_handlers, topic_name, topic_type, israw)        

    def remove_subscribe(self, topic_name):
        mlogger.debug("remove_subscribe %s",topic_name)        
        if self.gateway:
            self.gateway.remove_subscribe(topic_name)
        self.on_handler_event(self._req_unsubscribe_handlers, topic_name)

    def expose_service(self, srv_name, srv_type, israw=False):
        mlogger.debug("expose_service %s:%s:%s",srv_name, srv_type, israw)
        if self.gateway:            
            self.gateway.expose_service(srv_name, srv_type, israw)
        self.on_handler_event(self._req_expose_service_handlers, srv_name, srv_type, israw)        

    def hide_service(self, srv_name):
        mlogger.debug("hide_service %s",srv_name)        
        if self.gateway:
            self.gateway.hide_service(srv_name)
        self.on_handler_event(self._req_hide_service_handlers, srv_name)

    def expose_action(self, act_name, act_type, israw=False):
        mlogger.debug("expose_action %s:%s:%s",act_name, act_type, israw)
        if self.gateway:            
            self.gateway.expose_action(act_name, act_type, israw)
        self.on_handler_event(self._req_expose_action_handlers, act_name, act_type, israw)        

    def hide_action(self, act_name):
        mlogger.debug("hide_action %s",act_name)        
        if self.gateway:
            self.gateway.hide_action(act_name)
        self.on_handler_event(self._req_hide_action_handlers, act_name)

    async def __connect__(self):
        try:
            self.cancel_tasks()
            mlogger.debug("Connection to ros ws bridge - %s", self.uri)
            # Start connection
            self.conn = websockets.connect(self.uri, **self.connect_kwargs)
            # get websocket
            self.ws = await self.conn.__aenter__()  # self.ws is WebSocketClientProtocol

            self.loop = asyncio.get_event_loop()

            self.gateway = RosWsGateway(WebSocketClientInterface(self.ws),
                    self.node_manager, self.loop, timout=self.default_timeout)

            # register handlers
            self.gateway.register_connect_handler(self._on_connect)
            self.gateway.register_disconnect_handler(self._on_disconnect)

            # start reading incoming message
            self._read_task = asyncio.create_task(self.reader())

            # trigger connect handlers
            await self.gateway.on_connect()
            return self

        except ConnectionRefusedError:
            mlogger.debug("ros ws connection was refused by server")
            raise
        except ConnectionClosedError:
            mlogger.debug("ros ws connection lost")
            raise
        except ConnectionClosedOK:
            mlogger.debug("ros ws connection closed")
            raise
        except InvalidStatusCode as err:
            mlogger.debug(
                "ros ws Websocket failed - with invalid status code %s", err.status_code)
            raise
        except WebSocketException as err:
            mlogger.debug("ros ws Websocket failed - with %s", err)
            raise        
        except OSError as err:
            mlogger.debug("ros ws Connection failed - %s", err)
            raise
        except asyncio.exceptions.CancelledError as err:
            mlogger.debug("ros ws Connection cancelled - %s", err)
            raise               
        except Exception as err:
            mlogger.exception("ros ws Error")
            raise

    async def __aenter__(self):
        if self.retry_config is False:
            return await self.__connect__()
        return await retry(**self.retry_config)(self.__connect__)()

    async def __aexit__(self, *args, **kwargs):
        mlogger.debug("__aexit__")
        self.cancel_tasks()
        await self.close()
        if hasattr(self.conn, "ws_client"):
            await self.conn.__aexit__(*args, **kwargs)

    async def close(self):
        mlogger.debug("Closing ros ws client for %s", self.uri)
        # Close underlying connection
        if self.ws is not None:
            mlogger.debug("close websocket")
            await self.ws.close()
        # Notify callbacks (but just once)
        if not self.gateway.is_closed():
            mlogger.debug("close gateway")
            # notify handlers (if any)
            await self.gateway.on_disconnect()
        else:
            mlogger.debug("gateway closed")
        # Clear tasks
        #self.cancel_tasks()

    def cancel_tasks(self):
        mlogger.debug("cancel_tasks")
        # Stop reader - if created
        self.cancel_reader_task()

    def cancel_reader_task(self):
        mlogger.debug("cancel_reader_task")
        if self._read_task is not None:
            self._read_task.cancel()
            self._read_task = None

    async def reader(self):
        mlogger.debug("Reading ..")
        try:
            while True:
                raw_message = await self.ws.recv()
                await self.gateway.on_message(raw_message)
        except asyncio.exceptions.CancelledError:
            mlogger.debug("reader task was cancelled.")
            await self.close()
            raise asyncio.CancelledError()        
        except websockets.exceptions.ConnectionClosedError:
            # closed by server
            mlogger.debug("Connection was terminated.")
            await self.close()
            raise            
        except Exception:
            mlogger.exception("ros ws reader task failed")
            raise

    async def wait_on_reader(self):
        try:
            mlogger.debug("Wait read")
            await self._read_task
        except asyncio.CancelledError:
            mlogger.debug("ros ws Reader task was cancelled.")

    async def send(self, message, timeout=None):
        return await self.gateway.send(message)
