import type { ExtensionAPI } from "@greyagent/coding-agent";
import * as childProcess from "node:child_process";
import * as os from "node:os";
import * as path from "node:path";

// internal_tools.ts — local tools over the one-shot bridge, with lazy loading.
//
// One-shot bridge: each call spawns
//   python3 <root>/services/internal_tools.py call <tool>
// with a JSON args object on stdin and reads one JSON result on stdout.
//
// LAZY TOOL LOADING (owner 2026-11-19): every tool schema in the request costs
// CPU prefill, and llama only reuses a prompt prefix it has seen before, so the
// request carries a tiny stable set instead of the whole catalog:
//   always on — rag_search, rag_status, terminal, powershell, tool_search
//   on demand — everything else, pulled by tool_search
// tool_search scores the live Python registry (services/internal_tools.py
// list) with plain keyword heuristics, returns the full schemas in its result,
// and registers the winners through pi.registerTool, which refreshes the tool
// registry so they are callable on the model's very next step. Execution is
// unchanged; only reachability is deferred.

const ROOT =
	process.env.GREYAGENT_ROOT ?? path.join(os.homedir(), "greymicroagent");
const BRIDGE = path.join(ROOT, "services", "internal_tools.py");
// The packaged Windows build ships python.exe, not python3.
const PY = process.platform === "win32" ? "python" : "python3";

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
			proc = childProcess.spawn(PY, [BRIDGE, "call", tool], {
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

interface ToolSpec {
	name: string;
	description: string;
	params: Record<string, unknown>;
	timeout: number;
}

interface CatalogEntry {
	name: string;
	description: string;
	parameters: Record<string, unknown>;
}

// Always registered: the product's RAG core plus both shells for Linux and
// Windows, and the loader itself.
const HOT: ToolSpec[] = [
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
		name: "rag_status",
		description: "List local knowledge bases with record counts.",
		timeout: 30000,
		params: { type: "object", properties: {}, required: [] },
	},
	{
		name: "rag_list_sources",
		description: "List the sources recorded in a knowledge base. args: db.",
		timeout: 60000,
		params: {
			type: "object",
			properties: { db: { type: "string" } },
			required: ["db"],
		},
	},
	{
		name: "rag_ingest_urls",
		description: "Add web pages to a knowledge base. CONSENT-GATED: confirm=true required. args: db, urls (array), confirm (true).",
		timeout: 600000,
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
		name: "rag_ingest_text",
		description: "Add a SHORT note (max 8000 chars) to a knowledge base. For web pages use greysearch/search then rag_ingest_urls. CONSENT-GATED: confirm=true required. args: db, text, confirm (true).",
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
	// Internal memory is the other half of "memory" (owner 2026-11-19: memory
	// must check BOTH the agent memory and the RAG, so both surfaces stand).
	{
		name: "memory_report",
		description: "Report BOTH stores in one call: recent internal memory AND the RAG collections and sources.",
		timeout: 60000,
		params: { type: "object", properties: {}, required: [] },
	},
	{
		name: "memory_read",
		description: "Read the most recent internal memory entries.",
		timeout: 15000,
		params: { type: "object", properties: {}, required: [] },
	},
	{
		name: "memory_search",
		description: "Search the internal agent memory. args: query.",
		timeout: 15000,
		params: {
			type: "object",
			properties: { query: { type: "string" } },
			required: ["query"],
		},
	},
	{
		name: "memory_append",
		description: "Save an entry to internal memory. args: content.",
		timeout: 15000,
		params: {
			type: "object",
			properties: { content: { type: "string" } },
			required: ["content"],
		},
	},
	{
		name: "terminal",
		description: "Run a terminal command: bash on Linux, PowerShell on Windows. args: command (required, e.g. \"cat /etc/hostname\"), timeout(optional seconds).",
		timeout: 3600000,
		params: {
			type: "object",
			properties: { command: { type: "string" }, timeout: { type: "integer" } },
			required: ["command"],
		},
	},
	{
		name: "powershell",
		description: "Run a PowerShell command (pwsh on Linux, powershell.exe on Windows). args: command, timeout(optional seconds).",
		timeout: 3600000,
		params: {
			type: "object",
			properties: { command: { type: "string" }, timeout: { type: "integer" } },
			required: ["command"],
		},
	},
	// Research stays hot (owner 2026-11-19: the model could not reach research
	// through tool_search — it scored nothing and then matched "system" on the
	// word "systemd"). These three cost little and are the product's main use.
	{
		name: "search",
		description: "Quick web search over the local search lanes. args: query, k(optional).",
		timeout: 90000,
		params: {
			type: "object",
			properties: { query: { type: "string" }, k: { type: "integer" } },
			required: ["query"],
		},
	},
	{
		name: "greysearch",
		description: "Deep web research: multi-lane search plus full-page scraping. args: query, max_results(optional).",
		timeout: 420000,
		params: {
			type: "object",
			properties: { query: { type: "string" }, max_results: { type: "integer" } },
			required: ["query"],
		},
	},
	{
		name: "web_fetch",
		description: "Fetch one URL in the headless browser; returns cleaned text. args: url.",
		timeout: 180000,
		params: {
			type: "object",
			properties: { url: { type: "string" } },
			required: ["url"],
		},
	},
];

const HOT_NAMES = new Set(HOT.map((t) => t.name).concat(["tool_search"]));

// (2026-11-19) vision was removed from the registry entirely: the vendored
// engine cannot build the Qwen3-VL vision graph and the product now ships the
// text model, so there is no tool left to deny here.

// Heuristic routing: plain words the operator will use, mapped to tool names.
const ALIASES: Record<string, string[]> = {
	web: ["search", "web_search", "web_fetch", "browser_open"],
	search: ["search", "web_search", "greysearch", "web_fetch"],
	research: ["greysearch", "search", "web_fetch", "browser_open"],
	browse: ["browser_open", "chrome_navigate", "chrome_snapshot", "web_fetch"],
	page: ["browser_open", "web_fetch"],
	url: ["browser_open", "web_fetch", "rag_ingest_urls"],
	memory: ["memory_search", "memory_append", "memory_read"],
	remember: ["memory_append", "memory_search"],
	recall: ["memory_search", "memory_read"],
	file: ["files_read", "files_write", "files_edit", "files_list", "search_files", "search_grep"],
	files: ["files_list", "files_read", "files_write", "files_edit"],
	read: ["files_read", "search_grep", "memory_read"],
	write: ["files_write", "files_edit"],
	edit: ["files_edit"],
	grep: ["search_grep", "search_files"],
	find: ["search_files", "search_grep"],
	skill: ["skills_list", "skill"],
	skills: ["skills_list", "skill"],
	chart: ["charts"],
	graph: ["charts"],
	vision: ["vision"],
	image: ["vision"],
	picture: ["vision"],
	schedule: ["scheduler_add", "scheduler_list"],
	timer: ["scheduler_add", "scheduler_list"],
	subagent: ["spawn_subagent"],
	subagents: ["spawn_subagent"],
	knowledge: ["rag_list_sources", "rag_search", "rag_status"],
	document: ["parse_document", "rag_ingest_pdf"],
	pdf: ["parse_document", "rag_ingest_pdf"],
	ingest: ["rag_ingest_urls", "rag_ingest_text", "rag_ingest_pdf"],
	shell: ["shell", "terminal", "powershell"],
	system: ["system", "terminal"],
	chrome: ["chrome_status", "chrome_navigate", "chrome_snapshot", "chrome_health"],
	// Research intent in plain words (owner 2026-11-19: "find docs to add to
	// rag" scored nothing and the model got stuck).
	docs: ["search", "greysearch", "web_fetch", "browser_open"],
	doc: ["search", "greysearch", "web_fetch", "parse_document"],
	documentation: ["search", "greysearch", "web_fetch", "browser_open"],
	manual: ["search", "greysearch", "web_fetch"],
	guide: ["search", "greysearch", "web_fetch"],
	reference: ["search", "greysearch", "web_fetch"],
	howto: ["search", "greysearch", "web_fetch"],
	tutorial: ["search", "greysearch", "web_fetch"],
	linux: ["search", "greysearch", "web_fetch", "terminal", "rag_search"],
	unix: ["search", "greysearch", "web_fetch", "terminal"],
	systemd: ["search", "greysearch", "web_fetch"],
	admin: ["search", "greysearch", "terminal"],
	administration: ["search", "greysearch", "terminal"],
};

function timeoutFor(name: string): number {
	if (name === "terminal" || name === "powershell" || name === "shell") return 3600000;
	if (name === "greysearch" || name === "greysearch_health") return 420000;
	if (name === "browser_open" || name === "chrome_navigate") return 180000;
	if (name === "spawn_subagent") return 600000;
	return 90000;
}

function loadCatalog(): CatalogEntry[] {
	try {
		const out = childProcess.execFileSync(PY, [BRIDGE, "list"], {
			cwd: ROOT,
			timeout: 20000,
			encoding: "utf8",
			maxBuffer: 8 * 1024 * 1024,
		});
		const parsed = JSON.parse(out) as CatalogEntry[];
		return Array.isArray(parsed) ? parsed : [];
	} catch {
		return [];
	}
}

function hasWord(text: string, term: string): boolean {
	// Word-boundary match: "systemd" must not match the "system" tool.
	const esc = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
	return new RegExp("(^|[^a-z0-9_])" + esc + "($|[^a-z0-9_])").test(text);
}

function scoreEntry(entry: CatalogEntry, terms: string[]): number {
	const name = entry.name.toLowerCase();
	const desc = entry.description.toLowerCase();
	let score = 0;
	for (const term of terms) {
		if (hasWord(name, term)) score += 4;
		if (hasWord(desc, term)) score += 1;
		const targets = ALIASES[term];
		if (targets && targets.includes(entry.name)) score += 6;
	}
	return score;
}

function registerSpec(pi: ExtensionAPI, spec: ToolSpec): void {
	pi.registerTool({
		name: spec.name,
		label: spec.name,
		description: spec.description,
		parameters: spec.params as never,
		prepareArguments: (args: unknown) => args as never,
		execute: async (_id: unknown, params: unknown) => {
			const p = (params ?? {}) as Record<string, unknown>;
			// Deterministic arg check (owner 2026-11-19: heuristics should carry
			// the burden): a small model will sometimes emit the tool name with
			// an empty argument object. Reject it with the exact missing keys
			// instead of executing a no-op and confusing the next turn.
			const required = (spec.params as { required?: string[] }).required ?? [];
			const missing = required.filter((k) => p[k] === undefined || p[k] === null || p[k] === "");
			if (missing.length) {
				return {
					content: [{
						type: "text",
						text: "error: " + spec.name + " requires " + missing.join(", ") +
							". Re-issue the call with those arguments.",
					}],
					details: { tool: spec.name, error: "missing_args" },
				};
			}
			const text = await callBridge(spec.name, p, spec.timeout);
			return {
				content: [{ type: "text", text }],
				details: { tool: spec.name },
			};
		},
	} as never);
}

export default function internalTools(pi: ExtensionAPI): void {
	for (const spec of HOT) registerSpec(pi, spec);

	pi.registerTool({
		name: "tool_search",
		label: "tool_search",
		description:
			"Load a local tool that is not currently available. args: query (describe the job in plain words). " +
			"Use for web search, deep research, page reading, memory, files, skills, charts, vision, scheduling, subagents.",
		parameters: {
			type: "object",
			properties: { query: { type: "string" } },
			required: ["query"],
		} as never,
		prepareArguments: (args: unknown) => args as never,
		execute: async (_id: unknown, params: unknown) => {
			const query = String((params as Record<string, unknown> | undefined)?.query ?? "").trim();
			const catalog = loadCatalog();
			if (!catalog.length) {
				return {
					content: [{ type: "text", text: "tool catalog unavailable: the internal bridge did not answer." }],
					details: { tool: "tool_search" },
				};
			}
			const terms = query
				.toLowerCase()
				.split(/[^a-z0-9_]+/)
				.filter((t) => t.length >= 2);
			const ranked = catalog
				.filter((e) => !HOT_NAMES.has(e.name))
				.map((e) => ({ entry: e, score: scoreEntry(e, terms) }))
				.filter((x) => x.score > 0)
				.sort((a, b) => b.score - a.score)
				.slice(0, 3);
			if (!ranked.length) {
				// Never leave the model without a research path: an unclear or
				// misspelled request loads the web family instead of a dead end.
				const byName = new Map(catalog.map((e) => [e.name, e]));
				const fallback = ["search", "web_search", "greysearch"]
					.map((n) => byName.get(n))
					.filter((e): e is CatalogEntry => Boolean(e));
				for (const entry of fallback) {
					registerSpec(pi, {
						name: entry.name,
						description: entry.description,
						params: entry.parameters,
						timeout: timeoutFor(entry.name),
					});
				}
				const names = fallback.map((e) => e.name);
				return {
					content: [{
						type: "text",
						text:
							"No exact match for \"" + query + "\". Loaded the research tools instead: " +
							names.join(", ") + ". Call one directly.",
					}],
					details: { tool: "tool_search", matched: 0, fallback: names },
				};
			}
			for (const { entry } of ranked) {
				registerSpec(pi, {
					name: entry.name,
					description: entry.description,
					params: entry.parameters,
					timeout: timeoutFor(entry.name),
				});
			}
			const names = ranked.map((r) => r.entry.name);
			const schemas = JSON.stringify(ranked.map((r) => ({
				name: r.entry.name,
				description: r.entry.description,
				parameters: r.entry.parameters,
			})));
			return {
				content: [{
					type: "text",
					text:
						"Loaded for this session: " + names.join(", ") +
						". Call them directly on your next step.\nSchemas: " + schemas,
				}],
				details: { tool: "tool_search", matched: names.length, names },
			};
		},
	} as never);
}
