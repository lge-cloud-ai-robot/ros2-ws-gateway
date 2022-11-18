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

# rosextpy.ext_type_support (ros2-ws-gateway)
# Author: parasby@gmail.com


##  run the following instructions before using this module
##
##  ros:galactic, ros:rolling
##
##  rosdep update
##  sudo apt update
##  sudo apt install -y --no-install-recommends ros-$ROS_DISTRO-rmw-fastrtps-cpp
##  export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
##


import json
from typing import List, Dict
import importlib
import os
import logging
import traceback
import array
from rclpy.serialization import deserialize_message
from rclpy.serialization import serialize_message
from json import JSONEncoder
import pybase64
import zlib as Compressor
import cbor
from builtin_interfaces.msg._time import Time as ROSTime
from std_msgs.msg._header import Header as ROSHeader
import numpy

mlogger = logging.getLogger('ext_type_support')

from rosextpy import _rosextpy_pybind11
class GenericTypeSuperMeta(type): 
    _FUNC1 = None
    _FUNC2 = None    
    @classmethod
    def __import_type_support__(cls):
        pass
    @classmethod
    def __prepare__(cls,name, bases, **kwargs):
        return {            
        }

def SerializedTypeLoader(clsname):
    (mname, cname) = clsname.rsplit('/',1)    
    if mname.find('/msg')== -1:
        clsname = ''.join([mname, '/msg/',cname])
    ttype = type(clsname+'_meta',
        (GenericTypeSuperMeta,), {
        '_CREATE_ROS_MESSAGE':  _rosextpy_pybind11.create_ros_message_serialized_msg,
        '_CONVERT_FROM_PY' :  _rosextpy_pybind11.convert_from_py_serialized_msg,
        '_CONVERT_TO_PY' : _rosextpy_pybind11.convert_to_py_serialized_msg,
        '_DESTROY_ROS_MESSAGE' : _rosextpy_pybind11.destroy_ros_message_serialized_msg,
        '_TYPE_SUPPORT': _rosextpy_pybind11.get_type_support(clsname)
        })
            
    class temp(metaclass=ttype):
        pass
    return temp

# for sequnce<uint8>
# in ROS2 , type of sequnce is 'array.array'         

def is_ros_obj(obj):
    return hasattr(obj,'get_fields_and_field_types')   

def ros_to_text_dict(obj):
    if hasattr(obj,'get_fields_and_field_types'):    
        members: dict = obj._fields_and_field_types
        results = {}
        for name in members.keys():
            results[name] = ros_to_text_dict(getattr(obj, name))
        return results
    elif isinstance(obj, array.array):
        return pybase64.b64encode(obj.tobytes()).decode()
    elif isinstance(obj, numpy.ndarray):
        return obj.tolist()
        # return pybase64.b64encode(obj.tobytes()).decode()        
    elif isinstance(obj, bytes):
        return pybase64.b64encode(obj).decode()
    elif isinstance(obj, list):
        outlist = []
        for item in obj:
            outlist.append(ros_to_text_dict(item))
        return outlist        
    else:
        return obj          

# for ROS2
def ros_from_text_dict(data, obj):
    try:
        if isinstance(obj, ROSTime):            
            if 'nsecs' in  data.keys(): # if data has nsecs it must be ROS1
                sec = data.get('secs')
                nanosec = data.get('nsecs')
            else:
                sec = data.get('sec')
                nanosec = data.get('nanosec')
            return ROSTime(sec = sec, nanosec= nanosec)
        elif hasattr(obj,'get_fields_and_field_types'):        
            members: dict = obj._fields_and_field_types        
            for name, ntype in members.items():
                field_item = getattr(obj,name)
                if isinstance(field_item, list): # can be ros message list                    
                    item_cls = TypeLoader(get_ros_list_type(ntype))
                    setattr(obj, name, ros_from_text_list(data[name], item_cls))                    
                else:                   
                    setattr(obj, name, ros_from_text_dict(data[name], field_item))
            return obj
        elif isinstance(obj, array.array):
            obj.frombytes(pybase64.b64decode(data))
            return obj
        elif isinstance(obj, float):
            return float(data)
        elif isinstance(obj, numpy.ndarray):
            return numpy.array(data)            
        elif isinstance(obj, bytes):
            return pybase64.b64decode(data)
        else:
            obj = data
            return obj
    except Exception:        
        mlogger.debug('indata is %s', data)
        raise        

def get_ros_list_type(typestr):
    return typestr.split("<")[1].split('>')[0]

def get_ros_type_name(obj):
    if hasattr(obj,'get_fields_and_field_types'): 
        tn = obj.__class__.__module__.split('.')
        tn.pop()
        tn.append(obj.__class__.__name__)
        return '/'.join(tn)
    else:
        return obj.__class__.__name__

def ros_from_text_list(data, cls):
    out = []
    for item in data:
        out.append(ros_from_text_dict(item, cls()))
    return out  

def ros_from_bin_list(data, cls):
    out = []
    for item in data:
        out.append(ros_from_bin_dict(item, cls()))
    return out    

