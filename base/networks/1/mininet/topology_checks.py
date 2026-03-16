from time import sleep

from mininet.link import TCLink
from mininet.log import output, setLogLevel
from mininet.net import Mininet

from networks import Topology

PYTHON_INTERPREPTER = "/opt/p4/p4dev-python-venv/bin/python3"
TEST_DELAY_PRE = 60
TEST_DELAY_NEXT = 1
TEST_DELAY_POST = 10

if __name__ == "__main__":
    setLogLevel("info")

    topology = Topology()

    network = Mininet(
        topo=topology,
        link=TCLink,
        autoSetMacs=False,
    )
    network.start()

    as7h1 = network.getNodeByName("as7h1")
    as1h1 = network.getNodeByName("as1h1")

    output("*** Generating traffic\n")

    sleep(TEST_DELAY_PRE)

    as7h1.cmd(f"{PYTHON_INTERPREPTER} tests/1/checks/traffic_generator_1.py")

    sleep(TEST_DELAY_NEXT)

    as1h1.cmd(f"{PYTHON_INTERPREPTER} tests/1/checks/traffic_generator_2.py")

    sleep(TEST_DELAY_POST)

    network.stop()
