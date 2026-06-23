"""
pusher.py - copy per-node config files onto containerlab nodes and apply them.

Adapted from andrewohanian/ccie-spv5.1-labs `transfer_configs_to_nodes.py`:
  * mechanism is the same -- a local HTTP server serves the config files and each
    device pulls its file with `copy http://<server>:8000/... <storage>:`
  * added handling for `cisco_c8000v` (the original only had cisco_csr1000v)
  * node list + mgmt IPs are pulled live from `containerlab inspect` instead of
    being read statically from the topology file
  * after the file lands it is applied to the running-config (IOS-XE: copy to
    running-config + write mem; IOS-XR: load + commit)
  * `arista_ceos` switches (and anything unknown) are skipped automatically

Config files are flat:  <configs_dir>/<node>.cfg   e.g. configs/r1.cfg
"""

import os
import json
import socket
import subprocess
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler

import yaml
from netmiko import ConnectHandler

FILE_PORT = 8000

# Per-kind connection + storage settings. Add new kinds here.
KIND_PROFILES = {
    "cisco_c8000v": {
        "device_type": "cisco_xe",
        "username": "admin",
        "password": "admin",
        "storage": "flash:",
        "http_source": "GigabitEthernet1",  # mgmt interface for the HTTP client
    },
    "cisco_xrd": {
        "device_type": "cisco_xr",
        "username": "clab",
        "password": "clab@123",
        "storage": "disk0:",
    },
}

