import os
import re
import sys
import time
import json
import statistics
from datetime import datetime

from mininet.link import TCLink
from mininet.log import output, setLogLevel
from mininet.net import Mininet

from networks import Topology

SCRIPT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))
REPOSITORY_DIRECTORY = os.path.join(SCRIPT_DIRECTORY, "../../../")
TEMP_DIRECTORY = os.path.join(REPOSITORY_DIRECTORY, "temp")
RESULTS_DIRECTORY = os.path.join(REPOSITORY_DIRECTORY, "results")
CONTROLLER_LOG_FILE = os.path.join(
    TEMP_DIRECTORY,
    "p4rt_controller",
    "ixp1s1",
    "ixp1s1_controller-stdout.log",
)
CONTROLLER_LOG_FILE_IXP2 = os.path.join(
    TEMP_DIRECTORY,
    "p4rt_controller",
    "ixp2s1",
    "ixp2s1_controller-stdout.log",
)
SWITCH_STDOUT_FILE = os.path.join(
    TEMP_DIRECTORY,
    "p4_switch",
    "ixp1s1",
    "ixp1s1-stdout.txt",
)
SWITCH_STDOUT_FILE_IXP2 = os.path.join(
    TEMP_DIRECTORY,
    "p4_switch",
    "ixp2s1",
    "ixp2s1-stdout.txt",
)
SWITCH_BMV2_LOG_FILE = os.path.join(
    TEMP_DIRECTORY,
    "p4_switch",
    "ixp1s1",
    "ixp1s1-bmv2.txt",
)
SWITCH_BMV2_LOG_FILE_IXP2 = os.path.join(
    TEMP_DIRECTORY,
    "p4_switch",
    "ixp2s1",
    "ixp2s1-bmv2.txt",
)

PING_SOURCE_FR = "as1h1"
PING_TARGET_FR = "10.4.0.101"
PING_SOURCE_BW = "as4h1"
PING_TARGET_BW = "10.1.0.101"
INITIAL_WAIT = 30
MAX_RECONVERGENCE_WAIT = 30
PING_INTERVAL = 0.05
POST_RECOVERY_PROBES = 0
BASELINE_RTT_SAMPLES = int(os.environ.get("BASELINE_RTT_SAMPLES", "5"))
RECOVERY_STABLE_SUCCESSES = int(os.environ.get("RECOVERY_STABLE_SUCCESSES", "3"))
TIMELINE_MAX_POINTS = int(os.environ.get("TIMELINE_MAX_POINTS", "2000"))
POST_RECOVERY_WINDOW_S = float(os.environ.get("POST_RECOVERY_WINDOW_S", "60"))
POST_RECOVERY_WINDOW_INTERVAL_S = float(os.environ.get("POST_RECOVERY_WINDOW_INTERVAL_S", "0.5"))
POST_RECOVERY_PHASE_SPLIT_S = float(os.environ.get("POST_RECOVERY_PHASE_SPLIT_S", "30"))
TRACE_MAX_HOPS = int(os.environ.get("TRACE_MAX_HOPS", "16"))
TRACE_PROBES = int(os.environ.get("TRACE_PROBES", "1"))
TRACE_TIMEOUT_S = int(os.environ.get("TRACE_TIMEOUT_S", "1"))
RECOVERY_MODE = os.environ.get("RECOVERY_MODE", "bgp").strip().lower()
MODE_LABEL = "SDX_FAST" if RECOVERY_MODE == "sdx" else "BGP_ONLY"

LOG_FILE = os.path.join(TEMP_DIRECTORY, f"{RECOVERY_MODE}_convergence.log")
JSON_LOG_FILE = os.path.join(TEMP_DIRECTORY, f"{RECOVERY_MODE}_convergence.json")
PERSISTENT_LOG_FILE = os.path.join(RESULTS_DIRECTORY, f"{RECOVERY_MODE}_convergence.log")
PERSISTENT_JSON_LOG_FILE = os.path.join(RESULTS_DIRECTORY, f"{RECOVERY_MODE}_convergence.json")


def ping_once(host, target, timeout=1):
    result = host.cmd(f"ping -c 1 -W {timeout} {target}")
    if "1 received" not in result:
        return False, None

    for line in result.splitlines():
        if "rtt min" in line or "round-trip" in line:
            try:
                rtt_ms = float(line.split("=")[1].strip().split("/")[1])
                return True, rtt_ms
            except (IndexError, ValueError):
                return True, None
    return True, None


def collect_rtts(host, target, samples=3, timeout=1):
    rtts = []
    for _ in range(samples):
        success, rtt_ms = ping_once(host, target, timeout=timeout)
        if success and rtt_ms is not None:
            rtts.append(rtt_ms)
        time.sleep(0.2)
    return rtts


def percentile(values, pct):
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ranked = sorted(values)
    idx = (len(ranked) - 1) * pct
    lo = int(idx)
    hi = min(lo + 1, len(ranked) - 1)
    frac = idx - lo
    return ranked[lo] * (1 - frac) + ranked[hi] * frac


