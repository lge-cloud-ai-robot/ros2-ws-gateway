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

# filename: rosextpy.ros_ws_gateway
# author: parasby@gmail.com

import sys
import asyncio
import threading
import json
import uuid
import logging
import traceback
from typing import List, Dict, Tuple, Any
import cbor
from rosextpy.websocket_utils import WebSocketDisconnect
from rosextpy.node_manager import NodeManager, ROSServiceFailException
from rosextpy.ext_type_support import RosJsonEncodder, ros_to_json, ros_from_json

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
            "call_service": self._op_call_service, 
                    # The gateway receives a call service from another gateway through the websocket
            "service_response": self._op_service_response,
                    # The gateway receives a json service response and send ROS service response in the local client
            "advertise_service": self._op_advertise_service, 
                    # The gateway plays a role of a service server in the local network
            "unadvertise_service": self._op_unadvertise_service, 
                    # The gateway stops the role of a service server
            "call_action": self._op_call_action,              
                    # The gateway receives a ROS call action and send a JSON call action to another gateway
            "action_result": self._op_action_result, 
                    # The gateway receives an action result from another gateway and publishes the result in the local network.
            "action_feedback": self._op_action_feedback, 
                    # The gateway receives an action feedback from another gateway and publishes the feedback in the local network.
            "advertise_action": self._op_advertise_action, 
                    # The gateway plays a role of a action server in the local network
            "unadvertise_action": self._op_unadvertise_action, 
                    # The gateway stops the role of a action server
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
        self._adv_services : Dict[str, Dict[str,Any]] = {}
        self._adv_action_servers : Dict[str, Dict[str,Any]] = {}
        self.exposed_services: Dict[str,str] = {}
        self.exposed_actions: Dict[str,str] = {}

    async def send(self, data, israw=False):
        mlogger.debug("send %s", type(data))        
        try:
            if israw:                
                message = cbor.dumps(data)
            else:
#                message = json.dumps(data, cls=RosJsonEncodder)
                message = ros_to_json(data)
        except Exception:
            mlogger.error(traceback.format_exc())

