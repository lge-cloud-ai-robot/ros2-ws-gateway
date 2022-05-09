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

# rosextpy.ros_gateway_agent (ros-ws-gateway)
# Author: parasby@gmail.com
"""ros_gateway_agent
"""
import sys
import os
import logging
import asyncio
from typing import List, Dict, Any
## must import configuration module before any other sub modules
from ..mod_config import WS_CONFIG 
from rosextpy.ros_gateway_agent import RosWsGatewayAgent

#logging.basicConfig(stream=sys.stdout, format='%(levelname)-6s [%(filename)s:%(lineno)d] %(message)s', level=logging.INFO)
logging.basicConfig(stream=sys.stdout, format='%(levelname)-6s [%(filename)s:%(lineno)d] %(message)s', level=logging.DEBUG)
mlogger = logging.getLogger('ros_agent_main')
mlogger.setLevel(logging.DEBUG)
logging.getLogger('ros_rpc_gateway_client').setLevel(logging.DEBUG)
logging.getLogger('ros_gateway_agent').setLevel(logging.DEBUG)
logging.getLogger('ros_ws_gateway').setLevel(logging.DEBUG)
logging.getLogger('ros_ws_gateway_client').setLevel(logging.DEBUG)
logging.getLogger('node_manager').setLevel(logging.DEBUG)
logging.getLogger('websocket_utils').setLevel(logging.DEBUG)
   
if WS_CONFIG['wsf'] == 'fastapi':    # wsf means web service framework
    from fastapi import Body, FastAPI, WebSocket, status, BackgroundTasks    
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
    from enum import Enum
    import argparse
    import json 
    import uvicorn

    class GatewayAddresses(BaseModel):
        address: List[str]

    class GatewayRule(BaseModel):
        address: str
        publish: List[Dict[str,str]]=None
        subscribe: List[Dict[str,str]]=None
        service: List[Dict[str,str]]=None
        action: List[Dict[str,str]]=None

    class ROSRESTRule(BaseModel):
        service_name: str
        service_uri: str
        service_method : str
        request_rule: Dict[str,Any]
        response_rule: Dict[str,Any]

    class ROSRESTStopRule(BaseModel):
        id: str

    app = FastAPI()
    agent :RosWsGatewayAgent= None    

    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", type=int,
                        help="Listen port, default to :9090", default=9000)
    parser.add_argument("-f", "--file", help="config file name")
    options = parser.parse_args()

    @app.on_event("startup")
    def task_start():
        global agent, options, rest_agent
        mlogger.debug("Command option is %s", options)
        agent = RosWsGatewayAgent(loop=asyncio.get_event_loop())               
        if options.file:
            with open(options.file) as json_file:
                configs = json.load(json_file)
                agent.apply_configs(configs)

    @app.on_event("shutdown")
    async def task_stop():
        global agent
        await agent.close()
        print("Server stopped OK")

## Agent Information API        

    @app.get('/topic',
        summary="Get topic lists being published ",
        description="request to get topic lists being distributed ",
        responses={
            200: {"description": "topic lists being published",
                "content": {
                    "application/json": {
                        "example": ["/my_topic","/some_topic"]
                    },
                },
            },
        },
    )
    async def get_topic_list():
        global agent
        topic_list = agent.api_get_topic_list()
        return topic_list 


    @app.get('/gateway',
        summary="Get gateway lists",
        description="request to get gateway lists to be configured to connect ",
        responses={
            200: {"description": "gateway lists to connect",
                "content": {
                    "application/json": {
                        "example": ["ws://localhost:2020","ws://localhost:3030"]
                    },
                },
            },
        },
    )
    async def get_gateway_list():
        global agent
        gw_list = agent.api_get_gw_list()
        return gw_list

    @app.post('/gateway/get/config',
        summary="Get gateway configs",
        description="get configs requested by addresses",    
        responses={
            200: {"description": "gateway configs",
                "content": {
                    "application/json": {
                        "example": 
                            [{"title": "a1","address": "ws://localhost:2020",
                            "active": "True",
                            "publish": {"/example_topic": "std_msgs/msg/String"},
                            "subscribe":{"/my_topic": "std_msgs/msg/String"}},
                            {"title": "a2","address": "ws://localhost:3030",
                            "active": "True",
                            "publish": {"/my_topic": "std_msgs/msg/String"},
                            "subscribe": {"/your_topic": "std_msgs/msg/String"}
                            }]
                    },
                },
            },
        },
    )  # have to be changed RESTfull convention[ When want to show data, use HTTP GET]
    async def get_gateway_config(
        rule: GatewayAddresses = Body(
            ...,
            example= {
                'address' : ['ws://localhost:2020','ws://localhost:3030']
            },
        ),
    ):
        global agent        
        results = agent.api_get_config(rule.address)
        return results

    @app.post('/gateway/add',
        summary="Add gateway to connect",
        description="request to add gateways to connect",
        responses={
            200: {"description": "success",
                "content": {
                    "application/json": {
                        "example" : "ok" 
                    },
                },
            },
        },
    )
    async def add_gateways(
        rule: GatewayAddresses = Body(
            ...,
            example= {
                'address' : ['ws://localhost:2020','ws://localhost:3030']
            },
        ),
    ):
        global agent        
        results = agent.api_add_gateways(rule.address)
        return results

    @app.put('/gateway/remove',
        summary="Remove gateway connections",
        description="request to disconnect from the gateways",          
        responses={
            200: {"description": "operation success",
                "content": {
                    "application/json": {
                        "example" : "ok" 
                    },
                },
            },
        },    
    )
    async def remove_gateways(
        rule: GatewayAddresses = Body(
            ...,
            example= {
                'address' : ['ws://localhost:2020','ws://localhost:3030']
            },
        ),
    ):
        global agent
        results = agent.api_remove_gateways(rule.address)
        return results

