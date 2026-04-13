import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def load_data(json_path: Path) -> dict:
    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def plot_direction_time_metrics(data: dict, direction: str, out_dir: Path) -> Path:
    block = data[direction]
    bgp = block["bgp_only"]
    sdx = block["sdx_fast"]

    metrics = [
        "detection_time_s",
        "blackout_duration_s",
        "convergence_time_s",
        # "bgp_sync_time_s",
    ]
    labels = [
        "Detection",
        "Blackout",
        "Convergence",
        # "BGP Sync",
    ]

    bgp_vals = [bgp[m] for m in metrics]
    sdx_vals = [sdx[m] for m in metrics]

    x = np.arange(len(metrics))
    width = 0.36

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x - width / 2, bgp_vals, width, label="BGP_ONLY", color="#d95f02")
    ax.bar(x + width / 2, sdx_vals, width, label="SDX_FAST", color="#1b9e77")

    ax.set_title(f"{direction.capitalize()} Recovery Timing Comparison")
    ax.set_ylabel("Time (seconds)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend()

    fig.tight_layout()
    out_path = out_dir / f"{direction}_timing_comparison.png"
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


def plot_packet_stats(data: dict, out_dir: Path) -> Path:
    directions = ["forward", "reverse"]
    x = np.arange(len(directions))
    width = 0.15

    bgp_loss = [data[d]["bgp_only"]["packet_loss_count"] for d in directions]
    sdx_loss = [data[d]["sdx_fast"]["packet_loss_count"] for d in directions]
    bgp_sent = [data[d]["bgp_only"]["packets_sent"] for d in directions]
    sdx_sent = [data[d]["sdx_fast"]["packets_sent"] for d in directions]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x - 0.5 * width, bgp_loss, width, label="BGP loss", color="#d95f02")
    ax.bar(x - 1.5 * width, bgp_sent, width, label="BGP sent", color="#fc8d62")
    ax.bar(x + 1.0 * width, sdx_sent, width, label="SDX sent", color="#66c2a5")
    ax.bar(x + 2.0 * width, sdx_loss, width, label="SDX loss", color="#1b9e77")

    ax.set_title("Packet Loss and Packet Count by Direction")
    ax.set_ylabel("Packet Count")
    ax.set_xticks(x)
    ax.set_xticklabels([d.capitalize() for d in directions])
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend(ncol=2)

    fig.tight_layout()
    out_path = out_dir / "packet_comparison.png"
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


def plot_rtt(data: dict, out_dir: Path) -> Path:
    directions = ["forward", "reverse"]
    x = np.arange(len(directions))
    width = 0.36

    bgp_rtt = [data[d]["bgp_only"]["post_recovery_avg_rtt_ms"] for d in directions]
    sdx_rtt = [data[d]["sdx_fast"]["post_recovery_avg_rtt_ms"] for d in directions]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x - width / 2, bgp_rtt, width, label="BGP_ONLY", color="#7570b3")
    ax.bar(x + width / 2, sdx_rtt, width, label="SDX_FAST", color="#1b9e77")

    ax.set_title("Post-Recovery Average RTT")
    ax.set_ylabel("RTT (ms)")
    ax.set_xticks(x)
    ax.set_xticklabels([d.capitalize() for d in directions])
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend()

    fig.tight_layout()
    out_path = out_dir / "rtt_comparison.png"
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


def plot_delta_summary(data: dict, out_dir: Path) -> Path:
    metrics = [
        "blackout_duration_s",
        "convergence_time_s",
        "bgp_sync_time_s",
        "packet_loss_count",
    ]
    labels = ["Blackout", "Convergence", "BGP Sync", "Pkt Loss"]

    forward_vals = [data["forward"]["delta_sdx_minus_bgp"][m] for m in metrics]
    reverse_vals = [data["reverse"]["delta_sdx_minus_bgp"][m] for m in metrics]

    x = np.arange(len(metrics))
    width = 0.36

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x - width / 2, forward_vals, width, label="Forward", color="#1f78b4")
    ax.bar(x + width / 2, reverse_vals, width, label="Reverse", color="#33a02c")

    ax.axhline(0, color="black", linewidth=1)
    ax.set_title("SDX_FAST - BGP_ONLY Delta Summary")
    ax.set_ylabel("Delta (negative is better for these metrics)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend()

    fig.tight_layout()
    out_path = out_dir / "delta_summary.png"
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


def main() -> None:
    base_dir = Path(__file__).resolve().parent / "results"
    json_path = base_dir / "recovery_comparison.json"
    out_dir = base_dir / "graphs"
    out_dir.mkdir(parents=True, exist_ok=True)

    data = load_data(json_path)

    generated = [
        plot_direction_time_metrics(data, "forward", out_dir),
        plot_direction_time_metrics(data, "reverse", out_dir),
        plot_packet_stats(data, out_dir),
        plot_rtt(data, out_dir),
        plot_delta_summary(data, out_dir),
    ]

    print("Generated graph files:")
    for p in generated:
        print(f"- {p.name}")


if __name__ == "__main__":
    main()