def timeline_sample(events):
    if len(events) <= TIMELINE_MAX_POINTS:
        return events

    sampled = []
    step = max(1, len(events) // TIMELINE_MAX_POINTS)
    for i in range(0, len(events), step):
        sampled.append(events[i])
    if sampled[-1] != events[-1]:
        sampled.append(events[-1])
    return sampled


def trace_path_snapshot(host, target):
    raw = host.cmd(
        f"traceroute -n -q {TRACE_PROBES} -w {TRACE_TIMEOUT_S} -m {TRACE_MAX_HOPS} {target} || true"
    )
    hops = []
    for line in raw.splitlines():
        match = re.match(r"\s*(\d+)\s+(\S+)", line)
        if not match:
            continue
        hop = match.group(2)
        if hop != "*":
            hops.append(hop)
    return {
        "hops": hops,
        "hop_count": len(hops),
        "raw": raw,
    }


def route_get_snapshot(host, target):
    return host.cmd(f"ip route get {target} 2>/dev/null || true").strip()


def collect_post_recovery_window(host, target, stable_recovery_ts):
    if POST_RECOVERY_WINDOW_S <= 0:
        return []

    probes = []
    deadline = time.time() + POST_RECOVERY_WINDOW_S
    while time.time() < deadline:
        probe_start = time.time()
        success, rtt_ms = ping_once(host, target)
        probes.append(
            {
                "t_s": round(probe_start - stable_recovery_ts, 3),
                "ok": success,
                "rtt_ms": None if rtt_ms is None else round(rtt_ms, 3),
            }
        )
        elapsed = time.time() - probe_start
        sleep_s = POST_RECOVERY_WINDOW_INTERVAL_S - elapsed
        if sleep_s > 0:
            time.sleep(sleep_s)

    return probes


def summarize_post_recovery_window(window_probes, baseline_rtts, baseline_avg_rtt):
    sent = len(window_probes)
    losses = len([p for p in window_probes if not p["ok"]])
    success_rate = None if sent == 0 else (sent - losses) / sent
    rtts = [p["rtt_ms"] for p in window_probes if p["ok"] and p["rtt_ms"] is not None]

    avg_rtt = None if not rtts else statistics.fmean(rtts)
    p50_rtt = percentile(rtts, 0.50)
    p95_rtt = percentile(rtts, 0.95)
    jitter_rtt = None if len(rtts) < 2 else statistics.pstdev(rtts)
    min_rtt = None if not rtts else min(rtts)
    max_rtt = None if not rtts else max(rtts)

    split_s = max(0.0, min(POST_RECOVERY_PHASE_SPLIT_S, POST_RECOVERY_WINDOW_S))
    first_phase = [
        p["rtt_ms"]
        for p in window_probes
        if p["ok"] and p["rtt_ms"] is not None and p["t_s"] <= split_s
    ]
    second_phase = [
        p["rtt_ms"]
        for p in window_probes
        if p["ok"] and p["rtt_ms"] is not None and p["t_s"] > split_s
    ]
    first_phase_avg = None if not first_phase else statistics.fmean(first_phase)
    second_phase_avg = None if not second_phase else statistics.fmean(second_phase)

    baseline_p50 = percentile(baseline_rtts, 0.50)
    propagation_shift = None
    if baseline_p50 is not None and p50_rtt is not None:
        propagation_shift = p50_rtt - baseline_p50

    queueing_tail = None
    if p95_rtt is not None and p50_rtt is not None:
        queueing_tail = p95_rtt - p50_rtt

    second_phase_inflation = None
    if baseline_avg_rtt is not None and second_phase_avg is not None and baseline_avg_rtt > 0:
        second_phase_inflation = second_phase_avg / baseline_avg_rtt

    return {
        "post_recovery_window_s": POST_RECOVERY_WINDOW_S,
        "post_recovery_window_probe_interval_s": POST_RECOVERY_WINDOW_INTERVAL_S,
        "post_recovery_window_phase_split_s": split_s,
        "post_recovery_window_packets_sent": sent,
        "post_recovery_window_packet_loss_count": losses,
        "post_recovery_window_success_rate": success_rate,
        "post_recovery_window_avg_rtt_ms": avg_rtt,
        "post_recovery_window_p50_rtt_ms": p50_rtt,
        "post_recovery_window_p95_rtt_ms": p95_rtt,
        "post_recovery_window_jitter_ms": jitter_rtt,
        "post_recovery_window_min_rtt_ms": min_rtt,
        "post_recovery_window_max_rtt_ms": max_rtt,
        "post_recovery_window_first_phase_avg_rtt_ms": first_phase_avg,
        "post_recovery_window_second_phase_avg_rtt_ms": second_phase_avg,
        "propagation_shift_indicator_ms": propagation_shift,
        "queueing_tail_indicator_ms": queueing_tail,
        "second_phase_rtt_inflation_ratio": second_phase_inflation,
    }


def wait_for_initial_convergence(network, dir="forward"):
    if dir == "reverse":
        ping_source = PING_SOURCE_BW
        ping_target = PING_TARGET_BW
    else:
        ping_source = PING_SOURCE_FR
        ping_target = PING_TARGET_FR

    output(f"*** Waiting up to {INITIAL_WAIT}s for initial BGP convergence...\n")
    source = network.getNodeByName(ping_source)
    start = time.time()
    while time.time() - start < INITIAL_WAIT:
        success, _ = ping_once(source, ping_target)
        if success:
            output(f"*** Initial connectivity is up after {time.time() - start:.1f}s\n")
            return True
        time.sleep(2)
    return False


def show_best_paths(network, label):
    output(f"\n*** [{label}] BGP best paths\n")
    for node_name, prefix in [("as1r1", "10.4.0.0/24"), ("as4r1", "10.1.0.0/24")]:
        node = network.getNodeByName(node_name)
        output(f"*** [{label}] {node_name} -> {prefix}\n")
        output(node.cmd(f'vtysh -c "show bgp ipv4 unicast {prefix}"'))
        output(f"*** [{label}] {node_name} kernel route snapshot\n")
        output(node.cmd("ip route | egrep '10.4.0.0/24|10.1.0.0/24|10.0.1.0/24|10.0.2.0/24' || true"))


def as1_best_path_uses_as3(network):
    as1r1 = network.getNodeByName("as1r1")
    bgp_output = as1r1.cmd('vtysh -c "show bgp ipv4 unicast 10.4.0.0/24"')
    return "10.0.0.3 from 10.0.0.3" in bgp_output and "best" in bgp_output


def as1_best_path_uses_as2(network):
    as1r1 = network.getNodeByName("as1r1")
    bgp_output = as1r1.cmd('vtysh -c "show bgp ipv4 unicast 10.4.0.0/24"')
    return "10.0.0.2 from 10.0.0.2" in bgp_output and "best" in bgp_output


def as4_best_path_uses_as3(network):
    as4r1 = network.getNodeByName("as4r1")
    bgp_output = as4r1.cmd('vtysh -c "show bgp ipv4 unicast 10.1.0.0/24"')
    return "10.0.4.3 from 10.0.4.3" in bgp_output and "best" in bgp_output


def as4_best_path_uses_as2(network):
    as4r1 = network.getNodeByName("as4r1")
    bgp_output = as4r1.cmd('vtysh -c "show bgp ipv4 unicast 10.1.0.0/24"')
    return "10.0.4.2 from 10.0.4.2" in bgp_output and "best" in bgp_output


def bgp_is_fully_synced(network):
    return as1_best_path_uses_as3(network) and as4_best_path_uses_as3(network)


def as1_best_path_ready(network):
    return as1_best_path_uses_as2(network) or as1_best_path_uses_as3(network)


def as4_best_path_ready(network):
    return as4_best_path_uses_as2(network) or as4_best_path_uses_as3(network)


def wait_for_reverse_bgp_ready(network, timeout=INITIAL_WAIT):
    output(f"*** Waiting up to {timeout}s for reverse BGP routes...\n")
    start = time.time()
    while time.time() - start < timeout:
        if as1_best_path_ready(network) and as4_best_path_ready(network):
            output(f"*** Reverse BGP routes ready after {time.time() - start:.1f}s\n")
            return True
        time.sleep(2)
    return False


def wait_for_preferred_paths(network, timeout=INITIAL_WAIT):
    output(f"*** Waiting up to {timeout}s for preferred AS2 paths...\n")
    start = time.time()
    while time.time() - start < timeout:
        if as1_best_path_uses_as2(network) and as4_best_path_uses_as2(network):
            output(f"*** Preferred AS2 paths restored after {time.time() - start:.1f}s\n")
            return True
        time.sleep(2)
    return False


def show_reconvergence_state(network, label):
    output(f"\n*** [{label}] Reconvergence state\n")
    for node_name in ["as1r1", "as3r1", "as4r1"]:
        node = network.getNodeByName(node_name)
        output(f"*** [{label}] {node_name} summary\n")
        output(node.cmd('vtysh -c "show bgp summary"'))
        if node_name in ["as1r1", "as4r1"]:
            output(f"*** [{label}] {node_name} kernel route snapshot\n")
            output(node.cmd("ip route | egrep '10.4.0.0/24|10.1.0.0/24|10.0.1.0/24|10.0.2.0/24' || true"))


def show_as1_as3_as4_state(network, label):
    output(f"\n*** [{label}] AS1-AS3-AS4 neighbor state\n")
    for node_name in ["as1r1", "as3r1", "as4r1"]:
        node = network.getNodeByName(node_name)
        output(f"*** [{label}] {node_name} bgp summary\n")
        output(node.cmd('vtysh -c "show bgp summary"'))
        output(f"*** [{label}] {node_name} ip neigh\n")
        output(node.cmd("ip neigh"))
        if node_name == "as1r1":
            output(f"*** [{label}] {node_name} ping 10.0.0.3\n")
            output(node.cmd("ping -c 2 -W 1 10.0.0.3"))
        elif node_name == "as4r1":
            output(f"*** [{label}] {node_name} ping 10.0.0.1\n")
            output(node.cmd("ping -c 2 -W 1 10.0.0.1"))


def show_as1_as3_post_failure_probes(network, label):
    output(f"\n*** [{label}] AS1-AS3 post-failure probes\n")
    as1r1 = network.getNodeByName("as1r1")
    as3r1 = network.getNodeByName("as3r1")

    output(f"*** [{label}] as1r1 ping 10.0.0.3\n")
    output(as1r1.cmd("ping -c 2 -W 1 10.0.0.3"))
    output(f"*** [{label}] as3r1 ping 10.0.0.1\n")
    output(as3r1.cmd("ping -c 2 -W 1 10.0.0.1"))
    output(f"*** [{label}] as1r1 ip neigh\n")
    output(as1r1.cmd("ip neigh"))
    output(f"*** [{label}] as3r1 ip neigh\n")
    output(as3r1.cmd("ip neigh"))


def _tail_matching_lines(path, patterns, max_lines=40):
    if not os.path.exists(path):
        return f"{path} does not exist\n"

    with open(path, "r", encoding="utf-8", errors="replace") as file:
        lines = file.readlines()

    matched = []
    for line in lines:
        if any(pattern in line for pattern in patterns):
            matched.append(line)

    if not matched:
        return "(no matching lines)\n"

    return "".join(matched[-max_lines:])


def show_switch_side_state(network, label):
    output(f"\n*** [{label}] Switch-side state\n")

    for node_name in ["as1r1", "as3r1"]:
        node = network.getNodeByName(node_name)
        output(f"*** [{label}] {node_name} ip link show\n")
        output(node.cmd("ip link show"))
        output(f"*** [{label}] {node_name} ip route show table main\n")
        output(node.cmd("ip route show table main"))

    output(f"*** [{label}] ixp1s1 controller log summary\n")
    output(
        _tail_matching_lines(
            CONTROLLER_LOG_FILE,
            [
                "Port ",
                "Removing MAC entries",
                "Installed static router MAC",
                "SDX fast failover",
                "timed out",
                "Failed",
                "ERROR",
            ],
        )
    )
    output(f"*** [{label}] ixp1s1 bmv2 log summary\n")
    output(
        _tail_matching_lines(
            SWITCH_BMV2_LOG_FILE,
            [
                "port 1",
                "port 2",
                "port 3",
                "mcast_grp",
                "mark_to_drop",
                "Transmitting packet",
            ],
        )
    )


def show_ixp2_side_state(label):
    output(f"\n*** [{label}] IXP2 switch-side state\n")
    output(f"*** [{label}] ixp2s1 controller log summary\n")
    output(
        _tail_matching_lines(
            CONTROLLER_LOG_FILE_IXP2,
            [
                "Port ",
                "Removing MAC entries",
                "Installed static router MAC",
                "SDX fast failover",
                "timed out",
                "Failed",
                "ERROR",
            ],
        )
    )
    output(f"*** [{label}] ixp2s1 bmv2 log summary\n")
    output(
        _tail_matching_lines(
            SWITCH_BMV2_LOG_FILE_IXP2,
            [
                "port 1",
                "port 2",
                "port 3",
                "mcast_grp",
                "mark_to_drop",
                "Transmitting packet",
                "Replication requested",
                "open:",
            ],
        )
    )

def run_test(network, dir="forward"):
    if dir == "reverse":
        ping_source = PING_SOURCE_BW
        ping_target = PING_TARGET_BW
    else:
        ping_source = PING_SOURCE_FR
        ping_target = PING_TARGET_FR

    loss_until_bgp_sync = dir == "reverse"
    source = network.getNodeByName(ping_source)
    as2r1 = network.getNodeByName("as2r1")

    baseline_rtts = collect_rtts(source, ping_target, samples=BASELINE_RTT_SAMPLES, timeout=1)
    baseline_avg_rtt = None if not baseline_rtts else sum(baseline_rtts) / len(baseline_rtts)
    baseline_p50_rtt = percentile(baseline_rtts, 0.50)
    baseline_min_rtt = None if not baseline_rtts else min(baseline_rtts)

    pre_failure_trace = trace_path_snapshot(source, ping_target)
    pre_failure_route = route_get_snapshot(source, ping_target)

    probe_timeline = []

    def record_probe(phase, now_ts, success, rtt_ms):
        probe_timeline.append(
            {
                "t_s": round(now_ts - t_link_down, 4),
                "phase": phase,
                "ok": success,
                "rtt_ms": None if rtt_ms is None else round(rtt_ms, 3),
            }
        )

    success, _ = ping_once(source, ping_target)
    if not success:
        output("*** ERROR: No initial connectivity\n")
        return None

    output("*** Bringing down interface: as2r1-eth1 and as2r1-eth2\n")
    t_link_down = time.time()
    as2r1.cmd("ip link set dev as2r1-eth1 down")
    # Bring down as2r1-eth2 
    as2r1.cmd("ip link set dev as2r1-eth2 down")


    t_ping_fail = None
    packet_loss_count = 0
    packets_sent = 0
    longest_loss_burst_packets = 0
    current_loss_burst_packets = 0
    while time.time() - t_link_down < 30:
        packets_sent += 1
        now_ts = time.time()
        success, rtt_ms = ping_once(source, ping_target)
        record_probe("detect", now_ts, success, rtt_ms)
        if not success:
            t_ping_fail = time.time()
            packet_loss_count += 1
            current_loss_burst_packets += 1
            longest_loss_burst_packets = max(longest_loss_burst_packets, current_loss_burst_packets)
            output(f"*** Connectivity lost after {t_ping_fail - t_link_down:.2f}s\n")
            break
        current_loss_burst_packets = 0
        time.sleep(PING_INTERVAL)

    if t_ping_fail is None:
        output("*** WARNING: Connectivity never dropped after link failure\n")
        output("*** Restoring interface: as2r1-eth1 and as2r1-eth2\n")
        as2r1.cmd("ip link set dev as2r1-eth1 up")
        as2r1.cmd("ip link set dev as2r1-eth2 up")
        return None

    t_recovered = None
    t_stable_recovered = None
    t_first_success_after_fail = None
    post_recovery_avg_rtt = None
    t_bgp_synced = None
    recovery_rtts = []
    recovery_successes = 0
    recovery_failures = 0
    recovery_flap_count = 0
    last_recovery_ok = None
    consecutive_successes = 0
    deadline = time.time() + MAX_RECONVERGENCE_WAIT
    output(f"*** Waiting for {MODE_LABEL} recovery...\n")
    while time.time() < deadline:
        packets_sent += 1
        now_ts = time.time()
        success, rtt_ms = ping_once(source, ping_target)
        record_probe("recovery", now_ts, success, rtt_ms)

        if t_bgp_synced is None and bgp_is_fully_synced(network):
            t_bgp_synced = time.time()
            output(f"*** BGP fully synced after {t_bgp_synced - t_link_down:.2f}s\n")

        if last_recovery_ok is not None and last_recovery_ok != success:
            recovery_flap_count += 1
        last_recovery_ok = success

        if success:
            recovery_successes += 1
            consecutive_successes += 1
            current_loss_burst_packets = 0
            if rtt_ms is not None:
                recovery_rtts.append(rtt_ms)

            if t_first_success_after_fail is None:
                t_first_success_after_fail = now_ts

            if t_recovered is None:
                t_recovered = now_ts
                output(f"*** Recovered after {t_recovered - t_link_down:.2f}s\n")

            if loss_until_bgp_sync and t_bgp_synced is None:
                time.sleep(PING_INTERVAL)
                continue

            can_finalize = RECOVERY_MODE != "sdx" or t_bgp_synced is not None
            if can_finalize and consecutive_successes >= RECOVERY_STABLE_SUCCESSES:
                t_stable_recovered = now_ts
                break
            time.sleep(PING_INTERVAL)
            continue

        recovery_failures += 1
        consecutive_successes = 0
        packet_loss_count += 1
        current_loss_burst_packets += 1
        longest_loss_burst_packets = max(longest_loss_burst_packets, current_loss_burst_packets)
        time.sleep(PING_INTERVAL)

    if t_stable_recovered is None:
        show_as1_as3_post_failure_probes(network, "recovery timeout")
        show_switch_side_state(network, "recovery timeout")
        show_reconvergence_state(network, "recovery timeout")
        show_best_paths(network, "recovery timeout")
        output("*** Restoring interface: as2r1-eth1 and as2r1-eth2\n")
        as2r1.cmd("ip link set dev as2r1-eth1 up")
        as2r1.cmd("ip link set dev as2r1-eth2 up")
        output(f"*** ERROR: {MODE_LABEL} recovery did not complete within timeout\n")
        return None

    if t_bgp_synced is None and bgp_is_fully_synced(network):
        t_bgp_synced = time.time()
        output(f"*** BGP fully synced after {t_bgp_synced - t_link_down:.2f}s\n")

    for _ in range(POST_RECOVERY_PROBES):
        packets_sent += 1
        success, _ = ping_once(source, ping_target)
        if not success:
            packet_loss_count += 1
        time.sleep(PING_INTERVAL)

    rtts = collect_rtts(source, ping_target, samples=3, timeout=1)
    recovery_rtts.extend(rtts)
    if rtts:
        post_recovery_avg_rtt = sum(rtts) / len(rtts)

    recovery_success_rate = None
    if recovery_successes + recovery_failures > 0:
        recovery_success_rate = recovery_successes / (recovery_successes + recovery_failures)

    post_recovery_jitter = None
    if len(recovery_rtts) > 1:
        post_recovery_jitter = statistics.pstdev(recovery_rtts)

    post_recovery_p50 = percentile(recovery_rtts, 0.50)
    post_recovery_p95 = percentile(recovery_rtts, 0.95)

    control_data_skew = None
    if t_bgp_synced is not None:
        control_data_skew = t_bgp_synced - t_stable_recovered

    rtt_inflation = None
    if baseline_avg_rtt is not None and post_recovery_avg_rtt is not None and baseline_avg_rtt > 0:
        rtt_inflation = post_recovery_avg_rtt / baseline_avg_rtt

    post_recovery_trace = trace_path_snapshot(source, ping_target)
    post_recovery_route = route_get_snapshot(source, ping_target)
    path_changed_after_recovery = pre_failure_trace["hops"] != post_recovery_trace["hops"]

    post_recovery_window_timeline = collect_post_recovery_window(source, ping_target, t_stable_recovered)
    post_recovery_window_summary = summarize_post_recovery_window(
        post_recovery_window_timeline,
        baseline_rtts,
        baseline_avg_rtt,
    )

    post_window_trace = trace_path_snapshot(source, ping_target)
    post_window_route = route_get_snapshot(source, ping_target)
    path_changed_during_window = post_recovery_trace["hops"] != post_window_trace["hops"]

    show_best_paths(network, "after failure")
    output("*** Restoring interface: as2r1-eth1 and as2r1-eth2\n")
    as2r1.cmd("ip link set dev as2r1-eth1 up")
    as2r1.cmd("ip link set dev as2r1-eth2 up")

    result = {
        "t_link_down": t_link_down,
        "t_ping_fail": t_ping_fail,
        "t_recovered": t_recovered,
        "t_bgp_synced": t_bgp_synced,
        "detection_time": t_ping_fail - t_link_down,
        "blackout_duration": t_recovered - t_ping_fail,
        "convergence_time": t_recovered - t_link_down,
        "stable_convergence_time": t_stable_recovered - t_link_down,
        "recovery_stability_window": t_stable_recovered - t_recovered,
        "time_to_first_success": (
            None if t_first_success_after_fail is None else t_first_success_after_fail - t_ping_fail
        ),
        "bgp_sync_time": None if t_bgp_synced is None else t_bgp_synced - t_link_down,
        "control_data_plane_skew": control_data_skew,
        "packet_loss_count": packet_loss_count,
        "packets_sent": packets_sent,
        "longest_loss_burst_packets": longest_loss_burst_packets,
        "longest_loss_burst_s": longest_loss_burst_packets * PING_INTERVAL,
        "recovery_flap_count": recovery_flap_count,
        "recovery_success_rate": recovery_success_rate,
        "baseline_avg_rtt": baseline_avg_rtt,
        "baseline_p50_rtt_ms": baseline_p50_rtt,
        "baseline_min_rtt_ms": baseline_min_rtt,
        "post_recovery_avg_rtt": post_recovery_avg_rtt,
        "post_recovery_jitter_ms": post_recovery_jitter,
        "post_recovery_p50_rtt_ms": post_recovery_p50,
        "post_recovery_p95_rtt_ms": post_recovery_p95,
        "rtt_inflation_ratio": rtt_inflation,
        "pre_failure_path_hops": pre_failure_trace["hops"],
        "post_recovery_path_hops": post_recovery_trace["hops"],
        "post_window_path_hops": post_window_trace["hops"],
        "pre_failure_hop_count": pre_failure_trace["hop_count"],
        "post_recovery_hop_count": post_recovery_trace["hop_count"],
        "post_window_hop_count": post_window_trace["hop_count"],
        "path_changed_after_recovery": path_changed_after_recovery,
        "path_changed_during_window": path_changed_during_window,
        "pre_failure_route_get": pre_failure_route,
        "post_recovery_route_get": post_recovery_route,
        "post_window_route_get": post_window_route,
        "pre_failure_traceroute": pre_failure_trace["raw"],
        "post_recovery_traceroute": post_recovery_trace["raw"],
        "post_window_traceroute": post_window_trace["raw"],
        "probe_timeline": timeline_sample(probe_timeline),
        "post_recovery_window_timeline": timeline_sample(post_recovery_window_timeline),
    }

    result.update(post_recovery_window_summary)
    return result


def save_results(result, dir="forward"):
    if dir == "reverse":
        ping_source = PING_SOURCE_BW
        ping_target = PING_TARGET_BW
    else:
        ping_source = PING_SOURCE_FR
        ping_target = PING_TARGET_FR

    log_file = os.path.join(TEMP_DIRECTORY, f"{RECOVERY_MODE}_convergence_{dir}.log")
    json_log_file = os.path.join(TEMP_DIRECTORY, f"{RECOVERY_MODE}_convergence_{dir}.json")
    persistent_log_file = os.path.join(RESULTS_DIRECTORY, f"{RECOVERY_MODE}_convergence_{dir}.log")
    persistent_json_log_file = os.path.join(RESULTS_DIRECTORY, f"{RECOVERY_MODE}_convergence_{dir}.json")

    os.makedirs(TEMP_DIRECTORY, exist_ok=True)
    os.makedirs(RESULTS_DIRECTORY, exist_ok=True)
    with open(log_file, "w", encoding="utf-8") as file:
        file.write(f"{MODE_LABEL} Recovery Test\n")
        file.write("=" * 40 + "\n")
        file.write(f"Test time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        file.write(f"Mode:      {MODE_LABEL}\n")
        file.write(f"Ping:      {ping_source} -> {ping_target}\n\n")

        if result is None:
            file.write("Result: FAILED\n")
            return

        file.write("Result: SUCCESS\n")
        file.write(f"Link failed:          as2r1-eth1 and as2r1-eth2 administratively down\n")
        file.write(f"Detection time:       {result['detection_time']:.2f}s\n")
        file.write(f"Blackout duration:    {result['blackout_duration']:.2f}s\n")
        file.write(f"Convergence time:     {result['convergence_time']:.2f}s\n")
        file.write(f"Stable convergence:   {result['stable_convergence_time']:.2f}s\n")
        if result["bgp_sync_time"] is None:
            file.write("BGP sync time:        N/A\n")
        else:
            file.write(f"BGP sync time:        {result['bgp_sync_time']:.2f}s\n")
        if result["control_data_plane_skew"] is None:
            file.write("Ctrl/Data skew:       N/A\n")
        else:
            file.write(f"Ctrl/Data skew:       {result['control_data_plane_skew']:.2f}s\n")
        file.write(f"Packet loss count:    {result['packet_loss_count']}\n")
        file.write(f"Packets sent:         {result['packets_sent']}\n")
        file.write(f"Longest loss burst:   {result['longest_loss_burst_packets']} packets ({result['longest_loss_burst_s']:.2f}s)\n")
        file.write(f"Recovery flaps:       {result['recovery_flap_count']}\n")
        if result["recovery_success_rate"] is not None:
            file.write(f"Recovery success:     {100.0 * result['recovery_success_rate']:.2f}%\n")
        if result["time_to_first_success"] is not None:
            file.write(f"First success lag:    {result['time_to_first_success']:.2f}s\n")
        file.write(f"Stability window:     {result['recovery_stability_window']:.2f}s\n")
        if result["baseline_avg_rtt"] is not None:
            file.write(f"Baseline RTT:         {result['baseline_avg_rtt']:.3f} ms\n")
        if result["post_recovery_avg_rtt"] is None:
            file.write("Post-recovery RTT:    N/A\n")
        else:
            file.write(f"Post-recovery RTT:    {result['post_recovery_avg_rtt']:.3f} ms\n")
        if result["post_recovery_jitter_ms"] is not None:
            file.write(f"Post-recovery jitter: {result['post_recovery_jitter_ms']:.3f} ms\n")
        if result["post_recovery_p95_rtt_ms"] is not None:
            file.write(f"Post-recovery p95:    {result['post_recovery_p95_rtt_ms']:.3f} ms\n")
        if result["rtt_inflation_ratio"] is not None:
            file.write(f"RTT inflation:        {result['rtt_inflation_ratio']:.3f}x\n")
        if result["post_recovery_window_avg_rtt_ms"] is not None:
            file.write(f"Window avg RTT:       {result['post_recovery_window_avg_rtt_ms']:.3f} ms\n")
        if result["post_recovery_window_second_phase_avg_rtt_ms"] is not None:
            file.write(
                f"Window phase2 RTT:    {result['post_recovery_window_second_phase_avg_rtt_ms']:.3f} ms\n"
            )
        if result["propagation_shift_indicator_ms"] is not None:
            file.write(f"Prop shift indicator: {result['propagation_shift_indicator_ms']:.3f} ms\n")
        if result["queueing_tail_indicator_ms"] is not None:
            file.write(f"Queue tail indicator: {result['queueing_tail_indicator_ms']:.3f} ms\n")
        file.write(f"Path changed:         {result['path_changed_after_recovery']}\n")
        file.write(f"Path changed in win:  {result['path_changed_during_window']}\n")

    with open(persistent_log_file, "w", encoding="utf-8") as file:
        file.write(f"{MODE_LABEL} Recovery Test\n")
        file.write("=" * 40 + "\n")
        file.write(f"Test time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        file.write(f"Mode:      {MODE_LABEL}\n")
        file.write(f"Ping:      {ping_source} -> {ping_target}\n\n")

        if result is None:
            file.write("Result: FAILED\n")
        else:
            file.write("Result: SUCCESS\n")
            file.write(f"Link failed:          as2r1-eth1 and as2r1-eth2 administratively down\n")
            file.write(f"Detection time:       {result['detection_time']:.2f}s\n")
            file.write(f"Blackout duration:    {result['blackout_duration']:.2f}s\n")
            file.write(f"Convergence time:     {result['convergence_time']:.2f}s\n")
            file.write(f"Stable convergence:   {result['stable_convergence_time']:.2f}s\n")
            if result["bgp_sync_time"] is None:
                file.write("BGP sync time:        N/A\n")
            else:
                file.write(f"BGP sync time:        {result['bgp_sync_time']:.2f}s\n")
            if result["control_data_plane_skew"] is None:
                file.write("Ctrl/Data skew:       N/A\n")
            else:
                file.write(f"Ctrl/Data skew:       {result['control_data_plane_skew']:.2f}s\n")
            file.write(f"Packet loss count:    {result['packet_loss_count']}\n")
            file.write(f"Packets sent:         {result['packets_sent']}\n")
            file.write(f"Longest loss burst:   {result['longest_loss_burst_packets']} packets ({result['longest_loss_burst_s']:.2f}s)\n")
            file.write(f"Recovery flaps:       {result['recovery_flap_count']}\n")
            if result["recovery_success_rate"] is not None:
                file.write(f"Recovery success:     {100.0 * result['recovery_success_rate']:.2f}%\n")
            if result["time_to_first_success"] is not None:
                file.write(f"First success lag:    {result['time_to_first_success']:.2f}s\n")
            file.write(f"Stability window:     {result['recovery_stability_window']:.2f}s\n")
            if result["baseline_avg_rtt"] is not None:
                file.write(f"Baseline RTT:         {result['baseline_avg_rtt']:.3f} ms\n")
            if result["post_recovery_avg_rtt"] is None:
                file.write("Post-recovery RTT:    N/A\n")
            else:
                file.write(f"Post-recovery RTT:    {result['post_recovery_avg_rtt']:.3f} ms\n")
            if result["post_recovery_jitter_ms"] is not None:
                file.write(f"Post-recovery jitter: {result['post_recovery_jitter_ms']:.3f} ms\n")
            if result["post_recovery_p95_rtt_ms"] is not None:
                file.write(f"Post-recovery p95:    {result['post_recovery_p95_rtt_ms']:.3f} ms\n")
            if result["rtt_inflation_ratio"] is not None:
                file.write(f"RTT inflation:        {result['rtt_inflation_ratio']:.3f}x\n")
            if result["post_recovery_window_avg_rtt_ms"] is not None:
                file.write(f"Window avg RTT:       {result['post_recovery_window_avg_rtt_ms']:.3f} ms\n")
            if result["post_recovery_window_second_phase_avg_rtt_ms"] is not None:
                file.write(
                    f"Window phase2 RTT:    {result['post_recovery_window_second_phase_avg_rtt_ms']:.3f} ms\n"
                )
            if result["propagation_shift_indicator_ms"] is not None:
                file.write(f"Prop shift indicator: {result['propagation_shift_indicator_ms']:.3f} ms\n")
            if result["queueing_tail_indicator_ms"] is not None:
                file.write(f"Queue tail indicator: {result['queueing_tail_indicator_ms']:.3f} ms\n")
            file.write(f"Path changed:         {result['path_changed_after_recovery']}\n")
            file.write(f"Path changed in win:  {result['path_changed_during_window']}\n")

    payload = {
        "test_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": MODE_LABEL,
        "direction": dir,
        "ping_source": ping_source,
        "ping_target": ping_target,
        "result": "SUCCESS" if result is not None else "FAILED",
    }
    if result is not None:
        payload.update(
            {
                "failure_event": "as2r1-eth1 and as2r1-eth2 administratively down",
                "detection_time_s": round(result["detection_time"], 2),
                "blackout_duration_s": round(result["blackout_duration"], 2),
                "convergence_time_s": round(result["convergence_time"], 2),
                "stable_convergence_time_s": round(result["stable_convergence_time"], 2),
                "recovery_stability_window_s": round(result["recovery_stability_window"], 2),
                "time_to_first_success_s": (
                    None
                    if result["time_to_first_success"] is None
                    else round(result["time_to_first_success"], 2)
                ),
                "bgp_sync_time_s": (
                    None
                    if result["bgp_sync_time"] is None
                    else round(result["bgp_sync_time"], 2)
                ),
                "control_data_plane_skew_s": (
                    None
                    if result["control_data_plane_skew"] is None
                    else round(result["control_data_plane_skew"], 2)
                ),
                "packet_loss_count": result["packet_loss_count"],
                "packets_sent": result["packets_sent"],
                "longest_loss_burst_packets": result["longest_loss_burst_packets"],
                "longest_loss_burst_s": round(result["longest_loss_burst_s"], 2),
                "recovery_flap_count": result["recovery_flap_count"],
                "recovery_success_rate": (
                    None
                    if result["recovery_success_rate"] is None
                    else round(result["recovery_success_rate"], 4)
                ),
                "baseline_avg_rtt_ms": (
                    None
                    if result["baseline_avg_rtt"] is None
                    else round(result["baseline_avg_rtt"], 3)
                ),
                "baseline_p50_rtt_ms": (
                    None
                    if result["baseline_p50_rtt_ms"] is None
                    else round(result["baseline_p50_rtt_ms"], 3)
                ),
                "baseline_min_rtt_ms": (
                    None
                    if result["baseline_min_rtt_ms"] is None
                    else round(result["baseline_min_rtt_ms"], 3)
                ),
                "post_recovery_avg_rtt_ms": (
                    None
                    if result["post_recovery_avg_rtt"] is None
                    else round(result["post_recovery_avg_rtt"], 3)
                ),
                "post_recovery_jitter_ms": (
                    None
                    if result["post_recovery_jitter_ms"] is None
                    else round(result["post_recovery_jitter_ms"], 3)
                ),
                "post_recovery_p50_rtt_ms": (
                    None
                    if result["post_recovery_p50_rtt_ms"] is None
                    else round(result["post_recovery_p50_rtt_ms"], 3)
                ),
                "post_recovery_p95_rtt_ms": (
                    None
                    if result["post_recovery_p95_rtt_ms"] is None
                    else round(result["post_recovery_p95_rtt_ms"], 3)
                ),
                "rtt_inflation_ratio": (
                    None
                    if result["rtt_inflation_ratio"] is None
                    else round(result["rtt_inflation_ratio"], 3)
                ),
                "post_recovery_window_s": round(result["post_recovery_window_s"], 3),
                "post_recovery_window_probe_interval_s": round(
                    result["post_recovery_window_probe_interval_s"],
                    3,
                ),
                "post_recovery_window_phase_split_s": round(
                    result["post_recovery_window_phase_split_s"],
                    3,
                ),
                "post_recovery_window_packets_sent": result["post_recovery_window_packets_sent"],
                "post_recovery_window_packet_loss_count": result[
                    "post_recovery_window_packet_loss_count"
                ],
                "post_recovery_window_success_rate": (
                    None
                    if result["post_recovery_window_success_rate"] is None
                    else round(result["post_recovery_window_success_rate"], 4)
                ),
                "post_recovery_window_avg_rtt_ms": (
                    None
                    if result["post_recovery_window_avg_rtt_ms"] is None
                    else round(result["post_recovery_window_avg_rtt_ms"], 3)
                ),
                "post_recovery_window_p50_rtt_ms": (
                    None
                    if result["post_recovery_window_p50_rtt_ms"] is None
                    else round(result["post_recovery_window_p50_rtt_ms"], 3)
                ),
                "post_recovery_window_p95_rtt_ms": (
                    None
                    if result["post_recovery_window_p95_rtt_ms"] is None
                    else round(result["post_recovery_window_p95_rtt_ms"], 3)
                ),
                "post_recovery_window_jitter_ms": (
                    None
                    if result["post_recovery_window_jitter_ms"] is None
                    else round(result["post_recovery_window_jitter_ms"], 3)
                ),
                "post_recovery_window_min_rtt_ms": (
                    None
                    if result["post_recovery_window_min_rtt_ms"] is None
                    else round(result["post_recovery_window_min_rtt_ms"], 3)
                ),
                "post_recovery_window_max_rtt_ms": (
                    None
                    if result["post_recovery_window_max_rtt_ms"] is None
                    else round(result["post_recovery_window_max_rtt_ms"], 3)
                ),
                "post_recovery_window_first_phase_avg_rtt_ms": (
                    None
                    if result["post_recovery_window_first_phase_avg_rtt_ms"] is None
                    else round(result["post_recovery_window_first_phase_avg_rtt_ms"], 3)
                ),
                "post_recovery_window_second_phase_avg_rtt_ms": (
                    None
                    if result["post_recovery_window_second_phase_avg_rtt_ms"] is None
                    else round(result["post_recovery_window_second_phase_avg_rtt_ms"], 3)
                ),
                "propagation_shift_indicator_ms": (
                    None
                    if result["propagation_shift_indicator_ms"] is None
                    else round(result["propagation_shift_indicator_ms"], 3)
                ),
                "queueing_tail_indicator_ms": (
                    None
                    if result["queueing_tail_indicator_ms"] is None
                    else round(result["queueing_tail_indicator_ms"], 3)
                ),
                "second_phase_rtt_inflation_ratio": (
                    None
                    if result["second_phase_rtt_inflation_ratio"] is None
                    else round(result["second_phase_rtt_inflation_ratio"], 3)
                ),
                "pre_failure_path_hops": result["pre_failure_path_hops"],
                "post_recovery_path_hops": result["post_recovery_path_hops"],
                "post_window_path_hops": result["post_window_path_hops"],
                "pre_failure_hop_count": result["pre_failure_hop_count"],
                "post_recovery_hop_count": result["post_recovery_hop_count"],
                "post_window_hop_count": result["post_window_hop_count"],
                "path_changed_after_recovery": result["path_changed_after_recovery"],
                "path_changed_during_window": result["path_changed_during_window"],
                "pre_failure_route_get": result["pre_failure_route_get"],
                "post_recovery_route_get": result["post_recovery_route_get"],
                "post_window_route_get": result["post_window_route_get"],
                "pre_failure_traceroute": result["pre_failure_traceroute"],
                "post_recovery_traceroute": result["post_recovery_traceroute"],
                "post_window_traceroute": result["post_window_traceroute"],
                "probe_timeline": result["probe_timeline"],
                "post_recovery_window_timeline": result["post_recovery_window_timeline"],
            }
        )

    with open(json_log_file, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)
    with open(persistent_json_log_file, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)

    return {
        "log_file": log_file,
        "json_log_file": json_log_file,
        "persistent_log_file": persistent_log_file,
        "persistent_json_log_file": persistent_json_log_file,
    }


if __name__ == "__main__":
    setLogLevel("info")

    topology = Topology()
    network = Mininet(topo=topology, link=TCLink, autoSetMacs=False)
    network.start()

    if not wait_for_initial_convergence(network, dir="forward"):
        output("*** ERROR: Initial BGP convergence timed out\n")
        show_as1_as3_as4_state(network, "initial timeout")
        show_ixp2_side_state("initial timeout")
        save_results(None, dir="forward")
        network.stop()
        sys.exit(1)

    result = run_test(network, dir="forward")
    forward_paths = save_results(result, dir="forward")

    if result is not None:
        output("\n*** Summary\n")
        output(f"*** Mode:              {MODE_LABEL}\n")
        output(f"*** Direction:         forward ({PING_SOURCE_FR} -> {PING_TARGET_FR})\n")
        output(f"*** Detection time:    {result['detection_time']:.2f}s\n")
        output(f"*** Blackout duration: {result['blackout_duration']:.2f}s\n")
        output(f"*** Convergence time:  {result['convergence_time']:.2f}s\n")
        output(f"*** Stable conv time:  {result['stable_convergence_time']:.2f}s\n")
        if result["bgp_sync_time"] is not None:
            output(f"*** BGP sync time:     {result['bgp_sync_time']:.2f}s\n")
        if result["control_data_plane_skew"] is not None:
            output(f"*** Ctrl/data skew:    {result['control_data_plane_skew']:.2f}s\n")
        output(f"*** Packet loss:       {result['packet_loss_count']}\n")
        output(f"*** Loss burst max:    {result['longest_loss_burst_packets']} pkts\n")
        output(f"*** Recovery flaps:    {result['recovery_flap_count']}\n")
        output(f"*** Packets sent:      {result['packets_sent']}\n")
        if result["recovery_success_rate"] is not None:
            output(f"*** Recovery success:  {100.0 * result['recovery_success_rate']:.2f}%\n")
        if result["baseline_avg_rtt"] is not None:
            output(f"*** Baseline RTT:      {result['baseline_avg_rtt']:.3f} ms\n")
        if result["post_recovery_avg_rtt"] is not None:
            output(f"*** Post-recovery RTT: {result['post_recovery_avg_rtt']:.3f} ms\n")
        if result["post_recovery_jitter_ms"] is not None:
            output(f"*** Post-recovery jitter: {result['post_recovery_jitter_ms']:.3f} ms\n")
        if result["post_recovery_window_avg_rtt_ms"] is not None:
            output(f"*** Window avg RTT:     {result['post_recovery_window_avg_rtt_ms']:.3f} ms\n")
        if result["post_recovery_window_second_phase_avg_rtt_ms"] is not None:
            output(
                f"*** Window phase2 RTT:  {result['post_recovery_window_second_phase_avg_rtt_ms']:.3f} ms\n"
            )
        if result["propagation_shift_indicator_ms"] is not None:
            output(f"*** Prop shift ind:     {result['propagation_shift_indicator_ms']:.3f} ms\n")
        if result["queueing_tail_indicator_ms"] is not None:
            output(f"*** Queue tail ind:     {result['queueing_tail_indicator_ms']:.3f} ms\n")
        output(f"*** Path changed:       {result['path_changed_after_recovery']}\n")
        output(f"*** Path changed win:   {result['path_changed_during_window']}\n")
        output(f"*** Log saved to {forward_paths['log_file']}\n")
        output(f"*** JSON saved to {forward_paths['json_log_file']}\n")
        output(f"*** Persistent log:    {forward_paths['persistent_log_file']}\n")
        output(f"*** Persistent JSON:   {forward_paths['persistent_json_log_file']}\n")


    if not wait_for_reverse_bgp_ready(network, timeout=INITIAL_WAIT):
        output("*** ERROR: Reverse BGP routes not ready before reverse test\n")
        show_best_paths(network, "pre-reverse")
        save_results(None, dir="reverse")
        network.stop()
        sys.exit(1)

    if not wait_for_initial_convergence(network, dir="reverse"):
        output("*** ERROR: Initial BGP convergence timed out\n")
        show_as1_as3_as4_state(network, "initial timeout")
        show_ixp2_side_state("initial timeout")
        save_results(None, dir="reverse")
        network.stop()
        sys.exit(1)

    if not wait_for_preferred_paths(network, timeout=INITIAL_WAIT):
        output("*** ERROR: Preferred AS2 paths not restored before reverse test\n")
        show_best_paths(network, "pre-reverse")
        save_results(None, dir="reverse")
        network.stop()
        sys.exit(1)

    if not wait_for_initial_convergence(network, dir="reverse"):
        output("*** ERROR: Reverse data-plane connectivity not stable after path restore\n")
        show_as1_as3_as4_state(network, "reverse pre-check")
        show_ixp2_side_state("reverse pre-check")
        save_results(None, dir="reverse")
        network.stop()
        sys.exit(1)

    result = run_test(network, dir="reverse")
    reverse_paths = save_results(result, dir="reverse")

    if result is not None:
        output("\n*** Summary\n")
        output(f"*** Mode:              {MODE_LABEL}\n")
        output(f"*** Direction:         reverse ({PING_SOURCE_BW} -> {PING_TARGET_BW})\n")
        output(f"*** Detection time:    {result['detection_time']:.2f}s\n")
        output(f"*** Blackout duration: {result['blackout_duration']:.2f}s\n")
        output(f"*** Convergence time:  {result['convergence_time']:.2f}s\n")
        output(f"*** Stable conv time:  {result['stable_convergence_time']:.2f}s\n")
        if result["bgp_sync_time"] is not None:
            output(f"*** BGP sync time:     {result['bgp_sync_time']:.2f}s\n")
        if result["control_data_plane_skew"] is not None:
            output(f"*** Ctrl/data skew:    {result['control_data_plane_skew']:.2f}s\n")
        output(f"*** Packet loss:       {result['packet_loss_count']}\n")
        output(f"*** Loss burst max:    {result['longest_loss_burst_packets']} pkts\n")
        output(f"*** Recovery flaps:    {result['recovery_flap_count']}\n")
        output(f"*** Packets sent:      {result['packets_sent']}\n")
        if result["recovery_success_rate"] is not None:
            output(f"*** Recovery success:  {100.0 * result['recovery_success_rate']:.2f}%\n")
        if result["baseline_avg_rtt"] is not None:
            output(f"*** Baseline RTT:      {result['baseline_avg_rtt']:.3f} ms\n")
        if result["post_recovery_avg_rtt"] is not None:
            output(f"*** Post-recovery RTT: {result['post_recovery_avg_rtt']:.3f} ms\n")
        if result["post_recovery_jitter_ms"] is not None:
            output(f"*** Post-recovery jitter: {result['post_recovery_jitter_ms']:.3f} ms\n")
        if result["post_recovery_window_avg_rtt_ms"] is not None:
            output(f"*** Window avg RTT:     {result['post_recovery_window_avg_rtt_ms']:.3f} ms\n")
        if result["post_recovery_window_second_phase_avg_rtt_ms"] is not None:
            output(
                f"*** Window phase2 RTT:  {result['post_recovery_window_second_phase_avg_rtt_ms']:.3f} ms\n"
            )
        if result["propagation_shift_indicator_ms"] is not None:
            output(f"*** Prop shift ind:     {result['propagation_shift_indicator_ms']:.3f} ms\n")
        if result["queueing_tail_indicator_ms"] is not None:
            output(f"*** Queue tail ind:     {result['queueing_tail_indicator_ms']:.3f} ms\n")
        output(f"*** Path changed:       {result['path_changed_after_recovery']}\n")
        output(f"*** Path changed win:   {result['path_changed_during_window']}\n")
        output(f"*** Log saved to {reverse_paths['log_file']}\n")
        output(f"*** JSON saved to {reverse_paths['json_log_file']}\n")
        output(f"*** Persistent log:    {reverse_paths['persistent_log_file']}\n")
        output(f"*** Persistent JSON:   {reverse_paths['persistent_json_log_file']}\n")
    else:
        output("*** ERROR: Reverse test failed\n")

    network.stop()
