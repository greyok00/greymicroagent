import os, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "build", "src"))
import server

def test_ram_probe_env_override():
    os.environ["GREYLOCALRAG_ASSUME_RAM_GB"] = "8"
    assert server.open_ctx_default() == 32768
    os.environ["GREYLOCALRAG_ASSUME_RAM_GB"] = "16"
    assert server.open_ctx_default() == 65536
    del os.environ["GREYLOCALRAG_ASSUME_RAM_GB"]

def test_threads_is_four(monkeypatch):
    captured = {}
    class FakeProc:
        returncode = 0
        def poll(self): return 0
    def fake_popen(cmd, **k):
        captured.update(cmd=cmd); return FakeProc()
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(server, "is_ready", lambda: False)
    server.start_model(timeout=5)
    idx = captured["cmd"].index("--threads")
    assert captured["cmd"][idx + 1] == "4"
