import urllib.request
import json
from config import AFFINDA_API_KEY as API_KEY

for auth_header in [
    {"Authorization": f"Bearer {API_KEY}"},
    {"Authorization": f"Token {API_KEY}"},
    {"api-key": API_KEY},
    {"X-API-KEY": API_KEY}
]:
    url = "https://api.affinda.com/v3/workspaces"
    headers = {"Accept": "application/json"}
    headers.update(auth_header)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            print("SUCCESS with header:", auth_header)
            print(json.dumps(data, indent=2))
            break
    except urllib.error.HTTPError as e:
        print("Failed with:", auth_header, "->", e.code, e.reason)
