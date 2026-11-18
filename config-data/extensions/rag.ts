import type { ExtensionAPI } from "@greyagent/coding-agent";
import * as childProcess from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const REGISTRY = path.join(os.homedir(), ".greymicroagent", "agent", "mcp_registry.json");
const STATE_DIR = path.join(os.homedir(), ".greymicroagent", "state");
const TEMP_FILE = path.join(STATE_DIR, "rag-temp");
const OFFLINE_FILE = path.join(STATE_DIR, "rag-offline");
const TEMP_MIN = 0.0;
const TEMP_MAX = 0.2;

interface RegistryServer {
	name: string;
	command?: string;
	args?: string[];
	so?: string;
	enabled: boolean;
}

interface RagSource {
	url: string;
	date: string;
	records: number;
	sample: string;
}

function defaultDb(): string {
	return (process.env.GREYMICROAGENT_DBS ?? "commands").split(",")[0].trim() || "commands";
}

function ragServerCommand(): string[] | null {
	try {
		const reg = JSON.parse(fs.readFileSync(REGISTRY, "utf8")) as { servers: RegistryServer[] };
		const entry = (reg.servers ?? []).find((s) => s.name === "knowledge");
		if (!entry || !entry.enabled) return null;
		if (entry.command && entry.args?.length) return [entry.command, ...entry.args];
		if (entry.command) return ["/bin/sh", "-c", entry.command];
		if (entry.so) return ["/bin/sh", "-c", `python3 ${path.join(os.homedir(), "greymicroagent", "mcp", "run_server.py")} --server ${entry.name}`];
		return null;
	} catch {
		return null;
	}
}

function plainText(result: Record<string, unknown>): string {
	const content = result.content as { type?: string; text?: string }[] | undefined;
	if (!Array.isArray(content)) return JSON.stringify(result);
	return content
		.map((c) => (c.type === "text" ? String(c.text ?? "") : ""))
		.filter(Boolean)
		.join(" ");
}

async function ragCall(tool: string, args: Record<string, unknown>, timeoutMs: number): Promise<Record<string, unknown>> {
	const argv = ragServerCommand();
	if (!argv) throw new Error("the knowledge service is not registered or is switched off — run /mcp to check it");
	const proc = childProcess.spawn(argv[0], argv.slice(1), { cwd: os.homedir(), stdio: ["pipe", "pipe", "pipe"] });
	const stdio = proc.stdio as (NodeJS.ReadableStream | NodeJS.WritableStream)[];
	stdio.forEach((s) => s && s.unref());
	proc.unref();
	try {
		return await new Promise<Record<string, unknown>>((resolve, reject) => {
			let buffer = "";
			let stage = "init";
			let settled = false;
			const teardown = () => {
				clearTimeout(timer);
				try { proc.removeAllListeners(); } catch {}
				try { proc.stdin?.destroy(); } catch {}
				try { proc.stdout?.destroy(); } catch {}
				try { proc.stderr?.destroy(); } catch {}
				try { proc.kill("SIGKILL"); } catch {}
			};
			const settle = (message: string | null, value?: Record<string, unknown>) => {
				if (settled) return;
				settled = true;
				teardown();
				if (message === null) resolve(value ?? {});
				else reject(new Error(message));
			};
			const timer = setTimeout(
				() => settle(`${tool === "rag_ingest_urls" ? "reading the page" : "the knowledge base"} took longer than ${Math.round(timeoutMs / 1000)} seconds and was stopped`),
				timeoutMs,
			);
			proc.stdout!.on("data", (chunk: Buffer) => {
				buffer += chunk.toString();
				const pump = () => {
					const nl = buffer.indexOf("\n");
					if (nl === -1) return;
					const line = buffer.slice(0, nl).trim();
					buffer = buffer.slice(nl + 1);
					if (line) {
						let msg: { id?: number; result?: Record<string, unknown> & { isError?: boolean }; error?: { message?: string } };
						try {
							msg = JSON.parse(line);
						} catch {
							msg = undefined as never;
						}
						if (msg && msg.id === 1 && stage === "init") {
							stage = "call";
							proc.stdin!.write(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n");
							proc.stdin!.write(JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: tool, arguments: args } }) + "\n", (err: Error | null | undefined) => {
								if (err) settle(`could not reach the knowledge service: ${err.message}`);
							});
						} else if (msg && msg.id === 2 && stage === "call") {
							if (msg.error) {
								settle(String(msg.error.message ?? "the knowledge service reported a problem"));
							} else if (msg.result?.isError) {
								const words = plainText(msg.result).replace(/^error:\s*/i, "");
								settle(words || "the knowledge service reported a problem");
							} else {
								settle(null, msg.result ?? {});
							}
						}
					}
					pump();
				};
				pump();
			});
			proc.stderr?.resume();
			proc.on("error", (e: Error) => settle(`could not start the knowledge service: ${e.message}`));
			proc.on("exit", () => settle("the knowledge service stopped before answering"));
			proc.stdin!.write(
				JSON.stringify({
					jsonrpc: "2.0",
					id: 1,
					method: "initialize",
					params: { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "greymicroagent", version: "0.7.5.1" } },
				}) + "\n",
				(err: Error | null | undefined) => {
					if (err) settle(`could not reach the knowledge service: ${err.message}`);
				},
			);
		});
	} finally {
		try { proc.stdin?.destroy(); } catch {}
		try { proc.stdout?.destroy(); } catch {}
		try { proc.stderr?.destroy(); } catch {}
		try { proc.kill("SIGKILL"); } catch {}
	}
}

