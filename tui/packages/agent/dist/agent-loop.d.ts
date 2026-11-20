import { EventStream } from "@greyagent/ai";
import type { AgentContext, AgentEvent, AgentLoopConfig, AgentMessage, StreamFn } from "./types.ts";
export type AgentEventSink = (event: AgentEvent) => Promise<void> | void;
export declare function agentLoop(prompts: AgentMessage[], context: AgentContext, config: AgentLoopConfig, signal: AbortSignal | undefined, streamFn: StreamFn): EventStream<AgentEvent, AgentMessage[]>;
export declare function agentLoopContinue(context: AgentContext, config: AgentLoopConfig, signal: AbortSignal | undefined, streamFn: StreamFn): EventStream<AgentEvent, AgentMessage[]>;
export declare function runAgentLoop(prompts: AgentMessage[], context: AgentContext, config: AgentLoopConfig, emit: AgentEventSink, signal: AbortSignal | undefined, streamFn: StreamFn): Promise<AgentMessage[]>;
export declare function runAgentLoopContinue(context: AgentContext, config: AgentLoopConfig, emit: AgentEventSink, signal: AbortSignal | undefined, streamFn: StreamFn): Promise<AgentMessage[]>;
export declare function clearSessionCallBlocks(): void;
//# sourceMappingURL=agent-loop.d.ts.map