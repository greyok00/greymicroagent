import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_splash_geometry():
    # GM-03b canary (2026-11-03, rebased 2026-11-17): a stale splash .so that
    # shadows build/src/splash.py still carries the old identity, so the test
    # asserts the new front door is present and the retired 2B line is absent.
    from ui.splash import SPLASH_TEXT, SPLASH_MIN_W
    assert SPLASH_MIN_W() == 75
    rows = SPLASH_TEXT.split("\n")
    assert max(len(r) for r in rows) <= 90
    assert "qwen3.5-2b-abliterated" not in SPLASH_TEXT
    assert "GREYLOCALRAG" in SPLASH_TEXT
    assert "YOUR RAG" in SPLASH_TEXT


def test_palette_is_8bit_greyscale():
    from ui.splash import shade
    for i in range(8):
        assert shade(i).startswith("\x1b[38;5;")
    assert not any("38;2;" in shade(i) for i in range(8))


def test_compact_splash_is_narrow():
    from ui.splash import compact_splash
    lines = compact_splash().split("\n")
    assert max(len(l) for l in lines) < 70
    # mini identity, same GM-03b reason as test_splash_geometry
    assert any("GREYLOCALRAG" in l for l in lines)


def test_big_number_renders():
    from ui.splash import big_number
    rows = big_number(12.7).split("\n")
    assert len(rows) == 5
    assert len(rows[0]) == len(rows[4])


def test_ticker_line_has_three_stats():
    import ui.app as app
    app._state["cols"], app._state["rows"] = 120, 40
    text = app.ticker_text()
    assert "model" in text
    assert "comp" in text
    assert "mem" in text


def test_ticker_write_emits_prompt():
    import ui.app as app
    app._state["cols"], app._state["rows"] = 120, 40
    app._state["buffer"] = "say hi"
    buf = io.StringIO()
    with redirect_stdout(buf):
        app.ticker_write()
    out = buf.getvalue()
    assert "╰─" in out and "say hi" in out
    assert "model" in out


def test_log_write_streams_text():
    import ui.app as app
    app._state["cols"], app._state["rows"] = 120, 40
    buf = io.StringIO()
    with redirect_stdout(buf):
        app.log_write("> test line")
    out = buf.getvalue()
    assert "> test line" in out


def test_no_textual_dependency():
    import ui.app as app
    assert not hasattr(app, "compose")
    assert not hasattr(app, "CSS")