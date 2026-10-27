import { useEffect, useRef, useState } from 'react';
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
    selector: 'node.highlight',
    style: {
      'border-width': 4,
      'border-color': '#ff9800',
      'border-opacity': 0.95,
      'z-index': 999,
    },
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
  const [search, setSearch] = useState('');
  const [highlightId, setHighlightId] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      style: stylesheet,
      wheelSensitivity: 0.25,
      panningEnabled: true,
      userPanningEnabled: true,
      userZoomingEnabled: true,
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
    cy.fit(undefined, 28);
  }, [viewMode, asserted, inferred]);

  // #23：节点搜索/聚焦——输入实体名，匹配节点高亮并居中
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass('highlight');
    if (!search.trim()) {
      setHighlightId(null);
      return;
    }
    const q = search.trim().toLowerCase();
    const matches = cy.nodes().filter((n) => (n.data('label') as string).toLowerCase().includes(q) || (n.id() as string).toLowerCase().includes(q));
    if (matches.length > 0) {
      matches.addClass('highlight');
      setHighlightId(matches[0].id());
      cy.center(matches[0]);
      cy.zoom({ level: Math.max(cy.zoom(), 0.9), renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
    } else {
      setHighlightId(null);
    }
  }, [search]);

  const zoomBy = (factor: number) => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  };

  return (
    <div className="graph-shell">
      <div className="graph-toolbar">
        <input
          className="graph-search"
          placeholder="搜索节点（名称或 id）…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          title="输入类/个体名称或 id，自动高亮并聚焦"
        />
        {highlightId && <span className="graph-hit">已定位：{highlightId}</span>}
        <span className="graph-zoom-btns">
          <button className="secondary" onClick={() => zoomBy(1.25)} title="放大">＋</button>
          <button className="secondary" onClick={() => zoomBy(0.8)} title="缩小">－</button>
          <button className="secondary" onClick={() => cyRef.current?.fit(undefined, 28)} title="适应画布">⛶</button>
        </span>
      </div>
      <div ref={containerRef} id="graph" className="graph-wrap" />
    </div>
  );
}
