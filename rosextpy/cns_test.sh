#uvicorn rosextpy.gateway_endpoint_test:app --reload --host=0.0.0.0 --port=3000 --log-level 'info'
python -m rosextpy.test.gateway_cns_test
#uvicorn rosextpy.test.gateway_cns_test:app --reload --host=0.0.0.0 --port=3000 --log-level 'debug'
