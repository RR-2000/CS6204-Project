import ipaddress
import logging
import os
import pathlib
import sys
from typing import Dict, List, Tuple
import asyncio

import finsy

SCRIPT_DIRECTORY = os.path.abspath(
    os.path.dirname(__file__)
)
REPOSITORY_DIRECTORY = os.path.abspath(
    os.path.join(
        SCRIPT_DIRECTORY,
        "../../../"
    )
)

sys.path.append(REPOSITORY_DIRECTORY)

BUILD_DIRECTORY = os.path.join(
    REPOSITORY_DIRECTORY,
    "build/p4"
)

# Flag file: if present, SDX fast recovery is disabled (used by Test A).
FAST_RECOVERY_DISABLE_FILE = os.path.join(
    REPOSITORY_DIRECTORY, "temp", "disable_fast_recovery"
)

CPU_PORT = 510
CPU_SESSION = 64
NUM_PORTS = 32

logger = finsy.LoggerAdapter(
    logging.getLogger("finsy")
)

# ---------------------------------------------------------------------------
# SDX Fast Recovery: failover rules installed when a port goes down.
#
# Port layout on ixp1s1 (assigned in order of addLink calls in networks.py):
#   Port 1: ixp1s1-eth0  ->  ixp1s1_bird (route server)
#   Port 2: ixp1s1-eth1  ->  as1r1  (AS100)
#   Port 3: ixp1s1-eth2  ->  as2r1  (AS200)
#   Port 4: ixp1s1-eth3  ->  as3r1  (AS300)
#
# When AS2's port (ixp1s1-eth2) goes down, redirect AS4-bound traffic to AS3.
# When AS3's port (ixp1s1-eth3) goes down, redirect AS4-bound traffic to AS2.
#
# Format: { failed_port_name: [(dst_prefix, alt_port_name, alt_next_hop_mac)] }
# ---------------------------------------------------------------------------
FAILOVER_MAP: Dict[str, List[Tuple[str, str, str]]] = {
    "ixp1s1-eth2": [
        ("10.4.0.0/24", "ixp1s1-eth3", "f0:00:0a:01:03:01"),  # AS4 via AS3
    ],
    "ixp1s1-eth3": [
        ("10.4.0.0/24", "ixp1s1-eth2", "f0:00:0a:01:02:01"),  # AS4 via AS2
    ],
}

# Tracks installed failover entries so they can be removed on port up.
# { failed_port_name: [P4TableEntry, ...] }
active_failover: Dict[str, List[finsy.P4TableEntry]] = {}

# ---------------------------------------------------------------------------
# MAC learning table
# ---------------------------------------------------------------------------
mac_table: Dict[Tuple[str, str], int] = {}  # (switch_name, mac_addr) -> port


def _format_mac(mac_bytes: bytes) -> str:
    return ":".join(f"{b:02x}" for b in mac_bytes)


def _make_forward_entry(mac_addr: str, port: int) -> finsy.P4TableEntry:
    return finsy.P4TableEntry(
        "MyIngress.forwarding",
        match=finsy.Match({
            "hdr.ethernet.dstAddr": mac_addr,
        }),
        action=finsy.Action(
            "MyIngress.set_egress_port",
            port=port,
        ),
        idle_timeout_ns=10_000_000_000,  # 10 seconds
    )


def _make_route_alteration_entry(
    dst_prefix: str,
    next_hop_mac: str,
    port: int,
) -> finsy.P4TableEntry:
    """Create a route_alteration entry that redirects traffic for dst_prefix
    to the given next_hop_mac and egress port."""
    network = ipaddress.ip_network(dst_prefix)
    addr_int = int(network.network_address)
    mask_int = int(network.netmask)
    return finsy.P4TableEntry(
        "MyIngress.route_alteration",
        match=finsy.Match({
            "hdr.ipv4.srcAddr":  (0, 0),
            "hdr.ipv4.dstAddr":  (addr_int, mask_int),
            "hdr.ipv4.protocol": (0, 0),
            "meta.l4_src":       (0, 0),
            "meta.l4_dst":       (0, 0),
        }),
        action=finsy.Action(
            "MyIngress.set_route_override",
            next_hop=next_hop_mac,
            port=port,
        ),
        priority=100,
    )


async def _install_failover_rules(switch: finsy.Switch, failed_port_name: str):
    """Install route_alteration entries to redirect traffic away from a failed port."""
    if failed_port_name not in FAILOVER_MAP:
        return

    rules = FAILOVER_MAP[failed_port_name]
    entries = []

    for dst_prefix, alt_port_name, alt_mac in rules:
        # Resolve alternative port ID by name
        alt_port_id = None
        for p in switch.ports:
            if p.name == alt_port_name:
                alt_port_id = p.id
                break

        if alt_port_id is None:
            logger.error(f"SDX fast recovery: cannot find port '{alt_port_name}'")
            continue

        entry = _make_route_alteration_entry(dst_prefix, alt_mac, alt_port_id)
        entries.append(+entry)
        active_failover.setdefault(failed_port_name, []).append(entry)

    if entries:
        try:
            await switch.write(entries)
            logger.info(
                f"SDX fast recovery: installed {len(entries)} failover rule(s) "
                f"for port '{failed_port_name}'"
            )
        except Exception as exc:
            logger.error(f"SDX fast recovery: failed to install rules: {exc}")


