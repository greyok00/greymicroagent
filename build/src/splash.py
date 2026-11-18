from __future__ import annotations

SH = ["#101010", "#262626", "#3c3c3c", "#545454",
      "#6e6e6e", "#8c8c8c", "#acacac", "#cccccc"]

GREY8 = [232, 234, 236, 240, 244, 248, 252, 255]

def shade(i: int) -> str:
    return "\033[38;5;%dm" % GREY8[i % 8]

_G = [" ██████╗ ", "██╔════╝ ", "██║  ███╗", "██║   ██║", "╚██████╔╝", " ╚═════╝ "]
_R = ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔══██╗", "██║  ██║", "╚═╝  ╚═╝"]
_E = ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"]
_Y = ["██╗   ██╗", "╚██╗ ██╔╝", " ╚████╔╝ ", "  ╚██╔╝  ", "   ██║   ", "   ╚═╝   "]
_L = ["██╗     ", "██║     ", "██║     ", "██║     ", "███████╗", "╚══════╝"]
_O = [" ██████╗ ", "██╔═══██╗", "██║   ██║", "██║   ██║", "╚██████╔╝", " ╚═════╝ "]
_C = [" ██████╗", "██╔════╝", "██║     ", "██║     ", "╚██████╗", " ╚═════╝"]
_A = [" █████╗ ", "██╔══██╗", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"]

_NAME = "GREYMICROAGENT"
_BYLINE = "grounded answers from your own knowledge - RAG for CPU-only machines"
_HOWTO = [
    "Ask anything. Answers come from your KB with citations, temperature cold.",
    "No grounded material? The agent asks before it goes searching the web.",
    "What it finds stays out of your KB until you say yes.",
]
_RAG = [
    ("/rag ingest <file | url>", "teach it"),
    ("/rag remove <id | source>", "make it forget"),
    ("/rag status", "what it knows"),
    ("/rag temp <n>", "answer temperature (0.0-0.2)"),
]

def _word(glyphs) -> list:
    return ["".join(g[i] for g in glyphs) for i in range(6)]

def _layout() -> tuple:
    art = [_word((_G, _R, _E, _Y)), _word((_L, _O, _C, _A, _L)), _word((_R, _A, _G))]
    rows = list(art[0]) + list(art[1]) + list(art[2]) + [""]
    tones = [4] * 6 + [5] * 6 + [6] * 6 + [5]
    rows.append(_NAME)
    rows.append(_BYLINE)
    rows.append("")
    rows.append("HOW TO USE")
    for line in _HOWTO:
        rows.append("  " + line)
    rows.append("")
    rows.append("YOUR RAG")
    for cmd, note in _RAG:
        rows.append("  " + cmd.ljust(30) + note)
    tones += [7, 5, 5, 6] + [5] * len(_HOWTO) + [5, 6] + [5] * len(_RAG)
    return rows, tones

def splash_rows() -> list:
    return _layout()[0]

def splash_lines() -> list:
    rows, tones = _layout()
    return [shade(tones[i]) + row for i, row in enumerate(rows)]

def SPLASH_MIN_W() -> int:
    return max(len(r) for r in splash_rows())

SPLASH_MIN_WIDTH = SPLASH_MIN_W()
SPLASH_MIN_HEIGHT = len(splash_rows())
SPLASH_TEXT = "\n".join(splash_lines())

DIGITS = {
    "0": ["███", "█ █", "█ █", "█ █", "███"],
    "1": [" █ ", "██ ", " █ ", " █ ", "███"],
    "2": ["███", "  █", "███", "█  ", "███"],
    "3": ["███", "  █", "███", "  █", "███"],
    "4": ["█ █", "█ █", "███", "  █", "  █"],
    "5": ["███", "█  ", "███", "  █", "███"],
    "6": ["███", "█  ", "███", "█ █", "███"],
    "7": ["███", "  █", "  █", "  █", "  █"],
    "8": ["███", "█ █", "███", "█ █", "███"],
    "9": ["███", "█ █", "███", "  █", "███"],
    ".": ["   ", "   ", "   ", "   ", "  █"],
    " ": ["   ", "   ", "   ", "   ", "   "],
}

def big_number(value) -> str:
    text = ("%.1f" % value) if isinstance(value, (int, float)) else str(value)
    glyphs = [DIGITS.get(c, DIGITS[" "]) if len(c) == 1 else DIGITS[" "]
              for c in text]
    return "\n".join("    ".join(g[i] for g in glyphs) for i in range(5))

def compact_splash_lines() -> list:
    out = [shade(7) + _NAME]
    half = _BYLINE.split(" - ")
    for part in half:
        out.append(shade(5) + part.strip())
    out.append("")
    out.append(shade(6) + "YOUR RAG")
    for cmd, note in _RAG:
        out.append(shade(5) + "  " + cmd + "  " + note)
    return out

def compact_splash() -> str:
    return "\n".join(compact_splash_lines())
