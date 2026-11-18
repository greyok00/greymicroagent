// 2026-10-29 (greywebpentest): first-run onboarding — shows a clear card at
// the top of a fresh session telling the operator exactly how to drive the
// agent, and how to hide it again. The card lifts itself the moment the
// operator sends their first message.
import type { ExtensionAPI, ExtensionContext } from "@greyagent/coding-agent";
import * as fs from "node:fs";
const LOG = (m: string) => { try { fs.appendFileSync("/tmp/gwp-onboarding.log", new Date().toISOString() + " " + m + "\n"); } catch {} };

// SUITE-AWARE card (2026-10-30 owner). Every suite gets its own verb list and
// pipeline description — osinttest must never read as "launch the web scan".
interface SuiteCard {
	testLine: string;
	desc: string[];
	phrases?: string[];
}

const SUITE_CARDS: Record<string, SuiteCard> = {
	person: {
		testLine: "    test <name | handle | email>   (osinttest / personstest)",
		desc: [
			"I audit a PERSON's public security footprint: what traces their",
			"email leaves (search dorks), what accounts use their handles (maigret/",
			"blackbird), which files leak metadata (exiftool). ONLY public",
			"data — no logins, no web scanners. Then I explain the findings",
			"and generate the Authorization & Agreement PDF + report.",
		],
	},
	web: {
		testLine: "    test <target>              (webtest: URL · networktest: host/IP · devicetest: device)",
		desc: [
			"  Type that in the prompt below — I create the assessment, run recon",
			"  (tech fingerprint, headers, TLS), launch the automated pipeline",
			"  (ports, dirs, nikto, WAF, WordPress probes, CVE matching), then",
			"  explain every finding in plain language and generate the report.",
		],
	},
};

const CARD: string[] = (() => {
	const suite = process.env.GREYAGENT_PROFILE ?? "web";
	const sc = SUITE_CARDS[suite] ?? SUITE_CARDS.web;
	return [
		"GREYPENTEST — local pentest agent (local 4B + greyteam MCP; suite: " + suite + ")",
		"",
		"HOW TO RUN A TEST (verb depends on the suite you launched):",
		sc.testLine,
		...sc.desc,
		"",
		"USEFUL PHRASES:",
		"    report              generate the HTML/PDF report for the last assessment",
		"    explain <thing>     teach me what a tool or finding means",
		"    capture <target>    signals/metadata capture only (no active tier)",
		suite === "web"
			? "    active test <url>   allow CONFIRMATORY payload tools (nuclei/dalfox/arjun/sqlmap)"
			: "",
		"    <test> -ctf         DEEP audit + full content harvest (ctf mode)",
		"    stop                stop the running pipeline and report state",
		"    (a missing tool? say 'check tools' — the agent can install them)",
		"",
		"Every command I run is allowlist-gated; evidence lands in the database",
		"and the report is built from it. Start by typing a test command above.",
	].filter((l) => l !== "");
})();

export default function gwpOnboarding(pi: ExtensionAPI): void {
	LOG("extension loaded, registering");
	pi.on("session_start", (_event, ctx: ExtensionContext) => {
		LOG("session_start reason=" + (_event as { reason?: string }).reason + " hasUI=" + ctx.hasUI + " mode=" + ctx.ui.mode);
		if (!ctx.hasUI || (ctx.mode && ctx.mode !== "tui")) return;
		ctx.ui.setWidget("gwp-onboarding", CARD);
	});
	pi.on("agent_start", (_event, ctx: ExtensionContext) => {
		if (!ctx.hasUI) return;
		ctx.ui.setWidget("gwp-onboarding", undefined);
	});
}