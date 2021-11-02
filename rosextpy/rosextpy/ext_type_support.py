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
# Author: paraby@gmail.com


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

mlogger = logging.getLogger('ext_type_support')

from . import _rosextpy_pybind11
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

from builtin_interfaces.msg._time import Time as ROSTime

# for sequnce<uint8>
# in ROS2 , type of sequnce is 'array.array'


def ros_from_json(data, cls):
    if issubclass(cls, List):
        list_type = cls.__args__[0]
        instance: list = list()
        for value in data:
            instance.append(ros_from_json(value, list_type))
        return instance
    elif issubclass(cls, Dict):
            key_type = cls.__args__[0]
            val_type = cls.__args__[1]
            instance: dict = dict()
            for key, value in data.items():
                instance.update(ros_from_json(key, key_type), ros_from_json(value, val_type))
            return instance
    else:
        instance : cls = cls()
        for name, value in data.items():            
            field_type = getattr(instance,name)

            if isinstance(field_type, ROSTime):
                secs = value.get('sec')
                if secs:
                    nsecs = value.get('nanosec')
                else:
                    secs = value.get('secs')
                    nsecs = value.get('nsecs')
                data_time = ROSTime(sec=secs, nanosec = nsecs)
                setattr(instance, name, data_time)
            elif isinstance(field_type, array.array):
                b64_data = pybase64.b64decode(value)
                field_type.frombytes(b64_data)
            elif isinstance(field_type, bytes):
                b64_data = pybase64.b64decode(value)
                setattr(instance, name, b64_data)
            elif hasattr(field_type, 'get_fields_and_field_types') and isinstance(value, (dict, tuple, list, set, frozenset)):
                setattr(instance, name, ros_from_json(value, field_type.__class__))
            else:
                setattr(instance, name, value)
        return instance

import json
import array
from json import JSONEncoder
import pybase64
class RosJsonEncodder(JSONEncoder):
    def default(self, obj):
        try:
            if hasattr(obj,'get_fields_and_field_types'): # it will be ros type
                members: dict = obj._fields_and_field_types
                results = {}
                for name in members.keys():                
                    results[name] = getattr(obj, name)
                return results
            elif isinstance(obj, array.array):   
                b64data = str(pybase64.b64encode(obj.tobytes()), 'utf-8')
                # add obj.tolist to base64 encoded list
                return b64data
            elif isinstance(obj, bytes):   
                b64data = str(pybase64.b64encode(obj), 'utf-8')
                # add obj.tolist to base64 encoded list
                return b64data
            else:            
                return json.JSONEncoder.default(self,obj)
        except Exception as err:
            raise TypeModuleError(err)

def ros_to_json(obj):
    return json.dumps(obj,cls=RosJsonEncodder)        

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
    except Exception:
        raise TypeModuleError(clsname)