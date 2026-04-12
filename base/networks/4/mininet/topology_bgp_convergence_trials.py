import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_DIRECTORY = SCRIPT_DIRECTORY.parents[2]
TEMP_DIRECTORY = REPOSITORY_DIRECTORY / "temp"
RESULTS_DIRECTORY = REPOSITORY_DIRECTORY / "results"

RECOVERY_MODE = os.environ.get("RECOVERY_MODE", "bgp").strip().lower()
N_TRIALS = int(os.environ.get("N_TRIALS", "5"))

BASE_NAME_FWD = f"{RECOVERY_MODE}_convergence_forward"
BASE_NAME_REV = f"{RECOVERY_MODE}_convergence_reverse"

TEST_SCRIPT = SCRIPT_DIRECTORY / "topology_bgp_convergence_test.py"


def percentile(values, pct):
    if not values:
        return None
    ranked = sorted(values)
    if len(ranked) == 1:
        return ranked[0]
    idx = (len(ranked) - 1) * pct
    lo = int(idx)
    hi = min(lo + 1, len(ranked) - 1)
    frac = idx - lo
    return ranked[lo] * (1 - frac) + ranked[hi] * frac


def copy_if_exists(src: Path, dst: Path):
    if not src.exists():
        return False
    dst.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    return True


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None


def aggregate_direction(records, direction):
    success = [r for r in records if r.get("result") == "SUCCESS"]

    metrics = [
        "detection_time_s",
        "blackout_duration_s",
        "convergence_time_s",
        "stable_convergence_time_s",
        "bgp_sync_time_s",
        "control_data_plane_skew_s",
        "packet_loss_count",
        "post_recovery_avg_rtt_ms",
        "post_recovery_jitter_ms",
        "post_recovery_p95_rtt_ms",
        "rtt_inflation_ratio",
    ]

    summary = {
        "direction": direction,
        "trials_total": len(records),
        "trials_success": len(success),
        "trials_failed": len(records) - len(success),
        "success_rate": (len(success) / len(records)) if records else 0.0,
        "metrics": {},
    }

    for metric in metrics:
        values = [r.get(metric) for r in success if r.get(metric) is not None]
        if not values:
            continue
        summary["metrics"][metric] = {
            "min": min(values),
            "max": max(values),
            "mean": statistics.fmean(values),
            "p50": percentile(values, 0.50),
            "p90": percentile(values, 0.90),
            "p95": percentile(values, 0.95),
            "p99": percentile(values, 0.99),
        }

    return summary


def main():
    RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)

    all_forward = []
    all_reverse = []
    trial_artifacts = []

    for idx in range(N_TRIALS):
        print(f"=== Trial {idx + 1}/{N_TRIALS} ({RECOVERY_MODE}) ===", flush=True)
        started = time.time()

        proc = subprocess.run([sys.executable, str(TEST_SCRIPT)], check=False)
        elapsed = time.time() - started

        fwd_json = TEMP_DIRECTORY / f"{BASE_NAME_FWD}.json"
        rev_json = TEMP_DIRECTORY / f"{BASE_NAME_REV}.json"
        fwd_log = TEMP_DIRECTORY / f"{BASE_NAME_FWD}.log"
        rev_log = TEMP_DIRECTORY / f"{BASE_NAME_REV}.log"

        trial_suffix = f"_trial_{idx + 1:02d}"
        fwd_json_trial = RESULTS_DIRECTORY / f"{BASE_NAME_FWD}{trial_suffix}.json"
        rev_json_trial = RESULTS_DIRECTORY / f"{BASE_NAME_REV}{trial_suffix}.json"
        fwd_log_trial = RESULTS_DIRECTORY / f"{BASE_NAME_FWD}{trial_suffix}.log"
        rev_log_trial = RESULTS_DIRECTORY / f"{BASE_NAME_REV}{trial_suffix}.log"

        copy_if_exists(fwd_json, fwd_json_trial)
        copy_if_exists(rev_json, rev_json_trial)
        copy_if_exists(fwd_log, fwd_log_trial)
        copy_if_exists(rev_log, rev_log_trial)

        forward_payload = load_json(fwd_json_trial)
        reverse_payload = load_json(rev_json_trial)

        if forward_payload is not None:
            forward_payload["trial"] = idx + 1
            forward_payload["runner_rc"] = proc.returncode
            forward_payload["runner_elapsed_s"] = round(elapsed, 3)
            all_forward.append(forward_payload)

        if reverse_payload is not None:
            reverse_payload["trial"] = idx + 1
            reverse_payload["runner_rc"] = proc.returncode
            reverse_payload["runner_elapsed_s"] = round(elapsed, 3)
            all_reverse.append(reverse_payload)

        trial_artifacts.append(
            {
                "trial": idx + 1,
                "runner_rc": proc.returncode,
                "runner_elapsed_s": round(elapsed, 3),
                "forward_json": str(fwd_json_trial),
                "reverse_json": str(rev_json_trial),
                "forward_log": str(fwd_log_trial),
                "reverse_log": str(rev_log_trial),
            }
        )

    aggregate_payload = {
        "test_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": RECOVERY_MODE,
        "trials_requested": N_TRIALS,
        "artifacts": trial_artifacts,
        "forward": aggregate_direction(all_forward, "forward"),
        "reverse": aggregate_direction(all_reverse, "reverse"),
    }

    summary_file = RESULTS_DIRECTORY / f"{RECOVERY_MODE}_convergence_trials_summary.json"
    summary_file.write_text(json.dumps(aggregate_payload, indent=2), encoding="utf-8")

    print("=== Trials completed ===", flush=True)
    print(f"Summary: {summary_file}", flush=True)
    print(
        f"Forward success {aggregate_payload['forward']['trials_success']}/{aggregate_payload['forward']['trials_total']}",
        flush=True,
    )
    print(
        f"Reverse success {aggregate_payload['reverse']['trials_success']}/{aggregate_payload['reverse']['trials_total']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
