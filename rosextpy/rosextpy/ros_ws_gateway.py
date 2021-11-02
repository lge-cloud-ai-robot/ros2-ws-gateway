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

# filename: rosextpy.ros-ws-gateway
# author: paraby@gmail.com


import asyncio
import json
import uuid
import logging
import traceback
from typing import List, Dict
import cbor
#from .node_manager import NodeManager
from rosextpy.node_manager import NodeManager

from .ext_type_support import RosJsonEncodder

mlogger = logging.getLogger('ros_ws_gateway')

class InvalidCommandException(Exception):
    pass

class RosWsGatewayException(Exception):
    pass

class RosWsGatewayClosedException(Exception):
    """
    Raised when the gateway is closed
    """
    pass


async def OnConnectCallback(ws_gateway):
    pass

async def OnDisconnectCallback(ws_gateway):
    pass

async def OnErrorCallback(ws_gateway, err: Exception):
    pass


class MessageParser():
    """ MessageParser """

    def parse(self, msg):
        """ process """
        try:
            return json.loads(msg)
        except Exception:            
            try:                
                return cbor.loads(msg)                
            except Exception:
                mlogger.error(traceback.format_exc())
                raise InvalidCommandException


def bytesToJSBuffer(mesg):
    return {'type':'Buffer', 'data': list(mesg)}

class RosWsGateway():
    """ Process ros2 websocket gateway protocol
    """

    def __init__(self, wshandle, node_mgr , loop,
                 timeout=None, **kwargs):
        mlogger.debug("RosWsGateway created")
        self.activate = True
        self.bridge_id = uuid.uuid4()
        self.parser = MessageParser()
        self.op_map = {
            "advertise": self._op_advertise,
            "unadvertise": self._op_unadvertise,
            "publish": self._op_publish,
            "subscribe": self._op_subscribe,
            "unsubscribe": self._op_unsubscribe,
            "status" : self._op_status,
        }
        self.published_topic : Dict[str,str] = {}
        self.subscribed_topic : Dict[str,str] = {}
        self.node_manager :NodeManager = node_mgr
        self.wshandle = wshandle
        self.loop = loop
        self.timeout = timeout
        self.batch_queue = asyncio.Queue(loop=self.loop)
        self.id_counter = 0
        self._connect_handlers: List[OnConnectCallback] = []
        self._disconnect_handlers: List[OnDisconnectCallback] = []        
        self._error_handlers = []
        self._closed = asyncio.Event(loop=self.loop)
        self._context = kwargs or {}
        self._batch_task = None

    async def send(self, data, israw=False):
        mlogger.debug("send %s", type(data))
        try:
            if israw:                
                message = cbor.dumps(data)
            else:
                message = json.dumps(data, cls=RosJsonEncodder)
        except Exception:
            mlogger.error(traceback.format_exc())

#        mlogger.debug('send message CBOR %s', message)
        
        await self.wshandle.send(message)

    async def receive(self):
        return await self.wshandle.recv()

    async def close(self):
        mlogger.debug("close")
        try :
            res = await self.wshandle.close()
            self._closed.set()
            self._batch_task.cancel()
            if self.node_manager:     
                self.node_manager.remove_with_gateway(self.bridge_id)
            await self.on_handler_event(self._disconnect_handlers, self)
        except Exception:
            mlogger.error(traceback.format_exc())
        return res

    def is_closed(self):
        """ is_closed """
        return self._closed.is_set()

    async def wait_until_closed(self):
        return await self._closed.wait()

    async def on_message(self, data):
        mlogger.debug("on_message %s", data)
