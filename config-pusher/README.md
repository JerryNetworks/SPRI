# Config Pusher (web UI)

A small Flask app that copies your per-node config files onto the running lab
nodes and applies them — so you can build configs offline and push them in one
click. Adapted from
[`transfer_configs_to_nodes.py`](https://github.com/andrewohanian/ccie-spv5.1-labs)
(HTTP-server + `copy http://…` mechanism), with handling added for `cisco_c8000v`
and live mgmt-IP discovery via `containerlab inspect`.

## How it works

1. Starts a local HTTP server on **:8000** serving the `configs/` directory.
2. Reads the live node list (name, kind, mgmt IP) from `containerlab inspect`.
3. For each node you select, opens an SSH session (netmiko) and runs
   `copy http://<server>:8000/<node>.cfg <storage>:` then applies it.

| kind            | creds            | storage   | apply step                         |
|-----------------|------------------|-----------|------------------------------------|
| `cisco_c8000v`  | `admin/admin`    | `flash:`  | `copy flash:<f> running-config` + `write mem` |
| `cisco_xrd`     | `clab/clab@123`  | `disk0:`  | `load disk0:/<f>` + `commit`       |
| `arista_ceos`   | —                | —         | skipped (pure L2 switch)           |

> Run it **on the lab server** (`10.0.0.172`) — it must reach the nodes' mgmt
> network and the nodes must be able to reach its HTTP server.

## Config files

Flat, one file per node, named after the node:

```
configs/
  r1.cfg      # IOS-XE config for r1
  r2.cfg
  r5.cfg      # IOS-XR config for r5
  ...
```

A node with no matching `configs/<node>.cfg` is shown as “missing” and skipped.
See [`configs/README.md`](configs/README.md) for format notes and snippets.

## Run

```bash
cd config-pusher
pip install -r requirements.txt          # (use a venv if you like)
python app.py                            # open http://<server>:8080
```

Tick the nodes to push, choose whether to apply or just stage the file, and click
**Push selected**. Live per-node status and device output stream into the page.

Environment overrides: `CLAB_TOPOLOGY`, `CONFIGS_DIR`, `CLAB_BIN`, `UI_PORT`.

### CLI mode (no browser)

```bash
python pusher.py ../isis-lab.clab.yml            # push + apply all nodes
python pusher.py ../isis-lab.clab.yml --stage-only   # copy files only
```
