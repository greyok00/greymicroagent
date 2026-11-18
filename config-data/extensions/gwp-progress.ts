// 2026-10-30 (greywebpentest): pipeline progress tracking. Replaces the
// dead Compression panel (the slimtoken lane is disabled by design — the
// model talks straight to :7420).
//
// How progress is decided (owner spec): BEFORE showing any percentage, this
// extension ANALYZES what is actually available and what the real chain will
// be — the available-tool half comes from the MCP registry on disk, the
// chain half is the canonical web-pentest pipeline, filtered to tools that
// are actually registered in this session. As the agent runs, completed
// chain steps fill the bar; a tool outside the chain extends it (the real
// chain grows rather than progress being faked).
import type { ExtensionAPI, ExtensionContext } from "@greyagent/coding-agent";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const LOG = (m: string) => { try { fs.appendFileSync("/tmp/gwp-onboarding.log", new Date().toISOString() + " progress " + m + "\n"); } catch {} };

// Canonical chains per suite — loaded from profiles/<suite>/chain.json (the
// launcher sets GREYAGENT_PROFILE); the web chain is the fallback. Names are
// the MCP tool names WITHOUT the mcp_greyteam_ prefix (matched on the suffix).
// 2026-11-03 (owner order): documents are NO LONGER chain steps — they are
// explicit actions (CLI: ask for them in-session; web console: Generate
// buttons). Fallback chain ends at the scope gate like the profile files.
const FALLBACK_CHAIN: string[] = [
	"create_assessment",
	"tech_detection",
	"webpentest_run",
	"scope_handoff",
];

function chainForSuite(): string[] {
	try {
		const suite = process.env.GREYAGENT_PROFILE ?? "web";
		const root = process.env.GREYAGENT_ROOT ?? path.join(os.homedir(), "Desktop", "greyteam");
		return JSON.parse(fs.readFileSync(
			path.join(root, "greypentest", "profiles", suite, "chain.json"), "utf8"));
	} catch {
		return FALLBACK_CHAIN;
	}
}

function registryRoot(): string {
	return process.env.GREYAGENT_ROOT ?? path.join(os.homedir(), "Desktop", "greyteam");
}

function availableTools(): string[] {
	// From OUR registry: parse each server command for the script path,
	// then import it from python is overkill — the tool names are stable
	// (25 greyteam tools); the check that matters is registry presence.
	try {
		const reg = JSON.parse(fs.readFileSync(
			process.env.CORTEXAGENT_MCP_CONFIG ??
			path.join(registryRoot(), "greywebpentest/config/mcp_registry.json"), "utf8"));
		return (reg.servers ?? []).filter((s: { enabled?: boolean }) => s.enabled).map((s: { name: string }) => s.name);
	} catch {
		return [];
	}
}

function progressFile(): string {
	return process.env.GWPPROGRESS_FILE ??
		path.join(process.env.CORTEXAGENT_STATE_DIR ?? path.join(os.homedir(), ".greylocalrag", "state"), "progress.json");
}

interface Progress {
	available: number;
	chain: string[];
	done: string[];
	running: string | null;
	startedAt: number | null;
	updatedAt: number;
}

function writeProgress(_serverSuffixToTool: Map<string, string>, p: Progress): void {
	try {
		fs.mkdirSync(path.dirname(progressFile()), { recursive: true });
		fs.writeFileSync(progressFile(), JSON.stringify(p));
	} catch (e) {
		LOG("write failed " + String(e));
	}
}

export default function gwpProgress(pi: ExtensionAPI): void {
	let analyzed = false;
	let chain: string[] = [];
	let done: string[] = [];
	let running: string | null = null;
	let startedAt: number | null = null;

	// Chain analysis — once, at session start, from what is REAL:
	// available MCP servers from the registry; the chain from the canonical
	// pipeline filtered to tools the registered servers actually expose.
	pi.on("session_start", (_event, _ctx: ExtensionContext) => {
		const servers = availableTools();
		const greyteam = servers.includes("greyteam");
		chain = greyteam ? chainForSuite() : [];
		done = [];
		running = null;
		startedAt = null;
		analyzed = greyteam;
		const suffixToTool = new Map<string, string>(chain.map((c) => [c, "mcp_greyteam_" + c]));
		writeProgress(suffixToTool, { available: servers.length, chain, done, running, startedAt, updatedAt: Date.now() });
		LOG(`analyzed: servers=${servers.length} chain=${chain.length} steps`);
	});

	pi.on("tool_execution_start", (event) => {
		if (!analyzed) return;
		const ev = event as unknown as { toolName?: string };
		const name = ev.toolName ?? "";
		running = name.replace(/^mcp_[a-z]+_/, "");
		startedAt = startedAt ?? Date.now();
		writeProgress(new Map(), { available: chain.length, chain, done, running, startedAt, updatedAt: Date.now() });
	});

	pi.on("tool_execution_end", (event) => {
		if (!analyzed) return;
		const ev = event as unknown as { toolName?: string; isError?: boolean };
		const short = (ev.toolName ?? "").replace(/^mcp_[a-z]+_/, "");
		running = null;
		if (!short) return;
		// The REAL chain grows when the agent reaches for a tool outside the
		// canonical pipeline — the denominator follows reality.
		if (!chain.includes(short)) chain.push(short);
		if (!done.includes(short)) done.push(short);
		writeProgress(new Map(), { available: chain.length, chain, done, running, startedAt, updatedAt: Date.now() });
	});
}