function readTemp(): number | null {
	try {
		const v = Number(fs.readFileSync(TEMP_FILE, "utf8").trim());
		return Number.isFinite(v) && v >= TEMP_MIN && v <= TEMP_MAX ? v : null;
	} catch {
		return null;
	}
}

function offlineOn(): boolean {
	try {
		return fs.existsSync(OFFLINE_FILE);
	} catch {
		return false;
	}
}

const USAGE = [
	"knowledge base commands:",
	"  /rag status — what is in your knowledge base",
	"  /rag ingest <pdf, txt or md file, or a web address> — add it to your knowledge base",
	"  /rag remove <word or address> — shows what matches, then run the same command again to delete",
	"  /rag temp <number between 0.0 and 0.2> — how freely the model may answer",
	"  /rag offline on|off — keep answers to your knowledge base only, or let the model answer freely",
].join("\n");

function statusText(dbs: { name: string; records: number }[], total: number, modelState: string): string {
	const lines: string[] = [];
	if (!dbs.length) {
		lines.push("Your knowledge base is empty — nothing has been added yet.");
		lines.push("Start with: /rag ingest <pdf, txt or md file, or a web address>");
	} else {
		lines.push(`Knowledge base: ${dbs.length} ${dbs.length === 1 ? "collection" : "collections"}, ${total} records in total.`);
		for (const d of dbs) lines.push(`  ${d.name} — ${d.records} records`);
	}
	lines.push(`Document model: ${modelState}`);
	const temp = readTemp();
	lines.push(temp === null
		? "Answer freedom: not set — the 0.0 to 0.2 cap still applies."
		: `Answer freedom: ${temp.toFixed(2)} (the allowed range is 0.0 to 0.2).`);
	lines.push(offlineOn()
		? "Offline mode: on — answers come only from your knowledge base."
		: "Offline mode: off — the model may also answer from its own knowledge.");
	return lines.join("\n");
}

