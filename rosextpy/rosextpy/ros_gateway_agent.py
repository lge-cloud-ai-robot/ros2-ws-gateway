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

# rosextpy.ros_gateway_agent (ros2-ws-gateway)
# Author: parasby@gmail.com
"""ros_gateway_agent
"""
from asyncio.tasks import Task
import logging
import asyncio
import threading
from typing import List, Dict, Any
from tenacity import retry, wait
import tenacity
import traceback
import hashlib
from tenacity.retry import retry_if_exception
from tenacity.stop import stop_after_attempt, stop_when_event_set
from pydantic import BaseModel
import requests

## configuration module have to be importedbefore any other sub modules
#from ..mod_config import WS_CONFIG 
#WS_CONFIG['wsf'] = 'fastapi'

from rosextpy.ros_ws_gateway_client import RosWsGatewayClient, isNotForbbiden 
from rosextpy.node_manager import NodeManager
from rosextpy.ros_ws_gateway_endpoint import RosWsGatewayEndpoint
from rosextpy.ros_ws_gateway import RosWsGateway
from rosextpy.ros_rpc_gateway_client import RosRPCGatewayClient

mlogger = logging.getLogger('ros_gateway_agent')

def logerror(retry_state: tenacity.RetryCallState):    
    mlogger.debug("connection failed finally because %s", retry_state.outcome.exception())

########################
##
##  GatewayTaskLog : it stores the gateway tasks(pub/sub...)
#########################

class ROSRESTRule(BaseModel):
    service_name: str
    service_uri: str
    service_method : str
    request_rule: Dict[str,Any]
    response_rule: Dict[str,Any]

class GatewayTaskLog():
    def __init__(self, address, title, active):
        self.config={}
        self.config['title'] = title
        self.config['address'] = address
        self.config['active'] = str(active)
        self.active = active
        self.config['publish'] = []
        self.config['subscribe'] = []
        """
        config (dict): config dict
            ex: {'title' : 'a1', 'active' : True,address': 'ws://129.254.90.138:9090', 
                 'publish': [
                     { "name": "/chatter", "messageType": "std_msgs/msg/String", "israw": false},
                     { "name": "/sample", "messageType": "std_msgs/msg/String", "israw": false},
                    ]
                  'subscribe': [
                     { "name": "/chatter", "messageType": "std_msgs/msg/String", "israw": false},
                     { "name": "/sample", "messageType": "std_msgs/msg/String", "israw": false},
                    ]
                 }                    
        """        

    def __str__(self):
        return '("title" : {}, "address" : {}, "active" : {}, "publish" : {}, "subscribe" : {}'.format(
            self.config['title'], self.config['address'], self.config['active'],
            self.config['publish'], self.config['subscribe'])

    def get_config(self):
        return self.config


    def _check_pub_topic_exist_(self, topicName):
        if len(self.config['publish'])==0:
            return False
        for x in self.config['publish']:
            if x['name'] == topicName:
                return False
        return True


    def _check_sub_topic_exist_(self, topicName):
        if len(self.config['subscribe'])==0:
            return False
        for x in self.config['subscribe']:
            if x['name'] == topicName:
                return False
        return True


    def on_req_advertise(self,topicName, topicTypeStr, israw):
        mlogger.debug("GatewayTaskLog:on_req_advertise")
        if not self._check_pub_topic_exist_(topicName):            
            self.config['publish'].append({'name' : topicName, 'messageType' : topicTypeStr, 'israw' : israw})

    def on_req_unadvertise(self,topicName):
        mlogger.debug("GatewayTaskLog:on_req_unadvertise")        
        for x in self.config['publish']:
            self.config['publish'].remove(x)

    def on_req_subscribe(self, topicName, topicTypeStr, israw):
        mlogger.debug("GatewayTaskLog:on_req_subscribe")
        if not self._check_pub_topic_exist_(topicName):
            self.config['subscribe'].append({'name' : topicName, 'messageType' : topicTypeStr, 'israw' : israw})        

    def on_req_unsubscribe(self, topicName):
        mlogger.debug("GatewayTaskLog:on_req_unsubscribe")
        for x in self.config['subscribe']:
            self.config['subscribe'].remove(x)


