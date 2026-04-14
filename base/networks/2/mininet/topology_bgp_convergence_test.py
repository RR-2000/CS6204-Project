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

PING_SOURCE_FR = "as1h1"
PING_TARGET_FR = "10.4.0.101"
PING_SOURCE_BW = "as4h1"
PING_TARGET_BW = "10.1.0.101"
INITIAL_WAIT = 30
MAX_RECONVERGENCE_WAIT = 30
PING_INTERVAL = 0.05
POST_RECOVERY_PROBES = 0
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
    return "10.0.2.1 from 10.0.2.1" in bgp_output and "best" in bgp_output


def as4_best_path_uses_as2(network):
    as4r1 = network.getNodeByName("as4r1")
    bgp_output = as4r1.cmd('vtysh -c "show bgp ipv4 unicast 10.1.0.0/24"')
    return "10.0.1.1 from 10.0.1.1" in bgp_output and "best" in bgp_output


def bgp_is_fully_synced(network):
    return as1_best_path_uses_as3(network) and as4_best_path_uses_as3(network)


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

    success, _ = ping_once(source, ping_target)
    if not success:
        output("*** ERROR: No initial connectivity\n")
        return None

    output("*** Bringing down interface: as2r1-eth1\n")
    t_link_down = time.time()
    as2r1.cmd("ip link set dev as2r1-eth1 down")

    t_ping_fail = None
    packet_loss_count = 0
    packets_sent = 0
    while time.time() - t_link_down < 30:
        packets_sent += 1
        success, _ = ping_once(source, ping_target)
        if not success:
            t_ping_fail = time.time()
            packet_loss_count += 1
            output(f"*** Connectivity lost after {t_ping_fail - t_link_down:.2f}s\n")
            break
        time.sleep(PING_INTERVAL)

    if t_ping_fail is None:
        output("*** WARNING: Connectivity never dropped after link failure\n")
        output("*** Restoring interface: as2r1-eth1\n")
        as2r1.cmd("ip link set dev as2r1-eth1 up")
        return None

    t_recovered = None
    post_recovery_avg_rtt = None
    t_bgp_synced = None
    deadline = time.time() + MAX_RECONVERGENCE_WAIT
    output(f"*** Waiting for {MODE_LABEL} recovery...\n")
    while time.time() < deadline:
        packets_sent += 1
        success, rtt_ms = ping_once(source, ping_target)
        if t_bgp_synced is None and bgp_is_fully_synced(network):
            t_bgp_synced = time.time()
            output(f"*** BGP fully synced after {t_bgp_synced - t_link_down:.2f}s\n")
        if success:
            if t_recovered is None:
                t_recovered = time.time()
                output(f"*** Recovered after {t_recovered - t_link_down:.2f}s\n")
            if loss_until_bgp_sync and t_bgp_synced is None:
                time.sleep(PING_INTERVAL)
                continue
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
        output("*** Restoring interface: as2r1-eth1\n")
        as2r1.cmd("ip link set dev as2r1-eth1 up")
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
    if rtts:
        post_recovery_avg_rtt = sum(rtts) / len(rtts)

    show_best_paths(network, "after failure")
    output("*** Restoring interface: as2r1-eth1\n")
    as2r1.cmd("ip link set dev as2r1-eth1 up")

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
        "packets_sent": packets_sent,
        "post_recovery_avg_rtt": post_recovery_avg_rtt,
    }


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
        file.write(f"Link failed:          as2r1-eth1 administratively down\n")
        file.write(f"Detection time:       {result['detection_time']:.2f}s\n")
        file.write(f"Blackout duration:    {result['blackout_duration']:.2f}s\n")
        file.write(f"Convergence time:     {result['convergence_time']:.2f}s\n")
        if result["bgp_sync_time"] is None:
            file.write("BGP sync time:        N/A\n")
        else:
            file.write(f"BGP sync time:        {result['bgp_sync_time']:.2f}s\n")
        file.write(f"Packet loss count:    {result['packet_loss_count']}\n")
        file.write(f"Packets sent:         {result['packets_sent']}\n")
        if result["post_recovery_avg_rtt"] is None:
            file.write("Post-recovery RTT:    N/A\n")
        else:
            file.write(f"Post-recovery RTT:    {result['post_recovery_avg_rtt']:.3f} ms\n")

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
            file.write(f"Link failed:          as2r1-eth1 administratively down\n")
            file.write(f"Detection time:       {result['detection_time']:.2f}s\n")
            file.write(f"Blackout duration:    {result['blackout_duration']:.2f}s\n")
            file.write(f"Convergence time:     {result['convergence_time']:.2f}s\n")
            if result["bgp_sync_time"] is None:
                file.write("BGP sync time:        N/A\n")
            else:
                file.write(f"BGP sync time:        {result['bgp_sync_time']:.2f}s\n")
            file.write(f"Packet loss count:    {result['packet_loss_count']}\n")
            file.write(f"Packets sent:         {result['packets_sent']}\n")
            if result["post_recovery_avg_rtt"] is None:
                file.write("Post-recovery RTT:    N/A\n")
            else:
                file.write(f"Post-recovery RTT:    {result['post_recovery_avg_rtt']:.3f} ms\n")

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
                "failure_event": "as2r1-eth1 administratively down",
                "detection_time_s": round(result["detection_time"], 2),
                "blackout_duration_s": round(result["blackout_duration"], 2),
                "convergence_time_s": round(result["convergence_time"], 2),
                "bgp_sync_time_s": (
                    None
                    if result["bgp_sync_time"] is None
                    else round(result["bgp_sync_time"], 2)
                ),
                "packet_loss_count": result["packet_loss_count"],
                "packets_sent": result["packets_sent"],
                "post_recovery_avg_rtt_ms": (
                    None
                    if result["post_recovery_avg_rtt"] is None
                    else round(result["post_recovery_avg_rtt"], 3)
                ),
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
        if result["bgp_sync_time"] is not None:
            output(f"*** BGP sync time:     {result['bgp_sync_time']:.2f}s\n")
        output(f"*** Packet loss:       {result['packet_loss_count']}\n")
        output(f"*** Packets sent:      {result['packets_sent']}\n")
        if result["post_recovery_avg_rtt"] is not None:
            output(f"*** Post-recovery RTT: {result['post_recovery_avg_rtt']:.3f} ms\n")
        output(f"*** Log saved to {forward_paths['log_file']}\n")
        output(f"*** JSON saved to {forward_paths['json_log_file']}\n")
        output(f"*** Persistent log:    {forward_paths['persistent_log_file']}\n")
        output(f"*** Persistent JSON:   {forward_paths['persistent_json_log_file']}\n")


    if not wait_for_initial_convergence(network, dir="reverse"):
        output("*** ERROR: Initial BGP convergence timed out\n")
        show_as1_as3_as4_state(network, "initial timeout")
        save_results(None, dir="reverse")
        network.stop()
        sys.exit(1)

    if not wait_for_preferred_paths(network, timeout=INITIAL_WAIT):
        output("*** ERROR: Preferred AS2 paths not restored before reverse test\n")
        show_best_paths(network, "pre-reverse")
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
        if result["bgp_sync_time"] is not None:
            output(f"*** BGP sync time:     {result['bgp_sync_time']:.2f}s\n")
        output(f"*** Packet loss:       {result['packet_loss_count']}\n")
        output(f"*** Packets sent:      {result['packets_sent']}\n")
        if result["post_recovery_avg_rtt"] is not None:
            output(f"*** Post-recovery RTT: {result['post_recovery_avg_rtt']:.3f} ms\n")
        output(f"*** Log saved to {reverse_paths['log_file']}\n")
        output(f"*** JSON saved to {reverse_paths['json_log_file']}\n")
        output(f"*** Persistent log:    {reverse_paths['persistent_log_file']}\n")
        output(f"*** Persistent JSON:   {reverse_paths['persistent_json_log_file']}\n")
    else:
        output("*** ERROR: Reverse test failed\n")

    network.stop()
