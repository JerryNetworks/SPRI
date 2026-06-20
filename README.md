# IS-IS Study Lab (c8000v + XRd)

A [containerlab](https://containerlab.dev) topology for studying **IS-IS** on a mix
of Cisco **Catalyst 8000V** (IOS-XE) and **XRd** (IOS-XR) nodes.

- **8 routers** — `r1`–`r4` are c8000v, `r5`–`r8` are XRd
- **Single Level-2 area**
- **2 broadcast LAN segments** (one mixes IOS-XE + IOS-XR for DIS-election practice)
- **8 point-to-point links** forming a redundant mesh for SPF / path-selection study

> This repo intentionally ships **topology + cabling only** — no startup configs.
> You build the IS-IS config by hand. A suggested addressing/NET plan is below as a
> study aid.

## Topology

```
                 LAN-1 (broadcast)                        LAN-2 (broadcast)
              r1 --- r5 --- r6                          r3 --- r4 --- r8
              (xe)  (xr)   (xr)                         (xe)  (xe)   (xr)

  Point-to-point mesh:
      r1 --- r2 --- r3 --- r6
              |      |
             r7 --- r5 --- r4
              |
             r8 --- r6
      r7 --- r8

  Full link list:
    LAN-1: r1, r5, r6        LAN-2: r3, r4, r8
    p2p:   r1-r2  r2-r3  r2-r7  r4-r5  r5-r7  r6-r8  r7-r8  r3-r6
```

## Cabling / interface map

`ethN` is what you write in the topology file. The device-side name is what you
configure IS-IS on.

| Node | Kind        | eth1            | eth2            | eth3            |
|------|-------------|-----------------|-----------------|-----------------|
| r1   | c8000v      | Gi2  → LAN-1    | Gi3  → r2       | —               |
| r2   | c8000v      | Gi2  → r1       | Gi3  → r3       | Gi4 → r7        |
| r3   | c8000v      | Gi2  → r2       | Gi3  → LAN-2    | Gi4 → r6        |
| r4   | c8000v      | Gi2  → LAN-2    | Gi3  → r5       | —               |
| r5   | XRd         | Gi0/0/0/0 →LAN-1| Gi0/0/0/1 → r4  | Gi0/0/0/2 → r7  |
| r6   | XRd         | Gi0/0/0/0 →LAN-1| Gi0/0/0/1 → r8  | Gi0/0/0/2 → r3  |
| r7   | XRd         | Gi0/0/0/0 → r2  | Gi0/0/0/1 → r5  | Gi0/0/0/2 → r8  |
| r8   | XRd         | Gi0/0/0/0 →LAN-2| Gi0/0/0/1 → r6  | Gi0/0/0/2 → r7  |

> Mapping rule — **c8000v**: eth1=Gi2, eth2=Gi3, eth3=Gi4 (Gi1 is mgmt).
> **XRd**: eth1=Gi0/0/0/0, eth2=Gi0/0/0/1, eth3=Gi0/0/0/2.

## Suggested addressing & NET plan (study reference)

Single area `49.0001`. **Loopback0 in `198.19.0.0/24` (/32 each)**, **all transit/LAN
interfaces in `172.16.0.0/16`** — `/31` on p2p links, `/24` per LAN.

| Node | Loopback0       | NET address                  |
|------|-----------------|------------------------------|
| r1   | 198.19.0.1/32   | 49.0001.0000.0000.0001.00    |
| r2   | 198.19.0.2/32   | 49.0001.0000.0000.0002.00    |
| r3   | 198.19.0.3/32   | 49.0001.0000.0000.0003.00    |
| r4   | 198.19.0.4/32   | 49.0001.0000.0000.0004.00    |
| r5   | 198.19.0.5/32   | 49.0001.0000.0000.0005.00    |
| r6   | 198.19.0.6/32   | 49.0001.0000.0000.0006.00    |
| r7   | 198.19.0.7/32   | 49.0001.0000.0000.0007.00    |
| r8   | 198.19.0.8/32   | 49.0001.0000.0000.0008.00    |

Suggested link subnets (all under `172.16.0.0/16`):

| Link        | Subnet           | Addresses              |
|-------------|------------------|------------------------|
| LAN-1       | 172.16.1.0/24    | r1 .1, r5 .5, r6 .6    |
| LAN-2       | 172.16.2.0/24    | r3 .3, r4 .4, r8 .8    |
| r1-r2       | 172.16.12.0/31   | r1 .0, r2 .1           |
| r2-r3       | 172.16.23.0/31   | r2 .0, r3 .1           |
| r2-r7       | 172.16.27.0/31   | r2 .0, r7 .1           |
| r4-r5       | 172.16.45.0/31   | r4 .0, r5 .1           |
| r5-r7       | 172.16.57.0/31   | r5 .0, r7 .1           |
| r6-r8       | 172.16.68.0/31   | r6 .0, r8 .1           |
| r7-r8       | 172.16.78.0/31   | r7 .0, r8 .1           |
| r3-r6       | 172.16.36.0/31   | r3 .0, r6 .1           |

## Prerequisites

- Linux host (or WSL2 / Linux VM) with Docker + containerlab installed
- The two router images imported locally. On the lab server (`10.0.0.172`) these are:
  - `vrnetlab/cisco_c8000v:17.15.05` (also `17.12.05a` available)
  - `ios-xr/xrd-control-plane:26.1.1`
- **Resources**: c8000v ≈ 4 GB RAM each, XRd ≈ 2 GB each → budget **~24 GB RAM**
  and 8+ vCPUs for the full lab. The lab server has 28 cores / 125 GB RAM, so the
  full topology runs comfortably there.

## Deploy

```bash
# 1. Create the two host bridges for the broadcast segments
sudo ip link add br-lan1 type bridge && sudo ip link set br-lan1 up
sudo ip link add br-lan2 type bridge && sudo ip link set br-lan2 up

# 2. Deploy (c8000v nodes take ~5 min to boot)
sudo clab deploy -t isis-lab.clab.yml

# 3. Inspect
sudo clab inspect -t isis-lab.clab.yml
```

Access the nodes:

```bash
ssh admin@<r1..r4-mgmt-ip>            # c8000v, password: admin
ssh clab@<r5..r8-mgmt-ip>             # XRd,    password: clab@123
# or
docker exec -it clab-isis-lab-r5 /pkg/bin/xr_cli.sh   # XRd CLI shortcut
```

Destroy:

```bash
sudo clab destroy -t isis-lab.clab.yml --cleanup
sudo ip link del br-lan1 ; sudo ip link del br-lan2
```

## Study ideas

- Watch **DIS election** on LAN-1 (mixed IOS-XE/XR) vs LAN-2; change `isis priority`.
- Compare p2p vs broadcast adjacency formation and LSP/CSNP/PSNP behaviour.
- Tune metrics to force traffic across alternate paths; verify with `show isis route` /
  `show route isis` and traceroute.
- Enable wide metrics, then test mismatched metric-style behaviour.
- Break a link and observe SPF reconvergence and LSP flooding.
