import requests
import json
import os
from dotenv import load_dotenv

# Load env to get credentials
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'), override=True)

GW_IP = os.getenv("GATEWAY_IP", "192.168.1.1")
USER = os.getenv("GATEWAY_USER", "admin")
PASS = os.getenv("GATEWAY_PASSWORD", "password")

print(f"--- Diagnosing Gateway at {GW_IP} ---")
print(f"Credentials: {USER} / {PASS}")

# Timeout for requests
TO = 3

def try_endpoint(method, path, payload=None):
    url = f"http://{GW_IP}{path}"
    print(f"\nTesting {method} {url} ...")
    try:
        if method == 'GET':
            resp = requests.get(url, timeout=TO)
        else:
            resp = requests.post(url, json=payload, timeout=TO)
            
        print(f"Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('Content-Type', 'Unknown')}")
        print(f"Response (first 100 chars): {resp.text[:100]}")
        return resp.status_code == 200
    except Exception as e:
        print(f"Connection Error: {e}")
        return False

# 1. Check Root (is webserver up?)
try_endpoint('GET', '/')

# 2. Check Standard Login
payload = {"username": USER, "password": PASS}
try_endpoint('POST', '/api/login', payload)

# 3. Check Alternative Login (older firmware)
try_endpoint('POST', '/api/ur/login', payload)

# 4. Check internal.cgi (some old versions)
try_endpoint('POST', '/cgi-bin/internal.cgi', payload)

# 5. Check System Status directly (maybe no auth needed?)
try_endpoint('GET', '/api/status/system')
