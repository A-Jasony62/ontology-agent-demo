import { useEffect, useRef } from 'react';
import cytoscape from 'cytoscape';
import fcose from 'cytoscape-fcose';
import type { Core, ElementDefinition, StylesheetStyle, LayoutOptions } from 'cytoscape';
import type { GraphData } from '../api/client';

cytoscape.use(fcose);

export type GraphViewMode = 'asserted' | 'materialized' | 'diff';

interface Props {
  viewMode: GraphViewMode;
  asserted?: GraphData | null;
  inferred?: GraphData | null;
  onSelect?: (id: string | null) => void;
}

const INFERRED_COLOR = '#2f8f6b';
const EDGE_COLOR = '#9aa0a6';
const CLASS_COLOR = '#4a90a4';
const INDIVIDUAL_COLOR = '#c98a3d';

const stylesheet: StylesheetStyle[] = [
  {
    selector: 'node',
    style: {
      'background-color': 'data(color)',
      label: 'data(label)',
      'text-valign': 'bottom',
      'text-halign': 'center',
      color: '#33455f',
      'font-size': 11,
      'text-wrap': 'wrap',
      'text-max-width': '90px',
    },
  },
  {
    selector: 'node.inferred',
    style: {
      'border-style': 'dashed',
      'border-width': 2,
      'border-color': INFERRED_COLOR,
    },
  },
  {
    selector: 'node:selected',
    style: { 'border-width': 3, 'border-color': '#0078d4' },
  },
  {
    selector: 'edge',
    style: {
      width: 2,
      'line-color': EDGE_COLOR,
      'target-arrow-color': EDGE_COLOR,
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      label: 'data(label)',
      'font-size': 10,
      color: '#666',
      'text-background-color': '#ffffff',
      'text-background-opacity': 0.85,
      'text-background-padding': '2px',
    },
  },
  {
    selector: 'edge.inferred',
    style: {
      'line-style': 'dashed',
      'line-color': INFERRED_COLOR,
      'target-arrow-color': INFERRED_COLOR,
    },
  },
  {
    selector: 'edge:selected',
    style: { 'line-color': '#0078d4', 'target-arrow-color': '#0078d4' },
  },
];

function elementsFromGraphData(
  asserted: GraphData | null | undefined,
  inferred: GraphData | null | undefined,
  viewMode: GraphViewMode,
): ElementDefinition[] {
  const elements: ElementDefinition[] = [];
  const seenNodes = new Set<string>();
  const seenEdges = new Set<string>();

  const addData = (graph: GraphData | null | undefined, isInferred: boolean) => {
    if (!graph) return;
    for (const n of graph.nodes) {
      if (seenNodes.has(n.id)) continue;
      seenNodes.add(n.id);
      elements.push({
        data: {
          id: n.id,
          label: `${n.type === 'class' ? '◈' : '●'} ${n.label}`,
          color: isInferred && viewMode === 'diff' ? INFERRED_COLOR : n.type === 'class' ? CLASS_COLOR : INDIVIDUAL_COLOR,
        },
        classes: isInferred ? 'inferred' : undefined,
      });
    }
    for (const e of graph.edges) {
      if (!seenNodes.has(e.source) || !seenNodes.has(e.target)) continue;
      const eid = `${e.source}--${e.label}--${e.target}`;
      if (seenEdges.has(eid)) continue;
      seenEdges.add(eid);
      elements.push({
        data: { id: `edge|${eid}`, source: e.source, target: e.target, label: e.label },
        classes: isInferred ? 'inferred' : undefined,
      });
    }
  };

  if (viewMode === 'diff') {
    addData(inferred, true);
  } else {
    addData(asserted, false);
    if (viewMode === 'materialized') addData(inferred, true);
  }
  return elements;
}

export default function GraphView({ viewMode, asserted, inferred, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;

  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      style: stylesheet,
      wheelSensitivity: 0.3,
    });
    cy.on('tap', 'node', (evt) => selectRef.current?.(evt.target.id()));
    cy.on('tap', 'edge', (evt) => selectRef.current?.(evt.target.id()));
    cy.on('tap', (evt) => {
      if (evt.target === cy) selectRef.current?.(null);
    });
    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const elements = elementsFromGraphData(asserted, inferred, viewMode);
    cy.elements().remove();
    cy.add(elements);
    cy.layout({ name: 'fcose', animate: false, randomize: true, nodeSeparation: 60 } as LayoutOptions).run();
  }, [viewMode, asserted, inferred]);

  return <div ref={containerRef} id="graph" className="graph-wrap" />;
}
