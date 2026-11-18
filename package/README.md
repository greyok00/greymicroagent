# greymicroagent package

One folder, two entry points, dependencies installed before anything runs.

## Linux

    ./greymicroagent.sh

Checks python3 and node (>= 22), installs them via the system package
manager if missing, pip-installs requirements.txt, runs the frozen-tree
gate, then execs bin/greymicroagent (the full product: model chain, RAG
grounding gate, TUI).

## Windows (PowerShell)

    .\run.ps1

Winget-installs Python and Node if missing, pip-installs
requirements.txt, then starts greymicroagent.exe. If the exe does not
exist yet, run .\build-windows.ps1 first.

## Building greymicroagent.exe (on a Windows machine)

    .\build-windows.ps1

Builds the Windows model server binary from the vendored llama.cpp fork
source (vendor/llamacpp) and freezes package/entry.py into
package/greymicroagent.exe with PyInstaller. Needs Visual Studio Build
Tools and CMake (the script winget-installs both if absent).

## What the exe contains

entry.py boots the vendored model server binary and runs a plain console
chat against it. The full RAG-grounded product experience (grounding
gate, TUI, all 47 internal tools) runs under Linux or WSL via
greymicroagent.sh, which is the supported path; the exe covers the
local-model console on Windows.
