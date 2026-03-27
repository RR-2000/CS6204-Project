NETWORKS_DIR = networks

TASKS_DIR = tasks

SRC_MININET_DIR = mininet
SRC_P4_DIR = p4
SRC_CONTROLLER_DIR = p4rt_controller

BUILD_DIR = build
BUILD_P4_DIR = $(BUILD_DIR)/p4

TEMP_DIR = temp
TEMP_P4_SWITCH_DIR = $(TEMP_DIR)/p4_switch
TEMP_P4RT_CONTROLLER_DIR = $(TEMP_DIR)/p4rt_controller

TESTS_DIR = tests
TESTS_CHECKS_DIR = checks

P4_COMPILER = p4c-bm2-ss

CLI_NETWORK_FILE = $(SRC_MININET_DIR)/topology_cli.py

CHECKS_NETWORK_FILE = $(SRC_MININET_DIR)/topology_checks.py
CHECKS_CASES_FILE = $(TESTS_CHECKS_DIR)/traffic_checker.py
CONVERGENCE_NETWORK_FILE = $(SRC_MININET_DIR)/topology_bgp_convergence_test.py

PYTHON_INTERPRETER = /opt/p4/p4dev-python-venv/bin/python3

IXP_SWITCH_P4_COMPILER_IN_FILE = $(SRC_P4_DIR)/ixp_switch.p4
IXP_SWITCH_P4_COMPILER_OUT_NAME = ixp_switch
IXP_SWITCH_P4_COMPILER_ARGS += --p4v 16
IXP_SWITCH_P4_COMPILER_ARGS += --p4runtime-files $(BUILD_P4_DIR)/$(IXP_SWITCH_P4_COMPILER_OUT_NAME).p4info.txtpb
IXP_SWITCH_P4_COMPILER_ARGS += -o $(BUILD_P4_DIR)/$(IXP_SWITCH_P4_COMPILER_OUT_NAME).json

IXP1S1_CONTROLLER_SCRIPT_FILE = $(SRC_CONTROLLER_DIR)/ixp1s1_controller.py
IXP2S1_CONTROLLER_SCRIPT_FILE = $(SRC_CONTROLLER_DIR)/ixp2s1_controller.py
IXP1S1_CONTROLLER_TEMP_DIR = $(TEMP_P4RT_CONTROLLER_DIR)/ixp1s1
IXP2S1_CONTROLLER_TEMP_DIR = $(TEMP_P4RT_CONTROLLER_DIR)/ixp2s1
IXP1S1_CONTROLLER_LOG_FILE = $(IXP1S1_CONTROLLER_TEMP_DIR)/ixp1s1_controller-stdout.log
IXP2S1_CONTROLLER_LOG_FILE = $(IXP2S1_CONTROLLER_TEMP_DIR)/ixp2s1_controller-stdout.log
IXP1S1_CONTROLLER_PID_FILE = $(IXP1S1_CONTROLLER_TEMP_DIR)/ixp1s1_controller.pid
IXP2S1_CONTROLLER_PID_FILE = $(IXP2S1_CONTROLLER_TEMP_DIR)/ixp2s1_controller.pid

.PHONY: \
	build-init \
	build-task-1 \
	build-clean \
	run-init \
	run-task-1 \
	run-checks-1 \
	run-convergence-1 \
	run-sdx-convergence-1 \
	run-compare-1 \
	run-stop \
	run-clean \
	clean \
	generate-submission

all:

build-init:
	mkdir -p $(BUILD_P4_DIR)

build-task-1:
	$(MAKE) build-clean
	$(MAKE) build-init
	$(P4_COMPILER) $(IXP_SWITCH_P4_COMPILER_ARGS) $(TASKS_DIR)/1/$(IXP_SWITCH_P4_COMPILER_IN_FILE)

build-task-2:
	$(MAKE) build-clean
	$(MAKE) build-init
	$(P4_COMPILER) $(IXP_SWITCH_P4_COMPILER_ARGS) $(TASKS_DIR)/2/$(IXP_SWITCH_P4_COMPILER_IN_FILE)

build-task-3:
	$(MAKE) build-clean
	$(MAKE) build-init
	$(P4_COMPILER) $(IXP_SWITCH_P4_COMPILER_ARGS) $(TASKS_DIR)/3/$(IXP_SWITCH_P4_COMPILER_IN_FILE)

build-clean:
	rm -rf $(BUILD_DIR)

run-init:
	mkdir -p $(TEMP_P4RT_CONTROLLER_DIR)
	mkdir -p $(TEMP_P4_SWITCH_DIR)

run-task-1:
	$(MAKE) run-clean
	$(MAKE) build-task-1
	$(MAKE) run-init
	mkdir -p $(IXP1S1_CONTROLLER_TEMP_DIR)
	$(PYTHON_INTERPRETER) $(TASKS_DIR)/1/$(IXP1S1_CONTROLLER_SCRIPT_FILE) > $(IXP1S1_CONTROLLER_LOG_FILE) 2>&1 & echo $$! > $(IXP1S1_CONTROLLER_PID_FILE)
	sudo $(PYTHON_INTERPRETER) $(NETWORKS_DIR)/1/$(CLI_NETWORK_FILE)
	$(MAKE) run-stop

