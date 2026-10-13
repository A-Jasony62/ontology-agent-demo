import { useAppStore } from '../store/appStore';
import type { GraphData } from '../api/client';

function findNode(graph: GraphData | null, id: string) {
  return graph?.nodes.find((n) => n.id === id) ?? null;
}

function findEdge(graph: GraphData | null, edgeId: string) {
  return graph?.edges.find((e) => `edge|${e.source}--${e.label}--${e.target}` === edgeId) ?? null;
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
    return (
      <div className="panel">
        <h2>关系 · {edge?.label ?? selectedId}</h2>
        <div style={{ fontSize: 13, lineHeight: 1.8 }}>
          <div><b>来源 → 目标</b>：{edge?.source} → {edge?.target}</div>
          {provenance && <div><b>来源</b>：{provenance}</div>}
          {viewMode === 'materialized' && provenance === '推理新增' && (
            <div style={{ color: '#2f8f6b', fontSize: 12 }}>该边由 OWL 2 RL 推理推导（物化新增）。</div>
          )}
        </div>
      </div>
    );
  }

  const node = findNode(asserted, selectedId) ?? findNode(inferred, selectedId);
  const entity = ontology?.entityTypes.find((e) => e.id === selectedId);
  const isInferredNode = !findNode(asserted, selectedId) && findNode(inferred, selectedId);

  return (
    <div className="panel">
      <h2>{node?.label ?? selectedId}</h2>
      <div style={{ fontSize: 13, lineHeight: 1.8 }}>
        <div><b>类型</b>：{node?.type === 'class' ? '类（Class）' : '个体（Individual）'}</div>
        {isInferredNode && <div style={{ color: '#2f8f6b', fontSize: 12 }}>推理新增节点（物化产生）</div>}
        {entity && (
          <>
            <div><b>描述</b>：{entity.description || '—'}</div>
            <div><b>属性</b></div>
            <ul style={{ listStyle: 'none', paddingLeft: 8 }}>
              {entity.properties.map((p) => (
                <li key={p.name}>
                  {p.name} <span style={{ color: '#5a6b7f' }}>({p.type})</span>
                  {p.isIdentifier ? ' 🔑' : ''}
                  {p.unit ? ` · ${p.unit}` : ''}
                </li>
              ))}
            </ul>
          </>
        )}
        {!entity && ontology && (
          <div style={{ color: '#8a94a6' }}>该节点不在可编辑模型（实体集）中，仅作图谱展示。</div>
        )}
      </div>
    </div>
  );
}
