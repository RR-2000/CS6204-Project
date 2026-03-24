# CS6204-Project

Course project for CS6204: Advanced Topics in Networking.

## Overview

This project contains a Mininet + FRR + P4 experiment for BGP reconvergence and SDX fast recovery.

Current experiment goals:

- steady-state forwarding:
  - `AS1 -> AS2 -> AS4`
  - `AS4 -> AS3 -> AS1`
- BGP-only recovery:
  - when `AS2` loses its uplink to the shared exchange switch, BGP withdraws the old path and converges to `AS1 -> AS3 -> AS4`
- SDX fast recovery:
  - the controller directly monitors the local switch interface connected to `AS2`
  - when that interface goes down, it immediately installs a redirect rule on the switch
  - packets from `AS1` that were headed to `AS2` are immediately redirected to `AS3`
  - BGP later converges to the same final path, so SDX recovery does not replace BGP convergence

## Topology

- `as1r1`, `as2r1`, `as3r1` share subnet `10.0.0.0/24` through `ixp1s1`
- `as4r1` connects to:
  - `as2r1` via `10.0.1.0/24`
  - `as3r1` via `10.0.2.0/24`
- the `AS2-AS4` link is configured faster than the `AS3-AS4` link
- BGP policy prefers `AS2` for `AS1 -> AS4`
- BGP policy prefers `AS3` for `AS4 -> AS1`

## Run

From [base](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base):

`BGP-only`:

```bash
make run-convergence-1
```

`SDX fast recovery`:

```bash
make run-sdx-convergence-1
```

`Run both and generate a comparison`:

```bash
make run-compare-1
```

## Output

Successful runs save metrics to:

- [bgp_convergence.log](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/temp/bgp_convergence.log)
- [bgp_convergence.json](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/temp/bgp_convergence.json)
- [sdx_convergence.log](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/temp/sdx_convergence.log)
- [sdx_convergence.json](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/temp/sdx_convergence.json)

Persistent copies for comparison are saved to:

- [base/results/bgp_convergence.json](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/results/bgp_convergence.json)
- [base/results/sdx_convergence.json](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/results/sdx_convergence.json)
- [base/results/recovery_comparison.md](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/results/recovery_comparison.md)
- [base/results/recovery_comparison.json](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/results/recovery_comparison.json)

Recorded metrics include:

- detection time
- blackout duration
- traffic recovery time
- BGP sync time
- packet loss count
- average RTT over the first few successful pings after recovery

## Implementation Notes

- failure injection is performed by shutting down `as2r1-eth1`
- the P4 controller preinstalls static forwarding entries for router MAC addresses on the shared switch
- the SDX fast recovery rule rewrites packets from `AS1` that would have gone to `AS2`, and forwards them to the `AS3` switch port instead
- detailed failure analysis is documented in [BGP_RECOVERY_REPORT.md](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/BGP_RECOVERY_REPORT.md)