##        print("received ", data)
        try:
            cmd_data = self.parser.parse(data)
            await self._execute_command(cmd_data)
        except InvalidCommandException as err:
            mlogger.error(
                "Invalid command message message=%s, error=%s", data, err)
            await self.on_error(err)
        except Exception as err:
            mlogger.error(
                "Some command error message=%s, error=%s", data, err)
            await self.on_error(err)
            raise

    async def on_message_debug(self, data): # for _debug
        mlogger.debug("on_message_debug")
        mlogger.debug("received %s", data)
        # cmd_data = self.parser.parse(data)
        # if cmd_data['op'] == 'advertise':
        #     typestr = cmd_data['type']


    def register_connect_handler(self, coros: List[OnConnectCallback] = None):
        """Register a connection handler callback that will be called 
        (As an async task)) with the gateway
        
        :param coros (List[Coroutine]): async callback
        :return: None
        """
        if coros is not None:
            self._connect_handlers.extend(coros)

    def register_disconnect_handler(self, coros: List[OnDisconnectCallback] = None):
        """
        Register a disconnect handler callback that will be called
        (As an async task)) with the gateway id

        Args:
            coros (List[Coroutine]): async callback
        """
        if coros is not None:
            self._disconnect_handlers.extend(coros)

    def register_error_handler(self, coros: List[OnErrorCallback] = None):
        """
        Register an error handler callback that will be called
        (As an async task)) with the channel and triggered error.

        Args:
            coros (List[Coroutine]): async callback
        """
        if coros is not None:
            self._error_handlers.extend(coros)

    async def on_handler_event(self, handlers, *args, **kwargs):
        await asyncio.gather(*(callback(*args, **kwargs) for callback in handlers))

    async def on_connect(self):
        mlogger.debug("on_connect")
        self._batch_task = asyncio.ensure_future(self.batch_cmd())
        await self.on_handler_event(self._connect_handlers, self)        

    async def on_disconnect(self):
        mlogger.debug("on_disconnect")
        await self.close()        

    async def on_error(self, error: Exception):
        mlogger.debug("on_error")
        await self.on_handler_event(self._error_handlers, self, error)

    async def _op_advertise(self, cmd_data):
        mlogger.debug("advertise %s", cmd_data)
        topic_name = cmd_data['topic']
        topic_type = self.published_topic.get(topic_name)

        if not topic_type:  # None
            topic_type = cmd_data['type']
            self.published_topic[topic_name] = topic_type
            if self.node_manager:
                self.node_manager.create_publisher(
                    topic_type, topic_name, self.bridge_id)                   
        else:
            if topic_type != cmd_data['type']:
                raise RosWsGatewayException(
                    "The topic {} already exists with a different type".format(topic_name))       

        return "OK"

    async def _op_unadvertise(self, cmd_data):
        mlogger.debug("unadvertise %s", cmd_data)
        topic = cmd_data['topic']
        if not topic in self.published_topic.keys():
            raise RosWsGatewayException(
                "The topic {topic} does not exist".format(topic=topic))

        self.published_topic.pop(topic, None)

        if self.node_manager:
            self.node_manager.destroy_publisher(topic, self.bridge_id)

        return "OK"

    async def _op_publish(self, cmd_data): # When encoding is not cbor
        mlogger.debug("publish %s", cmd_data)
        topic = cmd_data['topic']
        if not topic in self.published_topic.keys():
            raise RosWsGatewayException(
                "The topic {topic} does not exist".format(topic=topic))        
        if self.node_manager:
            pub = self.node_manager.get_publisher_by_topic(topic)
            if pub:                   
                pub.publish(cmd_data['msg'])
            else:
                # add advertise and publish
                pass       

        return "OK"

    async def _op_subscribe(self, cmd_data):
        mlogger.debug("subscribe %s", cmd_data)        
        try:
            topic_name = cmd_data['topic']
            topic_type = cmd_data['type']
            self.subscribed_topic[topic_name] = topic_type
            queue_length = cmd_data.get('queue_length', 0)
            compression = cmd_data.get('compression', 'none')
            israw = False if compression=='none' else True            
            if self.node_manager:
                self.node_manager.create_subscription(
                    topic_type, topic_name, self.bridge_id, self._ros_send_subscription_callback, 
                    queue_length = queue_length, israw = israw)
        except Exception:
            mlogger.error(traceback.format_exc())       

        return "OK"

    async def _op_unsubscribe(self, cmd_data):
        mlogger.debug("unsubscribe  %s", cmd_data)
        topic = cmd_data['topic']
        self.subscribed_topic.pop(topic, None)
        if self.node_manager:
            if not self.node_manager.has_subscription(topic):
                raise RosWsGatewayException(
                    "The topic {topic} does not exist".format(topic=topic))
            self.node_manager.destroy_subscription(topic, self.bridge_id)

        return "OK"

    async def _op_status(self, cmd_data):
        mlogger.debug("_op_status  %s", cmd_data)
        return None

    def _ros_send_subscription_callback(self, topic_name, mesg):# node_manager needs sync callback
        mlogger.debug("sendSubscription  %s", topic_name)
        response = {"op": "publish", "topic": topic_name, "msg": mesg}
        if isinstance(mesg, bytes):
            if self.raw_type == 'js-buffer':
                response['msg'] = bytesToJSBuffer(mesg)
                israw = False
            else:
                israw = True
        else:
            israw = False

        asyncio.run_coroutine_threadsafe( self.send(response, israw), self.loop)

    async def _send_back_operation_status(self, opid, msg='', level='none'):
        mlogger.debug("sendBackOperationStatus id= %s", opid)
        if level=='none':
            return
        status = {"op": "status", "level": level, "msg": msg, "id": opid}
        #status = {"op": "set_level", "level": level, "msg": msg, "id": opid}
        await self.send(status)

    async def batch_cmd(self):
        """ batch_cmd """
        mlogger.debug("batch_cmd")
        while True:
#            print("RUN BATCH")
            item_tuple = await self.batch_queue.get()

            mlogger.debug("item is %s:%s:%s:%s",
                          item_tuple[0], item_tuple[1], item_tuple[2], item_tuple[3])