######################
# DefaultRPCManager
#######################
class DefaultRPCManager:  
    def __init__(self):        
        pass        

    def call(self, service_uri, service_method, data = None, files=None):
        mlogger.debug("emulate to send action result to action caller.............")
        try:
            if service_method == 'POST':
                return requests.post(service_uri, files=files, data=data)
        except Exception as err:
            mlogger.debug("An error occurred in requests due to [%s]", err)
            return None

    def close(self):
        pass

########################
##
##  RosWsGatewayAgent : create gateway_endpoint, and manage gateway_client
#########################

class RosWsGatewayAgent():
    """Forwards ROS messages from its own subnet to the gateway of another subnets, 
    receives ROS messages from other subnets, and delivers them to the subnet it belongs to.
    """
    def __init__(self, loop=None, **kwargs):
        self.node_manager = NodeManager()
        self.node_manager.setDaemon(True)
        self.node_manager.start()
        self.rpc_manager = DefaultRPCManager()
        self.endpoint = RosWsGatewayEndpoint(node_manager = self.node_manager)
        self.gw_task_logs : Dict[str, GatewayTaskLog] = {}
        self.gw_map : Dict[str, RosWsGatewayClient] ={}
        self.rpc_map: Dict[str, RosRPCGatewayClient] = {}
        self.gw_tasks : Dict[str, Task] = {}
        self.gw_tasks_lock = threading.RLock()     
        self.loop = loop if loop is not None else asyncio.get_event_loop()
        self.retry_config = {    
            'wait': wait.wait_random_exponential(min=0.1, max=10),  # debug config
            #'wait': wait.wait_random_exponential(min=0.1, max=120), # normal config
            'retry': retry_if_exception(isNotForbbiden),
            'reraise': True,
            #'stop' : stop_after_attempt(10), # normal config
            'stop' : stop_after_attempt(1), # debug config
            'retry_error_callback': logerror
        }

    async def _stop_client_tasks(self):
        mlogger.debug("_stop_client_tasks")
        try:
            for t_task in list(self.gw_tasks.values()):
                t_task.cancel()
        except :
            mlogger.debug(traceback.format_exc())

    async def _on_connect(self, gw : RosWsGateway):
        mlogger.debug("_on_connect")
        mlogger.debug("Connected to(from) %s", gw.wshandle.address())

    async def _on_disconnect(self, gw : RosWsGateway):
        mlogger.debug("_on_disconnect")

    async def _connect(self, uri, config:Dict=None):
        mlogger.debug("connect!!!!") 

        try :            
            async with RosWsGatewayClient(uri, self.node_manager,
                           on_connect=[self._on_connect],
                               on_disconnect=[self._on_disconnect], 
                               retry_config=False # for Debug, else None
                               ) as client:
                self.gw_map[uri] = client #  considered to be called from a single thread
                task_log = self.gw_task_logs.get(uri, None)
                task_config = config

                if task_log:
                    task_config = task_log.get_config()
                    task_log = GatewayTaskLog(uri, task_log.config['title'], True)
                else:
                    if task_config:
                        t_title = config.get('title',uri) # when no specific title, use uri
                    else:
                        t_title = uri
                    task_log = GatewayTaskLog(uri, t_title, True)
                
                client.register_req_advertise_handler([task_log.on_req_advertise])
                client.register_req_unadvertise_handler([task_log.on_req_unadvertise])
                client.register_req_subscribe_handler([task_log.on_req_subscribe])
                client.register_req_unsubscribe_handler([task_log.on_req_unsubscribe])

                self.gw_task_logs[uri] = task_log   
