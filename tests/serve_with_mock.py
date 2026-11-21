"""TEST ONLY: runs the real server against the synthetic mock services (for UI/API smoke tests)."""
import json, os, sys
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE); sys.path.insert(0,os.path.dirname(HERE))
import mock_server
srv=mock_server.start(0); port=srv.server_address[1]
os.environ["GPS_TEST_HOST_OVERRIDES"]=json.dumps(mock_server.overrides(port)); os.environ["GPS_MIN_INTERVAL"]="0"
import server
sys.argv=[sys.argv[0],"--port","8799","--state","/tmp/gps_ui_state","--root","/tmp/gps_ui_projects"]
server.main()