def ros_from_bin_dict(data, obj):    
    try:
        if isinstance(obj, ROSTime):            
            if 'nsecs' in  data.keys(): # if data has nsecs it must be ROS1
                sec = data.get('secs')
                nanosec = data.get('nsecs')
            else:
                sec = data.get('sec')
                nanosec = data.get('nanosec')
            return ROSTime(sec = sec, nanosec= nanosec)
        elif hasattr(obj,'get_fields_and_field_types'):        
            members: dict = obj._fields_and_field_types        
            for name, ntype in members.items():
                field_item = getattr(obj,name)
                if isinstance(field_item, list): # can be ros message list                    
                    item_cls = TypeLoader(get_ros_list_type(ntype))
                    setattr(obj, name, ros_from_bin_list(data[name], item_cls))                    
                else:                   
                    setattr(obj, name, ros_from_bin_dict(data[name], field_item))
            return obj
        elif isinstance(obj, float):
            return float(data)
        elif isinstance(obj, array.array):
            obj.frombytes(data)
            return obj
        elif isinstance(obj, numpy.ndarray):
            return numpy.frombuffer(data)
        else:
            obj = data
            return obj
    except Exception: 
        raise      

def ros_to_bin_dict(obj):
    if hasattr(obj,'get_fields_and_field_types'):
        members: dict = obj._fields_and_field_types
        results = {}
        for name in members.keys():
            results[name] = ros_to_bin_dict(getattr(obj, name))
        return results
    elif isinstance(obj, array.array):
        return obj.tobytes()
    elif isinstance(obj, numpy.ndarray):
        return obj.tobytes()
    elif isinstance(obj, list):
        outlist = []
        for item in obj:
            outlist.append(ros_to_bin_dict(item))
        return outlist        
    else:
        return obj

def ros_serialize(obj) -> bytes:
    return serialize_message(obj)

def ros_deserialize(data : bytes, cls_type):
    return deserialize_message(data, cls_type)

def ros_to_compress(obj):
    return Compressor.compress(cbor.dumps(ros_to_bin_dict(obj)))

def ros_from_compress(data, obj):
    return ros_from_bin_dict(cbor.loads(Compressor.decompress(data)),obj)

class TypeModuleError(Exception):
    def __init__(self, errorstr):
        self.errorstr = errorstr
    def __str__(self):
        return ''.join(['Cannot find modules for the type "',self.errorstr,'"'])

def TypeLoader(clsname):
    try:
        (mname, cname) = clsname.rsplit('/',1)
        mname = mname.replace('/','.')
        if mname.find('.msg')== -1:
            mname = ''.join([mname, '.msg'])
        mod = importlib.import_module(mname)
        clmod = getattr(mod, cname)
        return clmod
    except ValueError:
        (mname, cname) = clsname.rsplit('.',1)
        if mname.find('.msg')== -1:
            mname = ''.join([mname, '.msg'])
        mod = importlib.import_module(mname)
        clmod = getattr(mod, cname)
        return clmod

    except Exception:
        raise TypeModuleError(clsname)

def SrvTypeLoader(clsname):
    try:
        (mname, cname) = clsname.rsplit('/',1)  # sensor_msgs/srv/SetCameraInfo
        mname = mname.replace('/','.')        
        if mname.find('.srv')== -1:
            mname = ''.join([mname, '.srv'])
        mod = importlib.import_module(mname)
        clmod = getattr(mod, cname)
        return clmod
    except ValueError:
        (mname, cname) = clsname.rsplit('.',1) # sensor_msgs.srv.SetCameraInfo
        if mname.find('.srv')== -1:
            mname = ''.join([mname, '.srv'])
        mod = importlib.import_module(mname)
        clmod = getattr(mod, cname)
        return clmod
    except Exception:
        raise TypeModuleError(clsname)

def ActionTypeLoader(clsname):
    try:
        (mname, cname) = clsname.rsplit('/',1)  # ex: action_tutorials_interfaces/action/Fibonacci
        mname = mname.replace('/','.')        
        if mname.find('.action')== -1:
            mname = ''.join([mname, '.action'])
        mod = importlib.import_module(mname)
        clmod = getattr(mod, cname)
        return clmod
    except ValueError:
        (mname, cname) = clsname.rsplit('.',1) #  ex: action_tutorials_interfaces.action.Fibonacci
        if mname.find('.action')== -1:
            mname = ''.join([mname, '.action'])
        mod = importlib.import_module(mname)
        clmod = getattr(mod, cname)
        return clmod
    except Exception:
        raise TypeModuleError(clsname) 


#usage: 
#   get_ros_value(rosObj, 'aaa.bbb.ccc')
def get_ros_value(obj, attrname): 
    try:
        names= attrname.split('/',1)
        if len(names) == 1:
            return getattr(obj,names[0])
        else:
            return get_ros_value(getattr(obj,names[0]), names[1])
    except AttributeError:
        return None

def set_ros_value(obj, targetpath, value):
    names= targetpath.split('/',1)
    if len(names) == 1: # final path
        setattr(obj, names[0], value)        
    else:
        obj_m = getattr(obj,names[0])        
        setattr(obj, names[0], set_ros_value(obj_m, names[1], value))
    return obj


def get_json_value(obj, attrname): 
    try:
        if isinstance(obj, str):
            obj = json.loads(obj) 
        names= attrname.split('/',1)
        if len(names) == 1:
            return obj.get(names[0],None)
        else:
            return get_json_value(obj[names[0]], names[1])
    except AttributeError:
        return None
        

def set_json_value(obj, targetpath, value):
    names= targetpath.split('/',1)
    if len(names) == 1: # final path
        obj[names[0]] = value
        return obj
    else:
        obj_m = obj.get(names[0],{})        
        obj[names[0]] = set_json_value(obj_m, names[1], value)
        return obj   

