# Recovery Comparison

## Forward Direction

| Metric | BGP Only | SDX Fast Recovery | SDX - BGP |
| --- | ---: | ---: | ---: |
| Detection time (s) | 1.0 | 1.0 | 0.0 |
| Blackout duration (s) | 7.41 | 0.0 | -7.41 |
| Traffic recovery time (s) | 8.41 | 1.01 | -7.4 |
| BGP sync time (s) | 2.05 | 1.04 | -1.01 |
| Packet loss count | 8 | 1 | -7 |
| Total packets sent | None | None | -7 |
| Post-recovery RTT (ms) | 7.452 | 6.981 | -0.47 |

## Reverse Direction

| Metric | BGP Only | SDX Fast Recovery | SDX - BGP |
| --- | ---: | ---: | ---: |
| Detection time (s) | 1.01 | 1.01 | 0.0 |
| Blackout duration (s) | 8.45 | 0.0 | -8.45 |
| Traffic recovery time (s) | 9.46 | 1.01 | -8.45 |
| BGP sync time (s) | 2.04 | 1.04 | -1.0 |
| Packet loss count | 9 | 1 | -8 |
| Total packets sent | None | None | -8 |
| Post-recovery RTT (ms) | 8.084 | 8.335 | 0.25 |
