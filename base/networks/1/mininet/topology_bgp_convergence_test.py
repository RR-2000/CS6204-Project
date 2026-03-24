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
LOG_FILE = os.path.join(TEMP_DIRECTORY, "bgp_convergence.log")
JSON_LOG_FILE = os.path.join(TEMP_DIRECTORY, "bgp_convergence.json")
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
INITIAL_WAIT = 30
MAX_RECONVERGENCE_WAIT = 30
PING_INTERVAL = 1


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

def run_test(network):
    source = network.getNodeByName(PING_SOURCE)
    as2r1 = network.getNodeByName("as2r1")

    success, _ = ping_once(source, PING_TARGET)
    if not success:
        output("*** ERROR: No initial connectivity\n")
        return None

    output("*** Bringing down interface: as2r1-eth1\n")
    t_link_down = time.time()
    as2r1.cmd("ip link set dev as2r1-eth1 down")

    t_ping_fail = None
    packet_loss_count = 0
    while time.time() - t_link_down < 30:
        success, _ = ping_once(source, PING_TARGET)
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
    first_rtt = None
    deadline = time.time() + MAX_RECONVERGENCE_WAIT
    output("*** Waiting for BGP reconvergence...\n")
    while time.time() < deadline:
        success, rtt_ms = ping_once(source, PING_TARGET)
        if success:
            t_recovered = time.time()
            first_rtt = rtt_ms
            output(f"*** Recovered after {t_recovered - t_link_down:.2f}s\n")
            break
        packet_loss_count += 1
        time.sleep(PING_INTERVAL)

    if t_recovered is None:
        show_as1_as3_post_failure_probes(network, "recovery timeout")
        show_switch_side_state(network, "recovery timeout")
        show_reconvergence_state(network, "recovery timeout")
        show_best_paths(network, "recovery timeout")
        output("*** Restoring interface: as2r1-eth1\n")
        as2r1.cmd("ip link set dev as2r1-eth1 up")
        output("*** ERROR: BGP did not recover within timeout\n")
        return None
    output("*** Restoring interface: as2r1-eth1\n")
    as2r1.cmd("ip link set dev as2r1-eth1 up")

    return {
        "t_link_down": t_link_down,
        "t_ping_fail": t_ping_fail,
        "t_recovered": t_recovered,
        "detection_time": t_ping_fail - t_link_down,
        "blackout_duration": t_recovered - t_ping_fail,
        "convergence_time": t_recovered - t_link_down,
        "packet_loss_count": packet_loss_count,
        "first_response_rtt": first_rtt,
    }


def save_results(result):
    os.makedirs(TEMP_DIRECTORY, exist_ok=True)
    with open(LOG_FILE, "w", encoding="utf-8") as file:
        file.write("BGP Convergence Test\n")
        file.write("=" * 40 + "\n")
        file.write(f"Test time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        file.write(f"Ping:      {PING_SOURCE} -> {PING_TARGET}\n\n")

        if result is None:
            file.write("Result: FAILED\n")
            return

        file.write("Result: SUCCESS\n")
        file.write(f"Link failed:          as2r1-eth1 administratively down\n")
        file.write(f"Detection time:       {result['detection_time']:.2f}s\n")
        file.write(f"Blackout duration:    {result['blackout_duration']:.2f}s\n")
        file.write(f"Convergence time:     {result['convergence_time']:.2f}s\n")
        file.write(f"Packet loss count:    {result['packet_loss_count']}\n")
        if result["first_response_rtt"] is None:
            file.write("First response RTT:   N/A\n")
        else:
            file.write(f"First response RTT:   {result['first_response_rtt']:.3f} ms\n")

    payload = {
        "test_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ping_source": PING_SOURCE,
        "ping_target": PING_TARGET,
        "result": "SUCCESS" if result is not None else "FAILED",
    }
    if result is not None:
        payload.update(
            {
                "failure_event": "as2r1-eth1 administratively down",
                "detection_time_s": round(result["detection_time"], 2),
                "blackout_duration_s": round(result["blackout_duration"], 2),
                "convergence_time_s": round(result["convergence_time"], 2),
                "packet_loss_count": result["packet_loss_count"],
                "first_response_rtt_ms": (
                    None
                    if result["first_response_rtt"] is None
                    else round(result["first_response_rtt"], 3)
                ),
            }
        )

    with open(JSON_LOG_FILE, "w", encoding="utf-8") as file:
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

    result = run_test(network)
    save_results(result)

    if result is not None:
        output("\n*** Summary\n")
        output(f"*** Detection time:    {result['detection_time']:.2f}s\n")
        output(f"*** Blackout duration: {result['blackout_duration']:.2f}s\n")
        output(f"*** Convergence time:  {result['convergence_time']:.2f}s\n")
        output(f"*** Packet loss:       {result['packet_loss_count']}\n")
        if result["first_response_rtt"] is not None:
            output(f"*** First RTT:         {result['first_response_rtt']:.3f} ms\n")
        output(f"*** Log saved to {LOG_FILE}\n")
        output(f"*** JSON saved to {JSON_LOG_FILE}\n")

    network.stop()
