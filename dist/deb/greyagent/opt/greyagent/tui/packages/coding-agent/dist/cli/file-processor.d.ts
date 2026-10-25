import type { ImageContent } from "@greyagent/ai";
export interface ProcessedFiles {
    text: string;
    images: ImageContent[];
}
export interface ProcessFileOptions {
    autoResizeImages?: boolean;
}
export declare function processFileArguments(fileArgs: string[], options?: ProcessFileOptions): Promise<ProcessedFiles>;
//# sourceMappingURL=file-processor.d.ts.map