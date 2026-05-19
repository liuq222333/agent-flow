import { nodeCatalog } from "../constants";
import type { NodeDragPreview } from "../types";

export function NodeDragPreviewLayer({ preview }: { preview: NodeDragPreview }) {
  const item = nodeCatalog.find((node) => node.type === preview.type);
  if (!item) {
    return null;
  }

  const Icon = item.Icon;
  return (
    <div
      className={preview.overCanvas ? "node-drag-preview over-canvas" : "node-drag-preview"}
      style={{ transform: `translate3d(${preview.x + 14}px, ${preview.y - 18}px, 0)` }}
    >
      <Icon size={16} />
      <span>{item.label}</span>
    </div>
  );
}
