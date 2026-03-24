# CS6204-Project

Repository for CS6204: Advanced Topics in Networking course project.

This project implements a Software-Defined Exchange (SDX) using P4 programmable switches, Mininet network emulation, and BGP routing via FRR and BIRD.

---

## Network Topology

```
 AS1 (AS100)              AS2 (AS200)              AS3 (AS300)
 10.1.0.0/24              10.2.0.0/24              10.3.0.0/24
 as1h1 (10.1.0.101)       as2h1 (10.2.0.101)       as3h1 (10.3.0.101)
 as1h2 (10.1.0.102)       as2h2 (10.2.0.102)       as3h2 (10.3.0.102)
      |                        |                        |
   as1r1                    as2r1                    as3r1
 (10.0.0.1)              (10.0.0.2)               (10.0.0.3)
      |                        |                        |
      +------------------------+------------------------+
                               |
                          ixp1s1 (P4 Switch)
                               |
                        ixp1s1_bird (Route Server, AS1337)
                               |
                  10.0.1.0/24 (100 Mbps, fast)
                  as2r1 ------- as4r1
                  10.0.2.0/24 (1 Mbps, slow)
                  as3r1 ------- as4r1
                               |
                            as4r1 (AS400)
                            10.4.0.0/24
                       as4h1 (10.4.0.101)
                       as4h2 (10.4.0.102)
```

### Nodes

| Node | Type | AS | Loopback |
|---|---|---|---|
| ixp1s1 | P4 Switch (BMv2) | — | — |
| ixp1s1_bird | Route Server (BIRD) | AS1337 | 10.100.255.1 |
| as1r1 | FRR Router | AS100 | 10.100.1.1 |
| as2r1 | FRR Router | AS200 | 10.100.2.1 |
| as3r1 | FRR Router | AS300 | 10.100.3.1 |
| as4r1 | FRR Router | AS400 | 10.100.4.1 |

### IP Address Scheme

| Network | Subnet | Purpose |
|---|---|---|
| SDX fabric | 10.0.0.0/24 | AS1, AS2, AS3 connect to SDX |
| AS1 internal | 10.1.0.0/24 | Router (.1), hosts (.101, .102) |
| AS2 internal | 10.2.0.0/24 | Router (.1), hosts (.101, .102) |
| AS3 internal | 10.3.0.0/24 | Router (.1), hosts (.101, .102) |
| AS4 internal | 10.4.0.0/24 | Router (.1), hosts (.101, .102) |
| AS4–AS2 link | 10.0.1.0/24 | AS2 side .1, AS4 side .2 (100 Mbps) |
| AS4–AS3 link | 10.0.2.0/24 | AS3 side .1, AS4 side .2 (1 Mbps) |

### BGP Sessions

- AS1, AS2, AS3 establish eBGP sessions with the SDX route server (AS1337).
- AS4 is not directly connected to the SDX. It peers with AS2 and AS3 via direct links.
- Routes from AS4 are propagated to AS1/AS2/AS3 through the route server.
- Normal traffic path from AS1 to AS4: **AS1 → AS2 → AS4** (fast, 100 Mbps).
- Fallback path after AS2–AS4 failure: **AS1 → AS3 → AS4** (slow, 1 Mbps).

---

## Project Structure

```
base/
├── Makefile
├── requirements.txt
├── build/                          # Compiled P4 artifacts (auto-generated)
│   └── p4/
│       ├── ixp_switch.json         # BMv2 executable
│       └── ixp_switch.p4info.txtpb # P4Runtime control plane interface
├── common/
│   ├── mininet/nodes.py            # Mininet node classes (P4Switch, FRRRouter, BIRDRouter, ...)
│   └── p4/functions.py             # Utility functions (MAC/IP conversion, packet filtering)
├── networks/1/
│   ├── frr/                        # FRR BGP configuration for AS1–AS4
│   │   ├── as1r1-bgp.conf
│   │   ├── as2r1-bgp.conf
│   │   ├── as3r1-bgp.conf
│   │   └── as4r1-bgp.conf
│   └── mininet/
│       ├── networks.py             # Topology definition
│       ├── topology_cli.py         # Interactive mode (manual debugging)
│       ├── topology_checks.py      # Automated test mode
│       └── topology_convergence_test.py  # BGP convergence measurement
└── tasks/1/
    ├── bird/
    │   └── ixp1s1_bird.conf        # Route server configuration (BIRD)
    ├── p4/
    │   └── ixp_switch.p4           # P4 data plane program
    └── p4rt_controller/
        └── ixp1s1_controller.py    # P4Runtime controller (MAC learning + route alteration)
```

---

## P4 Data Plane

The P4 program (`ixp_switch.p4`) runs on the SDX switch and implements:

| Table | Match | Action | Purpose |
|---|---|---|---|
| `forwarding` | Destination MAC (exact) | `set_egress_port`, `flood` | Layer-2 forwarding |
| `route_alteration` | Src/Dst IP, Protocol, L4 ports (ternary) | `set_route_override` | Policy-based routing |

Every ingress packet is cloned to the controller for MAC learning. The `route_alteration` table allows the controller to override forwarding decisions for specific flows.

---

## P4Runtime Controller

