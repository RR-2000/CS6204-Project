"""
BGP Convergence vs SDX Fast Recovery Comparison Test

Both tests bring down the same link: AS2r1 <-> ixp1s1 (AS2's uplink to SDX).
This makes the failure scenario identical so the recovery mechanisms are
directly comparable.

Test A - BGP Convergence (SDX fast recovery DISABLED):
    Bring down the AS2r1 <-> ixp1s1 link with a flag file telling the
    controller NOT to install failover rules.
    AS2's BGP session with the route server drops; the route server withdraws
    AS2's routes from AS1.  AS1 must wait for BGP to reconverge and learn that
    AS4 is reachable via AS3 (~5-30s).

Test B - SDX Fast Recovery (SDX fast recovery ENABLED):
    Bring down the same AS2r1 <-> ixp1s1 link, this time without the flag file.
    The SDX controller detects the PORT_DOWN event immediately and installs
    route_alteration rules to redirect AS4-bound traffic to AS3.
    AS1 still sends with dst MAC = AS2's MAC, but SDX rewrites it to AS3's MAC.
    Recovery is sub-second (no BGP reconvergence required).
"""

import os
import sys
import time
from datetime import datetime

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel, output
from mininet.net import Mininet

from networks import Topology

SCRIPT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))
REPOSITORY_DIRECTORY = os.path.join(SCRIPT_DIRECTORY, "../../../")
TEMP_DIRECTORY = os.path.join(REPOSITORY_DIRECTORY, "temp")
LOG_FILE = os.path.join(TEMP_DIRECTORY, "bgp_convergence.log")

# Shared flag file: when present tells the controller to skip fast recovery.
FAST_RECOVERY_DISABLE_FILE = os.path.join(TEMP_DIRECTORY, "disable_fast_recovery")

PING_SOURCE = "as1h1"
PING_TARGET = "10.4.0.101"    # as4h1

INITIAL_WAIT = 60             # max seconds for initial BGP convergence
MAX_RECONVERGE_WAIT = 90      # max seconds to wait for reconvergence (hold timer 30s + margin)
STABILIZE_WAIT = 45           # seconds to wait between tests for full reconvergence


def ping_once(host, target, timeout=1):
    """Returns (success, rtt_ms). rtt_ms is None if ping failed."""
    result = host.cmd(f"ping -c 1 -W {timeout} {target}")
    if "1 received" in result:
        for line in result.splitlines():
            if "rtt min" in line or "round-trip" in line:
                try:
                    rtt_ms = float(line.split("=")[1].strip().split("/")[1])
                    return True, rtt_ms
                except (IndexError, ValueError):
                    pass
        return True, None
    return False, None


def wait_for_initial_convergence(network):
    output(f"*** Waiting up to {INITIAL_WAIT}s for initial BGP convergence...\n")
    source = network.getNodeByName(PING_SOURCE)
    start = time.time()
    while time.time() - start < INITIAL_WAIT:
        success, _ = ping_once(source, PING_TARGET)
        if success:
            output(f"*** BGP converged after {time.time() - start:.1f}s\n")
            return True
        time.sleep(2)
    output("*** ERROR: Initial BGP convergence timed out\n")
    return False


def wait_for_stabilization(network):
    """Wait for full BGP reconvergence between tests."""
    output(f"*** Waiting {STABILIZE_WAIT}s for network to stabilize before next test...\n")
    source = network.getNodeByName(PING_SOURCE)
    deadline = time.time() + STABILIZE_WAIT
    confirmed = False
    while time.time() < deadline:
        success, _ = ping_once(source, PING_TARGET)
        if success:
            confirmed = True
            time.sleep(5)  # a few more seconds to let BGP fully settle
            break
        time.sleep(2)
    if confirmed:
        output("*** Network stabilized\n")
    else:
        output("*** WARNING: Network may not be fully stabilized\n")


