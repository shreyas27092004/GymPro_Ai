# app/observability/metrics.py
import collections
import statistics
import threading
import time
from typing import Any, Dict, List


class MetricsRegistry:
    """Thread-safe metrics aggregator for GymPro AI."""

    def __init__(self):
        self._lock = threading.Lock()
        self.requests_total: collections.Counter = collections.Counter()
        self.errors_total: collections.Counter = collections.Counter()
        self.status_distribution: collections.Counter = collections.Counter()
        self.agent_runs_total: collections.Counter = collections.Counter()
        self.tool_calls_total: collections.Counter = collections.Counter()
        self.tokens_total: collections.Counter = collections.Counter()
        self.confirmations_total: collections.Counter = collections.Counter()
        self.bundle_outcomes_total: collections.Counter = collections.Counter()
        self.executor_failures: collections.Counter = collections.Counter()
        self.email_events: collections.Counter = collections.Counter()
        self.login_failures_total: int = 0
        self.pending_role_requests: int = 0
        self.latencies: collections.defaultdict[str, List[float]] = collections.defaultdict(list)

    def record_request(self, method: str, endpoint: str, status_code: int, duration_s: float):
        key = f"{method.upper()}:{endpoint}:{status_code}"
        with self._lock:
            self.requests_total[key] += 1
            if status_code >= 400:
                self.errors_total[f"http_{status_code}"] += 1
            # Keep max 500 latency observations per endpoint for percentile calculation
            l_list = self.latencies[f"{method.upper()}:{endpoint}"]
            if len(l_list) > 500:
                l_list.pop(0)
            l_list.append(duration_s)

    def record_agent_run(self, agent: str, status: str, tokens: int = 0, duration_s: float = 0.0):
        with self._lock:
            self.agent_runs_total[f"{agent}:{status}"] += 1
            self.status_distribution[status] += 1
            self.tokens_total[agent] += tokens
            if duration_s > 0:
                l_list = self.latencies[f"agent:{agent}"]
                if len(l_list) > 500:
                    l_list.pop(0)
                l_list.append(duration_s)

    def record_tool_call(self, tool: str, status: str = "OK"):
        with self._lock:
            self.tool_calls_total[f"{tool}:{status}"] += 1
            if status != "OK":
                self.errors_total[f"tool_{tool}_{status}"] += 1

    def record_confirmation(self, action_type: str, status: str):
        with self._lock:
            self.confirmations_total[f"{action_type}:{status}"] += 1

    def record_bundle_outcome(self, status: str):
        with self._lock:
            self.bundle_outcomes_total[status] += 1

    def record_executor_failure(self, reason: str):
        with self._lock:
            self.executor_failures[reason] += 1

    def record_email_event(self, event_type: str):  # 'sent', 'failed', 'bounced'
        with self._lock:
            self.email_events[event_type] += 1

    def record_login_failure(self):
        with self._lock:
            self.login_failures_total += 1

    def set_pending_role_requests(self, count: int):
        with self._lock:
            self.pending_role_requests = count

    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            percentiles = {}
            for k, v in self.latencies.items():
                if v:
                    sorted_v = sorted(v)
                    percentiles[k] = {
                        "p50_s": round(statistics.median(sorted_v), 4),
                        "p95_s": round(
                            sorted_v[int(len(sorted_v) * 0.95)]
                            if len(sorted_v) >= 20
                            else sorted_v[-1],
                            4,
                        ),
                        "count": len(sorted_v),
                    }

            return {
                "requests_total": dict(self.requests_total),
                "errors_total": dict(self.errors_total),
                "status_distribution": dict(self.status_distribution),
                "agent_runs": dict(self.agent_runs_total),
                "tool_calls": dict(self.tool_calls_total),
                "tokens_total": dict(self.tokens_total),
                "confirmations": dict(self.confirmations_total),
                "bundle_outcomes": dict(self.bundle_outcomes_total),
                "executor_failures": dict(self.executor_failures),
                "email_events": dict(self.email_events),
                "login_failures": self.login_failures_total,
                "pending_role_requests": self.pending_role_requests,
                "latency_percentiles": percentiles,
            }

    def to_prometheus_format(self) -> str:
        summary = self.get_summary()
        lines = ["# HELP gympro_requests_total Total HTTP requests handled", "# TYPE gympro_requests_total counter"]
        for k, v in summary["requests_total"].items():
            parts = k.split(":")
            if len(parts) >= 3:
                lines.append(f'gympro_requests_total{{method="{parts[0]}",endpoint="{parts[1]}",status="{parts[2]}"}} {v}')

        lines.extend(["# HELP gympro_errors_total Total errors recorded", "# TYPE gympro_errors_total counter"])
        for k, v in summary["errors_total"].items():
            lines.append(f'gympro_errors_total{{type="{k}"}} {v}')

        lines.extend(["# HELP gympro_agent_runs_total Total agent invocations", "# TYPE gympro_agent_runs_total counter"])
        for k, v in summary["agent_runs"].items():
            agent, st = k.split(":", 1)
            lines.append(f'gympro_agent_runs_total{{agent="{agent}",status="{st}"}} {v}')

        lines.extend(["# HELP gympro_tokens_total Total LLM tokens used", "# TYPE gympro_tokens_total counter"])
        for k, v in summary["tokens_total"].items():
            lines.append(f'gympro_tokens_total{{agent="{k}"}} {v}')

        lines.extend(["# HELP gympro_login_failures_total Total failed login attempts", "# TYPE gympro_login_failures_total counter"])
        lines.append(f"gympro_login_failures_total {summary['login_failures']}")

        return "\n".join(lines) + "\n"


metrics = MetricsRegistry()


def record_request(method: str, endpoint: str, status_code: int, duration_s: float):
    metrics.record_request(method, endpoint, status_code, duration_s)


def record_agent_run(agent: str, status: str, tokens: int = 0, duration_s: float = 0.0):
    metrics.record_agent_run(agent, status, tokens, duration_s)


def record_tool_call(tool: str, status: str = "OK"):
    metrics.record_tool_call(tool, status)