`ixp1s1_controller.py` implements the control plane using the [Finsy](https://github.com/byllyfish/finsy) P4Runtime library:

- **MAC learning**: learns source MAC → port mappings from cloned packets and installs entries in the `forwarding` table.
- **Idle timeout**: removes stale MAC entries after 10 seconds of inactivity.
- **Port events**: clears MAC entries when a port goes down or comes back up.
- **SDX fast recovery**: on `PORT_DOWN`, immediately installs `route_alteration` entries that redirect traffic for the affected prefix to an alternative next-hop — no BGP reconvergence required. Rules are removed when the port comes back up (`PORT_UP`).

### Fast Recovery Logic

When `ixp1s1-eth2` (AS2's uplink) goes down, the controller installs:

```
route_alteration: dst 10.4.0.0/24 → rewrite dst MAC to AS3's MAC, egress via ixp1s1-eth3
```

AS1 continues sending packets with AS2's destination MAC (BGP route not yet updated), but the SDX intercepts based on **destination IP** and rewrites the MAC before the `forwarding` table is consulted, effectively redirecting traffic to AS3 transparently and instantly.

A flag file (`temp/disable_fast_recovery`) can be written by the test harness to disable this behaviour for the baseline BGP-convergence test.

---

## Getting Started

### Prerequisites

- P4 development environment with `p4c-bm2-ss` and `simple_switch_grpc`
- Python 3 at `/opt/p4/p4dev-python-venv/bin/python3`
- FRR (`zebra`, `bgpd`)
- BIRD routing daemon
- Mininet

### Build

Compile the P4 program:

```bash
cd base
make build-task-1
```

### Run (Interactive)

Start the network and open a Mininet CLI for manual testing:

```bash
make run-task-1
```

After entering the CLI, wait ~30–60 seconds for BGP to converge, then test connectivity:

```bash
# Ping from AS1 to AS4
mininet> as1h1 ping 10.4.0.101

# Check BGP routing table on AS1
mininet> as1r1 vtysh -c "show bgp ipv4 unicast"

# Check system routing table on AS4
mininet> as4r1 ip route
```

### Run (Automated Checks)

```bash
make run-checks-1
```

### Run (BGP Convergence vs SDX Fast Recovery Test)

Runs two back-to-back tests that bring down the **same** link (`as2r1 ↔ ixp1s1`) and compare recovery time:

```bash
make run-convergence-1
```

| | Test A – BGP Convergence | Test B – SDX Fast Recovery |
|---|---|---|
| **Link failed** | `as2r1 ↔ ixp1s1` | `as2r1 ↔ ixp1s1` |
| **SDX fast recovery** | Disabled (flag file) | Enabled |
| **Recovery mechanism** | BGP withdraw → reconverge via AS3 | Controller installs `route_alteration` instantly |
| **Expected time** | 5–30 s | < 1 s |

**Test A** steps:
1. Write flag file `temp/disable_fast_recovery` so the controller skips failover rule installation.
2. Bring down the AS2–SDX link.
3. AS2's BGP session with the route server drops; route server withdraws AS2's routes from AS1.
4. AS1 waits for BGP to reconverge and learn that AS4 is reachable via AS3.
5. Restore the link; remove the flag file; wait for full BGP reconvergence.

**Test B** steps:
1. Bring down the same AS2–SDX link (no flag file — fast recovery is active).
2. SDX controller detects `PORT_DOWN` on `ixp1s1-eth2` and immediately installs a `route_alteration` rule: redirect traffic for `10.4.0.0/24` to AS3's MAC via `ixp1s1-eth3`.
3. AS1 still sends packets addressed to AS2's MAC; SDX rewrites the MAC and forwards to AS3.
4. Connectivity is restored in under one second with no BGP involvement.

Results are saved to `temp/bgp_convergence.log`:

```
BGP Convergence vs SDX Fast Recovery
==================================================
Test time: 2026-03-24 10:00:00
Ping:      as1h1 -> 10.4.0.101

--- BGP ---
Link failed:          as2r1 <-> ixp1s1
Link down at:         10:00:00.123456
Ping failed at:       10:00:02.456789
Recovered at:         10:00:17.654321
Detection time:       2.33s
Blackout duration:    15.20s
Convergence time:     17.53s
Packet loss count:    16 packets
First response RTT:   12.345 ms

--- SDX ---
Link failed:          as2r1 <-> ixp1s1
Link down at:         10:05:00.123456
Ping failed at:       10:05:00.456789
Recovered at:         10:05:00.789012
Detection time:       0.33s
Blackout duration:    0.33s
Convergence time:     0.67s
Packet loss count:    1 packets
First response RTT:   1.234 ms

--- Comparison ---
BGP convergence time:         17.53s
SDX fast recovery time:       0.67s
Time saved by SDX:            16.86s
SDX speedup:                  26.2x faster
BGP packet loss:              16 packets
SDX packet loss:              1 packets
```

### Clean Up

```bash
make clean
```

---

## Make Targets

| Target | Description |
|---|---|
| `make build-task-1` | Compile the P4 program |
| `make run-task-1` | Start network with interactive Mininet CLI |
| `make run-checks-1` | Run automated traffic checks |
| `make run-convergence-1` | Run BGP convergence measurement test |
| `make run-stop` | Stop the running network and kill all processes |
| `make clean` | Remove all build and temp files |
| `make generate-submission` | Package the `tasks/` directory into a zip file |
