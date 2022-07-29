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

# rosextpy.ros_node_manager (ros-ws-gateway)
# Author: parasby@gmail.com
#

"""ros2 subscription and publish management
"""

import os
import sys

from rclpy.task import Future
if os.environ['ROS_VERSION'] != '2':
    raise RuntimeError("ROS VERSION 2.0 required")
#
# ros version == foxy (rmw_fast_rtps of galactic version has some bugs )
import traceback
import functools
import json
import asyncio
from threading import Thread
import logging
import rclpy
from rclpy.action import ActionServer, ActionClient
from rclpy.qos import qos_profile_system_default
from rosextpy.ext_type_support import SerializedTypeLoader, TypeLoader, SrvTypeLoader, ActionTypeLoader, ros_from_json, ros_to_json

mlogger = logging.getLogger('node_manager')

ROS_SRV_CLIENT_TIMEOUT=3.0
ROS_ACTION_CLIENT_TIMEOUT=3.0

class NodeManagerException(Exception):    
    pass

class ROSServiceFailException(Exception):
    pass

class ActionClientManager:  
    def __init__(self, node, act_type:str, act_name:str ,israw : bool = False):
        self.node :rclpy.Node = node
        self.act_type : str = act_type
        self.act_name : str = act_name
        self.israw :bool = israw
        self.act_cls = ActionTypeLoader(self.act_type) 
        try:
            self.handle = ActionClient(self.node, self.act_cls, self.act_name)
        except Exception:
            mlogger.error(traceback.format_exc())

        mlogger.debug("node create_client completed")
        self.bridges = {}

    def _when_finished(self, response_callback, fut : Future):
        response = fut.result()
        response_callback(response)
  
    def encode_json_to_Goal(self, json_data):
        """remove_publish"""
        return ros_from_json(json_data, self.act_cls.Goal)

    def encode_json_to_Result(self, json_data):
        """remove_publish"""
        return ros_from_json(json_data, self.act_cls.Result)

    def encode_json_to_Feeback(self, json_data):
        """remove_publish"""
        return ros_from_json(json_data, self.act_cls.Feedback)    

    def __feedback_callback(self, feedback_msg, feedback_callback, call_id):
        mlogger.debug("__feedback_callback ")
        feedback_callback(self.act_name,call_id,feedback_msg.feedback)

    def __get_result_callback(self, future, action_result_callback, call_id):
        mlogger.debug("__get_result_callback ")
        action_result_callback(self.act_name, call_id, future.result().result)

    # it will be called by gateway
    # 
    # feedback_callback = (action_name, call_id, feedback_msg)
    # action_result_callback(action_name, call_id, result_data)
    def __call_goal_async(self, goal_msg, call_id, feedback_callback, action_result_callback,goal_accept_callback, goal_reject_callback):
        mlogger.debug("__call_goal_async ")
        def goal_response_callback(future):
            goal_handle = future.result()
            if  goal_handle.accepted:
                if goal_accept_callback is not None:
                    goal_accept_callback(self.act_name, call_id, goal_handle)

                if action_result_callback is not None:
                    _get_result_future = goal_handle.get_result_async()
                    _get_result_future.add_done_callback(functools.partial(self.__get_result_callback, 
                                action_result_callback=action_result_callback,call_id=call_id
                                ))
                
            else:
                if goal_reject_callback is not None:
                    goal_reject_callback(self.act_name, call_id, goal_handle)

        _send_goal_future = None

        if feedback_callback is not None:            
            _send_goal_future = self.handle.send_goal_async(goal_msg, 
                feedback_callback = functools.partial(self.__feedback_callback,
                    feedback_callback=feedback_callback,call_id=call_id))
        else:
            _send_goal_future = self.handle.send_goal_async(goal_msg)

        if _send_goal_future is not None:
            _send_goal_future.add_done_callback(goal_response_callback)

        return _send_goal_future

    def send_goal_async(self, request_json, call_id, feedback_callback = None, action_result_callback=None,
            goal_accept_callback=None, goal_reject_callback = None):

        """publish"""
        mlogger.debug("send_goal_async %s",request_json)

        the_future = None

        self.handle.wait_for_server(timeout_sec=ROS_ACTION_CLIENT_TIMEOUT) # sometimes, service can be unavailable        
        if not self.handle.server_is_ready():
            print("no action service available...")
            return None
            
        
        if isinstance(request_json, bytes):
            the_future = self.__call_goal_async(request_json, call_id,
                feedback_callback = feedback_callback, action_result_callback=action_result_callback,
                goal_accept_callback=goal_accept_callback, goal_reject_callback = goal_reject_callback)
        else:        
            if 'type' in request_json:
                if request_json['type'] == 'Buffer':
                    the_future = self.__call_goal_async(bytes(request_json['data']), call_id,
                        feedback_callback = feedback_callback, action_result_callback=action_result_callback,
                        goal_accept_callback=goal_accept_callback, goal_reject_callback = goal_reject_callback)
                else:
                    the_future = self.__call_goal_async(self.encode_json_to_Goal(request_json), call_id,
                        feedback_callback = feedback_callback, action_result_callback=action_result_callback,
                        goal_accept_callback=goal_accept_callback, goal_reject_callback = goal_reject_callback)
            else:
                # cmdData['msg'] will be json or {"type":"Buffer","data"}"
                the_future = self.__call_goal_async(self.encode_json_to_Goal(request_json), call_id,
                    feedback_callback = feedback_callback, action_result_callback=action_result_callback,
                    goal_accept_callback=goal_accept_callback, goal_reject_callback = goal_reject_callback)        
        return the_future

    def add_action_client(self, bridge_id):
        """add_subscription"""
        self.bridge_id = bridge_id        

    def remove_action_client(self, bridge_id):
        """remove_subscription"""
        _ = bridge_id 
        self.bridge_id = None        

    def destroy(self):
        self.callback=None
        self.node.destroy_client(self.handle)   

