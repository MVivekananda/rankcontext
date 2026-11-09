"""
Stretch goal: minimal web UI (PRD section 12).

Note on framework: the PRD specifies FastAPI. This sandbox has no
network access, so FastAPI/uvicorn couldn't be installed or tested
here - Flask was already present, so the web UI is built and verified
against Flask instead. The endpoint contract (POST /api/generate) and
the "no scoring logic in the web layer" rule are unchanged; swapping
back to FastAPI later is a thin-wrapper change, since all real logic
lives in pipeline.run_pipeline().

Run with network available:
    pip install -r requirements.txt
    python -m rankcontext.webapp
Then open http://127.0.0.1:8000
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from .pipeline import run_pipeline

app = Flask(__name__, static_folder=str(Path(__file__).parent / "static"))


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/generate")
def generate():
    payload = request.get_json(silent=True) or {}
    source = (payload.get("source") or "").strip()
    budget = payload.get("budget", 50_000)
    manifest_only = bool(payload.get("manifest_only", False))

    if not source:
        return jsonify({"error": "source is required"}), 400
    try:
        budget = int(budget)
    except (TypeError, ValueError):
        return jsonify({"error": "budget must be an integer"}), 400

    try:
        result = run_pipeline(source=source, budget=budget, manifest_only=manifest_only)
    except (FileNotFoundError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(
        {
            "source": result.source_label,
            "budget": result.budget,
            "used_tokens": result.used_tokens,
            "total_candidate_files": result.total_candidate_files,
            "included_count": result.included_count,
            "excluded_count": result.excluded_count,
            "used_tiktoken": result.used_tiktoken,
            "manifest_text": result.manifest_text,
            "bundle_text": result.bundle_text,
        }
    )


def main() -> None:
    app.run(host="127.0.0.1", port=8000, debug=False)


if __name__ == "__main__":
    main()
