"""
Flask web UI for pushing configs to the SPRI IS-IS lab.

Run on the lab server (it needs to reach the nodes' mgmt network and serve files):
    pip install -r requirements.txt
    python app.py            # then open http://<server>:8080

Lists every node from `containerlab inspect`, lets you tick the ones to push,
copies <configs_dir>/<node>.cfg onto each and applies it to the running-config.
"""

import os
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, render_template, request, jsonify

import pusher

# ---- configuration (override with env vars) --------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
TOPOLOGY = os.environ.get("CLAB_TOPOLOGY", os.path.join(HERE, "..", "isis-lab.clab.yml"))
CONFIGS_DIR = os.environ.get("CONFIGS_DIR", os.path.join(HERE, "configs"))
INSPECT_CMD = os.environ.get("CLAB_BIN", "containerlab")
UI_PORT = int(os.environ.get("UI_PORT", "8080"))

app = Flask(__name__)

SERVER_IP = pusher.get_server_ip()
pusher.start_file_server(CONFIGS_DIR)        # serve configs over :8000

# job_id -> {"results": {node: status}, "log": {node: [lines]}, "done": bool}
JOBS = {}
JOBS_LOCK = threading.Lock()


def _node_view(n):
    cfg = os.path.join(CONFIGS_DIR, f"{n['name']}.cfg")
    supported = n["kind"] in pusher.KIND_PROFILES
    return {
        **n,
        "supported": supported,
        "has_config": os.path.exists(cfg),
        "pushable": supported and os.path.exists(cfg) and n["state"].startswith("running"),
    }


@app.route("/")
def index():
    error = None
    nodes = []
    try:
        nodes = [_node_view(n) for n in pusher.inspect_nodes(TOPOLOGY, INSPECT_CMD)]
    except Exception as e:  # noqa: BLE001
        error = str(e)
    return render_template(
        "index.html", nodes=nodes, error=error,
        server_ip=SERVER_IP, topology=os.path.abspath(TOPOLOGY),
        configs_dir=CONFIGS_DIR)


@app.route("/push", methods=["POST"])
def push():
    selected = request.json.get("nodes", [])
    apply = bool(request.json.get("apply", True))
    all_nodes = {n["name"]: n for n in pusher.inspect_nodes(TOPOLOGY, INSPECT_CMD)}
    targets = [all_nodes[name] for name in selected if name in all_nodes]
    if not targets:
        return jsonify({"error": "no valid nodes selected"}), 400

    job_id = uuid.uuid4().hex[:8]
    with JOBS_LOCK:
        JOBS[job_id] = {"results": {}, "log": {n["name"]: [] for n in targets},
                        "done": False}

    def worker():
        def run_one(node):
            name = node["name"]

            def log(line):
                with JOBS_LOCK:
                    JOBS[job_id]["log"][name].append(line)

            status = pusher.push_to_node(
                node, SERVER_IP, CONFIGS_DIR, apply=apply, log=log)
            with JOBS_LOCK:
                JOBS[job_id]["results"][name] = status

        with ThreadPoolExecutor(max_workers=5) as ex:
            list(ex.map(run_one, targets))
        with JOBS_LOCK:
            JOBS[job_id]["done"] = True

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"error": "unknown job"}), 404
        # shallow copy is fine for JSON serialisation
        return jsonify({
            "results": dict(job["results"]),
            "log": {k: list(v) for k, v in job["log"].items()},
            "done": job["done"],
        })


if __name__ == "__main__":
    print(f"Config pusher UI -> http://{SERVER_IP}:{UI_PORT}")
    print(f"  topology : {os.path.abspath(TOPOLOGY)}")
    print(f"  configs  : {CONFIGS_DIR}  (served on http://{SERVER_IP}:{pusher.FILE_PORT})")
    app.run(host="0.0.0.0", port=UI_PORT, threaded=True)