#        mlogger.debug('send message CBOR %s', message)
        
        await self.wshandle.send(message)

    async def receive(self):
        return await self.wshandle.recv()

    async def _clear_act_pending_task(self, action_name):
        mlogger.debug("_clear_act_pending_task")
        t_ctx = self._adv_action_servers.get(action_name,None)
        if t_ctx:
            t_called =t_ctx['called'] 
            for (ft_fut, goal_handle, resp_cls , feed_cls) in t_called.values():
                goal_handle.abort()
                ft_fut.set_result(resp_cls())

    async def _clear_srv_pending_task(self,srv_name):
        mlogger.debug("_clear_srv_pending_task")
        t_svc_ctx = self._adv_services.get(srv_name,None)
        if t_svc_ctx:
            t_called =t_svc_ctx['called'] 
            for (ft_fut, _) in t_called.values():
                ft_fut.cancel()
                ft_fut.set_exception(ROSServiceFailException(srv_name))
            

    async def _clear_all_pending_task(self):
        mlogger.debug("_clear_all_pending_task")
        for t_svc_name in self._adv_services.keys():
            await self._clear_srv_pending_task(t_svc_name)
            self.node_manager.destroy_srv_service(t_svc_name)

        for t_act_name in self._adv_action_servers.keys():
            await self._clear_act_pending_task(t_act_name)
            self.node_manager.destroy_action_server(t_act_name)


    async def close(self):
        mlogger.debug("close")
        try :
            res = await self.wshandle.close()
            self._closed.set()
            await self._clear_all_pending_task()
            self._adv_services.clear()
            if self._batch_task:
                self._batch_task.cancel()
                self._batch_task = None
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

    # async def spin(self):
    #     try:
    #         while not self.is_closed():
    #             mesg = await self.receive()
    #             if not mesg:
    #                 raise WebSocketDisconnect
    #             await self.on_message(mesg)
    #     except Exception:
    #         raise
   
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
        mlogger.debug("_op_advertises %s", cmd_data)
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
        mlogger.debug("_op_unadvertise %s", cmd_data)
        topic = cmd_data['topic']
        if not topic in self.published_topic.keys():
            raise RosWsGatewayException(
                "The topic {topic} does not exist".format(topic=topic))

        self.published_topic.pop(topic, None)

        if self.node_manager:
            self.node_manager.destroy_publisher(topic, self.bridge_id)

        return "OK"

    async def _op_publish(self, cmd_data): # When encoding is not cbor
        mlogger.debug("_op_publish %s", cmd_data)
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
        mlogger.debug("_op_subscribe %s", cmd_data)        
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
        mlogger.debug("_op_unsubscribe  %s", cmd_data)
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


    #
    # _op_call_service
    # command [ 
    #           service : serviceName    
    #           type: service type
    #           args:  service parameters
    #         ]
    #

    async def _op_call_service(self, cmd_data):
        mlogger.debug("_op_call_service  %s", cmd_data)        
        try:
            service_name = cmd_data['service']
            type_name = cmd_data['type']
            args = cmd_data['args']
            call_id=cmd_data['id']
            if self.node_manager:
                srv_cli = self.node_manager.create_srv_client(
                    type_name, service_name, self.bridge_id)

                if srv_cli:
                    srv_cli.call_service_async(args, call_id,
                        response_callback=self._ros_send_srvcli_response_callback)
                else:
                    pass        
        except Exception:
            mlogger.error(traceback.format_exc())       

        return "OK"


    #
    # _op_service_response
    # command [ 
    #           service : serviceName    
    #           id: request id
    #           values:  result of service request
    #         ]
    #
    

    async def _op_service_response(self, cmd_data):
        mlogger.debug("_op_service_response  %s", cmd_data)
        service_name = cmd_data['service']
        ctx =  self._adv_services.get(service_name)
        if ctx:
            callid = cmd_data['id']
            t1 = ctx['called'][callid]
            if t1:                
                (rq_future, resp_cls) = t1                
                res_value = cmd_data['values']
                ros_response = ros_from_json(res_value, resp_cls)
                if cmd_data['result']:
                    rq_future.set_result(ros_response)
                else:       
                    rq_future.cancel()             
                    rq_future.set_exception(ROSServiceFailException(service_name))
            else:
                return "Unknon call id"            
        else:
            return "Unknown Service"

        return "OK"

    #
    # advertise_service
    # command [ 
    #           service : serviceName
    #           type    : serviceTypeName
    #         ]
    #
    async def _op_advertise_service(self, cmd_data):
        mlogger.debug("_op_advertise_service  %s", cmd_data)
        try:
            service_name = cmd_data['service']
            type_name = cmd_data['type']
            if self.node_manager:
                srv_svc = self.node_manager.create_srv_service(
                    type_name, service_name, self.bridge_id, 
                        callback=self._ros_service_proxy_callback)
                self._adv_services[service_name] = {'svc' :srv_svc, 'called': {}}
            
        except Exception:
            mlogger.error(traceback.format_exc())
        return "OK"

    #
    # _op_unadvertise_service
    # command [ 
    #           service : serviceName    
    #         ]
    #
    async def _op_unadvertise_service(self, cmd_data):
        mlogger.debug("_op_unadvertise_service  %s", cmd_data)
        try:
            service_name = cmd_data['service']
            if self._adv_services.get(service_name,None):
                await self._clear_srv_pending_task(service_name)
                self._adv_services.pop(service_name)
                if self.node_manager:     
                    self.node_manager.destroy_srv_service(service_name) 
        
        except Exception:
            mlogger.error(traceback.format_exc())       
        return "OK"

    #
    # advertise_service
    # command [ 
    #           action : actionName
    #           type    : serviceTypeName
    #         ]
    #
    async def _op_advertise_action(self, cmd_data):
        mlogger.debug("_op_advertise_action1111  %s", cmd_data)
        try:
            action_name = cmd_data['action']
            type_name = cmd_data['type']
            if self.node_manager:                
                act_svc = self.node_manager.create_action_server(
                    type_name, action_name, self.bridge_id, 
                        callback=self._ros_action_proxy_callback)                
                self._adv_action_servers[action_name] = {'svc' :act_svc, 'called': {}}            
        except Exception:
            mlogger.error(traceback.format_exc())
        return "OK"

    async def _op_call_action(self, cmd_data):
        mlogger.debug("_op_call_action  %s", cmd_data)
        try:
            action_name = cmd_data['action']
            type_name = cmd_data['type']
            args = cmd_data['args']
            call_id=cmd_data['id']
            if self.node_manager:
                srv_cli = self.node_manager.create_action_client(
                    type_name, action_name, self.bridge_id)

                if srv_cli:
                    srv_cli.send_goal_async(args, call_id,
                        feedback_callback=self._ros_send_actcli_feedback_callback,
                        action_result_callback=self._ros_send_actcli_result_callback,
                        goal_accept_callback=self._ros_send_actcli_accept_callback,
                        goal_reject_callback=self._ros_send_actcli_reject_callback
                        )
                else:
                    pass        
        except Exception:
            mlogger.error(traceback.format_exc())       

        return "OK"


    # 'op' : 'action_result', 
    # 'id' : callid,       
    # 'action' : 'fibonacci',
    # 'values' : {'sequence' : [0,1,2,3,4,5]},
    # 'result' : True
    async def _op_action_result(self, cmd_data):
        mlogger.debug("_op_action_result  %s", cmd_data)
        action_name = cmd_data['action']
        ctx =  self._adv_action_servers.get(action_name)
        if ctx:
            callid = cmd_data['id']
            t1 = ctx['called'][callid]
            if t1:                
                (rq_future, goal_handle, resp_cls, feed_cls) = t1
                res_value = cmd_data['values']
                ros_response = ros_from_json(res_value, resp_cls)
                if cmd_data['result']:
                    goal_handle.succeed()
                    rq_future.set_result(ros_response)
                else:                                        
                    goal_handle.abort()
                    rq_future.set_result(resp_cls())
                    #rq_future.cancel()
                    #rq_future.set_exception(ROSServiceFailException(action_name))
            else:
                return "Unknon action call id"
            
        else:
            return "Unknown Action"

        return "OK"

    async def _op_action_feedback(self, cmd_data):
        mlogger.debug("_op_action_feedback  %s", cmd_data)
        action_name = cmd_data['action']
        ctx =  self._adv_action_servers.get(action_name)
        if ctx:
            callid = cmd_data['id']
            t1 = ctx['called'][callid]
            if t1:                
                (rq_future, goal_handle, resp_cls, feed_cls) = t1                
                res_value = cmd_data['values']
                #print(dir(ctx.act_cls.Feedback))
                feedback = ros_from_json(res_value, feed_cls)
                goal_handle.publish_feedback(feedback)
            else:
                return "Unknon action call id"
            
        else:
            return "Unknown Action"

        return "OK"

    async def _op_unadvertise_action(self, cmd_data):
        mlogger.debug("_op_unadvertise_action  %s", cmd_data)
        try:
            action_name = cmd_data['action']
            if self._adv_action_servers.get(action_name,None):
                await self._clear_act_pending_task(action_name)
                self._adv_action_servers.pop(action_name)
                if self.node_manager:     
                    self.node_manager.destroy_action_server(action_name) 
        
        except Exception:
            mlogger.error(traceback.format_exc())       
        return "OK"

    def _ros_send_actcli_feedback_callback(self, act_name, call_id, feedback_data):
        mlogger.debug("_ros_send_actcli_feedback_callback ")                
        response = {"op": "action_feedback", 
                    "action": act_name,
                    "id": call_id,
                    "value" : feedback_data,                    
                    "result": True }       

        if isinstance(feedback_data, bytes):
            if self.raw_type == 'js-buffer':
                response['value'] = bytesToJSBuffer(feedback_data)
                israw = False
            else:
                israw = True
        else:
            israw = False

        asyncio.run_coroutine_threadsafe( self.send(response, israw), self.loop)

    def _ros_send_actcli_result_callback(self, act_name, call_id, result_data):
        mlogger.debug("_ros_send_actcli_result_callback ")
        response = {"op": "action_result", 
                    "action": act_name,
                    "id": call_id,
                    "value" : result_data,                    
                    "result": True }

        if isinstance(result_data, bytes):
            if self.raw_type == 'js-buffer':
                response['value'] = bytesToJSBuffer(result_data)
                israw = False
            else:
                israw = True
        else:
            israw = False

        asyncio.run_coroutine_threadsafe( self.send(response, israw), self.loop)

    def _ros_send_actcli_accept_callback(self, act_name, call_id, goal_handle):
        mlogger.debug("_ros_send_actcli_accept_callback ")
        # response = {"op": "action_accept", 
        #             "action": act_name,
        #             "id": call_id,
        #             "value" : result_data,                    
        #             "result": True }

        # print("RESULT IS ", response)

        # if isinstance(result_data, bytes):
        #     if self.raw_type == 'js-buffer':
        #         response['value'] = bytesToJSBuffer(result_data)
        #         israw = False
        #     else:
        #         israw = True
        # else:
        #     israw = False

        # asyncio.run_coroutine_threadsafe( self.send(response, israw), self.loop)

    def _ros_send_actcli_reject_callback(self, act_name, call_id, goal_handle):
        mlogger.debug("_ros_send_actcli_reject_callback ")
        # response = {"op": "action_reject", 
        #             "action": act_name,
        #             "id": call_id,
        #             "value" : result_data,                    
        #             "result": True }

        # print("RESULT IS ", response)

        # if isinstance(result_data, bytes):
        #     if self.raw_type == 'js-buffer':
        #         response['value'] = bytesToJSBuffer(result_data)
        #         israw = False
        #     else:
        #         israw = True
        # else:
        #     israw = False

        # asyncio.run_coroutine_threadsafe( self.send(response, israw), self.loop)

    async def _ros_action_proxy_callback(self, action_name, action_type, goal_handle):
        mlogger.debug("_ros_action_proxy_callback")

        callid = str(uuid.uuid4())

        callmsg = {'op' : 'call_action', 'id' : callid,
                'action' : action_name, 'type' : action_type,
                'args' : ros_to_json(goal_handle._goal_request)
            }
        ctx = self._adv_action_servers.get(action_name)
        if ctx:
            rq_future = ctx['svc'].get_waiter()  # get future from ros context
            ctx['called'][callid] = (rq_future, goal_handle, 
                        ctx['svc'].get_result_class(), ctx['svc'].get_feedback_class())            
            await self.send(callmsg)       # send func. is called from ROS loop
            try:
                return await rq_future # wait response and return it to ROS rclpy logic
            except ROSServiceFailException:                
                mlogger.debug("The call_action for [%s] gets an error", action_name)
                raise
            finally:
                if self._adv_action_servers.get(action_name,None):
                    del self._adv_action_servers[action_name]['called'][callid]                
        else:            
            mlogger.debug("The service [%s] was not advertised", action_name)  
            raise ROSServiceFailException(action_name)


    async def _ros_service_proxy_callback(self, srv_name, srv_type, request, response):
        mlogger.debug("_ros_service_proxy_callback")
        # this callback is called from ROS executor
        
        callid = str(uuid.uuid4())

        callmsg = {'op': 'call_service', 'id': callid, 
                'service': srv_name, 'type' : srv_type,
                'args' : ros_to_json(request)
            }        
        ctx =  self._adv_services.get(srv_name)        
        if ctx:
            rq_future = ctx['svc'].get_waiter()  # get future from ros context
            ctx['called'][callid] = (rq_future, ctx['svc'].get_response_class())            
            await self.send(callmsg)       # send func. is called from ROS loop
            try:
                return await rq_future # wait response and return it to ROS rclpy logic
            except ROSServiceFailException:                
                mlogger.debug("The call_service for [%s] gets an error", srv_name)
                raise
            finally:
                if self._adv_services.get(srv_name,None):
                    del self._adv_services[srv_name]['called'][callid]                
        else:            
            mlogger.debug("The service [%s] was not advertised", srv_name)  
            raise ROSServiceFailException(srv_name)



    def _ros_send_srvcli_response_callback(self, srv_name, call_id, res_mesg):# node_manager needs sync callback
        mlogger.debug("_ros_send_srvcli_response_callback ")
        response = {"op": "service_response", 
                    "service": srv_name,
                    "id": call_id,
                    "values" : res_mesg,                    
                    "result": True }

        if isinstance(res_mesg, bytes):
            if self.raw_type == 'js-buffer':
                response['value'] = bytesToJSBuffer(res_mesg)
                israw = False
            else:
                israw = True
        else:
            israw = False

        asyncio.run_coroutine_threadsafe( self.send(response, israw), self.loop)
        

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
                elif item_tuple[0] == 'expsrv': # expose service to remote gateway
                    self.id_counter += 1
                    reqid = ''.join(
                        ['exposesrv:', str(self.bridge_id), ':', str(self.id_counter)])
                    data = {'op' : 'advertise_service', 'id': reqid, 
                                'type' : item_tuple[2], 'service': item_tuple[1]}
                    self.exposed_services[item_tuple[1]] = item_tuple[2]
                    await self.send(data)

                elif item_tuple[0] == 'delsrv': # hide exposed service to remote gateway
                    self.id_counter += 1
                    reqid = ''.join(
                        ['delsrv:', str(self.bridge_id), ':', str(self.id_counter)])
                    data = {'op' : 'unadvertise_service', 'id': reqid, 
                                'service': item_tuple[1]}                    
                    await self.send(data)
                    self.exposed_services.pop(item_tuple[1], None)                    
                elif item_tuple[0] == 'expact': # expose action to remote gateway
                    self.id_counter += 1
                    reqid = ''.join(
                        ['exposeact:', str(self.bridge_id), ':', str(self.id_counter)])
                    data = {'op' : 'advertise_action', 'id': reqid, 
                                'type' : item_tuple[2], 'action': item_tuple[1]}
                    self.exposed_actions[item_tuple[1]] = item_tuple[2]
                    await self.send(data)
                elif item_tuple[0] == 'delact': # hide exposed action to remote gateway
                    self.id_counter += 1
                    reqid = ''.join(
                        ['delact:', str(self.bridge_id), ':', str(self.id_counter)])
                    data = {'op' : 'unadvertise_action', 'id': reqid, 
                                'action': item_tuple[1]}                    
                    await self.send(data)
                    self.exposed_actions.pop(item_tuple[1], None)
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

    def expose_service(self, srv_name, srv_type, israw=False):
        """ expose_service """
        mlogger.debug("expose_service")                
        asyncio.run_coroutine_threadsafe(self.batch_queue.put(
            ('expsrv', srv_name, srv_type, israw)), self.loop)

    def hide_service(self, srv_name, israw=False):
        """ hide_service """
        mlogger.debug("hide_service")        
        asyncio.run_coroutine_threadsafe(self.batch_queue.put(
            ('delsrv', srv_name, "", israw)), self.loop)

    def expose_action(self, act_name, act_type, israw=False):
        """ expose_action """
        mlogger.debug("expose_action")        
        asyncio.run_coroutine_threadsafe(self.batch_queue.put(
            ('expact', act_name, act_type, israw)), self.loop)

    def hide_action(self, act_name, israw=False):
        """ hide_action """
        mlogger.debug("hide_action")        
        asyncio.run_coroutine_threadsafe(self.batch_queue.put(
            ('delact', act_name, "", israw)), self.loop)                          

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
