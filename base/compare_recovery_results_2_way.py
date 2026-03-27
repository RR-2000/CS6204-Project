import json
import os


SCRIPT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))
TEMP_DIRECTORY = os.path.join(SCRIPT_DIRECTORY, "temp")
RESULTS_DIRECTORY = os.path.join(SCRIPT_DIRECTORY, "results")

DIRECTIONS = ["forward", "reverse"]

COMPARE_JSON_FILE = os.path.join(RESULTS_DIRECTORY, "recovery_comparison.json")
COMPARE_MD_FILE = os.path.join(RESULTS_DIRECTORY, "recovery_comparison.md")


def load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def metric_delta(bgp_data, sdx_data, key):
    bgp_value = bgp_data.get(key)
    sdx_value = sdx_data.get(key)
    if bgp_value is None or sdx_value is None:
        return None
    return round(sdx_value - bgp_value, 2)


def build_comparison(direction):
    bgp_path = os.path.join(RESULTS_DIRECTORY, f"bgp_convergence_{direction}.json")
    sdx_path = os.path.join(RESULTS_DIRECTORY, f"sdx_convergence_{direction}.json")
    bgp_data = load_json(bgp_path)
    sdx_data = load_json(sdx_path)

    return {
        "direction": direction,
        "bgp_only": bgp_data,
        "sdx_fast": sdx_data,
        "delta_sdx_minus_bgp": {
            "detection_time_s": metric_delta(bgp_data, sdx_data, "detection_time_s"),
            "blackout_duration_s": metric_delta(bgp_data, sdx_data, "blackout_duration_s"),
            "convergence_time_s": metric_delta(bgp_data, sdx_data, "convergence_time_s"),
            "bgp_sync_time_s": metric_delta(bgp_data, sdx_data, "bgp_sync_time_s"),
            "packet_loss_count": metric_delta(bgp_data, sdx_data, "packet_loss_count"),
            "total_packet_count": metric_delta(bgp_data, sdx_data, "packets_sent"),
            "post_recovery_avg_rtt_ms": metric_delta(
                bgp_data,
                sdx_data,
                "post_recovery_avg_rtt_ms",
            ),
        },
    }


def main():
    comparisons = {direction: build_comparison(direction) for direction in DIRECTIONS}

    with open(COMPARE_JSON_FILE, "w", encoding="utf-8") as file:
        json.dump(comparisons, file, indent=2)

    lines = ["# Recovery Comparison", ""]
    for direction in DIRECTIONS:
        comparison = comparisons[direction]
        bgp_data = comparison["bgp_only"]
        sdx_data = comparison["sdx_fast"]
        deltas = comparison["delta_sdx_minus_bgp"]

        lines.extend(
            [
                f"## {direction.title()} Direction",
                "",
                "| Metric | BGP Only | SDX Fast Recovery | SDX - BGP |",
                "| --- | ---: | ---: | ---: |",
            ]
        )

        for key, label in [
            ("detection_time_s", "Detection time (s)"),
            ("blackout_duration_s", "Blackout duration (s)"),
            ("convergence_time_s", "Traffic recovery time (s)"),
            ("bgp_sync_time_s", "BGP sync time (s)"),
            ("packet_loss_count", "Packet loss count"),
            ("total_packet_count", "Total packets sent"),
            ("post_recovery_avg_rtt_ms", "Post-recovery RTT (ms)"),
        ]:
            lines.append(
                f"| {label} | {bgp_data.get(key)} | {sdx_data.get(key)} | {deltas.get(key)} |"
            )
        lines.append("")

    with open(COMPARE_MD_FILE, "w", encoding="utf-8") as file:
        file.write("\n".join(lines).rstrip() + "\n")

    print(f"Saved comparison JSON to {COMPARE_JSON_FILE}")
    print(f"Saved comparison Markdown to {COMPARE_MD_FILE}")


if __name__ == "__main__":
    main()
