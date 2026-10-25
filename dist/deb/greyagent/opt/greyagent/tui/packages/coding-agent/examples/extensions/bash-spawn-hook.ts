import type { ExtensionAPI } from "@greyagent/coding-agent";
import { createBashTool } from "@greyagent/coding-agent";

export default function (cortex: ExtensionAPI) {
	const cwd = process.cwd();

	const bashTool = createBashTool(cwd, {
		spawnHook: ({ command, cwd, env }) => ({
			command: `source ~/.profile\n${command}`,
			cwd,
			env: { ...env, CORTEX_SPAWN_HOOK: "1" },
		}),
	});

	cortex.registerTool({
		...bashTool,
		execute: async (id, params, signal, onUpdate, _ctx) => {
			return bashTool.execute(id, params, signal, onUpdate);
		},
	});
}
