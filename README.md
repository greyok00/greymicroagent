<p align="center"><img src="assets/logo.svg" width="128" alt="greymicroagent logo"></p>

# greymicroagent

**A private AI assistant that runs on your own computer.**

You ask questions in a text window and it answers. It can also read documents you give it, and then answer from those documents. Nothing is sent to a company, there is no account, and no one tracks how you use it. It only goes online when you ask it to look something up on the web.

## Before you start

- A 64-bit Linux or Windows computer with about 4 GB of free memory and 2 GB of free disk space.
- Two free support programs: Python 3.13 or newer, and Node.js 22 or newer. The Windows launcher installs both for you the first time. Many Linux systems come with older versions, so the steps below include how to get the right ones.
- Two files from the download page, described in step 1 below.

The download page is called Releases. You can reach it from the right side of the project page:

    https://github.com/greyok00/greymicroagent/releases

## The two files you download

Every release has these:

1. The model file, qwen3.5-2b-abliterated.gguf. This is the assistant's "brain" and it is about 1.2 GB. Every release uses the same file, so you only download it once.
2. The program for your system. On Linux you can take either the .deb package or the .tar.gz folder. On Windows you take the .zip file.

The other file, THIRD-PARTY-NOTICES.txt, is a list of licenses. You do not need it to run the program.

## The fastest way: let an AI assistant install it

If you already use a coding assistant such as Claude Code or Codex, you can let it do the whole install. Paste this message into it:

    Install greymicroagent from its public release.
    Release page: https://github.com/greyok00/greymicroagent/releases/tag/v0.7.5.4
    Download greymicroagent_0.7.5.4_linux-x86_64.tar.gz and qwen3.5-2b-abliterated.gguf.
    Install Python 3.13 or newer and Node.js 22 or newer if they are missing.
    Unpack the archive into a folder named greymicroagent, then put the model file
    in that folder's model directory.
    Verify the model with: python3 scripts/fetch_model.py verify
    Stop and tell me if that check fails.
    Start the program with ./launch.sh and report what you see.
    Do not edit anything inside the state directory.

If you would rather do it yourself, follow the steps for your system.

## Install on Linux, option 1: the package

This is the easiest option on Ubuntu, Debian, or a system based on them.

**Step 1. Install the two support programs.** Open a terminal (the text window where you type commands; press Ctrl+Alt+T on most desktops) and run these two groups of commands.

For Node.js 22:

    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt install -y nodejs

For Python 3.13:

    sudo add-apt-repository ppa:deadsnakes/ppa
    sudo apt update
    sudo apt install -y python3.13

If your system already has Node.js 22 or newer and Python 3.13 or newer, skip this step. You can check with `node --version` and `python3 --version`.

**Step 2. Download the package and the model** from the Releases page.

**Step 3. Install the package.** In the folder where the files downloaded (usually Downloads):

    sudo apt install ./greymicroagent_0.7.5.4_amd64.deb

**Step 4. Put the model where the program looks for it:**

    mkdir -p ~/.greymicroagent/models
    mv qwen3.5-2b-abliterated.gguf ~/.greymicroagent/models/

**Step 5. Start it:**

    greymicroagent

## Install on Linux, option 2: the folder

Use this on any Linux system, or if you prefer not to install a package.

**Step 1.** Install Python 3.13 and Node.js 22 as shown in option 1.

**Step 2.** Download the .tar.gz file and the model file.

**Step 3.** Make a folder and unpack the archive into it:

    mkdir greymicroagent
    tar -xzf greymicroagent_0.7.5.4_linux-x86_64.tar.gz -C greymicroagent

**Step 4.** Move the model into the folder:

    mv qwen3.5-2b-abliterated.gguf greymicroagent/model/

**Step 5.** Start it:

    cd greymicroagent
    ./launch.sh

If anything is still missing, run `./package/greymicroagent.sh` once. That script installs the remaining pieces and then starts the program.

## Install on Windows

The Windows download is the full assistant, running natively. It does not need WSL and it never compiles anything.

**Step 1.** Download the .zip file and the model file.