class ActionServerManager: 
    def __init__(self, node, act_type:str, act_name:str , israw : bool = False):
        self.node = node
        self.act_type : str = act_type
        self.act_name : str = act_name
        self.israw :bool = israw
        self.act_cls = ActionTypeLoader(self.act_type)  
        self.exec_callback=None
        self.goal_callback=None
        self.cancel_callback=None
        self.handle_accepted_callback=None
        try:
            self.handle = ActionServer(self.node, self.act_cls, self.act_name, 
                execute_callback=self._inter_exec_callback,
                goal_callback=self._inter_goal_callback,
                cancel_callback=self._inter_cancel_callback,
                handle_accepted_callback =self._inter_handle_accepted_callback
                )
        except Exception:
            mlogger.error(traceback.format_exc())

        mlogger.debug("node create_action_server completed")
        self.callback = None

    async def _inter_exec_callback(self, goal_handle):
        mlogger.debug('action call received!!! %s', self.act_name)    
        if self.exec_callback:
            return await self.exec_callback(self.act_name, self.act_type, goal_handle)
        else:
            mlogger.debug('action call aborted!!! %s', self.act_name)    
            goal_handle.abort()
            return self.get_result_class()()

    async def _inter_goal_callback(self, goal_request):
        mlogger.debug('action goal callback ')
        if self.goal_callback:  
            return self.goal_callback(self.act_name, self.act_type,goal_request)
        else:
            return rclpy.action.server.default_goal_callback(goal_request)


    async def _inter_cancel_callback(self, cancel_request):
        mlogger.debug('action cancel callback ')
        if self.cancel_callback:  
            return self.cancel_callback(self.act_name, self.act_type,cancel_request)
        else:
            return rclpy.action.server.default_cancel_callback(cancel_request)


    async def _inter_handle_accepted_callback(self, goal_handle):
        mlogger.debug('action handle_accepted callback ')
        if self.handle_accepted_callback:  
            return self.handle_accepted_callback(self.act_name, self.act_type, goal_handle)
        else:
            return rclpy.action.server.default_handle_accepted_callback(goal_handle)



    def add_action_server(self, bridge_id, callback):
        """add_subscription"""
        self.bridge_id = bridge_id
        self.exec_callback = callback


    def get_result_class(self):
        return self.act_cls.Result

    def get_feedback_class(self):
        return self.act_cls.Feedback

    def get_waiter(self):
        fut = rclpy.task.Future()
        return fut        

    def remove_action_server(self, bridge_id):
        """remove_subscription"""
        _ = bridge_id 
        self.bridge_id = None
        self.exec_callback = None

    def destroy(self):
        mlogger.debug('destroy ActionServerManager')
        self.exec_callback=None
        if self.handle:
            self.handle.destroy()
            self.handle=None


