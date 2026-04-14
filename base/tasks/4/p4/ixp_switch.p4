#include <core.p4>
#include <v1model.p4>

// ********************************************************************************************************************************************
// Declarations: 
// Followed a lot of conventions and standards from the finsy examples and P4 tutorials
// https://github.com/byllyfish/finsy
// Most Formats and Conventions were looked up in https://github.com/byllyfish/finsy/blob/main/examples/ngsdn/ngsdn/p4/main.p4 and the corresponding controller code

// CoPilot was also used to suggest some code snippets
// Mostly to auto complete statements to speed up coding, but all code was reviewed and modified as necessary

// Things that might not work: The port status listener and response
// ********************************************************************************************************************************************

const bit<16> ETHERTYPE_IPV4 = 0x0800; // IPv4 EtherType, not needed but following convention
const bit<9>  CPU_PORT = 510; // Standard CPU port in BMv2
const bit<32> CPU_SESSION = 64;

typedef bit<48> macAddr_t;
typedef bit<9>  PortId_t;

header cpu_t {
    PortId_t ingress_port;
    bit<7>   _pad;
}

// Standard Ethernet Header
header ethernet_t {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16>   etherType;
}


// Standard IPv4 Header
header ipv4_t {
    bit<4>   version;
    bit<4>   ihl;
    bit<6>   dscp;
    bit<2>   ecn;
    bit<16>  totalLen;
    bit<16>  identification;
    bit<3>   flags;
    bit<13>  fragOffset;
    bit<8>   ttl;
    bit<8>   protocol;
    bit<16>  hdrChecksum;
    bit<32>  srcAddr;
    bit<32>  dstAddr;
}


// Standard TCP and UDP Headers
header tcp_t {
    bit<16> srcPort;
    bit<16> dstPort;
    bit<32> seqNo;
    bit<32> ackNo;
    bit<4>  dataOffset;
    bit<3>  res;
    bit<3>  ecn;
    bit<6>  ctrl;
    bit<16> window;
    bit<16> checksum;
    bit<16> urgentPtr;
}
header udp_t {
    bit<16> srcPort;
    bit<16> dstPort;
    bit<16> length;
    bit<16> checksum;
}

struct metadata {
    macAddr_t dstAddr;
    @field_list(1)
    macAddr_t srcAddr;
    @field_list(1)
    PortId_t  ingress_port;
    bit<16>   l4_src;
    bit<16>   l4_dst;
}

struct headers {
    cpu_t      cpu;
    ethernet_t ethernet;
    ipv4_t     ipv4;
    tcp_t      tcp;
    udp_t      udp;
}

parser MyParser(
    packet_in packet,
    out headers hdr,
    inout metadata meta,
    inout standard_metadata_t standard_metadata
) {
    state start {
        packet.extract(hdr.ethernet);

        meta.ingress_port = standard_metadata.ingress_port;
        meta.srcAddr = hdr.ethernet.srcAddr;
        meta.dstAddr = hdr.ethernet.dstAddr;
        
        transition select(hdr.ethernet.etherType) {
            ETHERTYPE_IPV4 : parse_ipv4;
            default : accept;
        }
    }

    state parse_ipv4 {
        packet.extract(hdr.ipv4);
        transition select(hdr.ipv4.protocol) {
            6 : parse_tcp;
            17 : parse_udp;
            default : accept;
        }
    }

    state parse_tcp {
        packet.extract(hdr.tcp);
        transition accept;
    }

    state parse_udp {
        packet.extract(hdr.udp);
        transition accept;
    }
}

control MyVerifyChecksum(
    inout headers hdr,
    inout metadata meta
) {
    apply { }
}

control MyIngress(
    inout headers hdr,
    inout metadata meta,
    inout standard_metadata_t standard_metadata
) {

    action set_egress_port(PortId_t port) {
        standard_metadata.egress_spec = port; // Set the egress port from the forwarding table
    }

    action flood() {
        standard_metadata.mcast_grp = 1; // Use multicast group 1 for flooding
    }

    action send_to_controller() {
        // Clone a copy of the ingress packet to the controller (CPU port)
        clone_preserving_field_list(CloneType.I2E, CPU_SESSION, 1); // Use field list 1 to preserve metadata
    }

    action set_route_override(macAddr_t next_hop, PortId_t port) {
        hdr.ethernet.dstAddr = next_hop;
        standard_metadata.egress_spec = port;
    }

    table forwarding {
        key = {
            hdr.ethernet.dstAddr: exact;
        }
        actions = {
            set_egress_port;
            flood;
        }
        size = 1024; // Need more than 1000 entries, 1024 for simplicity
        default_action = flood(); // Flood when MAC not known
        support_timeout = true; // Timeout support
        // idle_timeout_ns = 10000000000; // 10 seconds Not supported in this format
    }

    table fast_failover {
        key = {
            meta.ingress_port: exact;
            hdr.ethernet.dstAddr: exact;
        }
        actions = {
            set_route_override;
        }
        size = 32;
    }

    apply {
        standard_metadata.mcast_grp = 0;
        
        // Extract L4 info for matching
        if (hdr.tcp.isValid()) {
            meta.l4_src = hdr.tcp.srcPort;
            meta.l4_dst = hdr.tcp.dstPort;
        } else if (hdr.udp.isValid()) {
            meta.l4_src = hdr.udp.srcPort;
            meta.l4_dst = hdr.udp.dstPort;
        } else {
            meta.l4_src = 0;
            meta.l4_dst = 0;
        }
        
        bool override_hit = fast_failover.apply().hit;

        // Send a clone of every ingress packet (except CPU) to the controller for learning and filter out invalid src MACs
        if (standard_metadata.ingress_port != CPU_PORT &&
            hdr.ethernet.srcAddr != 0x000000000000) {
            send_to_controller();
        }

        if (!override_hit) {
            // Forward based on destination MAC address
            if (hdr.ethernet.dstAddr == 0xFFFFFFFFFFFF) { // Broadcast address Standard
                flood();
            } else {
                // Apply forwarding table
                forwarding.apply();
            }
        }
    }
}

control MyEgress(
    inout headers hdr,
    inout metadata meta,
    inout standard_metadata_t standard_metadata
) {
    apply {
        // If destined for CPU, attach the CPU header with the PRESERVED ingress port
        if (standard_metadata.egress_port == CPU_PORT) {
            hdr.cpu.setValid();
            hdr.cpu.ingress_port = meta.ingress_port; 
        }

        // This logic prevents the packet from being sent back out the port it arrived on during a flood.
        if (standard_metadata.mcast_grp == 1 && standard_metadata.egress_port == standard_metadata.ingress_port) {
            mark_to_drop(standard_metadata);
        }
    }
}

control MyComputeChecksum(
    inout headers hdr,
    inout metadata meta
) {
    apply { }
}

control MyDeparser(
    packet_out packet,
    in headers hdr
) {
    apply {
        packet.emit(hdr.cpu);
        packet.emit(hdr.ethernet); 
        packet.emit(hdr.ipv4);
        packet.emit(hdr.tcp);
        packet.emit(hdr.udp);
    }
}

V1Switch(
    MyParser(),
    MyVerifyChecksum(),
    MyIngress(),
    MyEgress(),
    MyComputeChecksum(),
    MyDeparser()
) main;
