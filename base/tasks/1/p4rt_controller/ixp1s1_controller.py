import logging
import os
import pathlib
import sys
from typing import Dict, Tuple
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

CPU_PORT = 510
CPU_SESSION = 64
NUM_PORTS = 32
MAC_ENTRY_IDLE_TIMEOUT_NS = 300_000_000_000  # 300 seconds
STATIC_ROUTER_MACS = {
    "f0:00:0a:01:01:01": 1,
    "f0:00:0a:01:02:01": 2,
    "f0:00:0a:01:03:01": 3,
}

logger = finsy.LoggerAdapter(
    logging.getLogger("finsy")
)

def _format_mac(mac_bytes: bytes) -> str:
    return ":".join(f"{b:02x}" for b in mac_bytes)

# MAC learning table to track learned MAC addresses (Just a Local Copy for this controller)
mac_table: Dict[Tuple[str, str], int] = {}  # (switch_name, mac_addr) -> port

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
        idle_timeout_ns=MAC_ENTRY_IDLE_TIMEOUT_NS,
    )


def _make_static_forward_entry(mac_addr: str, port: int) -> finsy.P4TableEntry:
    return finsy.P4TableEntry(
        "MyIngress.forwarding",
        match=finsy.Match({
            "hdr.ethernet.dstAddr": mac_addr,
        }),
        action=finsy.Action(
            "MyIngress.set_egress_port",
            port=port,
        ),
    )

async def controller_ready_handler(
    switch: finsy.Switch
):
    # Clear entities in P4 switch
    await switch.delete_all()
    # Empty the MAC table entries for this switch on this controller
    keys_to_remove = [key for key in mac_table if key[0] == switch.name]
    for key in keys_to_remove:
        mac_table.pop(key, None)
    
    # Set up multicast group for flooding to all 4 ports
    multicast_group = +finsy.P4MulticastGroupEntry(
        multicast_group_id=1,
        replicas=[i for i in range(1, NUM_PORTS + 1)], # Assuming ports 1-4 are valid ports according to the Task description
    )

    # Prep clone session to send copies of packets to controller CPU port
    clone_session = +finsy.P4CloneSessionEntry(
        session_id=CPU_SESSION,
        replicas=[CPU_PORT],
    )

    # Write the configurations to the switch
    await switch.write([
        multicast_group,
        clone_session,
        *[
            +_make_static_forward_entry(mac_addr, port)
            for mac_addr, port in STATIC_ROUTER_MACS.items()
        ],
    ])

    for mac_addr, port in STATIC_ROUTER_MACS.items():
        mac_table[(switch.name, mac_addr)] = port
        logger.info(
            "Installed static router MAC %s on port %d for switch %s",
            mac_addr,
            port,
            switch.name,
        )

    # Start background task for packet reading
    switch.create_task(packet_reader(switch), name=f"{switch.name}-packet-reader")
    
    # Register Port status listeners
    switch.ee.add_listener(finsy.SwitchEvent.PORT_UP, on_port_up)
    switch.ee.add_listener(finsy.SwitchEvent.PORT_DOWN, on_port_down)
    
    # Start idle timeout listener
    switch.create_task(handle_idle_timeouts(switch), name=f"{switch.name}-idle-timeout")
    
    logger.info(f"Switch {switch.name} ready with multicast group configured")


# Handler for idle timeouts
async def handle_idle_timeouts(switch: finsy.Switch):
    logger.info(f"Starting idle timeout listener for {switch.name}")
    try:
        async for notification in switch.read_idle_timeouts():
            logger.info(f"Received idle timeout notification on {switch.name}")
            updates = []
            for entry in notification:
                logger.info(f"Processing timeout entry: {entry}")
                mac_addr = entry.match["hdr.ethernet.dstAddr"]
                logger.info(f"MAC {mac_addr} timed out on {switch.name}")
                key = (switch.name, mac_addr)
                if mac_addr not in STATIC_ROUTER_MACS:
                    mac_table.pop(key, None)
                updates.append(-entry)
            
            if updates:
                try:
                    await switch.write(updates)
                except Exception as exc:
                    logger.error(f"Failed to write idle timeout deletions to {switch.name}: {exc}")
                
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error(f"Idle timeout listener failed: {exc}")  


