import os
import sys

from mininet.node import OVSSwitch
from mininet.topo import Topo

SCRIPT_DIRECTORY = os.path.abspath(
    os.path.dirname(__file__)
)
REPOSITORY_DIRECTORY = os.path.join(
    SCRIPT_DIRECTORY,
    "../../../"
)
TASKS_DIRECTORY = os.path.join(
    REPOSITORY_DIRECTORY,
    "tasks"
)
TASKS_SOURCE_DIRECTORY = os.path.join(
    TASKS_DIRECTORY,
    "1"
)
FRR_CONFIGURATION_DIRECTORY = os.path.join(
    SCRIPT_DIRECTORY,
    "../frr/"
)
BIRD_CONFIGURATION_DIRECTORY = os.path.join(
    TASKS_SOURCE_DIRECTORY,
    "bird"
)

sys.path.append(REPOSITORY_DIRECTORY)

# pylint: disable=E0401,C0413
from common.p4.functions import HelperFunctions
from common.mininet.nodes import Client, P4Switch, FRRRouter, BIRDRouter

class Topology(Topo):
    def build(
        self,
        *args,
        **params
    ):
        hosts_mac_addresses = {}

        hosts_mac_addresses["isp1r1"] = {
            "isp1r1-eth0": "f0:00:0d:01:ff:00",
            "isp1r1-eth1": "f0:00:0d:01:ff:01",
        }
        hosts_mac_addresses["as1r1"] = {
            "as1r1-eth0": "f0:00:0d:01:01:00",
            "as1r1-eth1": "f0:00:0d:01:01:01",
        }
        hosts_mac_addresses["as2r1"] = {
            "as2r1-eth0": "f0:00:0d:01:02:00",
            "as2r1-eth1": "f0:00:0d:01:02:01",
        }
        hosts_mac_addresses["as3r1"] = {
            "as3r1-eth0": "f0:00:0d:01:03:00",
            "as3r1-eth1": "f0:00:0d:01:03:01",
            "as3r1-eth2": "f0:00:0d:01:03:02",
        }
        hosts_mac_addresses["as4r1"] = {
            "as4r1-eth0": "f0:00:0d:01:04:00",
            "as4r1-eth1": "f0:00:0d:01:04:01",
            "as4r1-eth2": "f0:00:0d:01:04:02",
        }
        hosts_mac_addresses["as5r1"] = {
            "as5r1-eth0": "f0:00:0d:01:05:00",
            "as5r1-eth1": "f0:00:0d:01:05:01",
        }
        hosts_mac_addresses["as6r1"] = {
            "as6r1-eth0": "f0:00:0d:01:06:00",
            "as6r1-eth1": "f0:00:0d:01:06:01",
        }
        hosts_mac_addresses["as7r1"] = {
            "as7r1-eth0": "f0:00:0d:01:07:00",
            "as7r1-eth1": "f0:00:0d:01:07:01",
        }

        hosts_mac_addresses["as1h1"] = {
            "as1h1-eth0": "f0:00:0d:00:01:00"
        }
        hosts_mac_addresses["as1h2"] = {
            "as1h2-eth0": "f0:00:0d:00:01:01"
        }
        hosts_mac_addresses["as2h1"] = {
            "as2h1-eth0": "f0:00:0d:00:02:00"
        }
        hosts_mac_addresses["as2h2"] = {
            "as2h2-eth0": "f0:00:0d:00:02:01"
        }
        hosts_mac_addresses["as3h1"] = {
            "as3h1-eth0": "f0:00:0d:00:03:00"
        }
        hosts_mac_addresses["as3h2"] = {
            "as3h2-eth0": "f0:00:0d:00:03:01"
        }
        hosts_mac_addresses["as4h1"] = {
            "as4h1-eth0": "f0:00:0d:00:04:00"
        }
        hosts_mac_addresses["as4h2"] = {
            "as4h2-eth0": "f0:00:0d:00:04:01"
        }
        hosts_mac_addresses["as5h1"] = {
            "as5h1-eth0": "f0:00:0d:00:05:00"
        }
        hosts_mac_addresses["as5h2"] = {
            "as5h2-eth0": "f0:00:0d:00:05:01"
        }
        hosts_mac_addresses["as6h1"] = {
            "as6h1-eth0": "f0:00:0d:00:06:00"
        }
        hosts_mac_addresses["as6h2"] = {
            "as6h2-eth0": "f0:00:0d:00:06:01"
        }
        hosts_mac_addresses["as7h1"] = {
            "as7h1-eth0": "f0:00:0d:00:07:00"
        }

        ixp1s1 = self.addSwitch(
            "ixp1s1",
            cls=P4Switch,
            identifier=1,
            thrift_port=9091,
            grpc_address="0.0.0.0",
            grpc_port=50001,
        )

        ixp1s1_bird = self.addNode(
            "ixp1s1_bird",
            cls=BIRDRouter,
            configFile=os.path.join(BIRD_CONFIGURATION_DIRECTORY, "ixp1s1_bird.conf"),
            toEnableIpv4Forwarding=False,
        )

        isp1r1 = self.addNode(
            "isp1r1",
            cls=BIRDRouter,
            configFile=os.path.join(BIRD_CONFIGURATION_DIRECTORY, "isp1r1.conf"),
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["isp1r1"]) +
                [HelperFunctions.generate_add_loopback_interface_ip_command("100.100.254.1/32")]
            ),
        )

        as1r1 = self.addNode(
            "as1r1",
            cls=FRRRouter,
            zebraConfigFile=os.path.join(FRR_CONFIGURATION_DIRECTORY, "as1r1-zebra.conf"),
            bgpConfigFile=os.path.join(FRR_CONFIGURATION_DIRECTORY, "as1r1-bgp.conf"),
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as1r1"]) +
                [HelperFunctions.generate_add_loopback_interface_ip_command("100.100.1.1/32")]
            ),
        )
        as2r1 = self.addNode(
            "as2r1",
            cls=FRRRouter,
            zebraConfigFile=os.path.join(FRR_CONFIGURATION_DIRECTORY, "as2r1-zebra.conf"),
            bgpConfigFile=os.path.join(FRR_CONFIGURATION_DIRECTORY, "as2r1-bgp.conf"),
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as2r1"]) +
                [HelperFunctions.generate_add_loopback_interface_ip_command("100.100.2.1/32")]
            ),
        )
        as3r1 = self.addNode(
            "as3r1",
            cls=FRRRouter,
            zebraConfigFile=os.path.join(FRR_CONFIGURATION_DIRECTORY, "as3r1-zebra.conf"),
            bgpConfigFile=os.path.join(FRR_CONFIGURATION_DIRECTORY, "as3r1-bgp.conf"),
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as3r1"]) +
                [HelperFunctions.generate_add_loopback_interface_ip_command("100.100.3.1/32")]
            ),
        )
        as4r1 = self.addNode(
            "as4r1",
            cls=FRRRouter,
            zebraConfigFile=os.path.join(FRR_CONFIGURATION_DIRECTORY, "as4r1-zebra.conf"),
            bgpConfigFile=os.path.join(FRR_CONFIGURATION_DIRECTORY, "as4r1-bgp.conf"),
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as4r1"]) +
                [HelperFunctions.generate_add_loopback_interface_ip_command("100.100.4.1/32")]
            ),
        )
        as5r1 = self.addNode(
            "as5r1",
            cls=FRRRouter,
            zebraConfigFile=os.path.join(FRR_CONFIGURATION_DIRECTORY, "as5r1-zebra.conf"),
            bgpConfigFile=os.path.join(FRR_CONFIGURATION_DIRECTORY, "as5r1-bgp.conf"),
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as5r1"]) +
                [HelperFunctions.generate_add_loopback_interface_ip_command("100.100.5.1/32")]
            ),
        )
        as6r1 = self.addNode(
            "as6r1",
            cls=FRRRouter,
            zebraConfigFile=os.path.join(FRR_CONFIGURATION_DIRECTORY, "as6r1-zebra.conf"),
            bgpConfigFile=os.path.join(FRR_CONFIGURATION_DIRECTORY, "as6r1-bgp.conf"),
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as6r1"]) +
                [HelperFunctions.generate_add_loopback_interface_ip_command("100.100.6.1/32")]
            ),
        )
        as7r1 = self.addNode(
            "as7r1",
            cls=FRRRouter,
            zebraConfigFile=os.path.join(FRR_CONFIGURATION_DIRECTORY, "as7r1-zebra.conf"),
            bgpConfigFile=os.path.join(FRR_CONFIGURATION_DIRECTORY, "as7r1-bgp.conf"),
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as7r1"]) +
                [HelperFunctions.generate_add_loopback_interface_ip_command("100.100.7.1/32")]
            ),
        )

        as1s1 = self.addSwitch(
            "as1s1",
            cls=OVSSwitch
        )
        as2s1 = self.addSwitch(
            "as2s1",
            cls=OVSSwitch
        )
        as3s1 = self.addSwitch(
            "as3s1",
            cls=OVSSwitch
        )
        as4s1 = self.addSwitch(
            "as4s1",
            cls=OVSSwitch
        )
        as5s1 = self.addSwitch(
            "as5s1",
            cls=OVSSwitch
        )
        as6s1 = self.addSwitch(
            "as6s1",
            cls=OVSSwitch
        )
        as7s1 = self.addSwitch(
            "as7s1",
            cls=OVSSwitch
        )

        as1h1 = self.addHost(
            "as1h1",
            cls=Client,
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as1h1"]) +
                [HelperFunctions.generate_set_default_route_command("16.1.1.1")]
            ),
        )
        as1h2 = self.addHost(
            "as1h2",
            cls=Client,
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as1h2"]) +
                [HelperFunctions.generate_set_default_route_command("16.1.1.1")]
            ),
        )
        as2h1 = self.addHost(
            "as2h1",
            cls=Client,
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as2h1"]) +
                [HelperFunctions.generate_set_default_route_command("16.1.2.1")]
            ),
        )
        as2h2 = self.addHost(
            "as2h2",
            cls=Client,
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as2h2"]) +
                [HelperFunctions.generate_set_default_route_command("16.1.2.1")]
            ),
        )
        as3h1 = self.addHost(
            "as3h1",
            cls=Client,
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as3h1"]) +
                [HelperFunctions.generate_set_default_route_command("16.1.3.1")]
            ),
        )
        as3h2 = self.addHost(
            "as3h2",
            cls=Client,
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as3h2"]) +
                [HelperFunctions.generate_set_default_route_command("16.1.3.1")]
            ),
        )
        as4h1 = self.addHost(
            "as4h1",
            cls=Client,
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as4h1"]) +
                [HelperFunctions.generate_set_default_route_command("16.1.4.1")]
            ),
        )
        as4h2 = self.addHost(
            "as4h2",
            cls=Client,
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as4h2"]) +
                [HelperFunctions.generate_set_default_route_command("16.1.4.1")]
            ),
        )
        as5h1 = self.addHost(
            "as5h1",
            cls=Client,
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as5h1"]) +
                [HelperFunctions.generate_set_default_route_command("16.1.5.1")]
            ),
        )
        as5h2 = self.addHost(
            "as5h2",
            cls=Client,
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as5h2"]) +
                [HelperFunctions.generate_set_default_route_command("16.1.5.1")]
            ),
        )
        as6h1 = self.addHost(
            "as6h1",
            cls=Client,
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as6h1"]) +
                [HelperFunctions.generate_set_default_route_command("16.1.6.1")]
            ),
        )
        as6h2 = self.addHost(
            "as6h2",
            cls=Client,
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as6h2"]) +
                [HelperFunctions.generate_set_default_route_command("16.1.6.1")]
            ),
        )
        as7h1 = self.addHost(
            "as7h1",
            cls=Client,
            configCmds=(
                HelperFunctions.generate_set_interface_mac_commands(hosts_mac_addresses["as7h1"]) +
                [HelperFunctions.generate_set_default_route_command("16.1.7.1")]
            ),
        )

        self.addLink(
            ixp1s1_bird,
            ixp1s1,
            intfName1="ixp1s1-b-eth0",
            params1={"ip": "16.2.1.254/24"},
            intfName2="ixp1s1-eth0",
        )

        # Connect hosts and router in 1st AS together using a switch
        self.addLink(
            as1r1,
            as1s1,
            intfName1="as1r1-eth0",
            params1={"ip": "16.1.1.1/24"},
            intfName2="as1s1-eth0",
        )
        self.addLink(
            as1h1,
            as1s1,
            intfName1="as1h1-eth0",
            params1={"ip": "16.1.1.101/24"},
            intfName2="as1s1-eth1",
        )
        self.addLink(
            as1h2,
            as1s1,
            intfName1="as1h2-eth0",
            params1={"ip": "16.1.1.102/24"},
            intfName2="as1s1-eth2",
        )

        # Connect hosts and router in 2nd AS together using a switch
        self.addLink(
            as2r1,
            as2s1,
            intfName1="as2r1-eth0",
            params1={"ip": "16.1.2.1/24"},
            intfName2="as2s1-eth0",
        )
        self.addLink(
            as2h1,
            as2s1,
            intfName1="as2h1-eth0",
            params1={"ip": "16.1.2.101/24"},
            intfName2="as2s1-eth1",
        )
        self.addLink(
            as2h2,
            as2s1,
            intfName1="as2h2-eth0",
            params1={"ip": "16.1.2.102/24"},
            intfName2="as2s1-eth2",
        )

        # Connect hosts and router in 3rd AS together using a switch
        self.addLink(
            as3r1,
            as3s1,
            intfName1="as3r1-eth0",
            params1={"ip": "16.1.3.1/24"},
            intfName2="as3s1-eth0",
        )
        self.addLink(
            as3h1,
            as3s1,
            intfName1="as3h1-eth0",
            params1={"ip": "16.1.3.101/24"},
            intfName2="as3s1-eth1",
        )
        self.addLink(
            as3h2,
            as3s1,
            intfName1="as3h2-eth0",
            params1={"ip": "16.1.3.102/24"},
            intfName2="as3s1-eth2",
        )

        # Connect hosts and router in 4th AS together using a switch
        self.addLink(
            as4r1,
            as4s1,
            intfName1="as4r1-eth0",
            params1={"ip": "16.1.4.1/24"},
            intfName2="as4s1-eth0",
        )
        self.addLink(
            as4h1,
            as4s1,
            intfName1="as4h1-eth0",
            params1={"ip": "16.1.4.101/24"},
            intfName2="as4s1-eth1",
        )
        self.addLink(
            as4h2,
            as4s1,
            intfName1="as4h2-eth0",
            params1={"ip": "16.1.4.102/24"},
            intfName2="as4s1-eth2",
        )

        # Connect hosts and router in 5th AS together using a switch
        self.addLink(
            as5r1,
            as5s1,
            intfName1="as5r1-eth0",
            params1={"ip": "16.1.5.1/24"},
            intfName2="as5s1-eth0",
        )
        self.addLink(
            as5h1,
            as5s1,
            intfName1="as5h1-eth0",
            params1={"ip": "16.1.5.101/24"},
            intfName2="as5s1-eth1",
        )
        self.addLink(
            as5h2,
            as5s1,
            intfName1="as5h2-eth0",
            params1={"ip": "16.1.5.102/24"},
            intfName2="as5s1-eth2",
        )

        # Connect hosts and router in 6th AS together using a switch
        self.addLink(
            as6r1,
            as6s1,
            intfName1="as6r1-eth0",
            params1={"ip": "16.1.6.1/24"},
            intfName2="as6s1-eth0",
        )
        self.addLink(
            as6h1,
            as6s1,
            intfName1="as6h1-eth0",
            params1={"ip": "16.1.6.101/24"},
            intfName2="as6s1-eth1",
        )
        self.addLink(
            as6h2,
            as6s1,
            intfName1="as6h2-eth0",
            params1={"ip": "16.1.6.102/24"},
            intfName2="as6s1-eth2",
        )

        # Connect hosts and router in 7th AS together using a switch
        self.addLink(
            as7r1,
            as7s1,
            intfName1="as7r1-eth0",
            params1={"ip": "16.1.7.1/24"},
            intfName2="as7s1-eth0",
        )
        self.addLink(
            as7h1,
            as7s1,
            intfName1="as7h1-eth0",
            params1={"ip": "16.1.7.101/24"},
            intfName2="as7s1-eth1",
        )

        # Connect 1st AS to IXP switch
        self.addLink(
            as1r1,
            ixp1s1,
            intfName1="as1r1-eth1",
            params1={"ip": "16.2.1.1/24"},
            intfName2="ixp1s1-eth1",
        )

        # Connect 2nd AS to IXP switch
        self.addLink(
            as2r1,
            ixp1s1,
            intfName1="as2r1-eth1",
            params1={"ip": "16.2.1.2/24"},
            intfName2="ixp1s1-eth2",
        )

        # Connect 3rd AS to IXP switch
        self.addLink(
            as3r1,
            ixp1s1,
            intfName1="as3r1-eth1",
            params1={"ip": "16.2.1.3/24"},
            intfName2="ixp1s1-eth3",
        )

        # Connect 4th AS to IXP switch
        self.addLink(
            as4r1,
            ixp1s1,
            intfName1="as4r1-eth1",
            params1={"ip": "16.2.1.4/24"},
            intfName2="ixp1s1-eth4",
        )

        # Connect 5th AS to 3rd AS
        self.addLink(
            as5r1,
            as3r1,
            intfName1="as5r1-eth1",
            params1={"ip": "16.2.2.2/24"},
            intfName2="as3r1-eth2",
            params2={"ip": "16.2.2.1/24"},
        )

        # Connect 6th AS to 4th AS
        self.addLink(
            as6r1,
            as4r1,
            intfName1="as6r1-eth1",
            params1={"ip": "16.2.3.2/24"},
            intfName2="as4r1-eth2",
            params2={"ip": "16.2.3.1/24"},
        )

        # Connect ISP 1 AS to IXP switch
        self.addLink(
            isp1r1,
            ixp1s1,
            intfName1="isp1r1-eth1",
            params1={"ip": "16.2.1.5/24"},
            intfName2="ixp1s1-eth5",
        )

        # Connect 7th AS to ISP 1 AS
        self.addLink(
            isp1r1,
            as7r1,
            intfName1="isp1r1-eth0",
            params1={"ip": "16.2.4.1/24"},
            intfName2="as7r1-eth1",
            params2={"ip": "16.2.4.2/24"},
        )

# pylint: disable=W0108
topos = {
    "topology": (lambda: Topology())
}
