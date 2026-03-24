import json
import os


SCRIPT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))
TEMP_DIRECTORY = os.path.join(SCRIPT_DIRECTORY, "temp")
RESULTS_DIRECTORY = os.path.join(SCRIPT_DIRECTORY, "results")

BGP_JSON_FILE = os.path.join(RESULTS_DIRECTORY, "bgp_convergence.json")
SDX_JSON_FILE = os.path.join(RESULTS_DIRECTORY, "sdx_convergence.json")
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


def main():
    bgp_data = load_json(BGP_JSON_FILE)
    sdx_data = load_json(SDX_JSON_FILE)

    comparison = {
        "bgp_only": bgp_data,
        "sdx_fast": sdx_data,
        "delta_sdx_minus_bgp": {
            "detection_time_s": metric_delta(bgp_data, sdx_data, "detection_time_s"),
            "blackout_duration_s": metric_delta(bgp_data, sdx_data, "blackout_duration_s"),
            "convergence_time_s": metric_delta(bgp_data, sdx_data, "convergence_time_s"),
            "bgp_sync_time_s": metric_delta(bgp_data, sdx_data, "bgp_sync_time_s"),
            "packet_loss_count": metric_delta(bgp_data, sdx_data, "packet_loss_count"),
            "post_recovery_avg_rtt_ms": metric_delta(bgp_data, sdx_data, "post_recovery_avg_rtt_ms"),
        },
    }

    with open(COMPARE_JSON_FILE, "w", encoding="utf-8") as file:
        json.dump(comparison, file, indent=2)

    lines = [
        "# Recovery Comparison",
        "",
        "| Metric | BGP Only | SDX Fast Recovery | SDX - BGP |",
        "| --- | ---: | ---: | ---: |",
    ]

    for key, label in [
        ("detection_time_s", "Detection time (s)"),
        ("blackout_duration_s", "Blackout duration (s)"),
        ("convergence_time_s", "Traffic recovery time (s)"),
        ("bgp_sync_time_s", "BGP sync time (s)"),
        ("packet_loss_count", "Packet loss count"),
        ("post_recovery_avg_rtt_ms", "Post-recovery RTT (ms)"),
    ]:
        lines.append(
            f"| {label} | {bgp_data.get(key)} | {sdx_data.get(key)} | {comparison['delta_sdx_minus_bgp'].get(key)} |"
        )

    with open(COMPARE_MD_FILE, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")

    print(f"Saved comparison JSON to {COMPARE_JSON_FILE}")
    print(f"Saved comparison Markdown to {COMPARE_MD_FILE}")


if __name__ == "__main__":
    main()