class SrvClientManager:  
    def __init__(self, node, srv_type:str, srv_name:str ,israw : bool = False):
        self.node :rclpy.Node = node
        self.srv_type : str = srv_type
        self.srv_name : str = srv_name
        self.israw :bool = israw
        self.srv_cls = SrvTypeLoader(self.srv_type)  
        try:
            self.handle = self.node.create_client(self.srv_cls, self.srv_name, qos_profile =qos_profile_system_default )
        except Exception:
            mlogger.error(traceback.format_exc())

        mlogger.debug("node create_client completed")
        self.bridges = {}

    def _when_finished(self, fut : Future, call_id, response_callback):
        mlogger.debug("_when_finished")
        response = fut.result()        

        response_callback(self.srv_name, call_id, response)
    
    def encode_json_to_request(self, json_data):
        """remove_publish"""
        return ros_from_json(json_data, self.srv_cls.Request)

    def encode_json_to_respone(self, json_data):
        """remove_publish"""
        return ros_from_json(json_data, self.srv_cls.Response)    
    
    # it will be called by gateway
    # response_callback--> receive ROS response and send JSON message response
    def call_service_async(self, request_json, call_id, response_callback):
        """publish"""
        mlogger.debug("service_call %s",request_json)

        self.handle.wait_for_service(timeout_sec=ROS_SRV_CLIENT_TIMEOUT) # sometimes, service can be unavailable
        if not self.handle.service_is_ready():
            print("no service available...")
            return None            

        the_future = None
        
        if isinstance(request_json, bytes):
            the_future = self.handle.call_async(request_json)
        else:        
            if 'type' in request_json:
                if request_json['type'] == 'Buffer':
                    the_future = self.handle.call_async(bytes(request_json['data']))
                else:
                    the_future = self.handle.call_async(self.encode_json_to_request(request_json))
            else:
                # cmdData['msg'] will be json or {"type":"Buffer","data"}"
                the_future = self.handle.call_async(self.encode_json_to_request(request_json))

        the_future.add_done_callback(functools.partial( self._when_finished, call_id=call_id, 
                        response_callback=response_callback))

        return the_future

    def add_srv_client(self, bridge_id):
        """add_subscription"""
        self.bridge_id = bridge_id        

    def remove_srv_client(self, bridge_id):
        """remove_subscription"""
        _ = bridge_id 
        self.bridge_id = None        

    def destroy(self):
        self.callback=None
        self.node.destroy_client(self.handle)             

class SrvServiceManager: 
    def __init__(self, node, srv_type:str, srv_name:str , israw : bool = False):
        self.node = node
        self.srv_type : str = srv_type
        self.srv_name : str = srv_name
        self.israw :bool = israw
        self.srv_cls = SrvTypeLoader(self.srv_type)  

        try:
            self.handle = self.node.create_service(self.srv_cls, self.srv_name, self._inter_callback,                    
                    qos_profile =qos_profile_system_default )
        except Exception:
            mlogger.error(traceback.format_exc())

        mlogger.debug("node create_client completed")
        self.callback = None

    # The _inter_callback receives a request from local ROS peers and it should return a response.
    async def _inter_callback(self, request, response):
        mlogger.debug('service call received!!! %s', type(request))                      

        return await self.callback(self.srv_name, self.srv_type, request, response)

    def get_response_class(self):
        return self.srv_cls.Response

    def get_waiter(self):
        fut = rclpy.task.Future()
        return fut

    def add_srv_service(self, bridge_id, callback):
        """add_subscription"""
        self.bridge_id = bridge_id
        self.callback = callback

    def remove_srv_service(self, bridge_id):
        """remove_subscription"""
        _ = bridge_id 
        self.bridge_id = None
        self.callback = None

    def destroy(self):
        mlogger.debug('ros service %s destroyed',self.srv_name)
        self.callback=None
        self.node.destroy_service(self.handle)        


