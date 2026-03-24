# CS6204-Project

Course project for CS6204: Advanced Topics in Networking.

## Overview

This project contains a Mininet + FRR + P4 experiment for BGP reconvergence.

Current experiment goal:

- normal path:
  - `AS1 -> AS2 -> AS4`
  - `AS4 -> AS2 -> AS1`
- after `AS2` loses its uplink to the shared exchange switch:
  - BGP withdraws the old path
  - BGP relearns through `AS3`
  - traffic converges to:
    - `AS1 -> AS3 -> AS4`
    - `AS4 -> AS3 -> AS1`

## Topology

- `as1r1`, `as2r1`, `as3r1` share subnet `10.0.0.0/24` through `ixp1s1`
- `as4r1` connects to:
  - `as2r1` via `10.0.1.0/24`
  - `as3r1` via `10.0.2.0/24`
- the `AS2-AS4` link is configured faster than the `AS3-AS4` link
- BGP policy prefers `AS2` in the steady state

## Run

From [base](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base):

```bash
make run-convergence-1
```

## Output

Successful runs save metrics to:

- [bgp_convergence.log](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/temp/bgp_convergence.log)
- [bgp_convergence.json](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/temp/bgp_convergence.json)

Recorded metrics include:

- detection time
- blackout duration
- total convergence time
- packet loss count
- first response RTT after recovery

## Implementation Notes

- failure injection is performed by shutting down `as2r1-eth1`
- the P4 controller preinstalls static forwarding entries for router MAC addresses on the shared switch
- detailed failure analysis is documented in [BGP_RECOVERY_REPORT.md](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/BGP_RECOVERY_REPORT.md)
