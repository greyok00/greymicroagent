from __future__ import annotations
import json, os, time

IDLE, WORKING, DEGRADED, RECOVERING, BLOCKED = (
    "IDLE", "WORKING", "DEGRADED", "RECOVERING", "BLOCKED")

TRANSITIONS = {
    (IDLE, "task_started"): WORKING,
    (WORKING, "detector_fire"): DEGRADED,
    (WORKING, "task_ended"): IDLE,
    (DEGRADED, "ladder_act"): RECOVERING,
    (DEGRADED, "recovered_naturally"): WORKING,
    (DEGRADED, "ladder_exhausted"): BLOCKED,
    (RECOVERING, "result_improved"): WORKING,
    (RECOVERING, "ladder_exhausted"): BLOCKED,
    (RECOVERING, "detector_fire"): DEGRADED,
    (BLOCKED, "owner_clear"): IDLE,
    (BLOCKED, "session_end"): IDLE,
}
VALID_STATES = {IDLE, WORKING, DEGRADED, RECOVERING, BLOCKED}


class FSM:
    def __init__(self, state=IDLE):
        self.state = state if state in VALID_STATES else IDLE

    def fire(self, event: str) -> tuple[bool, str]:
        key = (self.state, event)
        if key not in TRANSITIONS:
            return False, self.state
        self.state = TRANSITIONS[key]
        return True, self.state

    @property
    def can_enforce(self) -> bool:
        return self.state in (DEGRADED, RECOVERING)


LEDGER_PATH = os.path.expanduser(
    "~/.greymicroagent/state/supervision/ledger.json")


class Ledger:
    def __init__(self, path=LEDGER_PATH):
        self.path = path
        self.task_id = None
        self.actions: list[dict] = []
        self.failures: list[dict] = []
        self.alternatives: dict[str, str] = {}

    def start_task(self, task_id: str):
        self.task_id = task_id
        self.actions: list = []
        self.failures: list = []
        self.alternatives: dict = {}
        self._flush()

    def record_action(self, tool: str, digest: str, ok: bool, why: str = ""):
        self.actions.append({"tool": tool, "digest": digest, "ok": ok,
                             "why": why[:200], "ts": time.time()})
        if len(self.actions) > 200:
            self.actions = self.actions[-100:]
        self._flush()

    def record_failure(self, fclass: str, detail: str, detector: str):
        self.failures.append({"class": fclass, "detail": detail[:200],
                              "detector": detector, "ts": time.time()})
        self._flush()

    def forbid(self, action_class: str, reason: str):
        self.alternatives[action_class] = reason
        self._flush()

    def is_forbidden(self, action_class: str) -> bool:
        return action_class in self.alternatives

    def summary(self) -> dict:
        ok = sum(1 for a in self.actions if a.get("ok"))
        return {"task": self.task_id, "actions": len(self.actions),
                "ok": ok, "failures": len(self.failures),
                "forbidden": dict(self.alternatives)}

    def _flush(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.summary() | {"actions_tail": self.actions[-40:],
                                            "failures": self.failures[-40:]}, f)
            os.replace(tmp, self.path)
        except OSError:
            pass