function sourceLines(sources: RagSource[], match: string, db: string): string | null {
	const hit = sources.filter((s) => (`${s.sample}\n${s.url}`).toLowerCase().includes(match.toLowerCase()));
	if (!hit.length) return null;
	const shown = hit.slice(0, 8).map((s) => {
		const what = s.sample || s.url || "(untitled)";
		const where = s.url && s.url !== s.sample ? ` — ${s.url}` : "";
		const when = s.date ? `, added ${s.date}` : "";
		return `  ${s.records} ${s.records === 1 ? "record" : "records"}: ${what}${where}${when}`;
	});
	if (hit.length > shown.length) shown.push(`  …and ${hit.length - shown.length} more`);
	shown.push(`Found ${hit.length} ${hit.length === 1 ? "match" : "matches"} in ${db}. To delete ${hit.length === 1 ? "it" : "them"}, type the same command again: /rag remove ${match}`);
	shown.push("Any other /rag command first cancels this — nothing is deleted until you repeat it.");
	return shown.join("\n");
}

export default function rag(pi: ExtensionAPI): void {
	let pendingRemove: string | null = null;

	const handler = async (args: string, ctx: { ui: { notify(msg: string, level?: string): Promise<void> } }) => {
		const parts = args.trim().split(/\s+/);
		const verb = parts[0] ?? "";
		const rest = args.trim().slice(verb.length).trim();
		const db = defaultDb();
		try {
			if (!verb || verb === "usage") {
				await ctx.ui.notify(USAGE);
				return;
			}
			if (verb === "status") {
				pendingRemove = null;
				const r = await ragCall("rag_status", {}, 30000);
				await ctx.ui.notify(statusText((r.dbs as { name: string; records: number }[]) ?? [], Number(r.records ?? 0), String(r.model_state ?? "unknown")));
				return;
			}
			if (verb === "ingest") {
				pendingRemove = null;
				const target = rest.replace(/^["']|["']$/g, "");
				if (!target) {
					await ctx.ui.notify("Tell me what to add, for example: /rag ingest report.pdf", "warning");
					return;
				}
				if (/^https?:\/\//i.test(target)) {
					const r = await ragCall("rag_ingest_urls", { db, urls: [target] }, 180000);
					const per = ((r.urls as { url?: string; added?: number; note?: string }[]) ?? [])[0] ?? {};
					const added = Number(per.added ?? r.added ?? 0);
					if (added > 0) await ctx.ui.notify(`Added ${added} ${added === 1 ? "record" : "records"} from that page into ${db}. Say /rag status to see it.`);
					else await ctx.ui.notify(`Nothing was added from that page — ${per.note ?? `${r.note ?? "the page could not be read"}`}.`, "warning");
					return;
				}
				if (!fs.existsSync(target) || !fs.statSync(target).isFile()) {
					await ctx.ui.notify(`That file does not exist or is not a plain file. I can add a pdf, txt or md file, or one web page: /rag ingest <file or address>`, "warning");
					return;
				}
				const kind = path.extname(target).toLowerCase();
				if (kind === ".pdf") {
					const r = await ragCall("rag_ingest_pdf", { db, path: target }, 120000);
					const added = Number(r.added ?? 0);
					if (added > 0) await ctx.ui.notify(`Added ${added} ${added === 1 ? "record" : "records"} from ${String(r.title ?? path.basename(target))} into ${db}.`);
					else await ctx.ui.notify(`Nothing was added — ${r.note ?? "the pdf could not be read"}.`, "warning");
					return;
				}
				if (kind === ".txt" || kind === ".md") {
					if (fs.statSync(target).size > 10 * 1024 * 1024) {
						await ctx.ui.notify("That file is larger than 10 MB — split it or use a smaller file.", "warning");
						return;
					}
					const title = path.basename(target, kind);
					const r = await ragCall("rag_ingest_text", { db, title, text: fs.readFileSync(target, "utf8"), source: "file", url: target }, 120000);
					const added = Number(r.added ?? 0);
					if (added > 0) await ctx.ui.notify(`Added ${added} ${added === 1 ? "record" : "records"} from "${title}" into ${db}.`);
					else await ctx.ui.notify(`Nothing was added from "${title}" — ${r.note ?? "the file could not be read"}.`, "warning");
					return;
				}
				await ctx.ui.notify("I can add a pdf, txt or md file, or one web page: /rag ingest <file or address>", "warning");
				return;
			}
			if (verb === "remove") {
				const match = rest.trim();
				if (!match) {
					await ctx.ui.notify("Say what to remove, for example: /rag remove <word or address> — it shows the matches first and deletes nothing on its own.", "warning");
					return;
				}
				if (pendingRemove !== null && pendingRemove === match) {
					pendingRemove = null;
					const r = await ragCall("rag_remove", { db, match, confirm: true }, 60000);
					const removed = Number(r.removed ?? 0);
					if (removed > 0) {
						const extra = r.vectors === "cleared" ? " The saved search index needed a rebuild and was cleared — searches still work." : "";
						await ctx.ui.notify(`Done — removed ${removed} ${removed === 1 ? "record" : "records"} matching "${match}" from ${db}.${extra}`);
					} else {
						await ctx.ui.notify(`Nothing matched "${match}" in ${db}, so nothing was removed.`, "warning");
					}
					return;
				}
				const r = await ragCall("rag_list_sources", { db }, 60000);
				const text = sourceLines((r.sources as RagSource[]) ?? [], match, db);
				if (text === null) {
					const n = Number(r.distinct ?? 0);
					await ctx.ui.notify(`Nothing in ${db} carries "${match}" in its titles or addresses — checked ${n} ${n === 1 ? "source" : "sources"}. Nothing will be removed.`, "warning");
					return;
				}
				await ctx.ui.notify(`${text}\nDeletion target: ${db}. Check the matches above before repeating the command.`);
				pendingRemove = match;
				return;
			}
			if (verb === "temp") {
				pendingRemove = null;
				const token = rest.split(/\s+/)[0] ?? "";
				if (!token) {
					const current = readTemp();
					await ctx.ui.notify(`Answer freedom is ${current === null ? "not set" : `set to ${current.toFixed(2)}`}; the allowed range is ${TEMP_MIN.toFixed(1)} to ${TEMP_MAX.toFixed(1)}. Example: /rag temp 0.1`);
					return;
				}
				const wanted = Number(token);
				if (!Number.isFinite(wanted)) {
					await ctx.ui.notify(`"${token}" is not a number. Give me something between 0.0 and 0.2, for example: /rag temp 0.1`, "warning");
					return;
				}
				const clamped = Math.min(TEMP_MAX, Math.max(TEMP_MIN, wanted));
				fs.mkdirSync(STATE_DIR, { recursive: true });
				fs.writeFileSync(TEMP_FILE, String(clamped));
				const note = clamped !== wanted
					? `${token} is outside the 0.0 to 0.2 range — set to ${clamped.toFixed(2)} instead. `
					: "";
				await ctx.ui.notify(`${note}Answer freedom is now ${clamped.toFixed(2)}: 0.0 sticks strictly to your documents, 0.2 allows a little more room.`);
				return;
			}
			if (verb === "offline") {
				pendingRemove = null;
				const want = rest.trim().toLowerCase();
				if (want === "on") {
					fs.mkdirSync(STATE_DIR, { recursive: true });
					fs.writeFileSync(OFFLINE_FILE, "");
					await ctx.ui.notify("Offline mode is ON — answers now come only from your knowledge base.");
					return;
				}
				if (want === "off") {
					try { fs.unlinkSync(OFFLINE_FILE); } catch {}
					await ctx.ui.notify("Offline mode is OFF — the model may answer from its own knowledge again.");
					return;
				}
				await ctx.ui.notify("Choose on or off: /rag offline on keeps answers to your knowledge base only, /rag offline off allows the model's own answers.", "warning");
				return;
			}
			pendingRemove = null;
			await ctx.ui.notify(USAGE, "warning");
		} catch (e) {
			pendingRemove = null;
			const words = e instanceof Error ? e.message : String(e);
			await ctx.ui.notify(words.charAt(0).toUpperCase() + words.slice(1), "warning");
			return;
		}
	};

	pi.registerCommand("rag", {
		description: "Knowledge base: status, add files or pages, remove, answer freedom, offline mode",
		handler,
	});
}