### Topic Publish

    @app.post('/gateway/publisher/add',
        summary="Add publish rule to the gateway",
        description="request to add publish rules to the gateway",       
        responses={
            200: {"description": "operation success",
                "content": {
                    "application/json": {
                        "example" : "ok" 
                    },
                },
            },
        },    
    )
    async def publisher_add(
        rule: GatewayRule = Body(
            ...,
            example= {
                'address' : 'ws://localhost:3030',
                "publish": [
                    {"name":"/my_topic", "messageType":"std_msgs/msg/String", "israw" : False}
                ],
            },
        ),
    ):
        global agent
        results = agent.api_publisher_add(rule.address, rule.publish)
        return results

    @app.put('/gateway/publisher/remove',
        summary="Remove Forwarding(publish) from gateway",
        description="request to remove subscribe rules from the gateway",
        responses={
            404: {"description": "The requested gateway was not found", 
                "content": {
                    "application/json" : {
                        "example" : "unknown gateway address" 
                    },
                },
            },            
            200: {"description": "Success",
                "content": {
                    "application/json" : {
                        "example" : "ok" 
                    },
                },
            },
        },    
    )
    async def publisher_remove(
        rule: GatewayRule = Body(
            ...,
            example= {
                'address' : 'ws://localhost:3030',
                'publish' : [
                    {"name":"/example_topic", "messageType":"std_msgs/msg/String"},
                    {"name":"/my_topic", "messageType":"std_msgs/msg/String"}
                ],
            },
        ),
    ):
        global agent
        results = agent.api_publisher_remove(rule.address, rule.publish)
        if results != "ok":
            return JSONResponse(status_code=404, content=results)
        return results        

### Topic Subscribe        

    @app.post('/gateway/subscriber/add',
        summary="Add subscribe rule to the gateway",
        description="request to add subscribe rules to the gateway ",    
        responses={
            200: {"description": "operation success",
                "content": {
                    "application/json": {
                        "example" : "ok" 
                    },
                },
            },
        },     
    )
    async def subscriber_add(
        rule: GatewayRule = Body(
            ...,
            example= {
                'address' : 'ws://localhost:9001',
                'subscribe' : [
                    {"name":"/chatter", "messageType":"std_msgs/msg/String", "israw": False}                    
                ],
            },
        ),
    ):
        global agent
        results = agent.api_subscriber_add(rule.address, rule.subscribe)
        return {"result": results}


    @app.put('/gateway/subscriber/remove',
        summary="Remove subscriptions from gateway",
        description="request to remove subscribe rules from the gateway",
        responses={
            404: {"description": "The requested gateway was not found", 
                "content": {
                    "application/json" : {
                        "example" : "unknown gateway address" 
                    },
                },
            },            
            200: {"description": "Success",
                "content": {
                    "application/json" : {
                        "example" : "ok" 
                    },
                },
            },
        },     
    )
    async def subscriber_remove(
        rule: GatewayRule = Body(
            ...,
            example= {
                'address' : 'ws://localhost',
                'subscribe' : [
                    {"name":"/example_topic", "messageType":"std_msgs/msg/String"},
                    {"name":"/my_topic", "messageType":"std_msgs/msg/String"}
                ],
            },           
        ),
    ):
        global agent
        results = agent.api_subscriber_remove(rule.address, rule.subscribe)
        return {"result": results} 


