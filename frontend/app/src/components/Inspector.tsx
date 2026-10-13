import { useAppStore } from '../store/appStore';
import type { GraphData, GraphNode, GraphEdge } from '../api/client';
import type { Ontology } from '../data/ontology';

function findNode(graph: GraphData | null, id: string): GraphNode | null {
  return graph?.nodes.find((n) => n.id === id) ?? null;
}

function findEdge(graph: GraphData | null, edgeId: string): GraphEdge | null {
  return graph?.edges.find((e) => `edge|${e.source}--${e.label}--${e.target}` === edgeId) ?? null;
}

/** entity id 由 parser 生成为首字母小写（requirementAnalysis），图谱节点 id 为后端短名（RequirementAnalysis），做大小写不敏感匹配 */
function findEntity(ontology: Ontology | null, id: string) {
  const lower = id.toLowerCase();
  return ontology?.entityTypes.find((e) => e.id.toLowerCase() === lower || e.name.toLowerCase() === lower) ?? null;
}

export default function Inspector() {
  const ontology = useAppStore((s) => s.ontology);
  const materialized = useAppStore((s) => s.materialized);
  const viewMode = useAppStore((s) => s.viewMode);
  const selectedId = useAppStore((s) => s.selectedId);

  if (!selectedId) {
    return (
      <div className="panel">
        <h2>检视器</h2>
        <div style={{ fontSize: 13, color: '#5a6b7f' }}>点击图谱中的节点 / 边查看详情。</div>
      </div>
    );
  }

  const isEdge = selectedId.startsWith('edge|');
  const asserted = materialized.asserted;
  const inferred = materialized.inferred;

  if (isEdge) {
    const edgeId = selectedId;
    const edge = findEdge(asserted, edgeId) ?? findEdge(inferred, edgeId);
    const provenance = findEdge(asserted, edgeId) ? '原始断言' : findEdge(inferred, edgeId) ? '推理新增' : '';
    const labelOf = (id: string) =>
      findNode(asserted, id)?.label ?? findNode(inferred, id)?.label ?? id;
    return (
      <div className="panel">
        <h2>关系 · {edge?.label ?? selectedId}</h2>
        <div style={{ fontSize: 13, lineHeight: 1.8 }}>
          <div><b>来源 → 目标</b>：{labelOf(edge?.source ?? '')} → {labelOf(edge?.target ?? '')}</div>
          <div><b>属性名</b>：{edge?.label}</div>
          {provenance && <div><b>来源</b>：{provenance}</div>}
          {viewMode === 'materialized' && provenance === '推理新增' && (
            <div style={{ color: '#2f8f6b', fontSize: 12 }}>该边由 OWL 2 RL 推理推导（物化新增）。</div>
          )}
        </div>
      </div>
    );
  }

  const node = findNode(asserted, selectedId) ?? findNode(inferred, selectedId);
  const entity = findEntity(ontology, selectedId);
  const isInferredNode = !findNode(asserted, selectedId) && findNode(inferred, selectedId);

  // 个体/类的关联属性边（出边 + 入边），来自断言与推理图数据
  const labelOf = (id: string) =>
    findNode(asserted, id)?.label ?? findNode(inferred, id)?.label ?? id;
  const relatedEdges: { edge: GraphEdge; direction: 'out' | 'in' }[] = [];
  const pushEdges = (graph: GraphData | null) => {
    if (!graph) return;
    const seen = new Set<string>();
    for (const e of graph.edges) {
      const eid = `edge|${e.source}--${e.label}--${e.target}`;
      if (seen.has(eid)) continue;
      seen.add(eid);
      if (e.source === selectedId) relatedEdges.push({ edge: e, direction: 'out' });
      else if (e.target === selectedId) relatedEdges.push({ edge: e, direction: 'in' });
    }
  };
  if (viewMode !== 'diff') pushEdges(asserted);
  if (viewMode === 'materialized' || viewMode === 'diff') pushEdges(inferred);

  // 类节点：展示可编辑模型中的实体定义（描述 / 属性 / 关系）
  const entityRelationships = entity
    ? ontology!.relationships.filter(
        (r) => r.from.toLowerCase() === entity.id.toLowerCase() || r.to.toLowerCase() === entity.id.toLowerCase(),
      )
    : [];

  return (
    <div className="panel" style={{ maxHeight: 560, overflowY: 'auto' }}>
      <h2>{node?.label ?? selectedId}</h2>
      <div style={{ fontSize: 13, lineHeight: 1.8 }}>
        <div><b>类型</b>：{node?.type === 'class' ? '类（Class）' : '个体（Individual）'}</div>
        {node?.types && node.types.length > 0 && (
          <div>
            <b>{node.type === 'class' ? '父类' : '所属类型'}</b>：{node.types.join('、')}
          </div>
        )}
        {isInferredNode && <div style={{ color: '#2f8f6b', fontSize: 12 }}>推理新增节点（物化产生）</div>}

        {entity ? (
          <>
            {entity.description && <div><b>描述</b>：{entity.description}</div>}
            {entity.properties.length > 0 && (
              <>
                <div><b>属性</b></div>
                <ul style={{ listStyle: 'none', paddingLeft: 8, margin: '2px 0 6px' }}>
                  {entity.properties.map((p) => (
                    <li key={p.name}>
                      {p.name} <span style={{ color: '#5a6b7f' }}>({p.type})</span>
                      {p.isIdentifier ? ' 🔑' : ''}
                      {p.unit ? ` · ${p.unit}` : ''}
                      {p.description ? <div style={{ color: '#8a94a6', fontSize: 12 }}>{p.description}</div> : null}
                    </li>
                  ))}
                </ul>
              </>
            )}
            {entityRelationships.length > 0 && (
              <>
                <div><b>关系</b></div>
                <ul style={{ listStyle: 'none', paddingLeft: 8, margin: '2px 0 6px' }}>
                  {entityRelationships.map((r) => (
                    <li key={r.id}>
                      {r.name}{' '}
                      <span style={{ color: '#5a6b7f' }}>
                        ({r.from} {r.cardinality === 'one-to-one' ? '↔' : r.cardinality === 'many-to-many' ? '⇄' : '→'} {r.to})
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        ) : (
          <div style={{ color: '#8a94a6' }}>
            该节点不在可编辑模型（实体集）中，以下为图谱中的属性边。
          </div>
        )}

        {relatedEdges.length > 0 && (
          <>
            <div style={{ marginTop: 4 }}><b>属性 / 关联</b></div>
            <ul style={{ listStyle: 'none', paddingLeft: 8, margin: '2px 0 6px', fontSize: 12 }}>
              {relatedEdges.map(({ edge, direction }) => (
                <li key={`edge|${edge.source}--${edge.label}--${edge.target}`} style={{ marginBottom: 2 }}>
                  {direction === 'out' ? (
                    <>
                      <span style={{ color: '#2f8f6b' }}>→</span> {edge.label}{' '}
                      <span style={{ color: '#8a94a6' }}>→ {labelOf(edge.target)}</span>
                    </>
                  ) : (
                    <>
                      <span style={{ color: '#8a94a6' }}>{labelOf(edge.source)}</span>{' '}
                      <span style={{ color: '#2f8f6b' }}>→ {edge.label}</span>
                    </>
                  )}
                  {edge.provenance === 'inferred' ? <span style={{ color: '#2f8f6b' }}> · 推理</span> : null}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