#            print("item is ",
#                          item_tuple[0], item_tuple[1], item_tuple[2], item_tuple[3])
            try:
                if item_tuple[0] == 'pub':
                    self.id_counter += 1
                    subid = ''.join(
                        ['subscribe:', str(self.bridge_id), ':', str(self.id_counter)])
                    await self._op_subscribe(
                        {'op': 'subscribe', 'id': subid,
                            'topic': item_tuple[1], 'type': item_tuple[2], 'compression':  'js-buffer' if item_tuple[3]==True else 'none'})
#                            'topic': item_tuple[1], 'type': item_tuple[2]})
#                            'topic': item_tuple[1], 'type': item_tuple[2], 'compression': 'cbor-raw'})
                    advid = ''.join(
                        ['advertise:', str(self.bridge_id), ':', str(self.id_counter)])
                    data = {'op': 'advertise', 'id': advid,
                            'topic': item_tuple[1], 'type': item_tuple[2]}
                    await self.send(data)

                elif item_tuple[0] == 'unadv':
                    try:
                        self.id_counter += 1
                        await self._op_unsubscribe({'op' : 'unsubscribe', 'topic' : item_tuple[1]})
                        cmdid= ''.join(
                            ['unadvertise:', str(self.bridge_id), ':', str(self.id_counter)])
                        data = {'op' : 'unadvertise', 'id': cmdid, 'topic': item_tuple[1]}                    
                        await self.send(data)
                    except RosWsGatewayException as err:
                        mlogger.debug("unadv exception '%s'", err)
                        pass

                elif item_tuple[0] == 'sub':                    
                    self.id_counter += 1
                    advid = ''.join(
                        ['advertise:', str(self.bridge_id), ':', str(self.id_counter)])
                    await self._op_advertise(
                        {'op': 'advertise', 'id': advid,
                            'topic': item_tuple[1], 'type': item_tuple[2]})
                    subid = ''.join(
                        ['subscribe:', str(self.bridge_id), ':', str(self.id_counter)])
                    data = {'op': 'subscribe',  'id': subid,
                            'topic': item_tuple[1], 'type': item_tuple[2], 
                            'compression':  'js-buffer' if item_tuple[3]==True else 'none'}
                    await self.send(data)             

                elif item_tuple[0] == 'unsub':
                    try:
                        self.id_counter += 1                    
                        await self._op_unadvertise({'op' : 'unadvertise', 'topic' : item_tuple[1]})
                        cmdid= ''.join(
                            ['unsubscribe:', str(self.bridge_id), ':', str(self.id_counter)])
                        data = {'op' : 'unsubscribe', 'id': cmdid, 'topic': item_tuple[1]}                    
                        await self.send(data)
                    except RosWsGatewayException as err:
                        mlogger.debug("unsub exception '%s'", err)
                        pass

                else:
                    mlogger.error("Unknwon command %s", item_tuple[0])
            except Exception as err:
                mlogger.error(traceback.format_exc())
                mlogger.debug("Error in batch_cmd for '%s'", err)

    async def _execute_command(self, command_data):
        mlogger.debug("executeCommand %s", str(command_data))
#        print("executeCommand ", str(command_data))
        op_func = self.op_map.get(command_data['op'])
        if not op_func:
            mlogger.error("Operation %s is not supported", command_data['op'])
            return
        try:
            result = await op_func(command_data)
            if result:
                await self._send_back_operation_status(command_data.get('id','0'), result, 'none')
        except RosWsGatewayException as err:
            error_data = {
                "id": command_data.get('id','0'),
                "op": command_data['op'], "reason": err}
            await self._send_back_operation_status(
                command_data.get('id','0'), 'error', json.dumps(error_data))

    def add_publish(self, topic_name, topic_type, israw=False):
        """ add_publish """
        mlogger.debug("add_publish")        
        asyncio.run_coroutine_threadsafe(self.batch_queue.put(
            ('pub', topic_name, topic_type, israw)), self.loop)

    def remove_publish(self, topic_name):
        """ remove_publish """
        mlogger.debug("remove_publish")
        asyncio.run_coroutine_threadsafe(self.batch_queue.put(
            ('unadv', topic_name, "", None)), self.loop)

    def remove_subscribe(self, topic_name):
        """ remove_subscribe """
        mlogger.debug("remove_subscribe")
        asyncio.run_coroutine_threadsafe(self.batch_queue.put(
            ('unsub', topic_name, "", None)), self.loop)

    def add_subscribe(self, topic_name, topic_type, israw=False):
        """ add_subscribe """
        mlogger.debug("add_subscribe")        
        asyncio.run_coroutine_threadsafe(self.batch_queue.put(
            ('sub', topic_name, topic_type, israw)), self.loop)

    def get_publihsed_topics(self) -> List[str]:
        """ get publihsed topic list
        """
        return list(self.published_topic.keys())

    def get_subscribed_topics(self) -> List[str]:
        """ get subscribed topic list
        """
        return list(self.subscribed_topic.keys())

    def get_publihsed(self) -> Dict[str,str] :
        """ get publihsed topic and type dict
        """
        return self.published_topic

    def get_subscribed(self) -> Dict[str,str] :
        """ get subscribed topic and type dict
        """
        return self.subscribed_topic