#### ROS SRV
    @app.post('/gateway/service/expose',
        summary="Add expose service rule to the gateway",
        description="request to add expose service rules to the gateway ",    
        responses={
            200: {"description": "operation success",
                "content": {
                    "application/json": {
                        "example" : "ok" 
                    },
                },
            },
        },     
    )
    async def service_expose(
        rule: GatewayRule = Body(
            ...,
            example= {
                'address' : 'ws://localhost:9001',
                'service' : [
                    {"service":"add_two_ints", "serviceType":"srv_tester_if.srv.AddTwoInts", "israw": False}                    
                ],
            },
        ),
    ):
        global agent
        results = agent.api_service_expose(rule.address, rule.service)
        return {"result": results}      

    @app.put('/gateway/service/hide',
        summary="Hide exposed service from remote gateway",
        description="request to hide exposed service to the gateway",
        responses={
            404: {"description": "The requested gateway was not found", 
                "content": {
                    "application/json" : {
                        "example" : "unknown gateway address" 
                    },
                },
            },            
            200: {"description": "Success",
                "content": {
                    "application/json" : {
                        "example" : "ok" 
                    },
                },
            },
        },     
    )
    async def service_hide(
        rule: GatewayRule = Body(
            ...,
            example= {
                'address' : 'ws://localhost:9001',
                'service' : [
                    {"service":"add_two_ints", "serviceType":"srv_tester_if.srv.AddTwoInts"}                    
                ],
            },           
        ),
    ):
        global agent
        results = agent.api_service_hide(rule.address, rule.service)
        return {"result": results}           

#### ROS ACTION
    @app.post('/gateway/action/expose',
        summary="Add expose action rule to the gateway",
        description="request to add expose action rules to the gateway ",    
        responses={
            200: {"description": "operation success",
                "content": {
                    "application/json": {
                        "example" : "ok" 
                    },
                },
            },
        },     
    )
    async def action_expose(
        rule: GatewayRule = Body(
            ...,
            example= {
                'address' : 'ws://localhost:9001',
                'action' : [
                    {"action":"fibonacci", "actionType":"action_tester_if.action.Fibonacci", "israw": False}                    
                ],
            },
        ),
    ):
        global agent
        results = agent.api_action_expose(rule.address, rule.action)
        return {"result": results}      

    @app.put('/gateway/action/hide',
        summary="Hide exposed action from remote gateway",
        description="request to hide exposed action to the gateway",
        responses={
            404: {"description": "The requested gateway was not found", 
                "content": {
                    "application/json" : {
                        "example" : "unknown gateway address" 
                    },
                },
            },            
            200: {"description": "Success",
                "content": {
                    "application/json" : {
                        "example" : "ok" 
                    },
                },
            },
        },     
    )
    async def action_hide(
        rule: GatewayRule = Body(
            ...,
            example= {
                'address' : 'ws://localhost:9001',
                'action' : [
                    {"action":"fibonacci", "actionType":"action_tester_if.action.Fibonacci"}                    
                ],
            },           
        ),
    ):
        global agent
        results = agent.api_action_hide(rule.address, rule.action)
        return {"result": results} 