# Handler to read packets from the switch
async def packet_reader(switch: finsy.Switch) -> None:
    logger.info(f"Starting packet reader for {switch.name}")
    try:
        async for packet in switch.read_packets():
            logger.info(f"Packet received on {switch.name}")
            await handle_packet_in(switch, packet)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Packet reader stopped for {switch.name}: {exc}")

# Handler for PacketIn messages to learn MAC addresses
async def handle_packet_in(
    switch: finsy.Switch,
    packet_in: finsy.P4PacketIn,
) -> None:
    """Handle PacketIn messages to learn MAC addresses."""
    
    # [CPUHeader (2 bytes)] [EthernetHeader (14 bytes)] ...
    payload = packet_in.payload

    if len(payload) < 16: return

    # Parse Ingress Port from the first 2 bytes (CPU Header)
    # This data relies on the 'field_list' successfully preserving 'meta.ingress_port' to MyEgress
    cpu_val = int.from_bytes(payload[0:2], "big")
    ingress_port = cpu_val >> 7 # Top 9 bits
    
    # Parse Src MAC from the Ethernet header (offset by 2 bytes)
    src_mac_bytes = payload[8:14] 
    src_mac = _format_mac(src_mac_bytes)

    if ingress_port == CPU_PORT: 
        return

    mac_key = (switch.name, src_mac)
    current_port = mac_table.get(mac_key)
    logger.info(f"Current port for MAC {src_mac} on switch {switch.name} is {current_port}, learned on port {ingress_port}")

    if current_port == ingress_port:
        return

    if src_mac in STATIC_ROUTER_MACS:
        return

    updates = []
    # Remove old entry
    if current_port is not None:
        updates.append(-_make_forward_entry(src_mac, current_port))

    # Add new entry
    updates.append(+_make_forward_entry(src_mac, ingress_port))
    await switch.write(updates)

    # Update local MAC table
    mac_table[mac_key] = ingress_port
    logger.info(
        "Learned MAC %s on port %d for switch %s",
        src_mac,
        ingress_port,
        switch.name,
    )

async def _clear_mac_entries_for_port(switch: finsy.Switch, port_id: int):
    logger.info(f"Removing MAC entries learned on port {port_id} for switch {switch.name}")
    # Remove MAC entries from the switch table
    updates = [
        -_make_forward_entry(mac_addr=key[1], port=port_id)
        for key, port_num in mac_table.items()
        if key[0] == switch.name and port_num == port_id and key[1] not in STATIC_ROUTER_MACS
    ]
    if updates:
        await switch.write(updates)
    
    # Remove MAC entries learned on this port
    keys_to_remove = [
        key
        for key, port_num in mac_table.items()
        if key[0] == switch.name and port_num == port_id and key[1] not in STATIC_ROUTER_MACS
    ]
    for key in keys_to_remove:
        mac_table.pop(key, None)

def on_port_up(switch: finsy.Switch, port: finsy.SwitchPort):
    logger.info(f"Port {port.id} ({port.name}) is UP")
    switch.create_task(_clear_mac_entries_for_port(switch, port.id))

def on_port_down(switch: finsy.Switch, port: finsy.SwitchPort):
    logger.info(f"Port {port.id} ({port.name}) is DOWN")
    switch.create_task(_clear_mac_entries_for_port(switch, port.id))


async def main():
    info_file_path = pathlib.Path(
        os.path.join(
            BUILD_DIRECTORY,
            "ixp_switch.p4info.txtpb"
        )
    )
    program_file_path = pathlib.Path(
        os.path.join(
            BUILD_DIRECTORY,
            "ixp_switch.json"
        )
    )

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

    controller = finsy.Controller(
        [ixp1s1]
    )
    
    logger.info("Starting MAC learning controller for ixp1s1")
    logger.info("Switch supports 4 ports (1-4) with 1024 MAC addresses")
    logger.info("MAC aging timeout: 300 seconds")
    
    await controller.run()

if __name__ == "__main__":
    finsy.run(main())
