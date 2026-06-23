# Per-node configs

Drop one file per node here, named `<node>.cfg` (matching the node name in the
topology): `r1.cfg`, `r2.cfg`, … `r8.cfg`. Switches (`sw1`, `sw2`) need nothing.

The file is plain device CLI. On push it is copied onto the device and (by
default) merged into the running-config, so write it as configuration-mode
commands — **not** wrapped in `configure terminal` / `commit` (the tool handles
that).

## IOS-XE (c8000v: r1–r4) — example snippet

Matches the addressing plan in the lab README (loopback `198.19.0.x/32`,
interfaces in `172.16.0.0/16`):

```
hostname r1
interface Loopback0
 ip address 198.19.0.1 255.255.255.255
 ip router isis
interface GigabitEthernet2
 ip address 172.16.1.1 255.255.255.0
 ip router isis
 no shutdown
router isis
 net 49.0001.0000.0000.0001.00
 is-type level-2-only
 metric-style wide
```

## IOS-XR (XRd: r5–r8) — example snippet

```
hostname r5
interface Loopback0
 ipv4 address 198.19.0.5 255.255.255.255
interface GigabitEthernet0/0/0/0
 ipv4 address 172.16.1.5 255.255.255.0
 no shutdown
router isis 1
 is-type level-2-only
 net 49.0001.0000.0000.0005.00
 address-family ipv4 unicast
  metric-style wide
 interface Loopback0
  address-family ipv4 unicast
 interface GigabitEthernet0/0/0/0
  point-to-point
  address-family ipv4 unicast
```

> These are reference snippets only — the lab intentionally ships without configs
> so you build IS-IS by hand. Save your own work as `<node>.cfg` to push it.
