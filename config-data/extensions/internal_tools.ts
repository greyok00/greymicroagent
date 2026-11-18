import type { ExtensionAPI } from "@greyagent/coding-agent";
import * as childProcess from "node:child_process";
import * as os from "node:os";
import * as path from "node:path";

// internal_tools.ts — local tools, converted from the old MCP stdio servers
// (owner order: MCP servers become internal tools). One-shot bridge instead
// of standing servers: each call spawns
//   python3 <root>/services/internal_tools.py call <tool>
// with a JSON args object on stdin and reads one JSON result on stdout.
// Kept lean (owner 2026-11-18): the chat tool list drives CPU prefill cost,
// so only the tools the chat model actually uses register here; knowledge
// upkeep stays on the /rag command; remaining tools live in the python
// registry (core.wiring) and the bridge can still invoke every one of them.

const ROOT =
	process.env.GREYAGENT_ROOT ?? path.join(os.homedir(), "greymicroagent");
const BRIDGE = path.join(ROOT, "services", "internal_tools.py");

function callBridge(tool: string, args: Record<string, unknown>, timeoutMs: number): Promise<string> {
	return new Promise((resolve) => {
		let done = false;
		const finish = (text: string): void => {
			if (!done) {
				done = true;
				resolve(text);
			}
		};
		let proc: childProcess.ChildProcess;
		try {
			proc = childProcess.spawn("python3", [BRIDGE, "call", tool], {
				cwd: ROOT,
				stdio: ["pipe", "pipe", "pipe"],
			});
		} catch (e) {
			finish("internal tool bridge failed to start: " + String(e));
			return;
		}
		proc.unref();
		proc.stdio.forEach((s) => s && s.unref());
		const timer = setTimeout(
			() => finish(tool + ": internal tool timed out after " + timeoutMs + "ms"),
			timeoutMs,
		);
		let out = "";
		proc.stdout?.on("data", (c: Buffer) => {
			out += c.toString();
		});
		proc.stderr?.on("data", () => undefined);
		proc.on("exit", () => {
			clearTimeout(timer);
			try {
				const r = JSON.parse(out) as { ok?: boolean; output?: string; error?: string };
				if (r && typeof r.output === "string" && r.output.length) {
					const tail = r.error ? "\n[error] " + r.error : "";
					finish(r.output + tail);
				} else if (r && r.error) {
					finish("error: " + r.error);
				} else {
					finish(out || "internal tool returned no output");
				}
			} catch {
				finish(out || "internal tool returned no output");
			}
		});
		proc.stdin?.end(JSON.stringify(args ?? {}));
	});
}

interface InternalTool {
	name: string;
	description: string;
	timeout: number;
	params: Record<string, unknown>;
	snippet?: string;
}

const OBJ: Record<string, unknown> = { type: "object", properties: {} };

const TOOLS: InternalTool[] = [
	{
		name: "rag_search",
		description: "Search the operator's knowledge base offline. args: db, query, k(optional).",
		timeout: 60000,
		params: {
			type: "object",
			properties: { db: { type: "string" }, query: { type: "string" }, k: { type: "integer" } },
			required: ["db", "query"],
		},
	},
	{
		name: "search",
		description: "Quick web search. args: query, k(optional).",
		timeout: 90000,
		params: {
			type: "object",
			properties: { query: { type: "string" }, k: { type: "integer" } },
			required: ["query"],
		},
	},
	{
		name: "greysearch",
		description: "Deep web research: search lanes plus full-page scraping. args: query, max_results(optional).",
		timeout: 420000,
		params: {
			type: "object",
			properties: { query: { type: "string" }, max_results: { type: "integer" } },
			required: ["query"],
		},
		snippet: "greysearch is the deep-research capability: for any web research task, call it once instead of scraping pages yourself.",
	},
	{
		name: "browser_open",
		description: "Read one web page in headless chromium. args: url. http(s) only.",
		timeout: 180000,
		params: {
			type: "object",
			properties: { url: { type: "string" } },
			required: ["url"],
		},
	},
	{
		name: "memory_append",
		description: "Save a memory entry. args: content.",
		timeout: 15000,
		params: {
			type: "object",
			properties: { content: { type: "string" } },
			required: ["content"],
		},
	},
	{
		name: "memory_search",
		description: "Search memory. args: query.",
		timeout: 15000,
		params: {
			type: "object",
			properties: { query: { type: "string" } },
			required: ["query"],
		},
	},
	{
		name: "terminal",
		description: "Run a terminal command: bash on Linux, PowerShell on Windows. args: command, timeout(optional seconds).",
		timeout: 3600000,
		params: {
			type: "object",
			properties: { command: { type: "string" }, timeout: { type: "integer" } },
			required: ["command"],
		},
	},
	{
		name: "powershell",
		description: "Run a PowerShell command (pwsh Linux, powershell.exe Windows). args: command, timeout(optional seconds).",
		timeout: 3600000,
		params: {
			type: "object",
			properties: { command: { type: "string" }, timeout: { type: "integer" } },
			required: ["command"],
		},
	},
	{
		name: "skills_list",
		description: "List the local skill library (methodology playbooks on disk).",
		timeout: 15000,
		params: OBJ,
	},
	{
		name: "skill",
		description: "Read one skill playbook in full. args: name (from skills_list).",
		timeout: 15000,
		params: {
			type: "object",
			properties: { name: { type: "string" } },
			required: ["name"],
		},
	},
];

export default function internalTools(pi: ExtensionAPI): void {
	for (const t of TOOLS) {
		const spec: Record<string, unknown> = {
			name: t.name,
			label: t.name,
			description: t.description,
			parameters: t.params as never,
			prepareArguments: (args: unknown) => args as never,
			execute: async (_id: unknown, params: unknown) => {
				const text = await callBridge(
					t.name,
					(params ?? {}) as Record<string, unknown>,
					t.timeout,
				);
				return {
					content: [{ type: "text", text }],
					details: { tool: t.name },
				};
			},
		};
		if (t.snippet) {
			spec.promptSnippet = t.snippet;
		}
		pi.registerTool(spec as never);
	}
}
