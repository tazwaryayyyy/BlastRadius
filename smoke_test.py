import httpx, json, sys, urllib.parse

base = "http://127.0.0.1:8000"
failures = []

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

    # 3. POST /api/analyze with demo diff
    diff_text = data["diff"]
    r = httpx.post(f"{base}/api/analyze", json={
        "diff": diff_text, "repo_path": "demo_repo", "pr_title": "smoke-test"
    }, timeout=60)
    assert r.status_code == 200, f"Analyze failed: {r.status_code} {r.text[:500]}"
    report = r.json()
    assert "call_chains" in report, "Missing call_chains"
    assert "risk_summary" in report, "Missing risk_summary"
    assert "merge_recommendation" in report, "Missing merge_recommendation"
    assert isinstance(report.get("suggested_actions", []), list), "suggested_actions not a list"
    for chain in report["call_chains"]:
        conf = chain.get("confidence", "MISSING")
        assert conf in ("HIGH", "MEDIUM", "LOW"), f"Bad confidence value: {conf!r}"
    print(f"PASS  /api/analyze  ({len(report['call_chains'])} chains, confidence normalized)")

    # 4. SSE stream endpoint
    params = urllib.parse.urlencode({"diff": diff_text, "repo_path": "demo_repo", "pr_title": "sse-smoke"})
    stream_report = None
    with httpx.stream("GET", f"{base}/api/stream?{params}", timeout=120) as resp:
        assert resp.status_code == 200, f"SSE failed: {resp.status_code}"
        ct = resp.headers.get("content-type", "")
        assert "text/event-stream" in ct, f"Wrong content-type: {ct}"
        token_count = 0
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[6:])
            if payload["type"] == "token":
                token_count += 1
            elif payload["type"] == "done":
                stream_report = payload["report"]
                break
            elif payload["type"] == "error":
                assert False, f"SSE returned error: {payload['message']}"

    assert stream_report is not None, "SSE stream never sent done event"
    assert isinstance(stream_report.get("suggested_actions", []), list)
    for chain in stream_report["call_chains"]:
        conf = chain.get("confidence", "MISSING")
        assert conf in ("HIGH", "MEDIUM", "LOW"), f"SSE confidence bad: {conf!r}"
    print(f"PASS  /api/stream   ({token_count} token events, report valid)")

    # 5. Bad repo path
    r = httpx.post(f"{base}/api/analyze", json={
        "diff": diff_text, "repo_path": "does_not_exist", "pr_title": "bad-repo"
    }, timeout=10)
    assert r.status_code == 404, f"Expected 404 for bad repo, got: {r.status_code}"
    print("PASS  Bad repo -> clean 404")

    print("\nAll smoke tests PASSED")
except Exception as e:
    print(f"FAIL: {str(e)}")
    sys.exit(1)