**Step 2.** Extract the archive. On Windows 11 you can right-click the file and choose Extract All. On older versions use 7-Zip.

**Step 3.** Put the model file here:

    %USERPROFILE%\.greymicroagent\models\qwen3.5-2b-abliterated.gguf

Create the folders if they do not exist. You can paste that path into the address bar of File Explorer.

**Step 4.** In the extracted folder, right-click **launch.ps1** and choose **Run with PowerShell**. If Windows blocks it, open PowerShell in that folder and run:

    powershell -ExecutionPolicy Bypass -File .\launch.ps1

**Step 5.** The first start installs Python, Node.js, the Microsoft C++ runtime, and the Python packages automatically if they are missing. It needs an internet connection the first time. Later starts are fast.

The first start also installs a starter knowledge base of about a thousand command references, so /rag has something to answer from out of the box.

The launcher checks for a Vulkan-capable graphics device and, when one is present, runs the model on it with every layer offloaded. Otherwise it runs on the CPU. Integrated graphics share system memory, so there is no VRAM setting to make and nothing is capped by the chip's own memory. The zip carries both x64 and ARM64 engines, and each keeps a matching CPU engine as an automatic fallback. Set GREYAGENT_NGL to pin the number of offloaded layers, or GREYAGENT_THREADS to pin the CPU thread count.

## Talking to it

Type a question and press Enter. The first answer can take a minute because the model is still loading; after that it answers faster.

The bottom of the window shows three small panels: how much the app compressed the conversation, recent activity, and the answer speed. You can ignore them.

## Teaching it your own documents

These commands work on both Linux and Windows. They start with /rag, which is short for retrieval augmented generation, the feature that lets the assistant answer from your own papers and pages.

| Type this | What it does |
| --- | --- |
| /rag status | Shows what the assistant already knows |
| /rag ingest <web address or file> | Adds one web page, PDF, text file, or markdown file. It asks before saving. |
| /rag remove <word> | Shows what would be deleted. Run the same command again to delete it. |
| /rag offline on | Answers only from your own documents |
| /rag offline off | Also allows the model's general knowledge |
| /rag temp 0.1 | Sets how adventurous the answers are, from 0.0 (strict) to 0.2 (looser) |

A document is only added after you confirm, and a deletion only happens when you repeat the same remove command. Nothing is changed silently.

## Is it private?

Yes. Answers are produced on your computer. Nothing is sent anywhere unless you ask for a web search. There is no account, no telemetry, and no cloud service.

Deep web research needs a local search helper, SearXNG, running on your computer. It works without it, using direct search, but a local SearXNG makes research faster and more reliable.

## If something goes wrong

| What you see | What to do |
| --- | --- |
| "command not found: greymicroagent" | The package is not installed. Use the folder option, or install the .deb. |
| "model missing" | The model file is not where the program looks. Put it in ~/.greymicroagent/models/ or in the folder's model/ directory. |
| "model size" or "hash" mismatch | The download is incomplete. Download the model file again. |
| "all sessions in use" | Two copies are already running. Close one. |
| "frozen tree" message | A program file changed after install. Download the release again. |
| Node.js or Python "too old" | Install Node.js 22 and Python 3.13 as shown above. |
| launch.ps1 "cannot be loaded" on Windows | Run the PowerShell command shown in the Windows steps. |

## Under the hood, for the curious

The assistant runs entirely on your machine. One session starts three small local services: the model server, a grounding gate that adds your documents to each question, and a compressor that shortens long tool output. They use a private range of local ports, 7640 to 7647, chosen automatically so two copies can run side by side. Every program file is listed in a signed-off inventory (state/MANIFEST.json) that is checked at every start, so a damaged installation refuses to run instead of giving wrong answers. The model runs on the processor only; no graphics card is required.

## Credits

The starter knowledge base is built from tldr-pages, licensed CC-BY-4.0 (https://github.com/tldr-pages/tldr). The model server is llama.cpp (MIT). slimtoken handles request compression, and patchright drives page reading for deep research. Full third-party license texts ship in THIRD-PARTY-NOTICES.txt inside the download.

## License

Apache License 2.0. The full text is in the LICENSE file.