#                print("CONNECT CONFIG", config)             
#                print("CONNECT TASSK CONFIG", task_config)

                if task_config:
                    if 'publish' in task_config:                        
                        for pub in task_config['publish']:                                                        
                            israw = pub.get('israw', False)
                            client.add_publish( pub['name'], pub['messageType'], israw)
                    if 'subscribe' in task_config:
                        for sub in task_config['subscribe']:                            
                            israw =sub.get('israw', False)
                            client.add_subscribe( sub['name'], sub['messageType'], israw)
                    if 'expose-service' in task_config:
                        for rule in task_config['expose-service']:                            
                            israw =rule.get('israw', False)
                            client.expose_service( rule['service'], rule['serviceType'], israw)
                    if 'expose-action' in task_config:
                        for rule in task_config['expose-action']:                            
                            israw =rule.get('israw', False)
                            client.expose_action( rule['action'], rule['actionType'], israw)
                await client.wait_on_reader()                
        except Exception as ex:
            # some error will be forwarded to retry connection
            mlogger.debug(traceback.format_exc())
            raise
        finally:
            self.gw_map.pop(uri, None)

    async def _keep_connect(self, uri, config:Dict=None):
        mlogger.debug("_keep_connect: ")
        try:
            # TODO: config:Dict에서 retry_config 수정값을 받아서, self.retry_config에 적용 필요
            #  critical system인 경우 retry 시도후, 복구가 안되면 모니터로 알릴 필요 있음. 
            # critical 하지 않다면 retry 시도후, 일정 조건이면 상태 기록만 남겨야함.
            # 상태 유지/관리를 위한 DB 부분과, 해당 상태 도달을 위한 에이전트 분리 필요 -K8S 개념 활용
            await retry(**self.retry_config)(self._connect)(uri, config)
        except Exception:
            mlogger.debug(traceback.format_exc())


    def _run_gateway_task(self, uri, config:Dict=None):
        """run gateway task [thread safe]
        """
        mlogger.debug("run_gateway_task: ")
        try:
            t1 = asyncio.ensure_future(self._keep_connect(uri, config), loop=self.loop)
            
            with self.gw_tasks_lock:
                self.gw_tasks[uri]= t1
        except Exception:
            mlogger.debug(traceback.format_exc())
            
    def apply_configs(self, configs):
        """apply the agent configuration about ROS pub/sub forwarding with configs[python object from json]
        Args:
            configs: python object[from json]
        Examples:
            >>> with open('filename.json') as json_file:
                    configs = json.load(json_file)
                    agent.apply_configs(configs)
        """
        if isinstance(configs, List):
            for data in configs:
                self.apply_config(data)
        elif isinstance(configs, Dict):
            self.apply_config(configs)
        else:
            mlogger.debug("Unknwon Configs")

    def apply_config(self, data:Dict):
        """ apply the config of ros2 publish/subscribe agent task
        Args:
            data (dict): config dict
                    ex:{'title' : 'a1', 
                        'active' : True,
                        'address': 'ws://129.254.90.138:9090', 
                        'publish': [{'name': '/example_topic', 'messageType': 'std_msgs/msg/String'},
                                    {'name': '/my_topic', 'messageType': 'std_msgs/msg/String'}], 
                        'subscribe': [{'name': '/my_topic', 'messageType': 'std_msgs/msg/String'}]
                        }
        """        
        mlogger.debug("apply_config %s", data)
        try:
            uri = data['address']
            active = data.get('active', True)
            if active:
                gw = self.gw_map.get(uri, None)
                if gw: # find running gateway client
                    mlogger.debug("gateway is running")
                    pass
                else:
                    self._run_gateway_task(uri, data)
        except Exception:
            mlogger.debug(traceback.format_exc())
            pass   
           
    def api_add_gateways(self, rule: List[str]):
        """Add the address of the gateway to connect to        
        Args:
            rule (List[str]): list of gateway addresses to connect
        Returns:
            "ok" 
        """
        mlogger.debug("api_add_gateways %s",rule)
        try:
            for uri in rule:              
                gw = self.gw_map.get(uri, None)
                if not gw:
                    self._run_gateway_task(uri, None)

            return "ok"
        except Exception:
            mlogger.debug(traceback.format_exc())
            pass

    def api_remove_gateways(self, rule: List[str]):
        """Set the address of the gateway to disconnect.
            It stops connection retry to the specified gateways.
        Args:
            rule (List[str]): list of gateway addresses to disconnect
        Returns:
            "ok" 
        """
        mlogger.debug("api_remove_gateways %s",rule)
        try:
            for uri in rule:              
                gw_task = self.gw_tasks.get(uri, None)
                if gw_task:
                    gw_task.cancel()

            return "ok"
        except Exception:
            mlogger.debug(traceback.format_exc())
            pass           


    def api_publisher_add(self, uri: str, rule: List[Dict[str,str]]):
        """ set the ROS message forwarding configuration to the specified gateway.
            It causes configured ROS messages to be delivered to the specified gateway.
        Args:
            uri : target gateway address
            rule (List[str]): list of publication forwarding rule        
        Returns:
            "ok" 
        Examples:
            api.add_publish("ws://targetgw",
                [{name:"/my_topic", messageType:"std_msgs/msg/String", israw: False}])
        """
        mlogger.debug("api_publisher_add %s", uri)        
        try:
            gw = self.gw_map.get(uri, None)
            if gw:
                for pub in rule:
                    gw.add_publish( pub['name'], pub['messageType'], pub.get('israw', False))
            else:
                temp_config = { 'address' : uri, 'publish': rule}