def _run_recovery_test(network, link_node1, link_node2, label):
    """
    Generic test: bring down a link, measure time to recovery.
    Returns a result dict or None on failure.
    """
    source = network.getNodeByName(PING_SOURCE)

    success, _ = ping_once(source, PING_TARGET)
    if not success:
        output(f"*** ERROR [{label}]: No initial connectivity, aborting\n")
        return None

    output(f"*** [{label}] Bringing down link: {link_node1} <-> {link_node2}\n")
    t_link_down = time.time()
    network.configLinkStatus(link_node1, link_node2, "down")

    # Wait for connectivity loss
    t_ping_fail = None
    packet_loss_count = 0
    output(f"*** [{label}] Waiting for connectivity loss...\n")
    for _ in range(30):
        success, _ = ping_once(source, PING_TARGET)
        if not success:
            t_ping_fail = time.time()
            packet_loss_count += 1
            output(f"*** [{label}] Connectivity lost {t_ping_fail - t_link_down:.2f}s after link down\n")
            break
        time.sleep(1)

    if t_ping_fail is None:
        output(f"*** [{label}] WARNING: Connectivity never lost\n")
        network.configLinkStatus(link_node1, link_node2, "up")
        return None

    # Wait for recovery
    output(f"*** [{label}] Waiting for recovery...\n")
    t_reconverged = None
    first_response_rtt = None
    deadline = time.time() + MAX_RECONVERGE_WAIT
    while time.time() < deadline:
        success, rtt_ms = ping_once(source, PING_TARGET)
        if success:
            t_reconverged = time.time()
            first_response_rtt = rtt_ms
            output(f"*** [{label}] Recovered! Convergence time: {t_reconverged - t_link_down:.2f}s\n")
            break
        packet_loss_count += 1
        time.sleep(1)

    # Restore link
    output(f"*** [{label}] Restoring link: {link_node1} <-> {link_node2}\n")
    network.configLinkStatus(link_node1, link_node2, "up")

    if t_reconverged is None:
        output(f"*** [{label}] ERROR: Did not recover within timeout\n")
        return None

    return {
        "label":              label,
        "link":               f"{link_node1} <-> {link_node2}",
        "t_link_down":        t_link_down,
        "t_ping_fail":        t_ping_fail,
        "t_reconverged":      t_reconverged,
        "detection_time":     t_ping_fail - t_link_down,
        "blackout_duration":  t_reconverged - t_ping_fail,
        "convergence_time":   t_reconverged - t_link_down,
        "packet_loss_count":  packet_loss_count,
        "first_response_rtt": first_response_rtt,
    }


def run_bgp_convergence_test(network):
    """Test A: AS2-SDX link fails, SDX fast recovery disabled. BGP must reconverge."""
    output("\n*** ========== TEST A: BGP Convergence ==========\n")
    output("*** Scenario: AS2r1 <-> ixp1s1 link goes down (SDX fast recovery DISABLED)\n")
    output("*** Expected: BGP reconvergence required (~5-30s)\n")

    # Signal the controller not to install failover rules for this test.
    os.makedirs(TEMP_DIRECTORY, exist_ok=True)
    open(FAST_RECOVERY_DISABLE_FILE, "w").close()
    output("*** [BGP] Fast-recovery flag file created — controller will skip failover rules\n")

    result = _run_recovery_test(network, "as2r1", "ixp1s1", "BGP")

    # Remove the flag so the controller is back to normal for Test B.
    if os.path.exists(FAST_RECOVERY_DISABLE_FILE):
        os.remove(FAST_RECOVERY_DISABLE_FILE)
    output("*** [BGP] Fast-recovery flag file removed — controller back to normal\n")

    return result


def run_sdx_fast_recovery_test(network):
    """Test B: AS2-SDX link fails. SDX controller installs failover rules instantly."""
    output("\n*** ========== TEST B: SDX Fast Recovery ==========\n")
    output("*** Scenario: AS2r1 <-> ixp1s1 link goes down (SDX fast recovery ENABLED)\n")
    output("*** Expected: SDX detects PORT_DOWN and redirects to AS3 (<1s)\n")
    return _run_recovery_test(network, "as2r1", "ixp1s1", "SDX")


