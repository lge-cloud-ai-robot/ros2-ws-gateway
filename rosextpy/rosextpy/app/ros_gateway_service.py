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
# Author: paraby@gmail.com
"""ros_gateway_agent
"""
import sys
import logging
import asyncio
from typing import List, Dict
## must import configuration module before any other sub modules
from ..mod_config import WS_CONFIG 
#from rosextpy.ros_gateway_agent import RosWsGatewayAgent
logging.basicConfig(stream=sys.stdout, format='%(levelname)-6s [%(filename)s:%(lineno)d] %(message)s', level=logging.INFO)
mlogger = logging.getLogger('ros_agent_main')
#mlogger.setLevel(logging.DEBUG)
from rosextpy.ros_gateway_agent import RosWsGatewayAgent
#logging.getLogger('ros_gateway_agent').setLevel(logging.DEBUG)
#logging.getLogger('ros_ws_gateway').setLevel(logging.DEBUG)
#logging.getLogger('ros_ws_gateway_client').setLevel(logging.DEBUG)
#logging.getLogger('node_manager').setLevel(logging.DEBUG)
#logging.getLogger('websocket_utils').setLevel(logging.DEBUG)
   
if WS_CONFIG['wsf'] == 'fastapi':    # wsf means web service framework
    from fastapi import Body, FastAPI, WebSocket, status, BackgroundTasks    
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
    from enum import Enum
    import argparse
    import json 
    import uvicorn

    class GatewayOperationType(str, Enum):
        add = 'add'
        remove = 'remove'
        disconnect = 'disconnect'

    class GatewayOperation(BaseModel):
        address: str
        operation: GatewayOperationType
        publish: List[Dict[str,str]]=None
        subscribe: List[Dict[str,str]]=None

    class GatewayAddresses(BaseModel):
        address: List[str]

    class GatewayRule(BaseModel):
        address: str
        publish: List[Dict[str,str]]=None
        subscribe: List[Dict[str,str]]=None

    app = FastAPI()
    agent = None    

    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", type=int,
                        help="Listen port, default to :9090", default=9000)
    parser.add_argument("-f", "--file", help="config file name")
    options = parser.parse_args()

    @app.on_event("startup")
    def task_start():
        global agent, options
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
    

    @app.post('/gateway/add/publish',
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
    async def add_gateway_publish(
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
        results = agent.api_add_publish(rule.address, rule.publish)
        return results

    @app.post('/gateway/add/subscribe',
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
    async def add_gateway_subscribe(
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
        results = agent.api_add_subscribe(rule.address, rule.subscribe)
        return {"result": results}

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

    @app.put('/gateway/remove/publish',
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
    async def remove_gateway_publish(
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
        results = agent.api_remove_publish(rule.address, rule.publish)
        if results != "ok":
            return JSONResponse(status_code=404, content=results)
        return results

    @app.put('/gateway/remove/subscribe',
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
    async def remove_gateway_subscribe(
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
        results = agent.api_remove_subscribe(rule.address, rule.subscribe)
        return {"result": results} 

    @app.websocket('/')
    async def ros_ws_endpoint(websocket:WebSocket):
        global agent
        await agent.serve(websocket)

    if __name__ == '__main__':
        uvicorn.run(app, host="0.0.0.0", port=9000, log_level="info")
#        uvicorn.run(app, host="0.0.0.0", port=9000, log_level="trace")
#        uvicorn.run(app, host="0.0.0.0", port=9000, log_level="debug")
#        uvicorn.run("rosextpy.app.ros_gateway_service:app", host="0.0.0.0", port=9000, log_level="debug")

else:
    print(WS_CONFIG['wsf'])
    # run 
    # uvicorn rosextpy.gateway_endpoint_test:app --reload --host=0.0.0.0 --port=3000





