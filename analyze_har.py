import json
import os
from urllib.parse import urlparse

har_path = 'provisioner_webapp_pg/debug_traffic.har'

try:
    with open(har_path, 'r', encoding='utf-8') as f:
        har_data = json.load(f)

    entries = har_data['log']['entries']
    
    print(f"Total entries: {len(entries)}")
    
    print("\n--- Login Requests ---")
    login_found = False
    for entry in entries:
        req = entry['request']
        url = req['url']
        if 'login' in url.lower() or 'cgi' in url.lower():
            method = req['method']
            print(f"\nMethod: {method}")
            print(f"URL: {url}")
            
            if method == 'POST' and 'postData' in req:
                print(f"Payload: {req['postData'].get('text', '')}")
            
            resp = entry['response']
            print(f"Response Status: {resp['status']}")
            
            # Check response cookies
            cookies = resp.get('cookies', [])
            if cookies:
                print("Set-Cookies:")
                for c in cookies:
                    print(f"  {c['name']} = {c['value']}")
            
            login_found = True

    print("\n--- Session Cookies Used ---")
    # Check what cookies are sent in subsequent requests
    seen_cookies = set()
    for entry in entries:
        req = entry['request']
        if 'cookie' in req.get('headers', []): # Sometimes headers are list of dicts
             pass 
        
        # HAR 'cookies' list in request
        cookies = req.get('cookies', [])
        for c in cookies:
            if c['name'] not in seen_cookies:
                print(f"Cookie in request to {urlparse(req['url']).path}: {c['name']}")
                seen_cookies.add(c['name'])

except Exception as e:
    print(f"Error parsing HAR: {e}")
