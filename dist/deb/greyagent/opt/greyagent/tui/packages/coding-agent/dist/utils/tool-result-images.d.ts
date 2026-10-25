import type { ImageContent, TextContent } from "@greyagent/ai";
export type ToolResultContent = TextContent | ImageContent;
export interface NormalizeToolResultImagesOptions {
    autoResizeImages?: boolean;
}
export declare function normalizeToolResultImages(content: ToolResultContent[], options?: NormalizeToolResultImagesOptions): Promise<ToolResultContent[]>;
//# sourceMappingURL=tool-result-images.d.ts.map