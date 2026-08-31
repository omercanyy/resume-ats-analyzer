import urllib.request
import json
import ssl
from config import GEMINI_API_KEY

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CONTEXT = ssl._create_unverified_context()

def test_gemini_key():
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=SSL_CONTEXT) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            models = [m.get("name") for m in data.get("models", [])]
            print("SUCCESS! Available Models count:", len(models))
            print("First 5 models:", models[:5])
            return True
    except urllib.error.HTTPError as e:
        print("HTTPError:", e.code, e.reason)
        print(e.read().decode('utf-8'))
        return False

if __name__ == "__main__":
    test_gemini_key()
