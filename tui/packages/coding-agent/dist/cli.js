#!/usr/bin/env node
import { APP_NAME } from "./config.js";
import { configureHttpDispatcher } from "./core/http-dispatcher.js";
import { main } from "./main.js";
process.title = APP_NAME;
process.env.CORTEX_CODING_AGENT = "true";
process.env.AI_AGENT = "cortex";
process.emitWarning = (() => { });
configureHttpDispatcher();
main(process.argv.slice(2));
//# sourceMappingURL=cli.js.map