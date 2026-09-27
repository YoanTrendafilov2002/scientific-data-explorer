"""Smoke-test the UI server in a subprocess and exit 0 on success."""
import subprocess, sys, time, urllib.request, json

p = subprocess.Popen(
    [sys.executable, "scripts/ui_server.py", "--port", "8766"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
)
time.sleep(1.5)
if p.poll() is not None:
    print("DIED:", p.stderr.read().decode())
    sys.exit(1)

errors = []
try:
    # GET /
    r = urllib.request.urlopen("http://127.0.0.1:8766/", timeout=3)
    assert r.status == 200
    html = r.read(500).decode()
    assert "Scientific Discovery" in html
    print("GET /          OK  (200, title present)")

    # GET /api/files — config files must be excluded (Fix 4)
    r2 = urllib.request.urlopen("http://127.0.0.1:8766/api/files", timeout=3)
    d2 = json.loads(r2.read())
    files = d2["files"]
    config_files = [f for f in files if "config" in f.lower() or "schema" in f.lower()]
    if config_files:
        errors.append(f"Config/schema files must not appear in /api/files: {config_files}")
    else:
        print(f"GET /api/files OK  ({len(files)} files, no config files listed)")

    # POST /api/discover
    body = json.dumps({
        "path": "examples/noaa_lga_20240101.json",
        "format": "noaa-global-hourly",
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8766/api/discover", data=body,
        headers={"Content-Type": "application/json"},
    )
    r3 = urllib.request.urlopen(req, timeout=10)
    d3 = json.loads(r3.read())
    state  = d3["contract"]["state"]
    fields = len(d3["contract"]["variable_mappings"])
    blocks = len(d3["contract"]["blocked_reasons"])
    print(f"POST /api/discover OK  (state={state}, fields={fields}, blocks={blocks})")

    # POST /api/discover - unsupported format should return 422
    body2 = json.dumps({"path": "examples/noaa_lga_20240101.json", "format": "xyz"}).encode()
    req2 = urllib.request.Request(
        "http://127.0.0.1:8766/api/discover", data=body2,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req2, timeout=5)
        errors.append("Expected 422 for unsupported format, got 200")
    except urllib.error.HTTPError as e:
        assert e.code == 422, f"Expected 422, got {e.code}"
        print(f"POST /api/discover (bad format) OK  (422 as expected)")

except Exception as exc:
    errors.append(str(exc))
finally:
    p.terminate()

if errors:
    print("FAILURES:", errors)
    sys.exit(1)
print("All smoke tests passed.")
