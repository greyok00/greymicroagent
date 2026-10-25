import type { ThinkingLevel } from "@greyagent/agent-core";
import { Container, SelectList } from "@greyagent/tui";
export declare class ThinkingSelectorComponent extends Container {
    private selectList;
    constructor(currentLevel: ThinkingLevel, availableLevels: ThinkingLevel[], onSelect: (level: ThinkingLevel) => void, onCancel: () => void);
    getSelectList(): SelectList;
}
//# sourceMappingURL=thinking-selector.d.ts.map