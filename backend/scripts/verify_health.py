
import urllib.request
import time
import json

URL = "http://localhost:8888/api/cro/compact"

print(f"Checking {URL}...")
for i in range(5):
    try:
        response = urllib.request.urlopen(URL, timeout=2)
        if response.status == 200:
            print("✅ Backend is UP and reachable!")
            print("Response:", json.loads(response.read()))
            exit(0)
    except Exception as e:
        print(f"Attempt {i+1}: Failed ({e}). Retrying...")
        time.sleep(2)
        
print("❌ Backend is NOT reachable after 5 attempts.")
exit(1)
