import os
import sys
import time
import json
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
SWITCH_STDOUT_FILE = os.path.join(
    TEMP_DIRECTORY,
    "p4_switch",
    "ixp1s1",
    "ixp1s1-stdout.txt",
)
SWITCH_BMV2_LOG_FILE = os.path.join(
    TEMP_DIRECTORY,
    "p4_switch",
    "ixp1s1",
    "ixp1s1-bmv2.txt",
)

PING_SOURCE = "as1h1"
PING_TARGET = "10.4.0.101"
REVERSE_PING_SOURCE = "as4h1"
REVERSE_PING_TARGET = "10.1.0.101"
INITIAL_WAIT = 30
MAX_RECONVERGENCE_WAIT = 30
PING_INTERVAL = 1
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


def _format_metrics(result, failure_event):
    return {
        "failure_event": failure_event,
        "detection_time_s": round(result["detection_time"], 2),
        "blackout_duration_s": round(result["blackout_duration"], 2),
        "convergence_time_s": round(result["convergence_time"], 2),
        "bgp_sync_time_s": (
            None
            if result["bgp_sync_time"] is None
            else round(result["bgp_sync_time"], 2)
        ),
        "packet_loss_count": result["packet_loss_count"],
        "packets_sent": result.get("packets_sent"),
        "post_recovery_avg_rtt_ms": (
            None
            if result["post_recovery_avg_rtt"] is None
            else round(result["post_recovery_avg_rtt"], 3)
        ),
    }


def _write_metrics_block(file, title, result, failure_event):
    file.write(f"\n{title}\n")
    file.write(f"Link failed:          {failure_event}\n")
    file.write(f"Detection time:       {result['detection_time']:.2f}s\n")
    file.write(f"Blackout duration:    {result['blackout_duration']:.2f}s\n")
    file.write(f"Convergence time:     {result['convergence_time']:.2f}s\n")
    if result["bgp_sync_time"] is None:
        file.write("BGP sync time:        N/A\n")
    else:
        file.write(f"BGP sync time:        {result['bgp_sync_time']:.2f}s\n")
    file.write(f"Packet loss count:    {result['packet_loss_count']}\n")
    file.write(f"Packets sent:         {result.get('packets_sent', 'N/A')}\n")
    if result["post_recovery_avg_rtt"] is None:
        file.write("Post-recovery RTT:    N/A\n")
    else:
        file.write(f"Post-recovery RTT:    {result['post_recovery_avg_rtt']:.3f} ms\n")


def wait_for_initial_convergence(network):
    output(f"*** Waiting up to {INITIAL_WAIT}s for initial BGP convergence...\n")
    source = network.getNodeByName(PING_SOURCE)
    start = time.time()
    while time.time() - start < INITIAL_WAIT:
        success, _ = ping_once(source, PING_TARGET)
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


def as4_best_path_uses_as3(network):
    as4r1 = network.getNodeByName("as4r1")
    bgp_output = as4r1.cmd('vtysh -c "show bgp ipv4 unicast 10.1.0.0/24"')
    return "10.0.2.1 from 10.0.2.1" in bgp_output and "best" in bgp_output


def bgp_is_fully_synced(network):
    return as1_best_path_uses_as3(network) and as4_best_path_uses_as3(network)


def show_reconvergence_state(network, label):
    output(f"\n*** [{label}] Reconvergence state\n")
    for node_name in ["as1r1", "as3r1", "as4r1"]:
        node = network.getNodeByName(node_name)
        output(f"*** [{label}] {node_name} summary\n")
        output(node.cmd('vtysh -c "show bgp summary"'))
        if node_name in ["as1r1", "as4r1"]:
            output(f"*** [{label}] {node_name} kernel route snapshot\n")
            output(node.cmd("ip route | egrep '10.4.0.0/24|10.1.0.0/24|10.0.1.0/24|10.0.2.0/24' || true"))


def show_as1_as3_state(network, label):
    output(f"\n*** [{label}] AS1-AS3 neighbor state\n")
    for node_name in ["as1r1", "as3r1"]:
        node = network.getNodeByName(node_name)
        output(f"*** [{label}] {node_name} bgp summary\n")
        output(node.cmd('vtysh -c "show bgp summary"'))
        output(f"*** [{label}] {node_name} ip neigh\n")
        output(node.cmd("ip neigh"))
        if node_name == "as1r1":
            output(f"*** [{label}] {node_name} ping 10.0.0.3\n")
            output(node.cmd("ping -c 2 -W 1 10.0.0.3"))
        else:
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

