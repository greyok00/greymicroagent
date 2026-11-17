# greylocalrag

greylocalrag is a local, offline, grounded AI assistant for the desktop. It
runs a fixed 2B hybrid vision-language model (huihui qwen3-vl 2B, abliterated)
through its own private llama.cpp build, and it grounds every answer in a
knowledge base you own: web pages and documents enter that base only when you
say yes, removal is always one command away, and the model is clamped to a
cool 0.0-0.2 temperature band on every request, whatever it is handed.

Everything runs on your machine. There is no cloud lane, no telemetry, no
analytics, and no account.

## What it is

One session occupies three ports in a private block and wires them in a chain:

    TUI  ->  RAG gate :7641  ->  slimtoken :7642  ->  model server :7640

The RAG gate in front of the chain reads your latest message, pulls grounded
context out of your knowledge base, and appends it to the system block. The
slimtoken lane distills oversized tool results before the model ever sees
them. The agent core, tools, and services are Cython-compiled; the terminal UI
is a Node application with a compiled scope. A frozen, hash-pinned manifest is
verified on every boot, so a damaged install refuses to start rather than
behaving strangely.

Greylocalrag owns the TCP port block 7640-7647 outright (never used by
anything else on your machine) and refuses to fight any other listener. The
policy file ships at config/port_policy.json.

## Install (Linux .deb)

    sudo dpkg -i greylocalrag_<version>_amd64.deb

The deb carries no model weights. Fetch the pinned model once:

    python3 scripts/fetch_model.py download

The command downloads the pinned blob from the ollama registry at

    https://registry.ollama.ai/v2/huihui_ai/qwen3-vl-abliterated/blobs/sha256:20ef83c3cae84e1dc03d3faee31c3c4ddda6ca806a8c99dc89d42e3e43e9c2ff

verifies its sha256 against the pin, repairs the rope metadata, and writes the
canonical text model to ~/.greylocalrag/models/qwen3-vl-2b-abliterated.gguf
(the companion mmproj file for vision is written beside it). A size or hash
mismatch refuses loudly and writes nothing.

Dependencies of the deb itself: python3 (3.13 or newer), nodejs (22 or
newer), and the usual C/C++ runtime libraries.

## First run

Start it from a terminal:

    greylocalrag

The splash screen shows the model boot line, then the terminal UI opens.
Sessions live in ~/.greylocalrag, model files in ~/.greylocalrag/models, and
nothing else on the machine is touched.

## The /rag commands

Inside a session, the /rag commands manage the knowledge base:

| Command | What it does |
| --- | --- |
| /rag status | shows what is in your knowledge base |
| /rag ingest <pdf, txt or md file, or a web address> | adds it to your knowledge base, after you confirm |
| /rag remove <word or address> | lists what matches, then deletes only when you run the same command again |
| /rag temp <number 0.0-0.2> | sets how freely the model may answer |
| /rag offline on/off | keeps answers to your knowledge base only, or lets the model answer freely |

Removal is two-step on purpose: nothing is deleted until you repeat the same
remove command, and any other /rag command first cancels the pending one.

## Offline behavior

The assistant answers from your knowledge base only when the /rag offline
switch is on; otherwise it answers freely with your knowledge base grounded
into the system block. Every request is temperature-clamped to 0.0-0.2, baked
at 0.1, no matter what the client asks for.

## The knowledge base seed

The commands knowledge base shipped at install is built from the tldr-pages
project at build time, whose pages are licensed under the Creative Commons
Attribution 4.0 International License (CC-BY-4.0),
https://creativecommons.org/licenses/by/4.0/ and
https://github.com/tldr-pages/tldr. The full list of source pages and licenses
ships in THIRD-PARTY-NOTICES.txt.

## Screenshots

A terminal capture of the splash screen and of the /rag status panel is a
placeholder here and is added to this file at release review.

## License

greylocalrag is licensed under the Apache License, Version 2.0; the license
text ships with the source repository as LICENSE. Third-party components are
listed in THIRD-PARTY-NOTICES.txt.
