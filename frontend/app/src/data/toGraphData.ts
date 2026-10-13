import type { Ontology } from './ontology';
import type { GraphData } from '../api/client';

/** 本地模型 → 图谱数据（断言视图用） */
export function ontologyToGraphData(o: Ontology): GraphData {
  const nodes = o.entityTypes.map((e) => ({ id: e.id, label: e.name, type: 'class' as const }));
  const edges = o.relationships.map((r) => ({
    id: `rel--${r.id}`,
    source: r.from,
    target: r.to,
    label: r.name,
    provenance: 'asserted' as const,
  }));
  return { nodes, edges };
}
