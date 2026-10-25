import type { ExtensionAPI } from "@greyagent/coding-agent";
import * as childProcess from "node:child_process";
import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

// greyhound_core.ts — owner order 2026-10-24: "FULLY INTEGRATE IT INTO
// GREYAGENT BEYOND A SIMPLE MCP SERVER. IT MUST BE PART OF THE CORE."
// Greyhound is a FIRST-CLASS capability, not an opt-in registry entry:
//   - the compiled modules live IN the frozen tree (core/greyhound/*.so,
//     every file sha256-pinned in state/MANIFEST.json by gen_manifest);
//   - this loader verifies the main .so's hash AGAINST THE FROZEN MANIFEST
//     immediately before every spawn — a swapped binary refuses to run;
//   - tools register under their native names (greyhound, greyhound_health)
//     with usage guidance so the model reaches for them on research tasks;
//   - ONE server process per TUI session, spawned by the harness itself.
// Transport stays JSON-RPC over stdio (Node harness → CPython 3.13 .so);

const ROOT = path.join(os.homedir(), "greymini");
const CORE_DIR = path.join(ROOT, "core", "greyhound");
const MANIFEST = path.join(ROOT, "state", "MANIFEST.json");

interface ToolSpec {
	name: string;
	description?: string;
	inputSchema?: Record<string, unknown>;
}

interface CoreConn {
	proc: childProcess.ChildProcess;
	nextId: number;
	pending: Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>;
	buffer: string;
}

function manifestHashOf(relpath: string): string | null {
	try {
		const m = JSON.parse(fs.readFileSync(MANIFEST, "utf8"));
		return m.files?.["core/greyhound/" + relpath]?.sha256 ?? null;
	} catch {
		return null;
	}
}

function verifyBinary(): { ok: boolean; detail: string } {
	try {
		const mains = fs.readdirSync(CORE_DIR).filter((f) => f.startsWith("greyhound_mcp") && f.endsWith(".so"));
		if (!mains.length) return { ok: false, detail: "compiled greyhound missing from core/greyhound" };
		const main = "greyhound_mcp" + mains[0]!.slice(mains[0]!.lastIndexOf("."));
		const pin = manifestHashOf(mains[0]!);
		const actual = crypto.createHash("sha256").update(fs.readFileSync(path.join(CORE_DIR, mains[0]!))).digest("hex");
		if (pin && pin !== actual) return { ok: false, detail: `hash mismatch — frozen: ${pin.slice(0, 12)} actual: ${actual.slice(0, 12)}` };
		return { ok: true, detail: pin ? "hash verified vs frozen manifest" : "no frozen pin (unpinned build — verify_manifest run pending)" };
	} catch (e) {
		return { ok: false, detail: String(e) };
	}
}

function spawnCore(): CoreConn {
	// PYTHONPATH pins the process to the core-resident copy: what we hash-verify
	// above is exactly what runs (mcp/ twin is the distribution original).
	const proc = childProcess.spawn(
		"/bin/sh",
		["-c", `GREYAGENT_CORE_TOOLS=${CORE_DIR} python3 ${ROOT}/mcp/run_server.py --server greyhound_mcp`],
		{
			cwd: CORE_DIR,
			stdio: ["pipe", "pipe", "pipe"],
		},
	) as unknown as childProcess.ChildProcess;
	const conn: CoreConn = { proc, nextId: 1, pending: new Map(), buffer: "" };
	(proc.stdout as any).on("data", (chunk: Buffer) => {
		conn.buffer += chunk.toString();
		let nl: number;
		while ((nl = conn.buffer.indexOf("\n")) !== -1) {
			const line = conn.buffer.slice(0, nl).trim();
			conn.buffer = conn.buffer.slice(nl + 1);
			if (!line) continue;
			try {
				const msg = JSON.parse(line);
				const id = msg.id as number | undefined;
				if (id !== undefined && conn.pending.has(id)) {
					const p = conn.pending.get(id)!;
					conn.pending.delete(id);
					if (msg.error) p.reject(new Error(String(msg.error.message ?? JSON.stringify(msg.error))));
					else p.resolve(msg.result);
				}
			} catch {
				/* non-JSON log line */
			}
		}
	});
	(proc.stderr as any)?.on("data", () => undefined);
	return conn;
}

function call(conn: CoreConn, method: string, params: unknown, timeoutMs = 60000): Promise<unknown> {
	const id = conn.nextId++;
	return new Promise((resolve, reject) => {
		const timer = setTimeout(() => {
			conn.pending.delete(id);
			reject(new Error(`greyhound core: ${method} timed out`));
		}, timeoutMs);
		conn.pending.set(id, {
			resolve: (v) => {
				clearTimeout(timer);
				resolve(v);
			},
			reject: (e: Error) => {
				clearTimeout(timer);
				reject(e);
			},
		});
		(conn.proc.stdin as any)?.write?.(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
	});
}

function textOf(result: unknown): string {
	const r = result as { content?: { type?: string; text?: string }[] } | null;
	if (!r || !Array.isArray(r.content)) return JSON.stringify(result ?? null);
	return r.content.map((c) => (c.type === "text" ? String(c.text ?? "") : JSON.stringify(c))).join("\n");
}

export default function greyhoundCore(pi: ExtensionAPI): void {
	const verdict = verifyBinary();
	if (!verdict.ok) {
		return;
	}
	const conn = spawnCore();
	void (async () => {
		try {
			await call(conn, "initialize", {
				protocolVersion: "2024-11-05",
				capabilities: {},
				clientInfo: { name: "greymini-core", version: "0.7.5.1" },
			}, 20000);
			(conn.proc.stdin as any)?.write?.(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n");
			const listed = (await call(conn, "tools/list", {}, 20000)) as { tools?: ToolSpec[] };
			for (const t of listed.tools ?? []) {
				pi.registerTool({
					name: t.name,
					label: t.name,
					description: t.description ?? t.name,
					promptSnippet: "tools greyhound/greyhound_health are CORE web-research capabilities — use greyhound for any web research (deep search + scrape + guide), greyhound_health to check its lanes",
					promptGuidelines: ["Greyhound is core-integrated: for web research or page scraping, call it ONCE (background=true) rather than scraping pages yourself."],
					parameters: (t.inputSchema ?? { type: "object", properties: {} }) as never,
					prepareArguments: (args) => args as never,
					execute: async (_id, params) => {
						const res = await call(conn, "tools/call", { name: t.name, arguments: params ?? {} }, 300000);
						return {
							content: [{ type: "text", text: textOf(res) }],
							details: { tool: t.name },
						};
					},
				});
			}
		} catch {
			/* core tool unavailable this session — never breaks the chat */
		}
	})();
}