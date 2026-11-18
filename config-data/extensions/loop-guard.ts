import type { ExtensionAPI } from "@greyagent/coding-agent";
import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";

const WINDOW = num(process.env.GREYMICROAGENT_LOOPGUARD_WINDOW, 20);
const MAX_PER_WINDOW = num(process.env.GREYMICROAGENT_LOOPGUARD_MAX_PER_WINDOW, 5);
const LIFETIME_MAX = num(process.env.GREYMICROAGENT_LOOPGUARD_LIFETIME_MAX, 40);
const WAIT_FAST_S = num(process.env.GREYMICROAGENT_LOOPGUARD_WAIT_FAST, 10);
const WAIT_MCP_S = num(process.env.GREYMICROAGENT_LOOPGUARD_WAIT_MCP, 300);
const SEARCH_RUN_FILE =
	process.env.GREYMICROAGENT_SEARCH_RUN_FILE ||
	path.join(os.homedir(), ".greymicroagent", "state", "search-run");

const LONG_JOB_TOOLS = ["rag_search", "search", "search_health"];

function num(raw: string | undefined, fallback: number): number {
	const v = Number(raw);
	return Number.isFinite(v) && v > 0 ? v : fallback;
}

function isLongJobTool(name: string): boolean {
	const rest = name.startsWith("mcp_") ? name.slice(4) : name;
	const cut = rest.indexOf("_");
	const tool = cut === -1 ? rest : rest.slice(cut + 1);
	return LONG_JOB_TOOLS.includes(rest) || LONG_JOB_TOOLS.includes(tool);
}

function searchRunBusy(): boolean {
	return fs.existsSync(SEARCH_RUN_FILE);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function loopGuard(pi: ExtensionAPI): void {
	const window: string[] = [];
	const lifetime = new Map<string, number>();
	const lastIssue = new Map<string, number>();

	pi.on("tool_call", async (event: { toolName: string; input: Record<string, unknown> }) => {
		const key = event.toolName + "::" + JSON.stringify(event.input ?? {});
		const now = Date.now();
		const life = (lifetime.get(key) ?? 0) + 1;
		lifetime.set(key, life);
		window.push(key);
		if (window.length > WINDOW) window.shift();

		const inWin = window.filter((k) => k === key).length;
		const last = lastIssue.get(key) ?? 0;

		if (last > 0 && now - last < WAIT_MCP_S * 1000) {
			if (isLongJobTool(event.toolName)) {
				const cap = now + WAIT_MCP_S * 1000;
				if (searchRunBusy()) {
					while (Date.now() < cap && searchRunBusy())
						await sleep(Math.min(5000, cap - Date.now()));
				} else if (Date.now() - last < WAIT_MCP_S * 1000) {
					const settled = last + 30000;
					if (settled > Date.now()) await sleep(settled - Date.now());
				}
			} else {
				const elapsed = now - last;
				if (elapsed < WAIT_FAST_S * 1000) await sleep(WAIT_FAST_S * 1000 - elapsed);
			}
		}
		lastIssue.set(key, now);

		if (life > LIFETIME_MAX) {
			return {
				block: true,
				reason:
					`refused: loop-guard - this EXACT call has been issued ${life} times this ` +
					`session (limit ${LIFETIME_MAX}). It is pathological. Do NOT reissue it, do ` +
					`NOT vary it cosmetically: END YOUR TURN and report to the owner what you ` +
					`have verified and what is blocking you, in plain text.`,
			};
		}
		if (inWin > MAX_PER_WINDOW) {
			return {
				block: true,
				reason:
					`refused: loop-guard - identical call issued ${inWin}x within the last ` +
					`${WINDOW} calls (limit ${MAX_PER_WINDOW}). The result will not change. ` +
					`The main loop must never absorb mechanical repetition. Instead: ` +
					`(a) ONE compound command with the iteration inside it (shell loop -> file, ` +
					`read the file once at the end), or (b) a BACKGROUND SUBAGENT (subagent tool, ` +
					`async) that does the repetition in its own context and returns ONE final ` +
					`summary. If neither applies, END YOUR TURN and tell the owner what you ` +
					`found and what is stuck.`,
			};
		}
	});
}