#                print("TEMP CONFIG ", temp_config)
                self._run_gateway_task(uri, temp_config)

            return "ok"
        except Exception:
            mlogger.debug(traceback.format_exc())
            pass

    def api_subscriber_add(self, uri: str, rule: List[Dict[str,str]]):
        """ set the ROS message pulling configuration to the specified gateway.
            It causes the configured ROS messages of the specified gateway to be delivered to its own gateway.
        Args:
            uri : target gateway address
            rule (List[str]): list of subscription rule        
        Returns:
            "ok" 
        Examples:
            api.add_subscribe("ws://targetgw",
                [{name:"/my_topic", messageType:"std_msgs/msg/String"}])
        """        
        mlogger.debug("api_subscriber_add %s", uri)
        try:
            gw = self.gw_map.get(uri, None)
            if gw:
                for pub in rule:                    
                    gw.add_subscribe( pub['name'], pub['messageType'],  pub.get('israw', False))
            else:
                temp_config = { 'address' : uri, 'subscribe': rule}
                self._run_gateway_task(uri, temp_config)

            return "ok"
        except Exception:
            mlogger.debug(traceback.format_exc())
#            traceback.print_stack()
            pass   

    def api_publisher_remove(self, uri: str, rule: List[Dict[str,str]]):
        """ stops the ROS message forwarding for the specified gateway
        Args:
            uri : target gateway address
            rule (List[str]): list of published ROS messages        
        Returns:
            "ok" If successful, "unknown gateway address" otherwise.
        Examples:
            api.api_remove_publish("ws://targetgw",
                [{name:"/my_topic", messageType:"std_msgs/msg/String"}])
        """        
        mlogger.debug("api_publisher_remove %s", uri)
        try:
            gw = self.gw_map.get(uri, None)
            if gw:
                for pub in rule:                    
                    gw.remove_publish( pub['name'])

                return "ok"
            else:
                return "unknown gateway address"
        except Exception:
            mlogger.debug(traceback.format_exc())
            pass

    def api_subscriber_remove(self, uri: str, rule: List[Dict[str,str]]):
        """ requests the specified gateway to stop sending ROS messages to its own gateway.
        Args:
            uri : target gateway address
            rule (List[str]): list of subscribed ROS messages        
        Returns:
            "ok" If successful, "unknown gateway address" otherwise.
        Examples:
            api.api_remove_subscribe("ws://targetgw",
                [{name:"/my_topic", messageType:"std_msgs/msg/String"}])
        """          
        mlogger.debug("api_subscriber_remove %s", uri)
        try:
            gw = self.gw_map.get(uri, None)
            if gw:
                for pub in rule:                    
                    gw.remove_subscribe( pub['name'])

                return "ok"
            else:
                return "unknown gateway address"
        except Exception:
            mlogger.debug(traceback.format_exc())
            pass

    def api_service_expose(self, uri: str, rule: List[Dict[str,str]]):
        """ set the service to be exposed to the specified gateway.            
        Args:
            uri : target gateway address
            rule (List[str]): list of service expose rule        
        Returns:
            "ok" 
        Examples:
            api.api_service_expose("ws://targetgw",
                [{service:"add_two_ints", "serviceType:"srv_tester_if.srv.AddTwoInts"}])
        """        
        mlogger.debug("api_service_expose %s", uri)
        try:
            gw = self.gw_map.get(uri, None)
            if gw:
                for srv in rule:                    
                    gw.expose_service( srv['service'], srv['serviceType'],srv.get('israw', False))
            else:
                temp_config = { 'address' : uri, 'expose-service': rule}
                self._run_gateway_task(uri, temp_config)

            return "ok"
        except Exception:
            mlogger.debug(traceback.format_exc())