run-task-2:
	$(MAKE) run-clean
	$(MAKE) build-task-2
	$(MAKE) run-init
	mkdir -p $(IXP1S1_CONTROLLER_TEMP_DIR)
	$(PYTHON_INTERPRETER) $(TASKS_DIR)/2/$(IXP1S1_CONTROLLER_SCRIPT_FILE) > $(IXP1S1_CONTROLLER_LOG_FILE) 2>&1 & echo $$! > $(IXP1S1_CONTROLLER_PID_FILE)
	sudo $(PYTHON_INTERPRETER) $(NETWORKS_DIR)/2/$(CLI_NETWORK_FILE)
	$(MAKE) run-stop

run-task-3:
	$(MAKE) run-clean
	$(MAKE) build-task-3
	$(MAKE) run-init
	mkdir -p $(IXP1S1_CONTROLLER_TEMP_DIR)
	mkdir -p $(IXP2S1_CONTROLLER_TEMP_DIR)
	$(PYTHON_INTERPRETER) $(TASKS_DIR)/3/$(IXP1S1_CONTROLLER_SCRIPT_FILE) > $(IXP1S1_CONTROLLER_LOG_FILE) 2>&1 & echo $$! > $(IXP1S1_CONTROLLER_PID_FILE)
	$(PYTHON_INTERPRETER) $(TASKS_DIR)/3/$(IXP2S1_CONTROLLER_SCRIPT_FILE) > $(IXP2S1_CONTROLLER_LOG_FILE) 2>&1 & echo $$! > $(IXP2S1_CONTROLLER_PID_FILE)
	sudo $(PYTHON_INTERPRETER) $(NETWORKS_DIR)/3/$(CLI_NETWORK_FILE)
	$(MAKE) run-stop

run-checks-1:
ifeq ("$(wildcard $(TESTS_DIR)/1/$(TESTS_CHECKS_DIR))", "")
	$(error The requested checks are unavailable)
endif
	$(MAKE) run-clean
	$(MAKE) build-task-1
	$(MAKE) run-init
	mkdir -p $(IXP1S1_CONTROLLER_TEMP_DIR)
	$(PYTHON_INTERPRETER) $(TASKS_DIR)/1/$(IXP1S1_CONTROLLER_SCRIPT_FILE) > $(IXP1S1_CONTROLLER_LOG_FILE) 2>&1 & echo $$! > $(IXP1S1_CONTROLLER_PID_FILE)
	sudo $(PYTHON_INTERPRETER) $(NETWORKS_DIR)/1/$(CHECKS_NETWORK_FILE)
	$(MAKE) run-stop
	$(PYTHON_INTERPRETER) $(TESTS_DIR)/1/$(CHECKS_CASES_FILE)

run-convergence-1:
	$(MAKE) run-clean
	$(MAKE) build-task-1
	$(MAKE) run-init
	mkdir -p $(IXP1S1_CONTROLLER_TEMP_DIR)
	ENABLE_SDX_FAST_FAILOVER=0 $(PYTHON_INTERPRETER) $(TASKS_DIR)/1/$(IXP1S1_CONTROLLER_SCRIPT_FILE) > $(IXP1S1_CONTROLLER_LOG_FILE) 2>&1 & echo $$! > $(IXP1S1_CONTROLLER_PID_FILE)
	sudo RECOVERY_MODE=bgp $(PYTHON_INTERPRETER) $(NETWORKS_DIR)/1/$(CONVERGENCE_NETWORK_FILE)
	$(MAKE) run-stop

run-convergence-2:
	$(MAKE) run-clean
	$(MAKE) build-task-2
	$(MAKE) run-init
	mkdir -p $(IXP1S1_CONTROLLER_TEMP_DIR)
	ENABLE_SDX_FAST_FAILOVER=0 $(PYTHON_INTERPRETER) $(TASKS_DIR)/2/$(IXP1S1_CONTROLLER_SCRIPT_FILE) > $(IXP1S1_CONTROLLER_LOG_FILE) 2>&1 & echo $$! > $(IXP1S1_CONTROLLER_PID_FILE)
	sudo RECOVERY_MODE=bgp $(PYTHON_INTERPRETER) $(NETWORKS_DIR)/2/$(CONVERGENCE_NETWORK_FILE)
	$(MAKE) run-stop

