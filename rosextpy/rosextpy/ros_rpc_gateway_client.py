#  MIT License
#
#  Copyright (c) 2021,
#    Electronics and Telecommunications Research Institute (ETRI) All Rights Reserved.
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

# rosextpy.ros_rpc_gateway_client (ros-ws-gateway)
# Author: paraby@gmail.com
"""ros_rest_gateway
"""
import logging
import uuid
import json
# from typing import List, Dict
import io
import functools
import pybase64
from PIL import Image as PILImage

# must import configuration module before any other sub modules
from rosextpy.node_manager import NodeManager
from rosextpy.ext_type_support import (
    set_json_value, get_json_value, get_ros_value, set_ros_value, is_ros_obj)

mlogger = logging.getLogger('ros_rpc_gateway_client')
mlogger.setLevel(logging.DEBUG)

# pylint: disable=broad-exception-caught
# pylint: disable=too-many-arguments
# pylint: disable=too-many-instance-attributes


class RosRPCGatewayClient():
    """RosRPCGatewayClient
    """

    def __init__(self, node_mgr, rpc_mgr, service_uri, service_method, request_rule, response_rule):
        self.node_manager: NodeManager = node_mgr
        self.rpc_manager = rpc_mgr
        self.service_uri = service_uri  # target service URI
        self.service_method = service_method  # default POST
        self.request_rule = request_rule    # json['request']
        self.response_rule = response_rule
        self.subscribers = {}   # {topic, handler} dict
        self.publishers = {}  # {topic, handler} dict
        self.gwid = uuid.uuid4().hex  # hex form "xxxxxxxx...xxx"
        self._init()

    def _init(self):
        mlogger.debug("_init  ")
        for topic, topic_type in self.request_rule['topics'].items():
            self.subscribers[topic] = self.node_manager.create_subscription(
                topic_type, topic, self.gwid,
                {'callback': self._ros_subscription_callback, 'compression': None})

        for topic, topic_type in self.response_rule['topics'].items():
            self.publishers[topic] = self.node_manager.create_publisher(
                topic_type, topic, self.gwid)

    def close(self):
        """close
        """
        for topics in list(self.publishers.keys()):
            self.node_manager.destroy_publisher(topics, self.gwid)
        for topics in list(self.subscribers.keys()):
            self.node_manager.destroy_subscription(topics, self.gwid)

    def reset(self, request_rule, response_rule):
        """reset

        Args:
            request_rule (_type_): _description_
            response_rule (_type_): _description_
        """
        self.close()
        self.request_rule = request_rule
        self.response_rule = response_rule
        self._init()

    def _ros_subscription_callback(self, topic_name, mesg, compression):
        mlogger.debug("_ros_subscription_callback  %s", topic_name)
        outctx = None
        response = None
        _ = compression  # reserved

        if self.request_rule['content-type'] == 'application/json':
            data = self.make_json_request(topic_name, mesg)
            if data:
                # response = requests.post(self.service_uri, data=json.dumps(data))
                response = self.rpc_manager.call(self.service_uri, self.service_method,
                                                 data=json.dumps(data))
        elif self.request_rule['content-type'] == 'multipart/form-data':
            files = self._make_file_request(topic_name, mesg)
            if files:
                # response = requests.post(self.service_uri, files=files)
                response = self.rpc_manager.call(self.service_uri, self.service_method,
                                                 files=files)

        if response:
            outctx = self.response_to_mesg(
                response, req_ctx={topic_name: mesg})

        if outctx:
            for k, _msg in outctx.items():
                mlogger.debug(" Topic [%s] ", k)
                self.publishers[k].publish(_msg)

    def _make_file_request(self, topic_name, mesg):
        topic_type = self.request_rule['topics'].get(topic_name)

        if topic_type == 'sensor_msgs/msg/CompressedImage':
            # files = { self.mapping.properties[0]['name'] : mesg.data}
            for rule in list(self.request_rule['mapping']):
                if rule['in'] == topic_name:
                    if rule['out'] == 'files':
                        return {rule['to']: mesg.data}

        elif topic_type == 'sensor_msgs/msg/Image':
            _img = None
            if mesg.encoding == 'rgb8':
                _img = PILImage.frombytes(
                    'RGB', (mesg.width, mesg.height), mesg.data)
            elif mesg.encoding == 'mono8':
                _img = PILImage.frombytes(
                    'L', (mesg.width, mesg.height), mesg.data)

            if _img:
                outdata = io.BytesIO()
                _img.save(outdata, format='jpeg')
                for rule in list(self.request_rule['mapping']):
                    if rule['in'] == topic_name:
                        if rule['out'] == 'files':
                            return {rule['to']: outdata.getvalue()}

        else:
            mlogger.debug("cannot make file request for [%s]", topic_type)

        return None

    def make_json_request(self, topic_name, mesg):
        """make_json_request:make REST service request body  """
        body = {}
        # check topic type :At present, it does not make JSON for Image type topic.

        topic_type = self.request_rule['topics'].get(topic_name)

        if topic_type == 'sensor_msgs/msg/CompressedImage':
            for rule in list(self.request_rule['mapping']):
                if rule['in'] == topic_name:
                    if rule['out'] == 'body':
                        return {rule['to']: pybase64.b64encode(mesg.data.tobytes()).decode()}

        elif topic_type == 'sensor_msgs/msg/Image':
            _img = None
            if mesg.encoding == 'rgb8':
                _img = PILImage.frombytes(
                    'RGB', (mesg.width, mesg.height), mesg.data)
            elif mesg.encoding == 'mono8':
                _img = PILImage.frombytes(
                    'L', (mesg.width, mesg.height), mesg.data)

            if _img:
                outdata = io.BytesIO()
                _img.save(outdata, format='jpeg')
                for rule in list(self.request_rule['mapping']):
                    if rule['in'] == topic_name:
                        if rule['out'] == 'files':
                            return {rule['to']: pybase64.b64encode(outdata.getvalue()).decode()}
        else:

            # Image types cannot be converted to JSON
            # if topicType in self.no_json_list:
            #     mlogger.error('type %s cannot be encoded to json', topicType)
            #     return None

            for rule in list(self.request_rule['mapping']):
                if rule['in'] == topic_name:
                    if rule['out'] == 'body':
                        body = set_json_value(body, rule['to'],
                                              get_ros_value(mesg, rule['from']))

        return body

    # outctx = {topicName: ros_obj}
    def _map_resp_to_mesg(self, outctx, mapping, req_ctx):
        """_map_resp_to_mesg: map REST json response to ROS message"""
        mlogger.debug("_map_resp_to_mesg")
        for rule in list(mapping):
            src_res = req_ctx.get(rule['in'], None)
            des_res = outctx.get(rule['out'], None)

            if src_res is None or des_res is None:
                mlogger.debug(
                    "illegal mapping in[%s] or out[%s]", rule['in'], rule['out'])
                return None

            if src_res:
                if is_ros_obj(src_res):
                    outctx[rule['out']] = set_ros_value(
                        des_res, rule['to'], get_ros_value(src_res, rule['from']))
                else:
                    outctx[rule['out']] = set_ros_value(
                        des_res, rule['to'], get_json_value(src_res, rule['from']))
            else:
                mlogger.error("Unknonw mapping context [%s]", rule['in'])
                return None

        return outctx

    # req_ctx = {subscribed topic name : subscribed ros message object}
    def response_to_mesg(self, resp, req_ctx):
        """response_to_mesg :  
            make ros message from REST response (when status==200 OK)
            Args:
                resp: response from python 'requests' call
                req_ctx: { resource_name : resource_object} : 
                    resource_name -> ros topic or body or content
        """
        outctx = {}
        content_type = resp.headers['content-type'].split('/')
        expected_type = self.response_rule['content-type'].split('/')
        if content_type[0] != expected_type[0]:
            mlogger.debug('Response type [%s] is not matched to expected type [%s]',
                          resp.headers['content-type'], self.response_rule['content-type'])
            return None

        if content_type[0] == 'application':
            # json to ros message
            if content_type[1] == 'json':
                resp_json = resp.json()
                # req_ctx us resued for response context
                req_ctx['body'] = resp_json
                # make empty ROS message object for each topics in response_rule
                outctx = dict(map(lambda x: (
                    x, self.publishers[x].get_class_obj()), self.response_rule['topics']))
                # fill ROS message object from request context
                outctx = self._map_resp_to_mesg(
                    outctx, self.response_rule['mapping'], req_ctx)
            else:
                mlogger.debug(
                    "Not Supported Yet for content-type [%s]", resp.headers['content-type'])

        elif content_type[0] == 'image':  # file type response image/jpeg, jpg, jpe
            # image to ros Image or CompressedImage
            outtopic = list(self.response_rule['topics'].keys())[0]
            outtype = list(self.response_rule['topics'].values())[0]
            if outtype == 'sensor_msgs/msg/CompressedImage':
                outmsg = self.publishers[outtopic].get_class_obj()
                outmsg.format = content_type[1]
                outmsg.data = resp.content
                outctx = {outtopic: outmsg}
            elif outtype == 'sensor_msgs/msg/Image':
                outmsg = self.publishers[outtopic].get_class_obj()
                _im = PILImage.open(io.BytesIO(resp.content))
                _im = _im.convert('RGB')
                outmsg.header.stamp = self.node_manager.get_now().to_msg()
                outmsg.height = _im.height
                outmsg.width = _im.width
                outmsg.encoding = 'rgb8'
                outmsg.is_bigendian = False
                outmsg.step = 3 * _im.width
                outmsg.data = _im.tobytes()
                outctx = {outtopic: outmsg}
            else:
                mlogger.warning(
                    "Not Supported Yet for converting image to %s", outtype)
        # 'text/css, text/html, text/plain, text/xml, text/xsl
        elif content_type[0] == 'text':
            # cannot handle 'text/html' in json api
            mlogger.warning("Not Supported Yet")

        return outctx
