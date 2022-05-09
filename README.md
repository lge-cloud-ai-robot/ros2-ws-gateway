# ROS2-WS-GATEWAY

ros-ws-gateway is a software agent to connect ROS components and others(REST, different subnet, etc.). It is inspired by [ros2-web-bridge](https://github.com/RobotWebTools/ros2-web-bridge)

## Features

  * Support rosbridge v2 protocol
  * Support ROS Service relay
  * Support ROS Action relay 
  * Configure Publish/Subscribe/Service/Action bridge function in runtime
  * Support ROS to REST API configuration in runtime

## Install and Run

### Run under Docker

1. Clone and make docker container
  ```bash
  $ git clone https://github.com/lge-cloud-ai-robot/ros2-ws-gateway.git
  $ cd ros2-ws-gateway
  $ docker build --rm -t ros2gw .
  ```
2. Run the gateway container
  ```bash
  $ docker run --name ros2gw_1 --rm -d -p 9000:9000 ros2gw
  ```
3. Check the gatway working

- Open http://localhost:9000/docs with a web browser


## Configure relay configuration

### ADD Topic Publish API

The ADD Topic Publish API configures the gateway to forward the topic to the target gateway set by address.

The API URL is 'http://localhost:9000/gateway/publisher/add'.

An example JSON request is as follows :

```json
{
  "address": "ws://targethost:3030",
  "publish": [
    {
      "name": "/my_topic",
      "messageType": "std_msgs/msg/String",
      "israw": false
    }
  ]
}
```
* address - the target gateway address to receive the specified topic.
* publish - an array of the topic configuration to send to the target
* publish.name - the topic name to send to the target
* publish.messageType - the topic type to send to the target
* publish.israw - reserved field : just set false

### ADD Topic Subscribe API

The ADD Topic Subscribe API configures the gateway to pull the topic from the target gateway set by address.

The API URL is 'http://localhost:9000/gateway/subscriber/add'.

An example JSON request is as follows :

```json
{
  "address": "ws://targethost:3030",
  "subscribe": [
    {
      "name": "/my_topic",
      "messageType": "std_msgs/msg/String",
      "israw": false
    }
  ]
}
```
* address - the target gateway address to request to send the specified topic .
* subscribe - an array of the topic configuration to receive from the target
* subscribe.name - the topic name to receive from the target
* subscribe.messageType - the topic type to receive from the target
* subscribe.israw - reserved field : just set false


### ADD Service Expose API

The ADD Service Expose API configures the gateway to receive the ROS service request from the target gateway set by address.

The API URL is 'http://localhost:9000/gateway/service/expose'.

An example JSON request is as follows :

```json
{
  "address": "ws://localhost:9001",
  "service": [
    {
      "service": "add_two_ints",
      "serviceType": "srv_tester_if.srv.AddTwoInts",
      "israw": false
    }
  ]
}
```
* address - the target gateway address to be allowed for the ROS service request
* service - an array of the service configuration to be exposed to the target
* service.service - the service name to be exposed to the target
* service.serviceType - the service type to be exposed to the target
* service.israw - reserved field : just set false

### ADD Action Expose API

The ADD Action Expose API configures the gateway to receive the ROS Action request from the target gateway set by address.

The API URL is 'http://localhost:9000/gateway/action/expose'.

An example JSON request is as follows :

```json
{
  "address": "ws://localhost:9001",
  "action": [
    {
      "action": "fibonacci",
      "actionType": "action_tester_if.action.Fibonacci",
      "israw": false
    }
  ]
}
```
* address - the target gateway address to allow to receive the ROS action request
* action - an array of the action configuration to be exposed to the target
* action.action - the action name to be exposed to the target
* action.actionType - the action type to be exposed to the target
* action.israw - reserved field : just set false

### ADD ROS-REST Mapping API

The ADD ROS-REST Mapping API configures the gateway to make REST request from ROS topics and send the created REST request to the target serivce uri.

The API URL is 'http://localhost:9000/gateway/rosrest/add'.

An example JSON request is as follows :

```json
{
  "service_name": "detect service",
  "service_uri": "http://localhost:9001/detect/",
  "service_method": "POST",
  "request_rule": {
    "content-type": "multipart/form-data",
    "topics": {
      "/image1": "sensor_msgs/msg/CompressedImage"
    },
    "mapping": [
      {
        "in": "/image1",
        "from": "data",
        "out": "files",
        "to": "files"
      }
    ]
  },
  "response_rule": {
    "content-type": "image/jpeg",
    "topics": {
      "/target": "sensor_msgs/msg/CompressedImage"
    },
    "mapping": [
      {
        "in": "content",
        "from": "",
        "out": "/target",
        "to": ""
      }
    ]
  }
}
```
* service_name - the target service name to send the created REST request to
* service_uri - the target service uri to send the created REST request to
* service_method - request method of the target service uri to send the created REST request to
* request_rule - the mapping rule to make a REST request from ROS topics
* request_rule.content-type - the REST request message content-type
* request_rule.topics - subscribed topics to make a REST request (topic name : topic type)
* request_rule.mapping - array of the mapping rule
* request_rule.mapping[].in - a source topic
* request_rule.mapping[].from - a member field of the source topic
* request_rule.mapping[].out - the target field of the REST request (files, data, params, headers, etc.)  
* request_rule.mapping[].to - a member of the target field of the REST request
  * .out is 'files': .to is the field name of the multipart/form-data
  * .out is 'data': .to is the member of JSON request body
  * .out is 'params': .to is the parameter key of URL query string
  * .out is 'headers': .to is the field name of the HTTP headers
* response_rule - the mapping rule to make a ROS message from REST response
* response_rule.content-type - the REST response message content-type
* response_rule.topics - ROS topic to be created from the REST response (topic name : topic type)
* response_rule.mapping - array of the mapping rule
* response_rule.mapping[].in - the source field of the REST response (content, json, raw, etc.)
  * .in is 'content': .in is the binary response content
  * .in is 'json': .in is the JSON response content
  * .in is 'raw': .in is the raw response content
* response_rule.mapping[].from - the member of the source field of the REST response 
* response_rule.mapping[].out - the target topics to be published
* response_rule.mapping[].to - a member of the target topics to be published