def run_test_for_pair(network, source_name, target_ip, label, link_down_intfs, loss_until_bgp_sync=False):
    source = network.getNodeByName(source_name)
    as2r1 = network.getNodeByName("as2r1")

    packets_sent = 0

    success, _ = ping_once(source, target_ip)
    packets_sent += 1
    if not success:
        output(f"*** ERROR: No initial connectivity for {label}\n")
        return None

    t_link_down = time.time()
    for intf in link_down_intfs:
        output(f"*** Bringing down interface: {intf}\n")
        as2r1.cmd(f"ip link set dev {intf} down")

    t_ping_fail = None
    packet_loss_count = 0
    while time.time() - t_link_down < 30:
        success, _ = ping_once(source, target_ip)
        packets_sent += 1
        if not success or (loss_until_bgp_sync and not bgp_is_fully_synced(network)):
            t_ping_fail = time.time()
            packet_loss_count += 1
            output(f"*** Connectivity lost after {t_ping_fail - t_link_down:.2f}s\n")
            break
        time.sleep(PING_INTERVAL)

    if t_ping_fail is None:
        output("*** WARNING: Connectivity never dropped after link failure\n")
        for intf in link_down_intfs:
            output(f"*** Restoring interface: {intf}\n")
            as2r1.cmd(f"ip link set dev {intf} up")
        return None

    t_recovered = None
    post_recovery_avg_rtt = None
    t_bgp_synced = None
    deadline = time.time() + MAX_RECONVERGENCE_WAIT
    output(f"*** Waiting for {MODE_LABEL} recovery...\n")
    while time.time() < deadline:
        success, rtt_ms = ping_once(source, target_ip)
        packets_sent += 1
        if t_bgp_synced is None and bgp_is_fully_synced(network):
            t_bgp_synced = time.time()
            output(f"*** BGP fully synced after {t_bgp_synced - t_link_down:.2f}s\n")
        if success:
            if loss_until_bgp_sync and t_bgp_synced is None:
                packet_loss_count += 1
                time.sleep(PING_INTERVAL)
                continue
            if t_recovered is None:
                t_recovered = time.time()
                output(f"*** Recovered after {t_recovered - t_link_down:.2f}s\n")
            if RECOVERY_MODE != "sdx" or t_bgp_synced is not None:
                break
            time.sleep(PING_INTERVAL)
            continue
        packet_loss_count += 1
        time.sleep(PING_INTERVAL)

    if t_recovered is None:
        show_as1_as3_post_failure_probes(network, "recovery timeout")
        show_switch_side_state(network, "recovery timeout")
        show_reconvergence_state(network, "recovery timeout")
        show_best_paths(network, "recovery timeout")
        for intf in link_down_intfs:
            output(f"*** Restoring interface: {intf}\n")
            as2r1.cmd(f"ip link set dev {intf} up")
        output(f"*** ERROR: {MODE_LABEL} recovery did not complete within timeout\n")
        return None

    if t_bgp_synced is None and bgp_is_fully_synced(network):
        t_bgp_synced = time.time()
        output(f"*** BGP fully synced after {t_bgp_synced - t_link_down:.2f}s\n")

    rtts = collect_rtts(source, target_ip, samples=3, timeout=1)
    packets_sent += 3
    if rtts:
        post_recovery_avg_rtt = sum(rtts) / len(rtts)

    show_best_paths(network, "after failure")
    for intf in link_down_intfs:
        output(f"*** Restoring interface: {intf}\n")
        as2r1.cmd(f"ip link set dev {intf} up")

    return {
        "t_link_down": t_link_down,
        "t_ping_fail": t_ping_fail,
        "t_recovered": t_recovered,
        "t_bgp_synced": t_bgp_synced,
        "detection_time": t_ping_fail - t_link_down,
        "blackout_duration": t_recovered - t_ping_fail,
        "convergence_time": t_recovered - t_link_down,
        "bgp_sync_time": None if t_bgp_synced is None else t_bgp_synced - t_link_down,
        "packet_loss_count": packet_loss_count,
        "post_recovery_avg_rtt": post_recovery_avg_rtt,
        "packets_sent": packets_sent,
    }


