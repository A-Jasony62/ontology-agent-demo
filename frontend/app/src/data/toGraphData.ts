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

/**
 * 把可视化编辑器的改动「合并」进后端断言图。
 *
 * 编辑器只负责类与对象关系，而断言图里还有个体、rdf:type、子类边等编辑器表达不了的内容。
 * 若直接用 ontologyToGraphData 覆盖，图会从「类 + 个体 + 实例边」缩水成「只有类」——
 * 看起来就像「一改动图就乱了」。这里：
 *  - 类节点以模型为准（支持改名 / 删除），个体节点原样保留；
 *  - 断言边默认全部保留，仅移除「上一版模型里存在、这一版被删掉」的关系边；
 *  - 模型里的关系边按 source+label+target 去重后并入。
 */
export function mergeOntologyIntoGraph(base: GraphData | null, prev: Ontology | null, next: Ontology): GraphData {
  if (!base) return ontologyToGraphData(next);

  const model = ontologyToGraphData(next);

  const nodes = [...base.nodes.filter((n) => n.type !== 'class'), ...model.nodes];
  const nodeIds = new Set(nodes.map((n) => n.id));

  // 仅删除「被显式删掉的关系」对应的断言边，其余保留（删关系后图里同步消失）
  const removed = (prev?.relationships ?? []).filter((r) => !next.relationships.some((n) => n.id === r.id));
  const removedKey = new Set(removed.map((r) => `${r.from}--${r.name}--${r.to}`));

  const keptEdges = base.edges.filter(
    (e) => nodeIds.has(e.source) && nodeIds.has(e.target) && !removedKey.has(`${e.source}--${e.label}--${e.target}`),
  );

  const keptKeys = new Set(keptEdges.map((e) => `${e.source}--${e.label}--${e.target}`));
  const extraEdges = model.edges.filter((e) => !keptKeys.has(`${e.source}--${e.label}--${e.target}`));

  return { nodes, edges: [...keptEdges, ...extraEdges] };
}
