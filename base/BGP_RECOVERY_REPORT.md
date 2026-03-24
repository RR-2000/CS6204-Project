# Recovery Report

## Goal

This experiment evaluates two recovery methods after the link between `AS2` and the shared exchange switch fails:

- pure BGP reconvergence
- SDX fast recovery followed by normal BGP convergence

Expected behavior:

- Normal forwarding:
  - `AS1 -> AS2 -> AS4`
  - `AS4 -> AS3 -> AS1`
- After failure of the `AS2` uplink to the exchange:
  - BGP withdraws the path through `AS2`
  - BGP relearns the path through `AS3`
  - Traffic converges to:
    - `AS1 -> AS3 -> AS4`
    - `AS4 -> AS3 -> AS1`

In SDX fast recovery mode:

- the experiment triggers an immediate SDX failover event when the `AS2` uplink is taken down
- packets from `AS1` that were previously sent to `AS2` are redirected to `AS3`
- BGP still converges in the background

## Topology Summary

- `as1r1`, `as2r1`, and `as3r1` share subnet `10.0.0.0/24` through `ixp1s1`
- `as4r1` connects directly to:
  - `as2r1` over `10.0.1.0/24`
  - `as3r1` over `10.0.2.0/24`
- BGP preference is configured to prefer `AS2` in the steady state

## Root Cause

The earlier implementation failed for two separate reasons.

### 1. Failure injection did not match the intended fault model

The test originally used:

```python
network.configLinkStatus("as2r1", "ixp1s1", "down")
```

For this custom BMv2/P4 switch setup, that did not produce a reliable switch-side port-down event.

Observed evidence:

- `ixp1s1` controller logs did not report `Port 2 DOWN`
- BMv2 logs still showed packets being processed and transmitted on `port 2`

As a result, the simulated failure was not a clean "AS2 disconnected from the exchange" event.

### 2. Control-plane reachability was too dependent on dynamic MAC learning

`AS1` and `AS3` are supposed to remain connected through the shared switch after `AS2` is removed. However, under the old setup:

- after the fault, `as1r1 ping 10.0.0.3` failed
- after the fault, `as3r1 ping 10.0.0.1` failed
- static ARP entries still existed

That showed the problem was below BGP:

- interfaces were still up
- IP addresses were still present
- ARP resolution still existed
- but layer-2 forwarding between `port 1` and `port 3` was not stable enough for BGP TCP sessions to survive

## Fix

Two changes were made.

### 1. Use interface shutdown on `as2r1`

The fault injection was changed to:

```python
ip link set dev as2r1-eth1 down
```

and recovery uses:

```python
ip link set dev as2r1-eth1 up
```

This accurately models `AS2` losing connectivity to the shared exchange while leaving `AS1` and `AS3` attached to the switch.

### 2. Install static forwarding entries for router MAC addresses

The controller now preinstalls static forwarding rules for:

- `as1r1-eth1` MAC on port 1
- `as2r1-eth1` MAC on port 2
- `as3r1-eth1` MAC on port 3

This prevents BGP control-plane traffic from depending on transient MAC learning behavior.

### 3. Add an SDX fast failover rule

The P4 program now contains a dedicated fast failover table that matches:

- ingress port from `AS1`
- destination MAC of `AS2`

and rewrites the packet to:

- destination MAC of `AS3`
- egress port of `AS3`

This gives immediate data-plane recovery for traffic from `AS1` toward `AS4` when `AS2` becomes unavailable on the exchange.

### 4. Keep BGP and SDX recovery separate

The SDX rule only accelerates forwarding. It does not replace the control-plane decision process.

Final steady state is still produced by BGP:

- `AS1` eventually selects `AS3`
- `AS4` is already configured to prefer `AS3` for return traffic

## Result

With the fixes applied:

- initial convergence succeeds
- failure is detected after the `AS2` uplink goes down
- BGP reconverges through `AS3`
- performance metrics are written to:
  - [bgp_convergence.log](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/temp/bgp_convergence.log)
  - [bgp_convergence.json](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/temp/bgp_convergence.json)

Example measured result from the latest successful BGP-only run:

- Detection time: `1.02 s`
- Blackout duration: `8.16 s`
- Convergence time: `9.19 s`
- Packet loss count: `4`
- First response RTT after recovery: `41.403 ms`

## Evaluation Notes

For grading or repeated evaluation:

- use `make run-convergence-1` for BGP-only recovery
- use `make run-sdx-convergence-1` for SDX fast recovery
- use `make run-compare-1` to generate a side-by-side comparison

Structured output files:

- [bgp_convergence.json](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/temp/bgp_convergence.json)
- [sdx_convergence.json](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/temp/sdx_convergence.json)
- [recovery_comparison.json](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/temp/recovery_comparison.json)
- [recovery_comparison.md](/C:/Myself/work/Course/CS6204/VM_share/CS6204-Project/base/temp/recovery_comparison.md)
