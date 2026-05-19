"use client";

import { type MouseEvent as ReactMouseEvent, useCallback, useRef } from "react";
import { type NodeProps, type NodeTypes } from "@xyflow/react";

import { nodeDropMoveThreshold } from "../constants";
import type { WorkflowFlowNode } from "../types";
import { normalizeStatus } from "../utils";

function WorkflowNodeView({ id, data, selected }: NodeProps<WorkflowFlowNode>) {
  const connectPointerStartRef = useRef<{ x: number; y: number } | null>(null);

  const handleQuickAddClick = useCallback(
    (event: ReactMouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();

      const startPoint = connectPointerStartRef.current;
      connectPointerStartRef.current = null;
      const moved = startPoint ? Math.hypot(event.clientX - startPoint.x, event.clientY - startPoint.y) : 0;
      if (moved >= nodeDropMoveThreshold) {
        return;
      }

      data.onQuickAdd(id);
    },
    [data, id],
  );

  return (
    <div className="node-card">
      {data.status ? <i className={`node-status-dot status-${normalizeStatus(data.status)}`} title={data.status} /> : null}
      <span>{data.name}</span>
      <small>{data.nodeType}</small>
      {selected ? (
        <div className="node-connect-tooltip">
          点击 添加节点
          <br />
          拖拽 连接节点
        </div>
      ) : null}
      <button
        aria-label="添加或连接节点"
        className="node-connect-button nodrag nopan"
        type="button"
        onClick={handleQuickAddClick}
        onMouseDown={(event) => {
          if (event.button !== 0) {
            return;
          }
          event.stopPropagation();
          connectPointerStartRef.current = { x: event.clientX, y: event.clientY };
          data.onManualConnectStart(id, event.clientX, event.clientY);
        }}
      />
    </div>
  );
}

export const workflowNodeTypes = {
  workflowNode: WorkflowNodeView,
} satisfies NodeTypes;
