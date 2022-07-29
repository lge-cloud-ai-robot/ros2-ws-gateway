# ROS2 Gateway Docker
#
#
#

FROM ros:foxy-ros-base as ros2_base
ENV DEBIAN_FRONTEND=noninteractive
ENV RMW_IMPLEMENTATION=rmw_fastrtps_cpp

RUN apt-get update && apt-get upgrade -y \    
    && apt-get install -y --no-install-recommends \
        python3-pip \
        python-is-python3 \
    && apt-get autoclean -y \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

FROM ros2_base as builder
COPY . /home/user/works
WORKDIR /home/user/works/dist
RUN pip install -r requirements.txt 
RUN /bin/bash -c ". /opt/ros/${ROS_DISTRO}/setup.bash; ./build.sh"

FROM ros2_base as runner
WORKDIR /opt/gateway
COPY --from=builder /home/user/works/dist/install ./
COPY --from=builder /home/user/works/dist/requirements.txt ./
RUN pip install -r requirements.txt
ENTRYPOINT \
    /bin/bash -c 'source ./setup.bash; ros2 launch rosextpy gateway_launch.xml'