run-convergence-3:
	$(MAKE) run-clean
	$(MAKE) build-task-3
	$(MAKE) run-init
	mkdir -p $(IXP1S1_CONTROLLER_TEMP_DIR)
	mkdir -p $(IXP2S1_CONTROLLER_TEMP_DIR)
	$(PYTHON_INTERPRETER) $(TASKS_DIR)/3/$(IXP1S1_CONTROLLER_SCRIPT_FILE) > $(IXP1S1_CONTROLLER_LOG_FILE) 2>&1 & echo $$! > $(IXP1S1_CONTROLLER_PID_FILE)
	$(PYTHON_INTERPRETER) $(TASKS_DIR)/3/$(IXP2S1_CONTROLLER_SCRIPT_FILE) > $(IXP2S1_CONTROLLER_LOG_FILE) 2>&1 & echo $$! > $(IXP2S1_CONTROLLER_PID_FILE)
	sudo RECOVERY_MODE=bgp $(PYTHON_INTERPRETER) $(NETWORKS_DIR)/3/$(CONVERGENCE_NETWORK_FILE)
	$(MAKE) run-stop

run-sdx-convergence-1:
	$(MAKE) run-clean
	$(MAKE) build-task-1
	$(MAKE) run-init
	mkdir -p $(IXP1S1_CONTROLLER_TEMP_DIR)
	ENABLE_SDX_FAST_FAILOVER=1 $(PYTHON_INTERPRETER) $(TASKS_DIR)/1/$(IXP1S1_CONTROLLER_SCRIPT_FILE) > $(IXP1S1_CONTROLLER_LOG_FILE) 2>&1 & echo $$! > $(IXP1S1_CONTROLLER_PID_FILE)
	sudo RECOVERY_MODE=sdx $(PYTHON_INTERPRETER) $(NETWORKS_DIR)/1/$(CONVERGENCE_NETWORK_FILE)
	$(MAKE) run-stop

run-sdx-convergence-2:
	$(MAKE) run-clean
	$(MAKE) build-task-2
	$(MAKE) run-init
	mkdir -p $(IXP1S1_CONTROLLER_TEMP_DIR)
	ENABLE_SDX_FAST_FAILOVER=1 $(PYTHON_INTERPRETER) $(TASKS_DIR)/2/$(IXP1S1_CONTROLLER_SCRIPT_FILE) > $(IXP1S1_CONTROLLER_LOG_FILE) 2>&1 & echo $$! > $(IXP1S1_CONTROLLER_PID_FILE)
	sudo RECOVERY_MODE=sdx $(PYTHON_INTERPRETER) $(NETWORKS_DIR)/2/$(CONVERGENCE_NETWORK_FILE)
	$(MAKE) run-stop

run-sdx-convergence-3:
	$(MAKE) run-clean
	$(MAKE) build-task-3
	$(MAKE) run-init
	mkdir -p $(IXP1S1_CONTROLLER_TEMP_DIR)
	mkdir -p $(IXP2S1_CONTROLLER_TEMP_DIR)
	ENABLE_SDX_FAST_FAILOVER=1 $(PYTHON_INTERPRETER) $(TASKS_DIR)/3/$(IXP1S1_CONTROLLER_SCRIPT_FILE) > $(IXP1S1_CONTROLLER_LOG_FILE) 2>&1 & echo $$! > $(IXP1S1_CONTROLLER_PID_FILE)
	ENABLE_SDX_FAST_FAILOVER=1 $(PYTHON_INTERPRETER) $(TASKS_DIR)/3/$(IXP2S1_CONTROLLER_SCRIPT_FILE) > $(IXP2S1_CONTROLLER_LOG_FILE) 2>&1 & echo $$! > $(IXP2S1_CONTROLLER_PID_FILE)
	sudo RECOVERY_MODE=sdx $(PYTHON_INTERPRETER) $(NETWORKS_DIR)/3/$(CONVERGENCE_NETWORK_FILE)
	$(MAKE) run-stop

run-compare-1:
	$(MAKE) run-convergence-1
	$(MAKE) run-sdx-convergence-1
	$(PYTHON_INTERPRETER) compare_recovery_results.py
	$(MAKE) run-stop

run-compare-2:
	$(MAKE) run-convergence-2
	$(MAKE) run-sdx-convergence-2
	$(PYTHON_INTERPRETER) compare_recovery_results_2_way.py
	$(MAKE) run-stop

run-compare-3:
	$(MAKE) run-convergence-3
	$(MAKE) run-sdx-convergence-3
	$(PYTHON_INTERPRETER) compare_recovery_results_2_way.py
	$(MAKE) run-stop


run-stop:
	sudo mn -c
	for pid_file in $$(find temp -type f -name "*.pid"); do sudo kill -9 $$(cat $$pid_file | sed "s/^[[:space:]]*//;s/[[:space:]]*$$//") || true; sudo rm -rf $$pid_file; done

run-clean:
	$(MAKE) run-stop
	sudo find $(TEMP_DIR) -mindepth 1 -exec rm -rf {} + 2>/dev/null || true
	sudo rm -rf $(TEMP_DIR) 2>/dev/null || true

clean:
	$(MAKE) run-clean
	$(MAKE) build-clean

generate-submission:
	@read -p "Student ID: " student_id; \
	echo "*** Generating submission file"; \
	zip -r $$student_id.zip tasks;
