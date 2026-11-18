// 2026-10-25: greymicroagent fork of greyagent's models.ts. Local GGUF usable in
// the picker — "greymicroagent-local" carries apiKey "none" so no OAuth/API-key
// check can block it. Cloud provider catalogs are emptied: greymicroagent is
// LOCAL-ONLY (same owner order as the cortexagent and greyagent forks).

import type { ExtensionAPI } from "@greyagent/coding-agent";  // 2026-10-24 hardened: renamed scope
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { state } from "./lib/shared.ts";

export default function modelsExtension(pi: ExtensionAPI): void {
	// Local-only directive: every builtin cloud catalog is emptied so the
	// picker can't offer cloud models.
	pi.registerProvider("amazon-bedrock", { models: [] });
	pi.registerProvider("anthropic", { models: [] });
	pi.registerProvider("azure-openai-responses", { models: [] });
	pi.registerProvider("baseten", { models: [] });
	pi.registerProvider("cerebras", { models: [] });
	pi.registerProvider("cloudflare-ai-gateway", { models: [] });
	pi.registerProvider("cloudflare-workers-ai", { models: [] });
	pi.registerProvider("fireworks", { models: [] });
	pi.registerProvider("github-copilot", { models: [] });
	pi.registerProvider("google", { models: [] });
	pi.registerProvider("google-vertex", { models: [] });
	pi.registerProvider("groq", { models: [] });
	pi.registerProvider("huggingface", { models: [] });
	pi.registerProvider("mistral", { models: [] });
	pi.registerProvider("nvidia", { models: [] });
	pi.registerProvider("openai", { models: [] });
	pi.registerProvider("openai-codex", { models: [] });
	pi.registerProvider("opencode", { models: [] });
	pi.registerProvider("opencode-go", { models: [] });
	pi.registerProvider("openrouter", { models: [] });
	pi.registerProvider("together", { models: [] });
	pi.registerProvider("vercel-ai-gateway", { models: [] });
	pi.registerProvider("xai", { models: [] });

	// 2026-10-18 (owner directive, carried into greyagent): samplingParams
	// force temp 0.6 + top_p 0.95 — the same GREYAGENT_TEMP/GREYAGENT_TOP_P
	// env names the launcher exports.
	const SAFE_TEMP = Number(process.env.GREYAGENT_TEMP ?? "0.6");
	const SAFE_TOP_P = Number(process.env.GREYAGENT_TOP_P ?? "0.95");
	// 2026-10-25 phase 2: labels follow the SESSION's slot (the launcher
	// exports GREYAGENT_MODEL_PORT/GREYAGENT_LANE_PORT per launch). Defaults
	// match slot 1 so a direct boot without the launcher still reads right.
	const LANE_PORT = process.env.GREYAGENT_LANE_PORT ?? "7081";
	const MODEL_PORT = process.env.GREYAGENT_MODEL_PORT ?? "7080";
	// 2026-10-25 (owner 400s at 221k tokens): the window MUST be declared
	// here. The TUI never asks the server for n_ctx — agent-session uses
	// `contextWindow ?? 0` (proactive compaction dead) and the summarizer
	// falls back to `?? 262144` (chunks budgeted 4x too big), so undeclared
	// models hit `exceed_context_size_error` with no recovery. GREYAGENT_CTX
	// is the same env server.py boots with, so this tracks the real window.
	// 2026-10-31 QA (GT-34 class): the server can settle on a DIFFERENT real
	// window than the launcher's env (VRAM ladder), and a stale env value made
	// compaction trigger ABOVE the usable window (400 overflow before
	// compaction). Read the settle file the server writes, prefer the smaller
	// of it and the env window; env keeps working as the override.
	const CTX = (() => {
		const envW = ((): number | null => {
			const v = process.env.GREYAGENT_CTX;
			return v ? Number(v) : null;
		})();
		let settled: number | null = null;
		// Fork-aware candidates: the VRAM ladder writes into THIS fork's own
		// state dir (server.py ROOT/"state"); greyagent's is the upstream
		// default. First existing file wins.
		const stateCandidates = [
			process.env.GREYAGENT_ROOT ? path.join(process.env.GREYAGENT_ROOT, "state", "model-ctx-settled.txt") : null,
			path.join(os.homedir(), "greyagent", "state", "model-ctx-settled.txt"),
		].filter((p): p is string => !!p);
		for (const p of stateCandidates) {
			try {
				const n = Number(fs.readFileSync(p, "utf8").trim());
				if (Number.isFinite(n) && n > 0) { settled = n; break; }
			} catch {}
		}
		if (settled && envW && envW > 0) return Math.min(settled, envW);
		return settled ?? envW ?? 65536;
	})();

	pi.registerProvider("greymicroagent-local", {
		name: `greymicroagent (:${LANE_PORT} lane)`,
		baseUrl: process.env.GREYAGENT_LOCAL_BASE || `http://127.0.0.1:${LANE_PORT}/v1`,
		apiKey: "none",
		api: "openai-completions",
		samplingParams: { temperature: SAFE_TEMP, top_p: SAFE_TOP_P },
		models: [
			{
				id: "greymicroagent",
				name: `Qwen3.5-2B-abliterated (local, :${MODEL_PORT})`,
				reasoning: true,
				input: ["text"],
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
				// Declared so both compaction ends act on the REAL window:
				// shouldCompact fires early (at 64k - reserve) and the
				// rolling-update summarizer chunks within 64k. maxTokens
				// stays unset (server decides per request).
				contextWindow: CTX > 0 ? CTX : 65536,
				samplingParams: { temperature: SAFE_TEMP, top_p: SAFE_TOP_P },
			},
		],
	});

	void state;
}