#            traceback.print_stack()
            pass


    def api_action_expose(self, uri: str, rule: List[Dict[str,str]]):
        """ set the action to be exposed to the specified gateway.            
        Args:
            uri : target gateway address
            rule (List[str]): list of action expose rule        
        Returns:
            "ok" 
        Examples:
            api.api_action_expose("ws://targetgw",
                [{action:"fibonacci", actionType:"action_tester_if.action.Fibonacci"}])
        """        
        mlogger.debug("api_action_expose %s", uri)
        try:
            gw = self.gw_map.get(uri, None)
            if gw:
                for act in rule:                    
                    gw.expose_action( act['action'], act['actionType'],act.get('israw', False))
            else:
                temp_config = { 'address' : uri, 'expose-action': rule}
                self._run_gateway_task(uri, temp_config)

            return "ok"
        except Exception:
            mlogger.debug(traceback.format_exc())
#            traceback.print_stack()
            pass


    def api_service_hide(self, uri: str, rule: List[Dict[str,str]]):
        """ requests the specified gateway to stop send ROS srv request
        Args:
            uri : target gateway address
            rule (List[str]): list of exposed ROS service to be hidden
        Returns:
            "ok" If successful, "unknown gateway address" otherwise.
        Examples:
            api.api_service_hide("ws://targetgw",
                [{service:"add_two_ints"}])
        """          
        mlogger.debug("api_service_hide %s", uri)
        try:
            gw = self.gw_map.get(uri, None)
            if gw:
                for srv in rule:                    
                    gw.hide_service(srv['service'])                    

                return "ok"
            else:
                return "unknown gateway address"
        except Exception:
            mlogger.debug(traceback.format_exc())
            pass   

    def api_action_hide(self, uri: str, rule: List[Dict[str,str]]):
        """ requests the specified gateway to stop send ROS action request
        Args:
            uri : target gateway address
            rule (List[str]): list of exposed ROS action to be hidden
        Returns:
            "ok" If successful, "unknown gateway address" otherwise.
        Examples:
            api.api_action_hide("ws://targetgw",
                [{action:"fibonacci"])
        """          
        mlogger.debug("api_action_hide %s", uri)
        try:
            gw = self.gw_map.get(uri, None)
            if gw:
                for act in rule:                    
                    gw.hide_action(act['action'])                    

                return "ok"
            else:
                return "unknown gateway address"
        except Exception:
            mlogger.debug(traceback.format_exc())
            pass      

    def api_get_config(self, rule: List[str]):
        """
        get the config set fro the request gateway address
        Args:
            rule (List[str]): list of gateway addresses to query
        Returns:
            list of configuration if successful, empty list otherwise.                    
        """
        mlogger.debug("api_get_config %s",rule)
        results = []

        for uri in rule:
            gw = self.gw_map.get(uri, None)
            if gw:
                results.append(self.gw_task_logs[uri].config)

        return results

    def api_get_gw_list(self):
        """ get connected gateway server list [ url ]
        """
        mlogger.debug("api_get_gw_list")
        return list(self.gw_map.keys())

    def api_get_topic_list(self):
        """ get topic list being published in the network
        """
        mlogger.debug("api_get_topic_list")
        topic_list = self.node_manager.get_topic_list()
        return topic_list

    def api_rosrest_add(self, rule : ROSRESTRule):
        """ add rot-to-rest binding configuration              

        ##  key is (output topic + service_uri + input_topic)
        Args:
            rule: ros-rest binding config            
        Returns:
            { "id" : id}
        Examples:
            api_add_ros_rest("{}")
        """
        mlogger.debug("api_add_ros_rest %s", rule)
        try:
            v = [ *list(rule.response_rule['topics'].keys()), 
                    rule.service_uri, *list(rule.request_rule['topics'].keys())]            
            _utxt = '<'.join(v)
            _ho = hashlib.sha256(_utxt.encode())
            _ukey = _ho.hexdigest()            
            _gw : RosRPCGatewayClient = self.rpc_map.get(_ukey, None)
            if _gw:                
                 _gw.reset(rule.request_rule, rule.response_rule)
            else:
                _gw = RosRPCGatewayClient(self.node_manager, self.rpc_manager, rule.service_uri, 
                        rule.service_method, rule.request_rule, rule.response_rule)                                
                self.rpc_map[_ukey] =  _gw
            return { "id" : _ukey}
        except Exception:
            mlogger.debug(traceback.format_exc())
            pass

    def api_rosrest_lists(self):
        """ add rot-to-rest binding configuration      
        Returns:
             [  
                { 
                    'id' : id,
                    'service_uri': uri,
                    'request_rule' : {
                        'topics': {
                            topicName : topicType
                        },
                    },                
                    'response_rule' : {
                        'topics': {
                            topicName : topicType
                        },
                    },
                },
            ]
        Examples:
            api_add_ros_rest("{}")
        """
        mlogger.debug("api_ros_rest_lists ")
        try:
            results = []
            for k, v in self.rpc_map.items():                
                value = { 
                    'id' : k,
                    'service_uri': v.service_uri,
                    'request_rule': {
                        'topics' : v.request_rule['topics']
                    },
                    'response_rule': {
                        'topics' : v.response_rule['topics']
                    }
                }
                results.append(value)
            return results
        except Exception:
            mlogger.debug(traceback.format_exc())
            pass 

    def api_rosrest_stop(self, id: str):
        """ requests the specified ROS-REST Mapping process .
        Args:
            id : ROS-REST mapping rule id
        Returns:
            "ok" If successful, "unknown rule id" otherwise.
        Examples:
            api.api_rosrest_stop("target-id-to-stop-process")
        """          
        mlogger.debug("api_rosrest_stop %s", id)
        try:
            gw = self.rpc_map.get(id, None)
            if gw:
                gw.close()
                self.rpc_map.pop(id)
                return "ok"
            else:
                return "unknown rule id"
        except Exception:
            mlogger.debug(traceback.format_exc())
            pass               

    async def close(self):
        """ close all client connections and the gateway endpoint service
        """
        mlogger.debug("agent stopped")
        await self._stop_client_tasks()
        self.node_manager.stop()
        self.node_manager.join()

    async def serve(self, websocekt, request=None):
        """ run the gateway endpoint service
        """
        await self.endpoint.serve(websocekt, request)
