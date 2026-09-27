"""Minimal UI server for the scientific discovery workflow.

Serves ui/app.html and exposes a JSON API via /api/discover so the browser
can call the discovery layer without any third-party dependencies.

Usage
-----
python scripts/ui_server.py [--port 8765]

Then open http://localhost:8765 in a browser.

Security notes
--------------
* Discovery is read-only; approved execution writes only new workflow_runs folders.
* Paths are restricted to the project root and its children.
* No credentials, no production databases, no network access.
* For local development only; not suitable for public exposure.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import secrets
import time
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.discovery import (
    ApprovalRecord,
    ContractNotApprovedError,
    apply_approval,
    build_draft_contract,
    discover_source,
    plan_workflow,
    recognize_science,
)
from src.discovery.models import WorkflowPlan, EvidenceItem
from src.data_reader import ReaderError, _loads as load_strict_json
from src.discovery.execution import ExecutionError, calculate, publish, source_hash
from src.explorer import preview as explorer_preview

PREPARED = {}
PREVIEW_TTL = 600


def _to_json(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _to_json(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        return {k: _to_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json(v) for v in obj]
    return obj


def _handle_discover(body: dict) -> tuple[int, dict]:
    """Run the discovery pipeline and return (http_status, response_dict)."""
    if not isinstance(body, dict):
        return 400, {"error": "Request must be a JSON object"}
    for key in ("answers", "question_decisions", "step_confirmations", "unit_overrides"):
        if key in body and not isinstance(body[key], dict):
            return 400, {"error": f"{key} must be an object"}
    path_str = body.get("path", "")
    if not isinstance(path_str, str):
        return 400, {"error": "path must be a string"}
    if not path_str:
        return 400, {"error": "path is required"}

    # Security: restrict to paths under ROOT
    try:
        target = (ROOT / path_str).resolve()
        target.relative_to(ROOT)
    except (ValueError, OSError):
        return 400, {"error": "Path is outside the project directory"}

    if not target.exists():
        return 404, {"error": f"File not found: {path_str}"}

    fmt = body.get("format") or None
    table = body.get("table") or None
    records_key = body.get("records_key") or None
    sampling_limit = body.get("sampling_limit")
    if sampling_limit is not None:
        if isinstance(sampling_limit, str) and re.fullmatch(r"[1-9][0-9]*", sampling_limit):
            try:
                sampling_limit = int(sampling_limit)
            except ValueError:
                return 400, {"error": "sampling_limit is too large"}
        if type(sampling_limit) is not int or sampling_limit < 1:
            return 400, {"error": "sampling_limit must be a positive integer or null"}

    outcome = body.get("outcome") or None
    approver = body.get("approver") or None
    answers: dict[str, str] = body.get("answers") or {}
    step_confirmations: dict[str, str] = body.get("step_confirmations") or {}

    try:
        revision = source_hash(target)
        inventory = discover_source(
            target, format=fmt, table=table, records_key=records_key,
            sampling_limit=sampling_limit,
            source_metadata={k: v for k, v in {
                "provider": body.get("provider"),
                "documentation": body.get("documentation"),
                "instrument": body.get("instrument"),
            }.items() if v},
        )
        mappings = recognize_science(inventory)
        unit_overrides = body.get("unit_overrides", {})
        if set(unit_overrides) - {m.source_field for m in mappings}:
            return 400, {"error": "Unit correction references an unknown field"}
        for i, mapping in enumerate(mappings):
            if mapping.source_field not in unit_overrides:
                continue
            correction = unit_overrides[mapping.source_field]
            if (not isinstance(correction, dict) or
                    not isinstance(correction.get("unit"), str) or not correction["unit"].strip() or
                    not isinstance(correction.get("evidence"), str) or not correction["evidence"].strip()):
                return 400, {"error": "Each unit correction requires a unit and supporting evidence"}
            unit = correction["unit"].strip()
            mappings[i] = dataclasses.replace(mapping, proposed_unit=unit,
                evidence=mapping.evidence + (EvidenceItem("human_declaration", correction["evidence"], 0.5),),
                unresolved=tuple(q for q in mapping.unresolved if "unit" not in q.lower()) +
                    (f"Field '{mapping.source_field}': confirm declared unit '{unit}' and its supporting evidence; values have not been converted.",))
        contract = build_draft_contract(
            inventory, mappings,
            source_provider=body.get("provider"),
            source_documentation=body.get("documentation"),
            source_instrument=body.get("instrument"),
        )
        if unit_overrides:
            contract = dataclasses.replace(contract, source_metadata_section={
                **contract.source_metadata_section, "unit_corrections": unit_overrides})

        if approver or "decision" in body or answers:
            try:
                if not approver or "decision" not in body:
                    return 400, {"error": "An approver and explicit decision are required", "contract": _to_json(contract)}
                record = ApprovalRecord(approver=approver, approved_answers=answers,
                                        decision=body["decision"],
                                        question_decisions=body.get("question_decisions", {}))
                contract = apply_approval(contract, record)
            except ContractNotApprovedError as exc:
                return 422, {"error": str(exc), "contract": _to_json(contract)}

        workflow_plan = None
        if outcome:
            if contract.state == "approved":
                workflow_plan = plan_workflow(contract, outcome,
                                             step_confirmations=step_confirmations or None)
            else:
                workflow_plan = WorkflowPlan(
                    outcome_description=outcome,
                    contract_state=contract.state,
                    steps=(),
                    blocked_reasons=(
                        f"Contract is '{contract.state}'; approve before planning.",
                    ),
                    missing_information=(),
                    warnings=(),
                )

        if source_hash(target) != revision:
            return 409, {"error": "Source changed during inspection; inspect again"}
        response: dict[str, Any] = {"contract": _to_json(contract), "source_revision": revision}
        if workflow_plan is not None:
            response["workflow_plan"] = _to_json(workflow_plan)
        return 200, response

    except ReaderError as exc:
        return 422, {"error": f"Reader error: {exc}"}
    except (ValueError, TypeError, AttributeError) as exc:
        return 400, {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return 500, {"error": str(exc)}


def _prepare_execution(body):
    if not isinstance(body, dict) or not isinstance(body.get("settings"), dict):
        return 400, {"error": "Execution settings are required"}
    status, response = _handle_discover(body)
    if status != 200:
        return status, response
    if body.get("source_revision") != response["source_revision"]:
        return 409, {"error": "Source revision is missing or changed; inspect and review again"}
    if not response.get("workflow_plan"):
        return 422, {"error": "A reviewed workflow plan is required"}
    try:
        result = calculate(response["contract"], response["workflow_plan"], body["settings"])
        if result["source_sha256"] != response["source_revision"]:
            raise ExecutionError("Source changed; inspect and review again")
        now = time.monotonic()
        for key in list(PREPARED):
            if now - PREPARED[key]["created"] > PREVIEW_TTL:
                del PREPARED[key]
        if len(PREPARED) >= 10:
            return 429, {"error": "Too many pending previews; execute one or wait ten minutes"}
        ticket = secrets.token_urlsafe(32)
        PREPARED[ticket] = {"created": now, "request": body, "contract": response["contract"],
                            "plan": response["workflow_plan"], "result": result}
        return 200, {"execution_ticket": ticket, "expires_in_seconds": PREVIEW_TTL,
                     "settings": result["settings"], "counts": result["counts"],
                     "preview": result["records"][:10], "source_sha256": result["source_sha256"],
                     "notice": "Calculated in memory. Approve these exact settings to save JSON result and provenance; no calibration or unit conversion is applied."}
    except (ExecutionError, ReaderError, TypeError, KeyError, OSError) as exc:
        return 422, {"error": str(exc)}


def _execute(body):
    if not isinstance(body, dict) or body.get("decision") != "approve":
        return 400, {"error": "Explicit execution approval is required"}
    reviewer = body.get("approved_by")
    if not isinstance(reviewer, str) or not reviewer.strip():
        return 400, {"error": "Execution approver is required"}
    ticket = body.get("execution_ticket")
    if not isinstance(ticket, str) or ticket not in PREPARED:
        return 409, {"error": "Preview is missing or already used; prepare it again"}
    item = PREPARED.pop(ticket)
    if time.monotonic() - item["created"] > PREVIEW_TTL:
        return 409, {"error": "Preview expired; prepare it again"}
    try:
        source = Path(item["contract"]["inventory"]["connector"]["path"])
        if source_hash(source) != item["result"]["source_sha256"]:
            return 409, {"error": "Source changed after preview; inspect and review again"}
        return 200, publish(ROOT, item, reviewer.strip())
    except (OSError, ExecutionError) as exc:
        return 422, {"error": str(exc)}


class DiscoveryHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet logging
        pass

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, indent=2, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, mime: str) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if not self._local_request():
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/explorer", "/explorer.js"):
            name = "explorer.html" if parsed.path == "/explorer" else "explorer.js"
            self._send_file(ROOT / "ui" / name, "text/html; charset=utf-8" if name.endswith("html") else "text/javascript; charset=utf-8")
        elif parsed.path in ("/", "/index.html"):
            html_path = ROOT / "ui" / "app.html"
            if html_path.exists():
                self._send_file(html_path, "text/html; charset=utf-8")
            else:
                self._send_json(404, {"error": "ui/app.html not found"})
        elif parsed.path == "/api/files":
            # List discoverable data files. Exclude known configuration files
            # (names ending in _config, schema files, and contract files) so
            # the picker only shows files that can be opened as data sources.
            _CONFIG_SUFFIXES = ("_config.json", ".schema.json")
            _CONFIG_NAMES = {"noaa_config.json", "reader_config.json"}

            def _is_data_file(p: Path) -> bool:
                if p.name.startswith("bob-task-"):
                    return False
                if not p.is_file():
                    return False
                if p.suffix.lower() not in (
                    ".csv", ".tsv", ".json", ".jsonl", ".db", ".sqlite", ".sqlite3"
                ):
                    return False
                if p.name in _CONFIG_NAMES:
                    return False
                if any(p.name.endswith(s) for s in _CONFIG_SUFFIXES):
                    return False
                return True

            files = []
            for p in sorted(ROOT.iterdir()):
                if _is_data_file(p):
                    files.append(p.name)
            for d in ("examples",):
                dd = ROOT / d
                if dd.is_dir():
                    for p in sorted(dd.iterdir()):
                        if _is_data_file(p):
                            files.append(f"{d}/{p.name}")
            self._send_json(200, {"files": files})
        elif re.fullmatch(r"/api/runs/[a-f0-9]{32}/(result|provenance)\.json", parsed.path):
            _, _, _, run_id, filename = parsed.path.split("/")
            target = ROOT / "workflow_runs" / run_id / filename
            if target.is_file() and target.resolve().is_relative_to((ROOT / "workflow_runs").resolve()) and not (ROOT / "workflow_runs").is_symlink():
                self._send_file(target, "application/json; charset=utf-8")
            else:
                self._send_json(404, {"error": "Run output not found"})
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if not self._local_request():
            return
        parsed = urllib.parse.urlparse(self.path)
        handlers = {"/api/discover": _handle_discover, "/api/prepare-execution": _prepare_execution, "/api/execute": _execute,
                    "/api/explore": lambda body: explorer_preview(ROOT, body)}
        if parsed.path not in handlers:
            self._send_json(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_json(400, {"error": "Invalid content length"})
            return
        max_body = (7 if parsed.path == "/api/explore" else 1) * 1024 * 1024
        if not 0 < length <= max_body or self.headers.get_content_type() != "application/json":
            self._send_json(400, {"error": f"Send a JSON request no larger than {max_body // (1024 * 1024)} MiB"})
            return
        raw = self.rfile.read(length)
        try:
            # Same duplicate-key and finite-number policy as source JSON.
            body = load_strict_json(raw)
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            self._send_json(400, {"error": f"Invalid JSON: {exc}"})
            return
        status, response = handlers[parsed.path](body)
        self._send_json(status, response)

    def _local_request(self):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if host not in hosts or (origin and origin != f"http://{host}"):
            self._send_json(403, {"error": "Only same-origin local requests are allowed"})
            return False
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = HTTPServer(("127.0.0.1", args.port), DiscoveryHandler)
    print(f"Scientific Discovery UI  http://127.0.0.1:{args.port}", flush=True)
    print("Ctrl-C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
