import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "services"))

import supervision.supervisor as sup
import supervision.detectors as det


def _ev(i, kind="tool_call", name="bash", args=None):
    return {"turn": i, "kind": kind, "tool": name,
            "args": args if args is not None else {"command": f"cmd {i}"},
            "digest": f"digest-{i}"}


def _state_paths(tmp_path, monkeypatch):
    state = tmp_path / "state" / "supervision"
    state.mkdir(parents=True)
    monkeypatch.setattr(sup, "STATE", str(state))
    monkeypatch.setattr(sup, "STEER_FILE", str(state / "steer.jsonl"))
    monkeypatch.setattr(sup, "SIDECAR_STREAM", str(state / "supervision_events.jsonl"))
    monkeypatch.setattr(sup, "SUPERVISOR_LOG", str(state / "supervisor.log"))
    return state


def _fresh_supervisor(s):
    s.ledger.path = str(sup.STATE) + "/ledger.json"
    return s


def test_rulebook_constants_match_spec():
    rb = sup._load_rulebook()
    assert rb == {"repetition_limit": 3, "storm_min_turns": 3,
                  "error_burst_min": 4, "error_burst_window": 6,
                  "refusal_repeat_limit": 3, "length_storm_limit": 3,
                  "steer_effectiveness_max": 3}
    assert det.error_burst.__defaults__ == (4, 6)
    assert det.refusal_repeat.__defaults__ == (3,)
    assert det.length_storm.__defaults__ == (3,)
    assert det.repetition_tool_loop.__defaults__ == (3,)


def test_identical_detector_at_three():
    evs = [{"turn": i, "kind": "tool_call", "tool": "bash",
            "args": {"command": "echo x"}, "digest": "same"} for i in range(4)]
    assert det.repetition_tool_loop(evs[:3], 3) == (
        "F4", "bash issued 3x with identical args and identical results", "high")
    assert det.repetition_tool_loop(evs[:2], 3) is None
    assert det.repetition_tool_loop(evs, 3) == (
        "F4", "bash issued 3x with identical args and identical results", "high")


def test_repetition_limit_and_ladder_first_step(tmp_path, monkeypatch):
    state = _state_paths(tmp_path, monkeypatch)
    s = _fresh_supervisor(sup.Supervisor(task_id="t"))
    for i in range(2):
        s.on_event({"turn": i, "kind": "tool_call", "tool": "bash",
                    "args": {"command": "echo loop"}, "digest": "same"})
    assert s.drain() == []
    s.on_event({"turn": 2, "kind": "tool_call", "tool": "bash",
                "args": {"command": "echo loop"}, "digest": "same"})
    out = s.drain()
    assert len(out) == 1 and "repeating identical work" in out[0]
    record = (state / "steer.jsonl").read_text().strip()
    assert '"msg": "%s"' % out[0] in record
    s.on_event({"turn": 3, "kind": "tool_call", "tool": "bash",
                "args": {"command": "echo loop"}, "digest": "same"})
    assert s.drain() == []


def test_fresh_events_never_escalate(tmp_path, monkeypatch):
    _state_paths(tmp_path, monkeypatch)
    s = _fresh_supervisor(sup.Supervisor(task_id="t"))
    for i in range(40):
        s.on_event(_ev(i))
    assert not s.drain()
    for i in range(40):
        s.on_event({"turn": i, "kind": "file_change", "path": f"p{i}"})
    assert not s.drain()


def test_ladder_node4_respawn_is_logged_noop_without_subprocess(tmp_path, monkeypatch):
    import sys, types
    calls = []
    fake = types.ModuleType("subprocess")
    fake.run = lambda *a, **kw: calls.append((a, kw))
    monkeypatch.setitem(sys.modules, "subprocess", fake)
    state = _state_paths(tmp_path, monkeypatch)
    s = _fresh_supervisor(sup.Supervisor(task_id="t"))
    ev = lambda i: {"turn": i, "kind": "tool_call", "tool": "bash",
                    "args": {"command": "echo loop"}, "digest": "same"}
    for i in range(12):
        s.on_event(ev(i))
    out = s.drain()
    assert len(out) == 4
    assert "repeating identical work" in out[0]
    assert "Stop using bash" in out[1]
    assert "Task cancelled by supervision" in out[2]
    assert "still looped after cancellation" in out[3]
    assert calls == []
    assert "respawn unavailable — session processes are launcher-managed; " \
        "surfacing to the operator" in (state / "supervisor.log").read_text()
    s.on_event(ev(12)); s.on_event(ev(13)); s.on_event(ev(14))
    final = s.drain()
    assert len(final) == 1 and "halted this task" in final[0]
    assert s.fsm.state == "BLOCKED"
    s.on_event(ev(15))
    assert s.drain() == []