class SubscriptionManager:
    """SubscriptionManager"""
    def __init__(self, node, topic_type:str, topic_name:str, queue_length: int = 0, israw : bool = False):
        self.node = node
        self.topic_type :str = topic_type
        self.topic_name :str = topic_name
        self.queue_length :int = queue_length
        self.israw :bool = israw
        if israw:
            self.type_cls = SerializedTypeLoader(topic_type)
        else:
            self.type_cls = TypeLoader(topic_type)
            
        try:
            self.handle = self.node.create_subscription(self.type_cls,
                 topic_name, self._inter_callback, qos_profile=qos_profile_system_default, raw=self.israw)
        except Exception:
            mlogger.error(traceback.format_exc())
        self.callbacks = {}
        mlogger.debug("subscription to %s", self.topic_name)

    def _inter_callback(self, message):
        mlogger.debug('mesage received!!! %s', type(message))

        for callback in list(self.callbacks.values()):
            callback(self.topic_name, message)        

    def add_subscription(self, bridge_id, callback):
        """add_subscription"""
        self.callbacks[bridge_id] = callback

    def remove_subscription(self, bridge_id):
        """remove_subscription"""
        self.callbacks.pop(bridge_id, None)

    def destroy(self):
        self.callbacks={}
        self.node.destroy_subscription(self.handle)        

    def destroy_when_empty(self):
        if len(self.callbacks) == 0:
            self.node.destroy_subscription(self.handle)
            return None
        return self

class PublishManager:
    """PublishManager"""
    def __init__(self, node, topic_type:str, topic_name:str, queue_length: int =10, israw : bool = False):
        mlogger.debug("create PublishManager")
        self.node = node
        self.topic_type :str = topic_type
        self.topic_name :str = topic_name
        self.queue_length :int = queue_length
        self.israw :bool = israw

        if israw:
            self.type_cls = SerializedTypeLoader(topic_type)
        else:
            self.type_cls = TypeLoader(topic_type)

        self.handle = self.node.create_publisher(self.type_cls, topic_name, qos_profile =qos_profile_system_default )
        mlogger.debug("node create_publisher completed")
        self.bridges = {}

    def get_empty_obj(self):
        return self.type_cls()

    def add_publish(self, bridge_id):
        """add_publish"""
        self.bridges[bridge_id] = 1

    def remove_publish(self, bridge_id):
        """remove_publish"""
        self.bridges.pop(bridge_id, None)

    def encode_json(self, json_data):
        """remove_publish"""
        return ros_from_json(json_data, self.type_cls)

    #  data=b'hello'
    #  {'type': 'Buffer', 'data': list(data)}   

    def raw_publish(self, ros_mesg):
        mlogger.debug("raw_publish called")
        self.handle.publish(ros_mesg)

    def publish(self, json_data):
        """publish"""
        mlogger.debug("publish %s",json_data)
        if isinstance(json_data, bytes):
            self.handle.publish(json_data)
        else:
            if 'type' in json_data:
                if json_data['type'] == 'Buffer':
                    self.handle.publish(bytes(json_data['data']))
                else:
                    self.handle.publish(self.encode_json(json_data))
            else:
                # cmdData['msg'] will be json or {"type":"Buffer","data"}"
                self.handle.publish(self.encode_json(json_data))

    def destroy(self):
        self.bridges={}
        self.node.destroy_publisher(self.handle)

    def destroy_when_empty(self):
        if len(self.bridges) == 0:
            self.node.destroy_publisher(self.handle)
            return None
        return self
            


# manage all subscription and publisher