############  ros-rest
############

    @app.post('/gateway/rosrest/add',
        summary="Add ROS-REST Mapping",
        description="add ROS-REST mapping",
        responses={
            200: {"description": "operation success",
                "content": {
                    "application/json": {
                        "example" : "ok" 
                    },
                },
            },
        },    
    )

    async def rosrest_add(
        rule: ROSRESTRule = Body(
            ...,
            examples={
                'file' : {
                    "summary": "File Up/Down example",
                    "description": "Post a file and receives a file response example",
                    "value": {
                        'service_name': 'detect service',
                        'service_uri' : 'http://localhost:9001/detect/',                
                        'service_method' : 'POST',
                        'request_rule' : { 
                            'content-type': 'multipart/form-data',
                            'topics' : {
                                '/image1' : 'sensor_msgs/msg/CompressedImage'
                            },
                            'mapping' : [
                                { 
                                    'in': '/image1', 'from' : 'data',  
                                    'out' : 'files', 'to': 'files' 
                                }
                            ],
                        },
                        'response_rule' : { 
                            'content-type': 'image/jpeg',
                            'topics': {'/target': 'sensor_msgs/msg/CompressedImage'},
                            'mapping' : [
                                {
                                    'in': 'content', 'from' : '', 
                                    'out' : '/target', 'to': ''
                                },
                            ],                                        
                        },
                    },
                },
                'json' : {  # At present  . I modify this rule
                    "summary": "JSON request/Json Response example",
                    "description": "Post a JSON body and receives a JSON response example",
                    "value": {
                        'service_name': 'joint state update service',
                        'service_uri' : 'http://localhost:9001/joint/', 
                        'service_method' : 'POST',
                        'request_rule' : { 
                            'content-type': 'application/json',
                            'topics' : {
                                '/joint1' : 'sensor_msgs/msg/JointState'
                            },
                            'mapping' : [
                                { 
                                    'in': '/joint1', 'from' : 'name',   # [ROS]JointState.name -->
                                    'out' : 'body', 'to': 'category/name'  #  { 'category' : { 'name' : xxx}}
                                },
                            ],                    
                        },
                        'response_rule' : { 
                            'content-type': 'application/json',
                            'topics': {'/targetJoint': 'sensor_msgs/msg/JointState'},
                            'mapping' : [
                                {
                                    # 'from' can be 'in' of SWAGGER spec:'topic of request', body, query, header, path
                                    'in': '/joint1', 'from' : 'name',   # reqeust의 데이터를 response에 활용
                                    'out' : '/targetJoint', 'to': 'name'
                                },
                                {
                                    'in': 'body', 'from' : 'position', 
                                    'out' : '/targetJoint', 'to': 'position'
                                },
                                { 
                                    'in': 'body', 'from' : 'velocity',  
                                    'out' : '/targetJoint', 'to': 'velocity'
                                },
                                { 
                                    'in': 'body', 'from' : 'effort', 
                                    'out' : '/targetJoint', 'to': 'effort'
                                },
                            ],  
                        },                   
                    },
                },
            },
        ),
    ):
        global agent        
        results = agent.api_rosrest_add(rule)
        return {"result": results} 

############  ros-rest lists
############
    @app.get('/gateway/rosrest/lists',
        summary="get ROS-REST Mapping lists",
        description="get ROS-REST Mapping lists",
        responses={
            200: {"description": "operation success",
                "content": {
                    "application/json": {
                        "detail" : "..." 
                    },
                },
            },
        },    
    )

    async def rosrest_lists():        
        global agent        
        results = agent.api_rosrest_lists()
        return {"results": results} 

############  ros-rest stop
############
    @app.put('/gateway/rosrest/stop',
        summary="Stop ROS-REST mapping process",
        description="Stop ROS-REST mapping process",
        responses={
            404: {"description": "The requested rule was not found", 
                "content": {
                    "application/json" : {
                        "example" : "unknown rule id" 
                    },
                },
            },            
            200: {"description": "Success",
                "content": {
                    "application/json" : {
                        "example" : "ok" 
                    },
                },
            },
        },    
    )
    async def rosrest_stop(
        rule: ROSRESTStopRule = Body(
            ...,
            example= {
                'id' : 'id-required-',
            },
        ),
    ):
        global agent
        results = agent.api_rosrest_stop(rule.id)
        if results != "ok":
            return JSONResponse(status_code=404, content=results)
        return { 'results': results }


#####################

    @app.websocket('/')
    async def ros_ws_endpoint(websocket:WebSocket):
        global agent
        await agent.serve(websocket)

    if __name__ == '__main__':
        uvicorn.run(app, host="0.0.0.0", port=options.port, log_level="info")
#        uvicorn.run(app, host="0.0.0.0", port=9000, log_level="trace")
#        uvicorn.run(app, host="0.0.0.0", port=9000, log_level="debug")
#        uvicorn.run("rosextpy.app.ros_gateway_service:app", host="0.0.0.0", port=9000, log_level="debug")

else:
    print(WS_CONFIG['wsf'])
    # run 
    # uvicorn rosextpy.gateway_endpoint_test:app --reload --host=0.0.0.0 --port=3000