def save_results(result_forward, result_reverse):
    failure_event = "as2r1-eth1 administratively down"
    os.makedirs(TEMP_DIRECTORY, exist_ok=True)
    os.makedirs(RESULTS_DIRECTORY, exist_ok=True)
    with open(LOG_FILE, "w", encoding="utf-8") as file:
        file.write(f"{MODE_LABEL} Recovery Test\n")
        file.write("=" * 40 + "\n")
        file.write(f"Test time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        file.write(f"Mode:      {MODE_LABEL}\n")
        file.write(f"Ping:      {PING_SOURCE} -> {PING_TARGET}\n")
        file.write(f"Ping:      {REVERSE_PING_SOURCE} -> {REVERSE_PING_TARGET}\n\n")

        if result_forward is None or result_reverse is None:
            file.write("Result: FAILED\n")
            return

        file.write("Result: SUCCESS\n")
        _write_metrics_block(file, "AS1 -> AS4 Metrics", result_forward, failure_event)
        _write_metrics_block(file, "AS4 -> AS1 Metrics", result_reverse, failure_event)

    with open(PERSISTENT_LOG_FILE, "w", encoding="utf-8") as file:
        file.write(f"{MODE_LABEL} Recovery Test\n")
        file.write("=" * 40 + "\n")
        file.write(f"Test time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        file.write(f"Mode:      {MODE_LABEL}\n")
        file.write(f"Ping:      {PING_SOURCE} -> {PING_TARGET}\n")
        file.write(f"Ping:      {REVERSE_PING_SOURCE} -> {REVERSE_PING_TARGET}\n\n")

        if result_forward is None or result_reverse is None:
            file.write("Result: FAILED\n")
        else:
            file.write("Result: SUCCESS\n")
            _write_metrics_block(file, "AS1 -> AS4 Metrics", result_forward, failure_event)
            _write_metrics_block(file, "AS4 -> AS1 Metrics", result_reverse, failure_event)

    payload = {
        "test_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": MODE_LABEL,
        "ping_source": PING_SOURCE,
        "ping_target": PING_TARGET,
        "reverse_ping_source": REVERSE_PING_SOURCE,
        "reverse_ping_target": REVERSE_PING_TARGET,
        "result": "SUCCESS" if result_forward is not None and result_reverse is not None else "FAILED",
    }
    if result_forward is not None:
        metrics_forward = _format_metrics(result_forward, failure_event)
        payload.update(metrics_forward)
        payload["as1_to_as4"] = metrics_forward
    if result_reverse is not None:
        payload["as4_to_as1"] = _format_metrics(result_reverse, failure_event)

    with open(JSON_LOG_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)
    with open(PERSISTENT_JSON_LOG_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)


if __name__ == "__main__":
    setLogLevel("info")

    topology = Topology()
    network = Mininet(topo=topology, link=TCLink, autoSetMacs=False)
    network.start()

    if not wait_for_initial_convergence(network):
        output("*** ERROR: Initial BGP convergence timed out\n")
        show_as1_as3_state(network, "initial timeout")
        save_results(None)
        network.stop()
        sys.exit(1)

    forward_result = run_test_for_pair(
        network,
        PING_SOURCE,
        PING_TARGET,
        "AS1 -> AS4",
        ["as2r1-eth1"],
    )
    reverse_result = run_test_for_pair(
        network,
        REVERSE_PING_SOURCE,
        REVERSE_PING_TARGET,
        "AS4 -> AS1",
        ["as2r1-eth1"],
        loss_until_bgp_sync=True,
    )
    save_results(forward_result, reverse_result)

    if forward_result is not None and reverse_result is not None:
        output("\n*** Summary\n")
        output(f"*** Mode:              {MODE_LABEL}\n")
        output("*** AS1 -> AS4\n")
        output(f"*** Detection time:    {forward_result['detection_time']:.2f}s\n")
        output(f"*** Blackout duration: {forward_result['blackout_duration']:.2f}s\n")
        output(f"*** Convergence time:  {forward_result['convergence_time']:.2f}s\n")
        if forward_result["bgp_sync_time"] is not None:
            output(f"*** BGP sync time:     {forward_result['bgp_sync_time']:.2f}s\n")
        output(f"*** Packet loss:       {forward_result['packet_loss_count']}\n")
        if forward_result["post_recovery_avg_rtt"] is not None:
            output(f"*** Post-recovery RTT: {forward_result['post_recovery_avg_rtt']:.3f} ms\n")
        output("*** AS4 -> AS1\n")
        output(f"*** Detection time:    {reverse_result['detection_time']:.2f}s\n")
        output(f"*** Blackout duration: {reverse_result['blackout_duration']:.2f}s\n")
        output(f"*** Convergence time:  {reverse_result['convergence_time']:.2f}s\n")
        if reverse_result["bgp_sync_time"] is not None:
            output(f"*** BGP sync time:     {reverse_result['bgp_sync_time']:.2f}s\n")
        output(f"*** Packet loss:       {reverse_result['packet_loss_count']}\n")
        if reverse_result["post_recovery_avg_rtt"] is not None:
            output(f"*** Post-recovery RTT: {reverse_result['post_recovery_avg_rtt']:.3f} ms\n")
        output(f"*** Log saved to {LOG_FILE}\n")
        output(f"*** JSON saved to {JSON_LOG_FILE}\n")
        output(f"*** Persistent log:    {PERSISTENT_LOG_FILE}\n")
        output(f"*** Persistent JSON:   {PERSISTENT_JSON_LOG_FILE}\n")

    network.stop()
