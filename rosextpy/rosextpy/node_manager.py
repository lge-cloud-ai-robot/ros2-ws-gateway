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
# Author: paraby@gmail.com
#

"""ros2 subscription and publish management
"""

import os
if os.environ['ROS_VERSION'] != '2':
    raise RuntimeError("ROS VERSION 2.0 required")
#
# ros version == foxy (rmw_fast_rtps of galactic version has some bugs )
import traceback
import json
from threading import Thread
import logging
import rclpy
from rclpy.qos import qos_profile_system_default
from rosextpy.ext_type_support import SerializedTypeLoader, TypeLoader, ros_from_json, ros_to_json


mlogger = logging.getLogger('node_manager')


class NodeManagerException(Exception):    
    pass

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

        #json_data = ros_to_json(message)
        
        # if isinstance(message, bytes):
            #message  will be raw
            #change bytes to json serializable


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
        mlogger.debug("ros node manager created")        

    def run(self):
        the_node = self.node
        mlogger.debug("ros node manager started")
        try:
            while rclpy.ok():
#                rclpy.spin_once(the_node)
                rclpy.spin_once(the_node, timeout_sec=0.001)
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
#        print("create_publisher 2", topic_type, topic_name, bridge_id,  queue_length, israw)
        
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

