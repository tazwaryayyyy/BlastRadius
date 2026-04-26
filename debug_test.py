import httpx, json, sys, urllib.parse

base = "http://127.0.0.1:8000"

try:
    # 1. Health check
    r = httpx.get(f"{base}/api/health")
    print(f"Health: {r.status_code}")

    # 2. Demo diff
    r = httpx.get(f"{base}/api/demo/diff")
    print(f"Demo Diff: {r.status_code}")
    data = r.json()
    diff_text = data["diff"]

    # 3. POST /api/analyze - See full error
    print("Testing /api/analyze...")
    r = httpx.post(f"{base}/api/analyze", json={
        "diff": diff_text, "repo_path": "demo_repo", "pr_title": "smoke-test"
    }, timeout=60)
    print(f"Analyze Status: {r.status_code}")
    if r.status_code != 200:
        print(f"Response: {r.text}")
    else:
        print("Analyze PASS")

except Exception as e:
    print(f"FAIL: {str(e)}")
    sys.exit(1)