# Kinds we deliberately do not push config to (pure L2 / infra).
SKIP_KINDS = {"arista_ceos", "linux", "bridge", "ovs-bridge"}


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def get_server_ip():
    """Primary IP of this host (the address the nodes use to reach the HTTP server)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return None


def _lab_name(topology_file):
    with open(topology_file) as f:
        return yaml.safe_load(f).get("name", "")


def _short_name(full_name, lab_name):
    prefix = f"clab-{lab_name}-"
    return full_name[len(prefix):] if full_name.startswith(prefix) else full_name


def inspect_nodes(topology_file, inspect_cmd="containerlab"):
    """
    Return a list of node dicts: {name, full_name, kind, mgmt_ip, state}
    using `containerlab inspect -f json`. Falls back to sudo on permission errors.
    """
    lab = _lab_name(topology_file)
    base = [inspect_cmd, "inspect", "-t", topology_file, "-f", "json"]

    def _run(cmd):
        return subprocess.run(cmd, capture_output=True, text=True)

    res = _run(base)
    if res.returncode != 0 and ("permission" in res.stderr.lower() or "denied" in res.stderr.lower()):
        res = _run(["sudo", "-n"] + base)
    if res.returncode != 0:
        raise RuntimeError(f"`{' '.join(base)}` failed: {res.stderr.strip() or res.stdout.strip()}")

    data = json.loads(res.stdout or "{}")

    # Normalise the various clab JSON shapes into a flat list of container dicts.
    if isinstance(data, dict) and "containers" in data:
        containers = data["containers"]
    elif isinstance(data, dict):
        containers = [c for v in data.values() if isinstance(v, list) for c in v]
    elif isinstance(data, list):
        containers = data
    else:
        containers = []

    nodes = []
    for c in containers:
        full = c.get("name", "")
        ip = (c.get("ipv4_address") or c.get("ipv4-address") or "").split("/")[0]
        nodes.append({
            "name": _short_name(full, lab),
            "full_name": full,
            "kind": c.get("kind", ""),
            "mgmt_ip": ip,
            "state": c.get("state", ""),
        })
    nodes.sort(key=lambda n: n["name"])
    return nodes


# --------------------------------------------------------------------------- #
# HTTP file server (serves the configs directory)
# --------------------------------------------------------------------------- #
def start_file_server(directory, port=FILE_PORT):
    """Serve `directory` over HTTP in a daemon thread. Returns the HTTPServer."""
    handler = partial(SimpleHTTPRequestHandler, directory=directory)
    httpd = HTTPServer(("0.0.0.0", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


# --------------------------------------------------------------------------- #
# Device interaction
# --------------------------------------------------------------------------- #
def _answer_prompts(conn, first_cmd, log, max_steps=8):
    """
    Run an interactive `copy`-style command, auto-answering the usual IOS / XR
    prompts (Destination filename / overwrite confirm / address). Returns output.
    """
    out = conn.send_command_timing(first_cmd, read_timeout=180)
    for _ in range(max_steps):
        low = out.lower()
        if any(p in low for p in ("destination filename", "[confirm]", "over write",
                                  "overwrite", "address or name", "]?")):
            out += conn.send_command_timing("\n", read_timeout=180)
        else:
            break
    log(out.strip().splitlines()[-1] if out.strip() else "(no output)")
    return out


def push_to_node(node, server_ip, configs_dir, apply=True, port=FILE_PORT, log=print):
    """
    Copy <configs_dir>/<node>.cfg to the node and (optionally) apply it.
    Returns one of: 'ok', 'skipped', 'no-config', 'error: <msg>'.
    """
    name, kind, ip = node["name"], node["kind"], node["mgmt_ip"]

    if kind in SKIP_KINDS:
        log(f"{name}: kind '{kind}' is infrastructure, skipping")
        return "skipped"
    profile = KIND_PROFILES.get(kind)
    if not profile:
        log(f"{name}: unsupported kind '{kind}', skipping")
        return "skipped"

    cfg_file = f"{name}.cfg"
    if not os.path.exists(os.path.join(configs_dir, cfg_file)):
        log(f"{name}: no config file '{cfg_file}'")
        return "no-config"
    if not ip:
        return "error: no mgmt IP (is the node running?)"

    url = f"http://{server_ip}:{port}/{cfg_file}"
    dev = {
        "device_type": profile["device_type"],
        "host": ip,
        "username": profile["username"],
        "password": profile["password"],
        "read_timeout_override": 120,
        "fast_cli": False,
    }

    try:
        log(f"{name}: connecting to {ip} ({profile['device_type']}) ...")
        conn = ConnectHandler(**dev)
        try:
            if kind == "cisco_c8000v":
                conn.send_config_set(
                    [f"ip http client source-interface {profile['http_source']}"])
                log(f"{name}: copying {url} -> flash:{cfg_file}")
                _answer_prompts(conn, f"copy {url} flash:{cfg_file}", log)
                if apply:
                    log(f"{name}: applying flash:{cfg_file} to running-config")
                    _answer_prompts(conn, f"copy flash:{cfg_file} running-config", log)
                    conn.save_config()
                    log(f"{name}: saved to startup-config")

            elif kind == "cisco_xrd":
                log(f"{name}: copying {url} -> disk0:/{cfg_file}")
                _answer_prompts(conn, f"copy {url} disk0:/{cfg_file}", log)
                if apply:
                    log(f"{name}: loading + committing disk0:/{cfg_file}")
                    # send_config_set enters config mode and auto-commits for cisco_xr
                    out = conn.send_config_set([f"load disk0:/{cfg_file}"], read_timeout=180)
                    log(out.strip().splitlines()[-1] if out.strip() else "committed")
        finally:
            conn.disconnect()
        log(f"{name}: DONE")
        return "ok"
    except Exception as e:  # noqa: BLE001 - surface any device/connection failure
        log(f"{name}: ERROR {e}")
        return f"error: {e}"


# --------------------------------------------------------------------------- #
# CLI fallback:  python pusher.py <topology.clab.yml> [--stage-only]
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from concurrent.futures import ThreadPoolExecutor

    ap = argparse.ArgumentParser(description="Push configs to containerlab nodes")
    ap.add_argument("topology", help="path to the *.clab.yml topology file")
    ap.add_argument("--configs", default="configs", help="dir of <node>.cfg files")
    ap.add_argument("--stage-only", action="store_true",
                    help="copy files but do not apply to running-config")
    ap.add_argument("--inspect-cmd", default="containerlab")
    args = ap.parse_args()

    configs_dir = os.path.abspath(args.configs)
    server_ip = get_server_ip()
    if not server_ip:
        raise SystemExit("Could not determine server IP; hardcode it in the script.")
    start_file_server(configs_dir)
    print(f"Serving {configs_dir} on http://{server_ip}:{FILE_PORT}")

    nodes = inspect_nodes(args.topology, args.inspect_cmd)
    print(f"Discovered {len(nodes)} nodes")

    def _job(n):
        return n["name"], push_to_node(
            n, server_ip, configs_dir, apply=not args.stage_only)

    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(_job, nodes))

    print("\n=== summary ===")
    for name, status in sorted(results):
        print(f"  {name:<8} {status}")