async def _remove_failover_rules(switch: finsy.Switch, port_name: str):
    """Remove previously installed failover entries when a port comes back up."""
    if port_name not in active_failover:
        return

    entries = [-e for e in active_failover.pop(port_name)]
    if entries:
        try:
            await switch.write(entries)
            logger.info(
                f"SDX fast recovery: removed {len(entries)} failover rule(s) "
                f"for port '{port_name}' (port is back up)"
            )
        except Exception as exc:
            logger.error(f"SDX fast recovery: failed to remove rules: {exc}")


# ---------------------------------------------------------------------------
# Switch lifecycle
# ---------------------------------------------------------------------------

async def controller_ready_handler(switch: finsy.Switch):
    await switch.delete_all()

    keys_to_remove = [key for key in mac_table if key[0] == switch.name]
    for key in keys_to_remove:
        mac_table.pop(key, None)

    multicast_group = +finsy.P4MulticastGroupEntry(
        multicast_group_id=1,
        replicas=[i for i in range(1, NUM_PORTS + 1)],
    )

    clone_session = +finsy.P4CloneSessionEntry(
        session_id=CPU_SESSION,
        replicas=[CPU_PORT],
    )

    await switch.write([multicast_group, clone_session])

    switch.create_task(packet_reader(switch), name=f"{switch.name}-packet-reader")
    switch.ee.add_listener(finsy.SwitchEvent.PORT_UP, on_port_up)
    switch.ee.add_listener(finsy.SwitchEvent.PORT_DOWN, on_port_down)
    switch.create_task(handle_idle_timeouts(switch), name=f"{switch.name}-idle-timeout")

    logger.info(f"Switch {switch.name} ready (MAC learning + SDX fast recovery enabled)")


# ---------------------------------------------------------------------------
# Idle timeout
# ---------------------------------------------------------------------------

async def handle_idle_timeouts(switch: finsy.Switch):
    logger.info(f"Starting idle timeout listener for {switch.name}")
    try:
        async for notification in switch.read_idle_timeouts():
            updates = [(-entry) for entry in notification]
            if updates:
                try:
                    await switch.write(updates)
                except Exception as exc:
                    logger.error(f"Failed to write idle timeout deletions: {exc}")
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error(f"Idle timeout listener failed: {exc}")


# ---------------------------------------------------------------------------
# Packet-in (MAC learning)
# ---------------------------------------------------------------------------

async def packet_reader(switch: finsy.Switch) -> None:
    logger.info(f"Starting packet reader for {switch.name}")
    try:
        async for packet in switch.read_packets():
            await handle_packet_in(switch, packet)
    except Exception as exc:
        logger.error(f"Packet reader stopped for {switch.name}: {exc}")


async def handle_packet_in(
    switch: finsy.Switch,
    packet_in: finsy.P4PacketIn,
) -> None:
    payload = packet_in.payload
    if len(payload) < 16:
        return

    cpu_val = int.from_bytes(payload[0:2], "big")
    ingress_port = cpu_val >> 7

    src_mac_bytes = payload[8:14]
    src_mac = _format_mac(src_mac_bytes)

    if ingress_port == CPU_PORT:
        return

    mac_key = (switch.name, src_mac)
    current_port = mac_table.get(mac_key)

    if current_port == ingress_port:
        return

    updates = []
    if current_port is not None:
        updates.append(-_make_forward_entry(src_mac, current_port))
    updates.append(+_make_forward_entry(src_mac, ingress_port))
    await switch.write(updates)

    mac_table[mac_key] = ingress_port
    logger.info("Learned MAC %s on port %d for switch %s", src_mac, ingress_port, switch.name)


async def _clear_mac_entries_for_port(switch: finsy.Switch, port_id: int):
    updates = [
        -_make_forward_entry(mac_addr=key[1], port=port_id)
        for key, port_num in mac_table.items()
        if key[0] == switch.name and port_num == port_id
    ]
    if updates:
        await switch.write(updates)

    keys_to_remove = [
        key for key, port_num in mac_table.items()
        if key[0] == switch.name and port_num == port_id
    ]
    for key in keys_to_remove:
        mac_table.pop(key, None)


# ---------------------------------------------------------------------------
# Port events
# ---------------------------------------------------------------------------

def on_port_up(switch: finsy.Switch, port: finsy.SwitchPort):
    logger.info(f"Port {port.id} ({port.name}) is UP")
    switch.create_task(_clear_mac_entries_for_port(switch, port.id))
    switch.create_task(_remove_failover_rules(switch, port.name))


def on_port_down(switch: finsy.Switch, port: finsy.SwitchPort):
    logger.info(f"Port {port.id} ({port.name}) is DOWN")
    switch.create_task(_clear_mac_entries_for_port(switch, port.id))
    if os.path.exists(FAST_RECOVERY_DISABLE_FILE):
        logger.info(
            f"SDX fast recovery DISABLED (flag file present) — "
            f"skipping failover rules for port '{port.name}'"
        )
    else:
        switch.create_task(_install_failover_rules(switch, port.name))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    info_file_path = pathlib.Path(os.path.join(BUILD_DIRECTORY, "ixp_switch.p4info.txtpb"))
    program_file_path = pathlib.Path(os.path.join(BUILD_DIRECTORY, "ixp_switch.json"))

    ixp1s1 = finsy.Switch(
        "ixp1s1",
        "127.0.0.1:50001",
        finsy.SwitchOptions(
            p4info=info_file_path,
            p4blob=program_file_path,
            device_id=1,
            ready_handler=controller_ready_handler,
        ),
    )

    controller = finsy.Controller([ixp1s1])

    logger.info("Starting controller for ixp1s1")
    logger.info("Features: MAC learning, idle timeout, SDX fast recovery")

    await controller.run()


if __name__ == "__main__":
    finsy.run(main())
