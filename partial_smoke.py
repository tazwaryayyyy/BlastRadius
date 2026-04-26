import httpx, json, sys, urllib.parse

base = "http://127.0.0.1:8000"

try:
    # 1. Health check
    r = httpx.get(f"{base}/api/health")
    assert r.status_code == 200, f"Health check failed: {r.status_code}"
    print("PASS  /api/health")

    # 2. Demo diff endpoint
    r = httpx.get(f"{base}/api/demo/diff")
    assert r.status_code == 200, f"Demo diff failed: {r.status_code}"
    data = r.json()
    assert "diff" in data and "pr_title" in data, f"Missing fields: {data.keys()}"
    print("PASS  /api/demo/diff")

    # 3. Bad repo path
    diff_text = data["diff"]
    r = httpx.post(f"{base}/api/analyze", json={
        "diff": diff_text, "repo_path": "does_not_exist", "pr_title": "bad-repo"
    }, timeout=10)
    assert r.status_code == 404, f"Expected 404 for bad repo, got: {r.status_code}"
    print("PASS  Bad repo -> clean 404")

    print("\nsmoke tests (partial) PASSED")
except Exception as e:
    print(f"FAIL: {str(e)}")
    sys.exit(1)
