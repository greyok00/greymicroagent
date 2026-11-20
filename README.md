# greymicroagent

greymicroagent is a local, offline assistant for the desktop. It runs one 2B
text model on the CPU, answers from a knowledge base you own, and only touches
the network when you ask it to research something.

There is no account, no telemetry, no analytics, and no cloud lane.

## What it is

One session wires three local services into a single chain:

    terminal UI  ->  RAG gate :7641  ->  slimtoken :7642  ->  model server :7640

The RAG gate reads your message, pulls matching chunks out of the knowledge
base, and attaches them to the request. slimtoken distills oversized tool
results before the model sees them. The agent core, tools, and services are
compiled Python modules; the terminal UI is a Node application. A hash-pinned
manifest is verified on every boot, so a damaged install refuses to start
instead of behaving strangely.

The product owns the port block 7640-7647 and never fights another listener.
Each launch takes the first free triple in that block, so two sessions can run
side by side (7640-7642 and 7643-7645). The policy ships at
config-data/port_policy.json.

The engine is CPU-only by construction: no GPU, no VRAM gate, one fixed 65536
token window. A 2B Q4 model needs roughly 2 GB of free RAM to load.

## What you need

| Component | Linux | Windows |
| --- | --- | --- |
| Python | 3.13 or newer | 3.13 or newer |
| Node.js | 22 or newer | 22 or newer |
| Model file | included as a release asset | included as a release asset |
| Build tools | not needed | CMake and Visual Studio Build Tools, only when building the Windows model server |

The Linux release ships the compiled modules and the CPU model server, so a
normal install needs no compiler. The Windows path builds the model server on
first use, which is why it needs the build tools.

## The model file

The release includes the model this build runs, as a release asset named
qwen3.5-2b-abliterated.gguf. Download it and put it in one of two places:

    ~/.greymicroagent/models/qwen3.5-2b-abliterated.gguf

or, for the portable archive, directly in the extracted folder:

    model/qwen3.5-2b-abliterated.gguf

The launcher checks the folder copy first and falls back to the home copy, so
either one works and the file is used in place, never duplicated. On Windows
use %USERPROFILE%\.greymicroagent\models\.

Its pinned identity is:

    size    1244030400 bytes
    sha256  b18f73c186906946e248bcfd921f4de36e39648d513970ff9462083b96ed1a67

Verify it before the first launch:

    python3 scripts/fetch_model.py verify

After a .deb install the script lives at /opt/greymicroagent/scripts/. The
launcher boots the model asynchronously, so the UI appears first and the model
line updates when the server answers.

## Run on Linux

Extract the release archive and start it:

    ./launch.sh

launch.sh opens the desktop terminal (x-terminal-emulator, gnome-terminal,
konsole, xfce4-terminal, or xterm) and runs the product there. With no display
set it runs in the current shell. The direct equivalent is:

    ./bin/greymicroagent

To install system wide with the Debian package:

    sudo dpkg -i greymicroagent_0.7.5.1_amd64.deb
    greymicroagent

The package installs to /opt/greymicroagent and puts the launcher on PATH. Its
post-install step runs the frozen-tree check, so a corrupted install fails at
install time.

## Run on Windows

In PowerShell, from the extracted folder:

    .\launch.ps1

The launcher opens Windows Terminal when it is available, otherwise PowerShell,
and runs package\run.ps1. That script installs Python 3.13 and Node.js LTS with
winget when they are missing, installs package\requirements.txt, and starts
package\greymicroagent.exe. If the exe is not present, package\build-windows.ps1
builds it: it compiles the model server from llama.cpp source placed in
vendor\llamacpp (CMake and Visual Studio Build Tools required) and freezes
package\entry.py with PyInstaller.

The Windows build is the console client for the local model. The full terminal
UI, the RAG gate, and the tool set run on Linux or under WSL.

## Install with an AI assistant

Any coding assistant can do the install if you hand it the folder. Paste this
prompt into Claude Code, Codex, or a similar tool:

    Install greymicroagent from this folder. Read README.md first.
    Install Python 3.13 or newer, Node.js 22 or newer, and the packages in
    package/requirements.txt.
    The model ships as the release asset qwen3.5-2b-abliterated.gguf.
    If it is not already in model/ or ~/.greymicroagent/models/, download it
    from the release and place it at ~/.greymicroagent/models/qwen3.5-2b-abliterated.gguf.
    Verify it with python3 scripts/fetch_model.py verify and stop if the
    check fails.
    Start ./launch.sh, wait for the session to open, and report which port
    triple it selected.
    Do not edit or regenerate state/MANIFEST.json.

The assistant should stop and report if the model check fails, a port triple is
unavailable, or the frozen-tree check rejects the install.

## First run

The splash screen shows the model boot line, then the terminal UI opens.
Sessions live under ~/.greymicroagent; nothing else on the machine is touched
unless you install the .deb.

Inside a session, the /rag commands manage the knowledge base:

| Command | Effect |
| --- | --- |
| /rag status | shows what the knowledge base contains |
| /rag ingest <file or URL> | adds a PDF, text file, markdown file, or web page after you confirm |
| /rag remove <word or URL> | previews the matches; deletes only when you run the same command again |
| /rag temp <0.0-0.2> | sets how freely the model may answer |
| /rag offline on/off | keeps answers to the knowledge base only, or lets the model answer freely |

Removal is two-step on purpose: nothing is deleted until you repeat the same
remove command, and any other /rag command cancels the pending one.

## Research

"Search", "research", and "look up" mean the web. The assistant has three web
paths: search for a quick query, greysearch for deep research that scrapes full
pages, and web_fetch for one known address. Deep research prefers a local
SearXNG instance on 127.0.0.1:8888 when it is running and falls back to direct
search lanes when it is not. Page scraping uses patchright's Chromium; install
it once with:

    python3 -m patchright install chromium

## Troubleshooting

If the boot says the frozen-tree check failed, the install no longer matches
state/MANIFEST.json. Reinstall from the release archive. Regenerating the
manifest is a development action, not a repair.

If it says all sessions are in use, two sessions already hold the 7640-7647
block; close one.

If the model line says the file is missing or the hash does not match, place the
pinned file described above. The build never downloads weights.

If deep research is slow, the local SearXNG instance is probably not running and
the run is using the fallback lanes.

## Credits

The command knowledge base seed is built from tldr-pages, licensed CC-BY-4.0
(https://github.com/tldr-pages/tldr). The model server is llama.cpp (MIT).
slimtoken provides request distillation, and patchright drives page scraping.
Model weights are supplied by the user and are not redistributed.

Third-party license texts ship in THIRD-PARTY-NOTICES.txt.

## License

Apache License 2.0. The full text ships as LICENSE.
