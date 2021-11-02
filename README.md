# ROS2-WS-GATEWAY

### 1. 소개
ros2-web-bridge 프로토콜과 호환되는 확장 gateway
* Features
    + subnet간 토픽 포워딩 (중앙의 웹브리지 경유)
        - ros-gateway-agent 실행시 configuration rule 설정
    + websocket을 이용한 토픽 pub/sub

### 2. 사용법
#### * 게이트웨이 컨테이너 만들기
  build_gw.sh를 실행합니다.
#### * 게이트웨이 실행
  build_gw.sh 실행 이후 run_gw.sh를 실행합니다.
#### * API를 통한 사용
  run_gw.sh로 실행하면 브라우저로 http://localhost:9000/docs 에 접속하여 API를 확인가능합니다.
