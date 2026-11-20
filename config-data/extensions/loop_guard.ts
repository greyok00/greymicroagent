import type { ExtensionAPI } from "@greyagent/coding-agent";

// loop_guard.ts - deterministic repetition guard, ported from cortex-agent
// (2026-11-11) for the 2B: no model tokens, no LLM judgement, just call
// bookkeeping. A repeated identical tool call is held briefly and then
// refused by window and lifetime thresholds, with an off-ramp in the refusal
// text (do the repetition inside one command or a subagent, then report).
//
// Tiers:
//   WINDOW   - the same name+args more than MAX_PER_WINDOW times inside the
//              last WINDOW calls is a loop: blocked.
//   LIFETIME - the same call blocked or executed LIFETIME_MAX times in one
//              process is pathological: blocked for the rest of the session.
//   REISSUE  - an immediate identical re-issue is held for WAIT_FAST_S so a
//              state change behind it has a chance to land first.
// Env overrides: GREYMICROAGENT_LOOPGUARD_WINDOW / _MAX_PER_WINDOW /
// _LIFETIME_MAX / _WAIT_FAST.

const WINDOW = num(process.env.GREYMICROAGENT_LOOPGUARD_WINDOW, 20);
const MAX_PER_WINDOW = num(process.env.GREYMICROAGENT_LOOPGUARD_MAX_PER_WINDOW, 4);
const LIFETIME_MAX = num(process.env.GREYMICROAGENT_LOOPGUARD_LIFETIME_MAX, 25);
const WAIT_FAST_S = num(process.env.GREYMICROAGENT_LOOPGUARD_WAIT_FAST, 5);

function num(raw: string | undefined, fallback: number): number {
	const v = Number(raw);
	return Number.isFinite(v) && v > 0 ? v : fallback;
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

		if (last > 0 && now - last < WAIT_FAST_S * 1000) {
			await sleep(WAIT_FAST_S * 1000 - (now - last));
		}
		lastIssue.set(key, Date.now());

		if (life > LIFETIME_MAX) {
			return {
				block: true,
				reason:
					`refused: loop-guard - this exact call has been issued ${life} times this ` +
					`session (limit ${LIFETIME_MAX}). It is pathological. Do not reissue it and do ` +
					`not vary it cosmetically: end your turn and tell the operator what you verified ` +
					`and what is blocking you, in plain text.`,
			};
		}
		if (inWin > MAX_PER_WINDOW) {
			return {
				block: true,
				reason:
					`refused: loop-guard - identical call issued ${inWin}x within the last ` +
					`${WINDOW} calls (limit ${MAX_PER_WINDOW}); its result will not change. ` +
					`Do the repetition as ONE command with the loop inside it, or hand it to a ` +
					`background subagent, or end your turn and report what is stuck.`,
			};
		}
	});
}
