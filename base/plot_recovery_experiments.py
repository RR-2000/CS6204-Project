#!/usr/bin/env python3
"""Generate graphs and comparisons from recovery experiment JSON outputs.

Usage:
    python plot_recovery_experiments.py \
        --input recovery_comparison.json \
        --outdir recovery_plots
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


MODE_KEYS = {
    "bgp_only": "BGP_ONLY",
    "sdx_fast": "SDX_FAST",
}

CORE_METRICS = [
    ("detection_time_s", "Detection (s)"),
    ("blackout_duration_s", "Blackout (s)"),
    ("convergence_time_s", "Convergence (s)"),
    ("stable_convergence_time_s", "Stable Conv (s)"),
    ("bgp_sync_time_s", "BGP Sync (s)"),
]

RELIABILITY_METRICS = [
    ("packet_loss_count", "Packet Loss"),
    ("longest_loss_burst_packets", "Max Loss Burst (pkts)"),
    ("recovery_flap_count", "Recovery Flaps"),
    ("recovery_success_rate", "Recovery Success"),
]

LATENCY_METRICS = [
    ("baseline_avg_rtt_ms", "Baseline Avg RTT (ms)"),
    ("post_recovery_avg_rtt_ms", "Post-Recovery Avg RTT (ms)"),
    ("post_recovery_window_avg_rtt_ms", "60s Window Avg RTT (ms)"),
    ("post_recovery_window_p95_rtt_ms", "60s Window P95 RTT (ms)"),
    # ("post_recovery_window_jitter_ms", "60s Window Jitter (ms)"),
    ("rtt_inflation_ratio", "RTT Inflation (x)"),
    # ("second_phase_rtt_inflation_ratio", "Phase2 RTT Inflation (x)"),
]

LOWER_IS_BETTER_METRICS = [
    ("blackout_duration_s", "Blackout Duration"),
    ("convergence_time_s", "Convergence Time"),
    ("stable_convergence_time_s", "Stable Convergence Time"),
    ("bgp_sync_time_s", "BGP Sync Time"),
    ("packet_loss_count", "Packet Loss Count"),
    ("longest_loss_burst_packets", "Longest Loss Burst"),
    ("recovery_flap_count", "Recovery Flaps"),
    ("post_recovery_avg_rtt_ms", "Post-Recovery Avg RTT"),
    ("post_recovery_p95_rtt_ms", "Post-Recovery P95 RTT"),
    ("post_recovery_window_avg_rtt_ms", "Window Avg RTT"),
    ("post_recovery_window_p95_rtt_ms", "Window P95 RTT"),
    ("post_recovery_window_jitter_ms", "Window Jitter"),
    ("rtt_inflation_ratio", "RTT Inflation"),
    ("second_phase_rtt_inflation_ratio", "Phase2 RTT Inflation"),
]

LOSS_PENALTY_MS = 1000.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot recovery experiment results")
    parser.add_argument(
        "--input",
        default="recovery_comparison.json",
        help="Path to recovery_comparison.json",
    )
    parser.add_argument(
        "--outdir",
        default=None,
        help="Output directory (default: <input-dir>/recovery_plots_<timestamp>)",
    )
    return parser.parse_args()


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_get(payload: Dict[str, Any], key: str) -> Optional[float]:
    val = payload.get(key)
    if isinstance(val, (int, float)) and not math.isnan(val):
        return float(val)
    return None


def extract_modes(direction_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for key in MODE_KEYS:
        if isinstance(direction_data.get(key), dict):
            out[key] = direction_data[key]
    return out


def mk_plot_dir(input_path: Path, outdir_arg: Optional[str]) -> Path:
    if outdir_arg:
        outdir = Path(outdir_arg)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        outdir = input_path.parent / f"recovery_plots_{stamp}"
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir


def grouped_bar_plot(
    title: str,
    metrics: List[Tuple[str, str]],
    mode_payloads: Dict[str, Dict[str, Any]],
    output_file: Path,
    value_scale: Dict[str, float] | None = None,
) -> None:
    labels = [pretty for _, pretty in metrics]
    x = list(range(len(metrics)))
    width = 0.36

    fig, ax = plt.subplots(figsize=(max(10, len(metrics) * 1.5), 5.2))

    colors = {
        "bgp_only": "#3a6ea5",
        "sdx_fast": "#d95f02",
    }

    for idx, mode_key in enumerate(["bgp_only", "sdx_fast"]):
        payload = mode_payloads.get(mode_key, {})
        vals = []
        for metric_key, _ in metrics:
            raw = safe_get(payload, metric_key)
            if raw is None:
                vals.append(float("nan"))
            else:
                scale = 1.0 if value_scale is None else value_scale.get(metric_key, 1.0)
                vals.append(raw * scale)

        offset = -width / 2 if idx == 0 else width / 2
        ax.bar(
            [p + offset for p in x],
            vals,
            width,
            label=MODE_KEYS[mode_key],
            color=colors[mode_key],
            alpha=0.9,
        )

    ax.set_title(title)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_file, dpi=160)
    plt.close(fig)


def plot_timeline_probe(direction: str, mode_payloads: Dict[str, Dict[str, Any]], output_file: Path) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 4.8))

    for mode_key, color in [("bgp_only", "#3a6ea5"), ("sdx_fast", "#d95f02")]:
        payload = mode_payloads.get(mode_key, {})
        timeline = payload.get("probe_timeline") or []
        if not timeline:
            continue
        ts = [pt.get("t_s") for pt in timeline if isinstance(pt.get("t_s"), (int, float))]
        ys = [1 if pt.get("ok") else 0 for pt in timeline if isinstance(pt.get("t_s"), (int, float))]
        if not ts:
            continue
        ax.step(ts, ys, where="post", label=MODE_KEYS[mode_key], linewidth=2.0, color=color)

    ax.set_yticks([0, 1])
    ax.set_yticklabels(["loss", "success"], fontsize=13)
    ax.set_xlabel("Time Since Link-Down (s)", fontsize=14)
    ax.set_ylabel("Probe Outcome", fontsize=14)
    ax.set_title(f"{direction.title()} Probe Timeline (Detection + Recovery)", fontsize=17)
    ax.tick_params(axis="x", labelsize=13)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=13)
    fig.tight_layout()
    fig.savefig(output_file, dpi=160)
    plt.close(fig)


def collect_rtts(timeline: Iterable[Dict[str, Any]]) -> List[float]:
    out = []
    for pt in timeline:
        rtt = pt.get("rtt_ms")
        if isinstance(rtt, (int, float)):
            out.append(float(rtt))
    return out


def plot_window_rtt(direction: str, mode_payloads: Dict[str, Dict[str, Any]], output_file: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))

    for mode_key, color in [("bgp_only", "#3a6ea5"), ("sdx_fast", "#d95f02")]:
        payload = mode_payloads.get(mode_key, {})
        timeline = payload.get("post_recovery_window_timeline") or []
        xs = []
        ys = []
        for pt in timeline:
            t_s = pt.get("t_s")
            rtt = pt.get("rtt_ms")
            if isinstance(t_s, (int, float)) and isinstance(rtt, (int, float)):
                xs.append(float(t_s))
                ys.append(float(rtt))
        if xs:
            ax.plot(xs, ys, label=MODE_KEYS[mode_key], linewidth=1.5, alpha=0.95, color=color)

    ax.set_xlabel("Time Since Stable Recovery (s)")
    ax.set_ylabel("RTT (ms)")
    ax.set_title(f"{direction.title()} Post-Recovery Window RTT Time Series")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_file, dpi=160)
    plt.close(fig)


def cdf(values: List[float]) -> Tuple[List[float], List[float]]:
    if not values:
        return [], []
    vals = sorted(values)
    n = len(vals)
    ys = [(i + 1) / n for i in range(n)]
    return vals, ys


def _combined_timeline_points(payload: Dict[str, Any]) -> List[Tuple[float, Optional[float], bool]]:
    points: List[Tuple[float, Optional[float], bool]] = []

    for pt in payload.get("probe_timeline") or []:
        t_s = pt.get("t_s")
        ok = bool(pt.get("ok"))
        rtt = pt.get("rtt_ms")
        if not isinstance(t_s, (int, float)):
            continue
        rtt_val = float(rtt) if isinstance(rtt, (int, float)) else None
        points.append((float(t_s), rtt_val, ok))

    stable_conv = payload.get("stable_convergence_time_s")
    stable_offset = float(stable_conv) if isinstance(stable_conv, (int, float)) else 0.0
    for pt in payload.get("post_recovery_window_timeline") or []:
        t_s = pt.get("t_s")
        ok = bool(pt.get("ok"))
        rtt = pt.get("rtt_ms")
        if not isinstance(t_s, (int, float)):
            continue
        rtt_val = float(rtt) if isinstance(rtt, (int, float)) else None
        points.append((stable_offset + float(t_s), rtt_val, ok))

    points.sort(key=lambda x: x[0])
    return points


def combined_rtt_metrics(payload: Dict[str, Any], loss_penalty_ms: float = LOSS_PENALTY_MS) -> Dict[str, Optional[float]]:
    points = _combined_timeline_points(payload)
    if not points:
        return {
            "combined_total_probes": 0,
            "combined_success_probes": 0,
            "combined_loss_probes": 0,
            "combined_success_rtt_avg_ms": None,
            "combined_effective_rtt_ms": None,
        }

    success_rtts = [rtt for _, rtt, ok in points if ok and rtt is not None]
    total = len(points)
    success = len(success_rtts)
    losses = total - success

    success_avg = (sum(success_rtts) / success) if success > 0 else None
    effective_sum = sum(success_rtts) + losses * loss_penalty_ms
    effective_avg = effective_sum / total if total > 0 else None

    return {
        "combined_total_probes": float(total),
        "combined_success_probes": float(success),
        "combined_loss_probes": float(losses),
        "combined_success_rtt_avg_ms": success_avg,
        "combined_effective_rtt_ms": effective_avg,
    }


def plot_combined_rtt_timeline(direction: str, mode_payloads: Dict[str, Dict[str, Any]], output_file: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5.2))

    for mode_key, color in [("bgp_only", "#3a6ea5"), ("sdx_fast", "#d95f02")]:
        payload = mode_payloads.get(mode_key, {})
        points = _combined_timeline_points(payload)
        xs = [t for t, rtt, ok in points if ok and rtt is not None]
        ys = [rtt for _, rtt, ok in points if ok and rtt is not None]
        if xs:
            ax.plot(xs, ys, label=MODE_KEYS[mode_key], linewidth=1.6, alpha=0.95, color=color)

    ax.set_xlabel("Time Since Failure Injection (s)")
    ax.set_ylabel("RTT (ms)")
    ax.set_title(f"{direction.title()} Combined RTT Timeline (Failure to End of Window)")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_file, dpi=160)
    plt.close(fig)


def plot_combined_rtt_summary(direction: str, mode_payloads: Dict[str, Dict[str, Any]], output_file: Path) -> None:
    summary = {
        mode_key: combined_rtt_metrics(payload)
        for mode_key, payload in mode_payloads.items()
    }

    metrics = [
        ("combined_success_rtt_avg_ms", "Combined Success RTT Avg (ms)"),
        ("combined_effective_rtt_ms", f"Combined Effective RTT (ms, loss={int(LOSS_PENALTY_MS)}ms)"),
    ]
    x = list(range(len(metrics)))
    width = 0.36

    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    colors = {
        "bgp_only": "#3a6ea5",
        "sdx_fast": "#d95f02",
    }

    for idx, mode_key in enumerate(["bgp_only", "sdx_fast"]):
        vals = []
        for metric_key, _ in metrics:
            vals.append(safe_get(summary.get(mode_key, {}), metric_key) or float("nan"))
        offset = -width / 2 if idx == 0 else width / 2
        ax.bar(
            [p + offset for p in x],
            vals,
            width,
            label=MODE_KEYS[mode_key],
            color=colors[mode_key],
            alpha=0.9,
        )

    ax.set_title(f"{direction.title()} Combined RTT Summary")
    ax.set_xticks(x)
    ax.set_xticklabels([m[1] for m in metrics], rotation=15, ha="right")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_file, dpi=160)
    plt.close(fig)


def plot_sdx_advantage_summary(data: Dict[str, Any], output_file: Path) -> None:
    labels: List[str] = []
    improvements: List[float] = []

    for direction in ["forward", "reverse"]:
        section = data.get(direction)
        if not isinstance(section, dict):
            continue
        bgp = section.get("bgp_only", {}) if isinstance(section.get("bgp_only"), dict) else {}
        sdx = section.get("sdx_fast", {}) if isinstance(section.get("sdx_fast"), dict) else {}

        for metric_key, metric_name in LOWER_IS_BETTER_METRICS:
            sdx_val = safe_get(sdx, metric_key)
            bgp_val = safe_get(bgp, metric_key)
            imp = pct_improvement(sdx_val, bgp_val, lower_is_better=True)
            if imp is None or imp <= 0:
                continue
            labels.append(f"{direction[:3]}.{metric_name}")
            improvements.append(imp)

        bgp_combined = combined_rtt_metrics(bgp)
        sdx_combined = combined_rtt_metrics(sdx)
        for metric_key, metric_name in [
            ("combined_success_rtt_avg_ms", "Combined Success RTT Avg"),
            ("combined_effective_rtt_ms", "Combined Effective RTT"),
        ]:
            imp = pct_improvement(
                safe_get(sdx_combined, metric_key),
                safe_get(bgp_combined, metric_key),
                lower_is_better=True,
            )
            if imp is None or imp <= 0:
                continue
            labels.append(f"{direction[:3]}.{metric_name}")
            improvements.append(imp)

    if not labels:
        return

    fig, ax = plt.subplots(figsize=(max(11, len(labels) * 0.45), 5.3))
    ax.bar(range(len(labels)), improvements, color="#2ca02c", alpha=0.9)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.set_ylabel("Improvement vs BGP_ONLY (%)")
    ax.set_title("Metrics Where SDX_FAST Outperforms BGP_ONLY")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_file, dpi=160)
    plt.close(fig)


def plot_window_rtt_cdf(direction: str, mode_payloads: Dict[str, Dict[str, Any]], output_file: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))

    for mode_key, color in [("bgp_only", "#3a6ea5"), ("sdx_fast", "#d95f02")]:
        timeline = (mode_payloads.get(mode_key, {}) or {}).get("post_recovery_window_timeline") or []
        vals = collect_rtts(timeline)
        xs, ys = cdf(vals)
        if xs:
            ax.plot(xs, ys, label=MODE_KEYS[mode_key], linewidth=2, color=color)

    ax.set_xlabel("RTT (ms)")
    ax.set_ylabel("CDF")
    ax.set_title(f"{direction.title()} Post-Recovery Window RTT CDF")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_file, dpi=160)
    plt.close(fig)


def plot_delta_bars(direction: str, delta_payload: Dict[str, Any], output_file: Path) -> None:
    if not delta_payload:
        return

    keys = []
    vals = []
    for k, v in delta_payload.items():
        if isinstance(v, (int, float)):
            keys.append(k)
            vals.append(float(v))

    if not keys:
        return

    fig, ax = plt.subplots(figsize=(max(9, len(keys) * 1.2), 4.8))
    colors = ["#2ca02c" if v < 0 else "#d62728" for v in vals]
    ax.bar(range(len(keys)), vals, color=colors, alpha=0.9)
    ax.axhline(0, color="black", linewidth=1.0)
    ax.set_xticks(range(len(keys)))
    ax.set_xticklabels(keys, rotation=25, ha="right")
    ax.set_title(f"{direction.title()} Delta: SDX_FAST - BGP_ONLY")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_file, dpi=160)
    plt.close(fig)


def pct_improvement(sdx: Optional[float], bgp: Optional[float], lower_is_better: bool) -> Optional[float]:
    if sdx is None or bgp is None or bgp == 0:
        return None
    if lower_is_better:
        return 100.0 * (bgp - sdx) / bgp
    return 100.0 * (sdx - bgp) / bgp


def write_report(data: Dict[str, Any], outdir: Path, plots: List[Path]) -> None:
    lines: List[str] = []
    lines.append("# Recovery Experiment Plot Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    compare_metrics = [
        ("blackout_duration_s", "Blackout", True),
        ("convergence_time_s", "Convergence", True),
        ("packet_loss_count", "Packet Loss", True),
        ("post_recovery_window_p95_rtt_ms", "60s Window P95 RTT", True),
        ("post_recovery_window_jitter_ms", "60s Window Jitter", True),
    ]

    for direction in ["forward", "reverse"]:
        section = data.get(direction, {}) if isinstance(data.get(direction), dict) else {}
        bgp = section.get("bgp_only", {}) if isinstance(section.get("bgp_only"), dict) else {}
        sdx = section.get("sdx_fast", {}) if isinstance(section.get("sdx_fast"), dict) else {}

        lines.append(f"## {direction.title()}")
        lines.append("")

        for key, label, lower_is_better in compare_metrics:
            imp = pct_improvement(safe_get(sdx, key), safe_get(bgp, key), lower_is_better=lower_is_better)
            if imp is None:
                lines.append(f"- {label}: N/A")
            else:
                lines.append(f"- {label}: {imp:+.2f}% (SDX vs BGP)")

        path_note = "unknown"
        traceroute = (bgp.get("pre_failure_traceroute") or "") + (sdx.get("pre_failure_traceroute") or "")
        if "command not found" in traceroute:
            path_note = "traceroute missing in host images (hop-path comparisons unavailable)"
        lines.append(f"- Path diagnostics: {path_note}")

        bgp_combined = combined_rtt_metrics(bgp)
        sdx_combined = combined_rtt_metrics(sdx)
        eff_imp = pct_improvement(
            safe_get(sdx_combined, "combined_effective_rtt_ms"),
            safe_get(bgp_combined, "combined_effective_rtt_ms"),
            lower_is_better=True,
        )
        suc_imp = pct_improvement(
            safe_get(sdx_combined, "combined_success_rtt_avg_ms"),
            safe_get(bgp_combined, "combined_success_rtt_avg_ms"),
            lower_is_better=True,
        )
        if suc_imp is not None:
            lines.append(f"- Combined success-RTT improvement: {suc_imp:+.2f}% (SDX vs BGP)")
        if eff_imp is not None:
            lines.append(f"- Combined effective RTT improvement: {eff_imp:+.2f}% (SDX vs BGP)")
        lines.append("")

    lines.append("## Generated Plots")
    lines.append("")
    for p in sorted(plots):
        lines.append(f"- {p.name}")

    (outdir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    outdir = mk_plot_dir(input_path, args.outdir)
    data = load_json(input_path)

    generated: List[Path] = []

    for direction in ["forward", "reverse"]:
        section = data.get(direction)
        if not isinstance(section, dict):
            continue

        modes = extract_modes(section)
        if not modes:
            continue

        core_out = outdir / f"{direction}_core_recovery.png"
        grouped_bar_plot(
            title=f"{direction.title()} Core Recovery Metrics",
            metrics=CORE_METRICS,
            mode_payloads=modes,
            output_file=core_out,
        )
        generated.append(core_out)

        reliability_out = outdir / f"{direction}_reliability.png"
        grouped_bar_plot(
            title=f"{direction.title()} Reliability Metrics",
            metrics=RELIABILITY_METRICS,
            mode_payloads=modes,
            output_file=reliability_out,
            value_scale={"recovery_success_rate": 100.0},
        )
        generated.append(reliability_out)

        latency_out = outdir / f"{direction}_latency_summary.png"
        grouped_bar_plot(
            title=f"Latency Summary",
            metrics=LATENCY_METRICS,
            mode_payloads=modes,
            output_file=latency_out,
        )
        generated.append(latency_out)

        timeline_out = outdir / f"{direction}_probe_timeline.png"
        plot_timeline_probe(direction, modes, timeline_out)
        generated.append(timeline_out)

        window_ts_out = outdir / f"{direction}_window_rtt_timeseries.png"
        plot_window_rtt(direction, modes, window_ts_out)
        generated.append(window_ts_out)

        window_cdf_out = outdir / f"{direction}_window_rtt_cdf.png"
        plot_window_rtt_cdf(direction, modes, window_cdf_out)
        generated.append(window_cdf_out)

        combined_ts_out = outdir / f"{direction}_combined_rtt_timeline.png"
        plot_combined_rtt_timeline(direction, modes, combined_ts_out)
        generated.append(combined_ts_out)

        combined_summary_out = outdir / f"{direction}_combined_rtt_summary.png"
        plot_combined_rtt_summary(direction, modes, combined_summary_out)
        generated.append(combined_summary_out)

        delta_payload = section.get("delta_sdx_minus_bgp")
        if isinstance(delta_payload, dict):
            delta_out = outdir / f"{direction}_delta_sdx_minus_bgp.png"
            plot_delta_bars(direction, delta_payload, delta_out)
            if delta_out.exists():
                generated.append(delta_out)

    sdx_adv_out = outdir / "sdx_advantage_metrics.png"
    plot_sdx_advantage_summary(data, sdx_adv_out)
    if sdx_adv_out.exists():
        generated.append(sdx_adv_out)

    write_report(data, outdir, generated)

    summary = {
        "input": str(input_path),
        "output_dir": str(outdir),
        "plots_generated": [p.name for p in generated],
        "report": "report.md",
    }
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
