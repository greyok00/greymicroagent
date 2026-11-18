from __future__ import annotations
import collections
import hashlib
import json
import os
import sys
import time
import typing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fsm import FSM, Ledger, IDLE, WORKING, DEGRADED, RECOVERING, BLOCKED
from detectors import (STRUCTURED_TOOLS, args_conform, error_burst,
                       one_token_storm, refusal_repeat, repetition_tool_loop,
                       length_storm, _digest)

STATE = os.path.expanduser("~/.greymicroagent/state/supervision")
STEER_FILE = os.path.join(STATE, "steer.jsonl")
SIDECAR_STREAM = os.path.join(STATE, "supervision_events.jsonl")
SUPERVISOR_LOG = os.path.join(STATE, "supervisor.log")

DETACH = True


def _load_rulebook() -> dict:
    defaults = {
        "repetition_limit": 3,
        "storm_min_turns": 3,
        "error_burst_min": 4,
        "error_burst_window": 6,
        "refusal_repeat_limit": 3,
        "length_storm_limit": 3,
        "steer_effectiveness_max": 3,
    }
    return defaults


class LadderResult(typing.NamedTuple):
    node: int
    prose: str
    fclass: str


class Supervisor:
    def __init__(self, task_id: str = "adhoc"):
        self.rb = _load_rulebook()
        self.fsm = FSM(IDLE)
        self.ledger = Ledger()
        self.task_id = task_id
        self.window: collections.deque = collections.deque(maxlen=40)
        self.steer_counts: dict[str, int] = collections.Counter()
        self.reliability = {"C": 1.0, "S": 1.0, "E": 1.0}
        self.sidecar_ok = os.path.isdir(STATE)
        self.fsm.fire("task_started") if False else None
        self.observe_only = False
        self._armed_signature = None
        self._sig_count = collections.Counter()
        self._last_call_digest = None

    def on_event(self, ev: dict):
        try:
            self._on_event(ev)
        except Exception as e:
            self.observe_only = True
            self._log(f"supervisor internal error → observe-only: {e}")

    def _on_event(self, ev: dict):
        kind = ev.get("kind")
        if kind == "task_started":
            self.task_id = str(ev.get("task") or "adhoc")[:80]
            self.ledger.start_task(self.task_id)
            self.fsm = FSM(WORKING)
        elif kind == "task_ended":
            if self.fsm.state != IDLE:
                self.fsm.fire("task_ended")
        self.window.append(ev)
        self.ledger.record_action(
            ev.get("tool", kind), ev.get("digest", ""), not ev.get("error"))

        det = (repetition_tool_loop(self.window, self.rb["repetition_limit"])
               or one_token_storm(self.window, self.rb["storm_min_turns"])
               or error_burst(self.window, self.rb["error_burst_min"],
                              self.rb["error_burst_window"])
               or refusal_repeat(self.window, self.rb["refusal_repeat_limit"])
               or length_storm(self.window, self.rb["length_storm_limit"]))

        if kind == "tool_call" and ev.get("args") is not None:
            ok, why = args_conform(ev.get("tool") or "", ev.get("args") or {})
            if not ok:
                det = ("F1", why, "medium")

        if det and kind in ("tool_call", "tool_result", "model_turn",
                            "refusal", "stop_reason"):
            fclass, detail, severity = det
            sig = f"{fclass}:{detail[:48]}"
            self._sig_count[sig] += 1
            should_fire = (self._sig_count[sig] == 1
                           or (self._sig_count[sig] - 1) % max(
                               self.rb["repetition_limit"], 1) == 0)
            if should_fire:
                self._armed_signature = sig
                self._escalate(fclass, detail, severity, ev)
        else:
            if kind == "tool_call":
                d = ev.get("digest")
                if d != self._last_call_digest:
                    self._armed_signature = None
                    self._sig_count.clear()
                self._last_call_digest = d
        self._reliability_tick()
        self._sidecar_stream(ev, det)

    def _escalate(self, fclass: str, detail: str, severity: str, ev: dict):
        if self.fsm.state == BLOCKED:
            return
        self.fsm.state = DEGRADED
        self.ledger.record_failure(fclass, detail, "tier1")
        key = f"{fclass}:{detail[:48]}"

        n = self.steer_counts[key]
        self.steer_counts[key] = n + 1
        if n < 1:
            prose = self._lesson(fclass, detail, ev)
            lres = LadderResult(1, prose, fclass)
        elif n < 2:
            action_class = ev.get("tool") or ev.get("reason_family") or "the failing action"
            reason = f"already failed {fclass}: {detail}"
            self.ledger.forbid(action_class, reason)
            prose = (f"Stop using {action_class} for this task — it already "
                     f"failed ({detail}). Take a different approach.")
            lres = LadderResult(2, prose, fclass)
        elif n < 3:
            self.fsm.fire("ladder_act")
            prose = (f"Task cancelled by supervision: {detail}. "
                     "Report what is blocked to the owner and end the turn.")
            lres = LadderResult(3, prose, fclass)
        elif n < 4:
            self._heal_respawn(detail)
            prose = (f"This task still looped after cancellation ({detail}). "
                     "A recovery cycle is running; change approach now.")
            lres = LadderResult(4, prose, fclass)
        else:
            self.fsm.fire("ladder_exhausted")
            prose = (f"Supervision halted this task after repeated failures "
                     f"(last: {detail}). Owner attention required.")
            lres = LadderResult(5, prose, fclass)
            self._log(f"LADDER-5 surface: {detail}")
        if lres.node == 2:
            self.fsm.fire("ladder_act")
        self._emit(lres.prose)
        self._log(f"LADDER-{lres.node} [{fclass}/{self.fsm.state}] "
                  f"{lres.prose[:90]}")

    def _lesson(self, fclass: str, detail: str, ev: dict) -> str:
        lessons = {
            "F1": f"That call was structurally invalid: {detail}. Fix the "
                  "arguments and retry once.",
            "F2": f"The last commands keep failing: {detail}. Change the "
                  "approach or write the steps into one script and run it once.",
            "F3": f"You repeated the same refused action: {detail}. Read the "
                  "earlier reason and do something different.",
            "F4": f"You are repeating identical work: {detail}. Do the "
                  "iteration in ONE command (shell loop to a file) or a "
                  "background subagent, then read the single result.",
        }
        return lessons.get(fclass, f"Supervision note: {detail}.")

    def _sidecar_stream(self, ev: dict, det):
        if not self.sidecar_ok:
            return
        try:
            rec = {"ts": time.time(), "kind": ev.get("kind"), "state": self.fsm.state}
            if det:
                rec["detector"] = {"class": det[0], "detail": det[1][:120],
                                   "severity": det[2]}
            with open(SIDECAR_STREAM, "a") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            self.sidecar_ok = False
            self._log("sidecar stream lost — continuing observe-only")

    def _heal_respawn(self, detail: str):
        self._log("respawn unavailable — session processes are launcher-managed; "
                  "surfacing to the operator")

    def new_task(self, task_id: str):
        self.task_id = str(task_id)[:80]
        self.ledger.start_task(self.task_id)
        self.fsm = FSM(WORKING)
        self.steer_counts.clear()
        self._sig_count.clear()
        self._armed_signature = None
        self._last_call_digest = None
        self._log(f"new task {self.task_id} — ladder re-armed at node 1")

    def _reliability_tick(self):
        w = list(self.window)
        if not w:
            return
        errs = [r for r in w if r.get("kind") == "tool_result"]
        self.reliability["E"] = (sum(1 for r in errs if not r.get("error"))
                                 / len(errs)) if errs else 1.0
        unique = len({(r.get("tool"), r.get("digest")) for r in w
                      if r.get("kind") == "tool_call"})
        self.reliability["S"] = unique / max(len(w) // 2, 1) if w else 1.0
        self.reliability["S"] = min(1.0, self.reliability["S"])
        self.reliability["C"] = 1.0 if self.fsm.state in (WORKING, IDLE) else (
            0.5 if self.fsm.state == RECOVERING else 0.2)

    def _emit(self, prose: str):
        self._pending = getattr(self, "_pending", [])
        self._pending.append(prose)
        try:
            with open(STEER_FILE, "a") as f:
                f.write(json.dumps({"ts": time.time(), "msg": prose}) + "\n")
        except OSError:
            self._log("steer write failed: " + prose[:80])

    @staticmethod
    def _log(msg: str):
        try:
            with open(SUPERVISOR_LOG, "a") as f:
                f.write(time.strftime("[%m-%d %H:%M:%S] ") + msg + "\n")
        except OSError:
            pass

    def drain(self) -> list[str]:
        out = getattr(self, "_pending", [])
        self._pending = []
        return out
