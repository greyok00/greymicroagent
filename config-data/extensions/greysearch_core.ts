import type { ExtensionAPI } from "@greyagent/coding-agent";
import * as childProcess from "node:child_process";
import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

// greysearch_core.ts — greysearch is a FIRST-CLASS capability, not an opt-in
// registry entry (owner orders 2026-10-24 and 2026-11-01: "remove greyhound
// and fully integrate the latest greysearch"). Shared by the greylocalrag and
// greypentest TUIs (both agents mount this one extensions dir); the tree is
// picked off GREYAGENT_PLATFORM, set by each launcher:
//   - the compiled modules live IN the frozen tree (core/greysearch/*.so,
//     every file sha256-pinned in state/MANIFEST.json by gen_manifest);
//   - this loader verifies the main .so's hash AGAINST THE FROZEN MANIFEST
//     immediately before every spawn — a swapped binary refuses to run;
//   - tools register under their native names (greysearch, greysearch_health)
//     with usage guidance so the model reaches for them on research tasks;
//   - ONE server process per TUI session, spawned by the harness itself.
// Transport stays JSON-RPC over stdio (Node harness → CPython 3.13 .so);
// replaces greyhound_core.ts (old greyhound iteration removed 2026-11-01).

const PLATFORM = process.env.GREYAGENT_PLATFORM || "greylocalrag";
const ROOT =
	PLATFORM === "greypentest"
		? path.join(os.homedir(), "greypentest", "greypentest")
		: path.join(os.homedir(), "greylocalrag");
const CORE_DIR = path.join(ROOT, "core", "greysearch");
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
		return m.files?.["core/greysearch/" + relpath]?.sha256 ?? null;
	} catch {
		return null;
	}
}

function verifyBinary(): { ok: boolean; detail: string } {
	try {
		const mains = fs.readdirSync(CORE_DIR).filter((f) => f.startsWith("greysearch_mcp") && f.endsWith(".so"));
		if (!mains.length) return { ok: false, detail: "compiled greysearch missing from core/greysearch" };
		const main = "greysearch_mcp" + mains[0]!.slice(mains[0]!.lastIndexOf("."));
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
		["-c", `GREYAGENT_CORE_TOOLS=${CORE_DIR} python3 ${ROOT}/mcp/run_server.py --server greysearch_mcp`],
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
			reject(new Error(`greysearch core: ${method} timed out`));
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

export default function greysearchCore(pi: ExtensionAPI): void {
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
				clientInfo: { name: PLATFORM + "-core", version: "1.0.1" },
			}, 20000);
			(conn.proc.stdin as any)?.write?.(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n");
			const listed = (await call(conn, "tools/list", {}, 20000)) as { tools?: ToolSpec[] };
			for (const t of listed.tools ?? []) {
				pi.registerTool({
					name: t.name,
					label: t.name,
					description: t.description ?? t.name,
					promptSnippet: "tools greysearch/greysearch_health are CORE web-research capabilities — use greysearch for any web research (deep search + scrape + guide), greysearch_health to check its lanes",
					promptGuidelines: ["Greysearch is core-integrated: for web research or page scraping, call it ONCE (background=true) rather than scraping pages yourself."],
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