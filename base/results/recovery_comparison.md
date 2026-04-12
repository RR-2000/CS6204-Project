# Recovery Comparison

## Forward Direction

| Metric | BGP Only | SDX Fast Recovery | SDX - BGP |
| --- | ---: | ---: | ---: |
| Detection time (s) | 1.01 | 1.01 | 0.0 |
| Blackout duration (s) | 8.45 | 0.03 | -8.42 |
| Traffic recovery time (s) | 9.46 | 1.04 | -8.42 |
| BGP sync time (s) | 2.03 | 1.04 | -0.99 |
| Packet loss count | 9 | 1 | -8 |
| Total packets sent | None | None | -8 |
| Post-recovery RTT (ms) | 7.728 | 6.827 | -0.9 |

## Reverse Direction

| Metric | BGP Only | SDX Fast Recovery | SDX - BGP |
| --- | ---: | ---: | ---: |
| Detection time (s) | 1.01 | 1.01 | 0.0 |
| Blackout duration (s) | 7.4 | 0.03 | -7.37 |
| Traffic recovery time (s) | 8.4 | 1.04 | -7.36 |
| BGP sync time (s) | 2.03 | 1.04 | -0.99 |
| Packet loss count | 8 | 1 | -7 |
| Total packets sent | None | None | -7 |
| Post-recovery RTT (ms) | 7.958 | 7.876 | -0.08 |
