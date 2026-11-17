from __future__ import annotations

SH = ["#101010", "#262626", "#3c3c3c", "#545454",
      "#6e6e6e", "#8c8c8c", "#acacac", "#cccccc"]

GREY8 = [232, 234, 236, 240, 244, 248, 252, 255]

def shade(i: int) -> str:
    return "\033[38;5;%dm" % GREY8[i % 8]

_D = ["█▄        ▄█", "███▄▄▄▄▄▄███", " ██ ▀██▀ ██", " ███▀▀▀▀███",
      "▄██████████▄", "██▀██████▀██", "   ██████", "  ▄█▀  ▀█▄"]

def banner_rows() -> list:
    return _D

def _grey_banner() -> list:
    G = [" ██████╗ ", "██╔════╝ ", "██║  ███╗", "██║   ██║", "╚██████╔╝", " ╚═════╝ "]
    R = ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔══██╗", "██║  ██║", "╚═╝  ╚═╝"]
    E = ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"]
    Y = ["██╗   ██╗", "╚██╗ ██╔╝", " ╚████╔╝ ", "  ╚██╔╝  ", "   ██║   ", "   ╚═╝   "]
    glyphs = [G, R, E, Y]
    return ["".join(g[i] for g in glyphs) for i in range(6)]

def _agent_banner() -> list:
    A = [" █████╗ ", "██╔══██╗", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"]
    G = [" ██████╗ ", "██╔════╝ ", "██║  ███╗", "██║   ██║", "╚██████╔╝", " ╚═════╝ "]
    E = ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"]
    N = ["███╗   ██╗", "████╗  ██║", "██╔██╗ ██║", "██║╚██╗██║", "██║ ╚████║", "╚═╝  ╚═══╝"]
    T = ["████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "]
    glyphs = [A, G, E, N, T]
    return ["    " + "".join(g[i] for g in glyphs) for i in range(6)]

def splash_rows() -> list:
    B = _grey_banner() + _agent_banner()
    DW = 11
    rows = []
    for i in range(14):
        d = _D[i] if i < 8 else ""
        g = B[i - 1] if 1 <= i <= 12 else ""
        rows.append(d.ljust(DW) + "   " + g if g else d.ljust(DW) + "   ")
    return rows

def splash_lines() -> list:
    out = []
    for i, line in enumerate(splash_rows()):
        out.append(shade(4) + line if i < 8 else shade(2) + line)
    out.append("")
    for line in ["MODEL: qwen3.5-2b-abliterated", "AUTHOR: greyok00",
                 "PROMPT: model/greylocalrag.md"]:
        out.append(shade(6) + line)
    out.append("")
    out.append(shade(2) + "ctrl+c quit | ctrl+n new | ctrl+k sched | ctrl+f mem")
    return out

def SPLASH_MIN_W() -> int:
    return max(len(r) for r in splash_rows())

SPLASH_MIN_WIDTH = SPLASH_MIN_W()
SPLASH_MIN_HEIGHT = 15
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
    dev = _D[1]
    w = SPLASH_MIN_W()
    return [shade(5) + dev.rjust((w + len(dev)) // 2), "", shade(7) + "GREYLOCALRAG",
            shade(5) + "MODEL: qwen3.5-2b-abliterated", shade(5) + "AUTHOR: greyok00",
            shade(5) + "PROMPT: model/greylocalrag.md", "",
            shade(2) + "ctrl+c quit | ctrl+n new | ctrl+k sched | ctrl+f mem"]

def compact_splash() -> str:
    return "\n".join(compact_splash_lines())
