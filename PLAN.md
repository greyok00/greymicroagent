# Plan — ollama timeouts (2026-10-22)

1. Diagnose: ollama procs, listeners (:11600/:11434), curl /api/version, GPU, disk, unit state
2. Identify root cause (hung server / GPU held / not running / disk full)
3. Fix WITHOUT rebooting the machine: restart ollama unit or kill hung PID (systemd respawns)
4. Verify: curl /api/version + `ollama ps` respond
5. Report; clarify "log out of ollama" (no such operation exists) + greywatch/perplexity question