class NodeManager(Thread):
    """NodeManager"""
    def __init__(self, options=None):
        super().__init__(daemon=True)
        rclpy.init(args=options)
        self.node = rclpy.create_node('ros_nod_mgr')
        self.publisher = {}
        self.subscriptions = {}
        self.srv_services = {}
        self.srv_clients = {}
        self.act_servers = {}
        self.act_clients = {}
        self.srv_name_and_types = {}
        mlogger.debug("ros node manager created")        

    def run(self):
        the_node = self.node
        mlogger.debug("ros node manager started")
        try:
            while rclpy.ok():
                #rclpy.spin_once(the_node)
                try:
                    rclpy.spin_once(the_node, timeout_sec=0.001)                    
                except ROSServiceFailException as ex:   
                    # ROS executer raises an exception.
                    mlogger.error('service call gets error for [%s]',ex)
                except Exception:
                    raise
        except Exception:
            mlogger.error(traceback.format_exc())
        finally:            
            if self.node:
                self.node.destroy_node()
                self.node =None
                rclpy.shutdown()        

    def stop(self):                
        mlogger.debug("ros node manager stopping")
        if self.node:
            self.node.destroy_node()
            self.node = None
            rclpy.shutdown()

    def get_now(self):
        """get_now"""
        return self.node.get_clock().now()

    def get_node(self):
        """get_node"""
        return self.node

    def get_topic_list(self):
        """get topic list"""
        return self.node.get_topic_names_and_types()

    def remove_with_gateway(self, bridge_id):
        """remove_bridges"""
        self.destroy_subscription_by_bridge_id(bridge_id)
        self.destroy_publisher_by_bridge_id(bridge_id)

    def create_action_server(self, act_type, act_name, bridge_id, callback):
        mlogger.debug("create_action_server %s :%s :%s", act_type, act_name, bridge_id)        
        act_mgr = self.act_servers.get(act_name)
        if not act_mgr:
            try:
                act_mgr = ActionServerManager(self.node, act_type, act_name)
                self.act_servers[act_name] = act_mgr
            except Exception:
                mlogger.debug(traceback.format_exc())
                raise
        act_mgr.add_action_server(bridge_id, callback) 
        return act_mgr

    def create_action_client(self, act_type, act_name, bridge_id):
        mlogger.debug("create_action_client %s :%s :%s", act_type, act_name, bridge_id)  
        cli_mgr = self.act_clients.get(act_name)
        if not cli_mgr:
            try:
                cli_mgr = ActionClientManager(self.node, act_type, act_name)
                self.act_clients[act_name] = cli_mgr
            except Exception:
                mlogger.debug(traceback.format_exc())
                raise
        else:
            if act_type != cli_mgr.act_type:
                raise NodeManagerException(
                    "The action {act} already exists with different action type {type}".format(
                        act=act_name, type=cli_mgr.act_type))

        cli_mgr.add_action_client(bridge_id)
        return cli_mgr

    def create_srv_service(self, srv_type, srv_name, bridge_id, callback):
        mlogger.debug("create_srv_service %s :%s :%s", srv_type, srv_name, bridge_id)        
        srv_mgr = self.srv_services.get(srv_name)
        if not srv_mgr:
            try:
                srv_mgr = SrvServiceManager(self.node, srv_type, srv_name)
                self.srv_services[srv_name] = srv_mgr  # service name is unique
            except Exception:
                mlogger.debug(traceback.format_exc())
                raise
        srv_mgr.add_srv_service(bridge_id, callback) 
        return srv_mgr

    def get_service_type(self, srv_name):
        mlogger.debug("get_service_type %s", srv_name)
        srvtype = self.srv_name_and_types.get(srv_name)        
        if not srvtype:            
            srvinfos = self.node.get_service_names_and_types()            
            for info in list(srvinfos):
                self.srv_name_and_types[info[0]] = info[1][0]
                if srv_name == info[0]:                    
                    srvtype = info[1][0]
        return srvtype


    def create_srv_client(self, srv_type, srv_name, bridge_id):        
        mlogger.debug("create_srv_client %s :%s :%s", srv_type, srv_name, bridge_id)

        cli_mgr = self.srv_clients.get(srv_name)
        if not cli_mgr:
            try:
                srv_type = self.get_service_type(srv_name)      
                if not srv_type:
                    raise NodeManagerException(
                    "The srv {topic} doest not serve ".format(topic=srv_name))
                cli_mgr = SrvClientManager(self.node, srv_type, srv_name)
                self.srv_clients[srv_name] = cli_mgr
            except Exception:
                mlogger.debug(traceback.format_exc())
                raise
        # else:  # do not use.. because srv_type argument can be null
            # if srv_type != cli_mgr.srv_type:
            #     raise NodeManagerException(
            #         "The srv {topic} already exists with d different srv type {type}".format(
            #             topic=srv_name, type=cli_mgr.srv_type))

        cli_mgr.add_srv_client(bridge_id)                
        return cli_mgr
        
    def create_subscription(self, topic_type, topic_name, bridge_id, callback, queue_length=0, israw=False):    
        """create_subscription"""
        mlogger.debug("create_subscription %s :%s :%s", topic_type, topic_name, bridge_id)        
        sub_mgr = self.subscriptions.get(topic_name)  # needs split raw and not raw
        if not sub_mgr:
            try :
                sub_mgr = SubscriptionManager(self.node, topic_type, topic_name, queue_length, israw)                
                self.subscriptions[topic_name] = sub_mgr
            except Exception:
                mlogger.debug(traceback.format_exc())
                raise
        sub_mgr.add_subscription(bridge_id, callback)
        return sub_mgr

    def create_publisher(self, topic_type, topic_name, bridge_id,  queue_length=10, israw=False):
        """create_publisher"""
        mlogger.debug("create_publisher")
        
        pub_mgr = self.publisher.get(topic_name)
        if not pub_mgr:
            try:
                pub_mgr = PublishManager(self.node, topic_type, topic_name, queue_length, israw)
                self.publisher[topic_name] = pub_mgr
            except Exception:
                mlogger.debug(traceback.format_exc())
                raise                
        else:
            if topic_type != pub_mgr.topic_type:
                raise NodeManagerException(
                    "The topic {topic} already exists with d different type {type}".format(
                        topic=topic_name, type=pub_mgr.topic_type))
        pub_mgr.add_publish(bridge_id)
        return pub_mgr

    def get_publisher_by_topic(self, topic_name):
        """get_publisher_by_topic"""
        pub_mgr = self.publisher.get(topic_name)
        if pub_mgr:
            return pub_mgr
        return None

    def get_subscription_by_topic(self, topic_name):
        """get_subscription_by_topic"""
        sub_mgr = self.subscriptions.get(topic_name)
        if sub_mgr:
            return sub_mgr
        return None

    def has_subscription(self, topic_name):
        """has_subscription"""
        return self.subscriptions.get(topic_name,None) is not None

    def destroy_action_server(self, action_name):
        mlogger.debug("<destroy_action_server> [%s]", action_name)
        act_mgr = self.act_servers.get(action_name,None)
        if act_mgr:
            act_mgr.destroy()            
            self.act_servers.pop(action_name)

    def destroy_srv_service(self, srvname):
        mlogger.debug("<destroy_srv_service> [%s]", srvname)
        svc_mgr = self.srv_services.get(srvname,None)
        if svc_mgr:
            svc_mgr.destroy()            
            self.srv_services.pop(srvname)

    def destroy_publisher(self, topic_name, bridge_id):
        """destroy_publisher"""
        pub_mgr = self.publisher.get(topic_name, None)
        if pub_mgr:
            pub_mgr.remove_publish(bridge_id)
            if not pub_mgr.destroy_when_empty():
                self.publisher.pop(topic_name)

    def destroy_subscription(self, topic_name, bridge_id):
        """destroy_subscription"""
        sub_mgr = self.subscriptions.get(topic_name, None)
        if sub_mgr:
            sub_mgr.remove_subscription(bridge_id)
            if not sub_mgr.destroy_when_empty():
                self.subscriptions.pop(topic_name)

    def destroy_publisher_by_topic(self, topic_name):
        """destroy_publisher_by_topic"""
        v = self.publisher.pop(topic_name, None)
        if v is not None:
            v.destroy()

    def destroy_subscription_by_topic(self, topic_name):
        """destroy_subscription_by_topic"""
        v = self.subscriptions.pop(topic_name, None)
        if v is not None:
            v.destroy()
            

    def destroy_publisher_by_bridge_id(self, bridge_id):   
        """destroy_publisher_by_bridge_id"""
        mlogger.debug("destroy_publisher_by_bridge_id")
        try:
            for sub in list(self.publisher.values()):
                sub.remove_publish(bridge_id)

            tempv = {}
            for k,v in list(self.publisher.items()):
                if v.destroy_when_empty():
                    tempv[k] = v
            self.publisher = tempv
        except Exception:
            mlogger.error(traceback.format_exc())            

    def destroy_subscription_by_bridge_id(self, bridge_id):
        """destroy_subscription_by_bridge_id"""
        mlogger.debug("destroy_subscription_by_bridge_id")
        try:
            for sub in list(self.subscriptions.values()):
                sub.remove_subscription(bridge_id)

            tempv = {}
            for k,v in list(self.subscriptions.items()):
                if v.destroy_when_empty():
                    tempv[k] = v
            self.subscriptions = tempv
        except Exception:
            mlogger.error(traceback.format_exc())