def save_results(results_a, results_b):
    os.makedirs(TEMP_DIRECTORY, exist_ok=True)
    fmt = "%H:%M:%S.%f"

    def fmt_rtt(r):
        return f"{r['first_response_rtt']:.3f} ms" if r['first_response_rtt'] is not None else "N/A"

    with open(LOG_FILE, "w") as f:
        f.write("BGP Convergence vs SDX Fast Recovery\n")
        f.write("=" * 50 + "\n")
        f.write(f"Test time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Ping:      {PING_SOURCE} -> {PING_TARGET}\n")
        f.write("\n")

        for r in [results_a, results_b]:
            if r is None:
                continue
            f.write(f"--- {r['label']} ---\n")
            f.write(f"Link failed:          {r['link']}\n")
            f.write(f"Link down at:         {datetime.fromtimestamp(r['t_link_down']).strftime(fmt)}\n")
            f.write(f"Ping failed at:       {datetime.fromtimestamp(r['t_ping_fail']).strftime(fmt)}\n")
            f.write(f"Recovered at:         {datetime.fromtimestamp(r['t_reconverged']).strftime(fmt)}\n")
            f.write(f"Detection time:       {r['detection_time']:.2f}s\n")
            f.write(f"Blackout duration:    {r['blackout_duration']:.2f}s\n")
            f.write(f"Convergence time:     {r['convergence_time']:.2f}s\n")
            f.write(f"Packet loss count:    {r['packet_loss_count']} packets\n")
            f.write(f"First response RTT:   {fmt_rtt(r)}\n")
            f.write("\n")

        if results_a and results_b:
            speedup = results_a['convergence_time'] / results_b['convergence_time']
            saved = results_a['convergence_time'] - results_b['convergence_time']
            f.write("--- Comparison ---\n")
            f.write(f"BGP convergence time:         {results_a['convergence_time']:.2f}s\n")
            f.write(f"SDX fast recovery time:       {results_b['convergence_time']:.2f}s\n")
            f.write(f"Time saved by SDX:            {saved:.2f}s\n")
            f.write(f"SDX speedup:                  {speedup:.1f}x faster\n")
            f.write(f"BGP packet loss:              {results_a['packet_loss_count']} packets\n")
            f.write(f"SDX packet loss:              {results_b['packet_loss_count']} packets\n")

    output(f"*** Results saved to {LOG_FILE}\n")


if __name__ == "__main__":
    setLogLevel("info")

    topology = Topology()
    network = Mininet(topo=topology, link=TCLink, autoSetMacs=False)
    network.start()

    if not wait_for_initial_convergence(network):
        network.stop()
        sys.exit(1)

    # Test A: BGP convergence (AS2-AS4 link fails, SDX cannot detect this)
    results_a = run_bgp_convergence_test(network)

    # Wait for network to fully stabilize before Test B
    wait_for_stabilization(network)

    # Test B: SDX fast recovery (AS2-SDX link fails, controller reacts instantly)
    results_b = run_sdx_fast_recovery_test(network)

    # Save and print comparison
    save_results(results_a, results_b)

    output("\n*** ========== Summary ==========\n")
    if results_a:
        output(f"*** [BGP]  Convergence time: {results_a['convergence_time']:.2f}s  |  "
               f"Packet loss: {results_a['packet_loss_count']}  |  "
               f"First RTT: {results_a['first_response_rtt']:.3f}ms\n"
               if results_a['first_response_rtt'] else
               f"*** [BGP]  Convergence time: {results_a['convergence_time']:.2f}s  |  "
               f"Packet loss: {results_a['packet_loss_count']}\n")
    if results_b:
        output(f"*** [SDX]  Convergence time: {results_b['convergence_time']:.2f}s  |  "
               f"Packet loss: {results_b['packet_loss_count']}  |  "
               f"First RTT: {results_b['first_response_rtt']:.3f}ms\n"
               if results_b['first_response_rtt'] else
               f"*** [SDX]  Convergence time: {results_b['convergence_time']:.2f}s  |  "
               f"Packet loss: {results_b['packet_loss_count']}\n")
    if results_a and results_b:
        speedup = results_a['convergence_time'] / results_b['convergence_time']
        output(f"*** SDX is {speedup:.1f}x faster than BGP convergence\n")
    output("*** =================================\n\n")

    output("*** Entering CLI for manual inspection (type 'exit' to quit)...\n")
    CLI(network)
    network.stop()
