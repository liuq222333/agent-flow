"use client";

import { ViewportPortal } from "@xyflow/react";

import type { NodeEdgeAnchors, PendingConnection, WorkflowGraph } from "../types";
import { getNodeEdgePoint, getWorkflowEdgeMidpoint, makeWorkflowEdgePath } from "../utils";

export function WorkflowEdgeOverlay({
  deleteEdge,
  graph,
  nodeEdgeAnchors,
  pendingConnection,
  selectedEdgeId,
  selectEdge,
}: {
  deleteEdge: (edgeId: string) => void;
  graph: WorkflowGraph;
  nodeEdgeAnchors: NodeEdgeAnchors;
  pendingConnection: PendingConnection | null;
  selectedEdgeId: string | null;
  selectEdge: (edgeId: string) => void;
}) {
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const edgeLines = graph.edges
    .map((edge) => {
      const sourceNode = nodeById.get(edge.source);
      const targetNode = nodeById.get(edge.target);
      if (!sourceNode || !targetNode) {
        return null;
      }
      return {
        id: edge.id,
        from: nodeEdgeAnchors[sourceNode.id]?.source ?? getNodeEdgePoint(sourceNode, "source"),
        to: nodeEdgeAnchors[targetNode.id]?.target ?? getNodeEdgePoint(targetNode, "target"),
        label: edge.label,
      };
    })
    .filter(
      (
        edge,
      ): edge is {
        id: string;
        from: { x: number; y: number };
        to: { x: number; y: number };
        label: string | undefined;
      } => edge !== null,
    );

  const anchorPoints = Object.values(nodeEdgeAnchors).flatMap((anchor) => [anchor.source, anchor.target]);
  const maxX = Math.max(
    1200,
    ...graph.nodes.map((node) => node.position.x + 360),
    ...anchorPoints.map((point) => point.x + 160),
    pendingConnection?.to.x ?? 0,
  );
  const maxY = Math.max(
    800,
    ...graph.nodes.map((node) => node.position.y + 240),
    ...anchorPoints.map((point) => point.y + 160),
    pendingConnection?.to.y ?? 0,
  );

  return (
    <ViewportPortal>
      <svg className="workflow-edge-overlay" viewBox={`0 0 ${maxX} ${maxY}`} style={{ width: maxX, height: maxY }}>
        <defs>
          <marker
            id="workflow-edge-arrow"
            markerHeight="7"
            markerUnits="userSpaceOnUse"
            markerWidth="7"
            orient="auto"
            refX="6.5"
            refY="3.5"
            viewBox="0 0 7 7"
          >
            <path d="M 0 0 L 7 3.5 L 0 7 z" />
          </marker>
          <marker
            className="edge-marker-selected"
            id="workflow-edge-arrow-selected"
            markerHeight="7"
            markerUnits="userSpaceOnUse"
            markerWidth="7"
            orient="auto"
            refX="6.5"
            refY="3.5"
            viewBox="0 0 7 7"
          >
            <path d="M 0 0 L 7 3.5 L 0 7 z" />
          </marker>
        </defs>
        {edgeLines.map((edge) => {
          const selected = edge.id === selectedEdgeId;
          const midpoint = getWorkflowEdgeMidpoint(edge.from, edge.to);
          const path = makeWorkflowEdgePath(edge.from, edge.to);
          return (
            <g className={selected ? "workflow-edge-group selected" : "workflow-edge-group"} key={edge.id}>
              <path
                className="workflow-edge-hitbox"
                d={path}
                onClick={(event) => {
                  event.stopPropagation();
                  selectEdge(edge.id);
                }}
              />
              <path className={selected ? "workflow-edge-path selected" : "workflow-edge-path"} d={path} />
              {selected ? (
                <>
                  <circle className="workflow-edge-endpoint" cx={edge.from.x} cy={edge.from.y} r="4.5" />
                  <circle className="workflow-edge-endpoint" cx={edge.to.x} cy={edge.to.y} r="4.5" />
                  <g
                    className="workflow-edge-delete"
                    onClick={(event) => {
                      event.stopPropagation();
                      deleteEdge(edge.id);
                    }}
                  >
                    <circle cx={midpoint.x} cy={midpoint.y} r="10.5" />
                    <path d={`M ${midpoint.x - 4} ${midpoint.y - 4} L ${midpoint.x + 4} ${midpoint.y + 4}`} />
                    <path d={`M ${midpoint.x + 4} ${midpoint.y - 4} L ${midpoint.x - 4} ${midpoint.y + 4}`} />
                  </g>
                </>
              ) : null}
              {edge.label ? (
                <text className="workflow-edge-label" x={midpoint.x} y={midpoint.y - 12}>
                  {edge.label}
                </text>
              ) : null}
            </g>
          );
        })}
        {pendingConnection ? (
          <path className="workflow-edge-path pending" d={makeWorkflowEdgePath(pendingConnection.from, pendingConnection.to)} />
        ) : null}
      </svg>
    </ViewportPortal>
  );
}
