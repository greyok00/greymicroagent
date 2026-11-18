import type { ExtensionAPI } from "@greyagent/coding-agent";
import * as childProcess from "node:child_process";
import * as os from "node:os";
import * as path from "node:path";

// internal_tools.ts — local tools, converted from the old MCP stdio servers
// (owner order: MCP servers become internal tools). One-shot bridge instead
// of standing servers: each call spawns
//   python3 <root>/services/internal_tools.py call <tool>
// with a JSON args object on stdin and reads one JSON result on stdout.
// Every tool routes through the agent's own registry (core.wiring), so the
// TUI and the agent loop share one tool set. No JSON-RPC, no registry
// file, no long-lived child process.

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
		name: "terminal",
		description:
			"Run a terminal command: bash on Linux, PowerShell on Windows. args: command (string), timeout (seconds, optional).",
		timeout: 3600000,
		params: {
			type: "object",
			properties: { command: { type: "string" }, timeout: { type: "integer" } },
			required: ["command"],
		},
	},
	{
		name: "powershell",
		description:
			"Run a PowerShell command (pwsh on Linux, powershell.exe on Windows builds). args: command, timeout (seconds, optional).",
		timeout: 3600000,
		params: {
			type: "object",
			properties: { command: { type: "string" }, timeout: { type: "integer" } },
			required: ["command"],
		},
	},
	{
		name: "rag_status",
		description: "List local knowledge bases with record counts.",
		timeout: 30000,
		params: OBJ,
	},
	{
		name: "rag_search",
		description:
			"Search a local knowledge base offline. args: db (name), query, k (optional, default 5).",
		timeout: 60000,
		params: {
			type: "object",
			properties: {
				db: { type: "string" },
				query: { type: "string" },
				k: { type: "integer" },
			},
			required: ["db", "query"],
		},
	},
	{
		name: "rag_ingest_text",
		description:
			"Ingest text into a knowledge base. CONSENT-GATED: pass confirm=true. args: db, text, confirm.",
		timeout: 120000,
		params: {
			type: "object",
			properties: {
				db: { type: "string" },
				text: { type: "string" },
				confirm: { type: "boolean" },
			},
			required: ["db", "text", "confirm"],
		},
	},
	{
		name: "rag_ingest_pdf",
		description:
			"Ingest a PDF into a knowledge base. CONSENT-GATED: pass confirm=true. args: db, path, confirm.",
		timeout: 300000,
		params: {
			type: "object",
			properties: {
				db: { type: "string" },
				path: { type: "string" },
				confirm: { type: "boolean" },
			},
			required: ["db", "path", "confirm"],
		},
	},
	{
		name: "rag_ingest_urls",
		description:
			"Ingest web pages into a knowledge base. CONSENT-GATED: pass confirm=true. args: db, urls (string list), confirm.",
		timeout: 300000,
		params: {
			type: "object",
			properties: {
				db: { type: "string" },
				urls: { type: "array", items: { type: "string" } },
				confirm: { type: "boolean" },
			},
			required: ["db", "urls", "confirm"],
		},
	},
	{
		name: "rag_remove",
		description:
			"Two-step removal: the first call previews matches, the confirmed repeat deletes. args: db, match, confirm.",
		timeout: 60000,
		params: {
			type: "object",
			properties: {
				db: { type: "string" },
				match: { type: "string" },
				confirm: { type: "boolean" },
			},
			required: ["db", "match"],
		},
	},
	{
		name: "rag_list_sources",
		description: "List sources recorded in a knowledge base. args: db.",
		timeout: 30000,
		params: {
			type: "object",
			properties: { db: { type: "string" } },
			required: ["db"],
		},
	},
	{
		name: "search",
		description:
			"Quick web search over the local search lanes. args: query, k (optional).",
		timeout: 90000,
		params: {
			type: "object",
			properties: { query: { type: "string" }, k: { type: "integer" } },
			required: ["query"],
		},
	},
	{
		name: "search_health",
		description: "Check the quick-search lane health.",
		timeout: 30000,
		params: OBJ,
	},
	{
		name: "greysearch",
		description:
			"Deep web research: multi-lane search plus full-page scraping; call ONCE for a research task rather than scraping pages yourself. args: query, max_results (optional).",
		timeout: 420000,
		params: {
			type: "object",
			properties: {
				query: { type: "string" },
				max_results: { type: "integer" },
			},
			required: ["query"],
		},
		snippet:
			"greysearch is the core deep-research capability (multi-lane search + page scraping). For any web research task, call it once instead of scraping pages yourself.",
	},
	{
		name: "greysearch_health",
		description: "Check the deep-research lane health.",
		timeout: 30000,
		params: OBJ,
	},
	{
		name: "browser_open",
		description:
			"Read ONE web page in a real headless chromium: {title, text, url_final, links, status}. http(s) urls only. args: url.",
		timeout: 180000,
		params: {
			type: "object",
			properties: { url: { type: "string" } },
			required: ["url"],
		},
	},
	{
		name: "browser_close",
		description: "Free the shared browser opened by browser_open. Idempotent.",
		timeout: 30000,
		params: OBJ,
	},
	{
		name: "memory_append",
		description: "Save memory. args: content (string).",
		timeout: 15000,
		params: {
			type: "object",
			properties: { content: { type: "string" } },
			required: ["content"],
		},
	},
	{
		name: "memory_search",
		description: "Search memory. args: query (string).",
		timeout: 15000,
		params: {
			type: "object",
			properties: { query: { type: "string" } },
			required: ["query"],
		},
	},
	{
		name: "memory_read",
		description: "Recent memory entries.",
		timeout: 15000,
		params: OBJ,
	},
	{
		name: "skills_list",
		description: "List the local skill library (methodology playbooks on disk).",
		timeout: 15000,
		params: OBJ,
	},
	{
		name: "skill",
		description:
			"Read one local skill playbook in full. args: name (from skills_list).",
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
