import { useState } from 'react';
import type { Ontology, EntityType, Property, Relationship } from '../data/ontology';
import { validateOntology } from '../data/validate';
import type { ValidationLevel } from '../data/validate';
import { ontologyToGraphData } from '../data/toGraphData';
import { useAppStore } from '../store/appStore';

const PROPERTY_TYPES = ['string', 'integer', 'decimal', 'double', 'date', 'datetime', 'boolean', 'enum'];
const CARDINALITIES = ['one-to-one', 'one-to-many', 'many-to-one', 'many-to-many'];
const COLORS = ['#0078D4', '#107C10', '#D83B01', '#5C2D91', '#008272', '#00A9E0', '#FFB900', '#E81123'];

export default function Designer() {
  const ontology = useAppStore((s) => s.ontology);
  const setOntology = useAppStore((s) => s.setOntology);
  const setGraphData = useAppStore((s) => s.setGraphData);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [selectedRelId, setSelectedRelId] = useState<string | null>(null);

  if (!ontology) {
    return (
      <div className="panel">
        <h2>可视化编辑器</h2>
        <div style={{ fontSize: 13, color: '#5a6b7f' }}>暂无本体模型。请先导入 .owl 文件，或加载默认本体。</div>
      </div>
    );
  }

  const errors = validateOntology(ontology);
  const selectedEntity = ontology.entityTypes.find((e) => e.id === selectedEntityId) ?? null;
  const selectedRel = ontology.relationships.find((r) => r.id === selectedRelId) ?? null;

  // #22：按严重度分组折叠（blocker/required 默认展开，suggestion 折叠），点击可定位实体
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({ suggestion: false });
  const groupLabels: { key: ValidationLevel; label: string }[] = [
    { key: 'blocker', label: '阻断（必须修复）' },
    { key: 'required', label: '必改（命名/标识/合法性）' },
    { key: 'suggestion', label: '建议（历史遗留可优化，不影响使用）' },
  ];
  const toggleGroup = (k: ValidationLevel) => setCollapsedGroups((g) => ({ ...g, [k]: !g[k] }));

  const commit = (next: Ontology) => {
    setOntology(next);
    setGraphData(ontologyToGraphData(next));
  };

  const updateEntity = (id: string, patch: Partial<EntityType>) => {
    commit({ ...ontology, entityTypes: ontology.entityTypes.map((e) => (e.id === id ? { ...e, ...patch } : e)) });
  };

  const updateProperty = (entityId: string, idx: number, patch: Partial<Property>) => {
    commit({
      ...ontology,
      entityTypes: ontology.entityTypes.map((e) =>
        e.id === entityId
          ? { ...e, properties: e.properties.map((p, i) => (i === idx ? { ...p, ...patch } : p)) }
          : e,
      ),
    });
  };

  const updateRel = (id: string, patch: Partial<Relationship>) => {
    commit({ ...ontology, relationships: ontology.relationships.map((r) => (r.id === id ? { ...r, ...patch } : r)) });
  };

  return (
    <div className="panel" id="designer-root">
      <h2>可视化编辑器</h2>
      {errors.length > 0 && (
        <div className="validation-groups">
          <div className="validation-guide">
            校验发现 {errors.length} 项提示（部分为默认本体历史遗留的命名/描述可优化项，不影响当前使用）；点击条目可定位到对应实体。
          </div>
          {groupLabels.map(({ key, label }) => {
            const list = errors.filter((e) => e.level === key);
            if (list.length === 0) return null;
            const open = !collapsedGroups[key];
            return (
              <details key={key} className={`validation-group level-${key}`} open={open}>
                <summary onClick={(e) => { e.preventDefault(); toggleGroup(key); }}>
                  {open ? '▾' : '▸'} {label}（{list.length}）
                </summary>
                <ul>
                  {list.map((it, i) => (
                    <li
                      key={i}
                      className={it.targetId ? 'clickable' : ''}
                      onClick={() => { if (it.targetId) { setSelectedEntityId(it.targetId); (document.getElementById('designer-root') as HTMLElement | null)?.scrollIntoView({ behavior: 'smooth', block: 'start' }); } }}
                      title={it.targetId ? '点击定位到该实体' : undefined}
                    >
                      {it.message}
                    </li>
                  ))}
                </ul>
              </details>
            );
          })}
        </div>
      )}

      <div className="editor-grid">
        {/* 实体 */}
        <div className="col">
          <h4>实体类型（{ontology.entityTypes.length}）</h4>
          <ul>
            {ontology.entityTypes.map((e) => (
              <li key={e.id} style={{ cursor: 'pointer', fontWeight: selectedEntityId === e.id ? 700 : 400 }} onClick={() => setSelectedEntityId(e.id)}>
                <span style={{ background: e.color, width: 10, height: 10, borderRadius: '50%', display: 'inline-block' }} />
                {e.icon} {e.name}
                <button className="secondary" onClick={() => {
                  commit({ ...ontology, entityTypes: ontology.entityTypes.filter((x) => x.id !== e.id) });
                  if (selectedEntityId === e.id) setSelectedEntityId(null);
                }}>删</button>
              </li>
            ))}
          </ul>
          <button
            onClick={() => {
              const id = `entity${ontology.entityTypes.length + 1}`;
              const entity: EntityType = { id, name: `Entity${ontology.entityTypes.length + 1}`, description: '', icon: '📦', color: COLORS[ontology.entityTypes.length % COLORS.length], properties: [] };
              commit({ ...ontology, entityTypes: [...ontology.entityTypes, entity] });
              setSelectedEntityId(id);
            }}
          >
            + 新增实体
          </button>
          {selectedEntity && (
            <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <input placeholder="id（小写 slug）" value={selectedEntity.id} onChange={(e) => updateEntity(selectedEntity.id, { id: e.target.value })} />
              <input placeholder="名称" value={selectedEntity.name} onChange={(e) => updateEntity(selectedEntity.id, { name: e.target.value })} />
              <input placeholder="描述" value={selectedEntity.description} onChange={(e) => updateEntity(selectedEntity.id, { description: e.target.value })} />
              <input placeholder="图标（emoji）" value={selectedEntity.icon} onChange={(e) => updateEntity(selectedEntity.id, { icon: e.target.value })} />
              <select value={selectedEntity.color} onChange={(e) => updateEntity(selectedEntity.id, { color: e.target.value })}>
                {COLORS.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          )}
        </div>

        {/* 属性 */}
        <div className="col">
          <h4>属性（{selectedEntity ? selectedEntity.name : '—'}）</h4>
          {!selectedEntity && <div style={{ fontSize: 13, color: '#8a94a6' }}>先选择实体</div>}
          {selectedEntity && (
            <>
              <ul>
                {selectedEntity.properties.map((p, idx) => (
                  <li key={idx}>
                    {p.name} ({p.type}){p.isIdentifier ? ' 🔑' : ''}
                    <button className="secondary" onClick={() => {
                      commit({
                        ...ontology,
                        entityTypes: ontology.entityTypes.map((e) =>
                          e.id === selectedEntity.id ? { ...e, properties: e.properties.filter((_, i) => i !== idx) } : e,
                        ),
                      });
                    }}>删</button>
                  </li>
                ))}
              </ul>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
                <input placeholder="属性名（camelCase）" value={selectedEntity.properties[selectedEntity.properties.length - 1]?.name ?? ''}
                  onChange={(e) => {
                    const last = selectedEntity.properties.length - 1;
                    if (last < 0) return;
                    updateProperty(selectedEntity.id, last, { name: e.target.value });
                  }} />
                <select
                  value={selectedEntity.properties[selectedEntity.properties.length - 1]?.type ?? 'string'}
                  onChange={(e) => {
                    const last = selectedEntity.properties.length - 1;
                    if (last < 0) return;
                    updateProperty(selectedEntity.id, last, { type: e.target.value as Property['type'] });
                  }}
                >
                  {PROPERTY_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
                <label style={{ fontSize: 12 }}>
                  <input
                    type="checkbox"
                    checked={selectedEntity.properties[selectedEntity.properties.length - 1]?.isIdentifier ?? false}
                    onChange={(e) => {
                      const last = selectedEntity.properties.length - 1;
                      if (last < 0) return;
                      updateProperty(selectedEntity.id, last, { isIdentifier: e.target.checked });
                    }}
                  />
                  标识属性（🔑）
                </label>
                <button
                  onClick={() => {
                    commit({
                      ...ontology,
                      entityTypes: ontology.entityTypes.map((e) =>
                        e.id === selectedEntity.id
                          ? { ...e, properties: [...e.properties, { name: `prop${e.properties.length + 1}`, type: 'string' }] }
                          : e,
                      ),
                    });
                  }}
                >
                  + 新增属性
                </button>
              </div>
            </>
          )}
        </div>

        {/* 关系 */}
        <div className="col">
          <h4>关系（{ontology.relationships.length}）</h4>
          <ul>
            {ontology.relationships.map((r) => (
              <li key={r.id} style={{ cursor: 'pointer', fontWeight: selectedRelId === r.id ? 700 : 400 }} onClick={() => setSelectedRelId(r.id)}>
                {r.name} ({r.from} → {r.to}, {r.cardinality})
                <button className="secondary" onClick={() => {
                  commit({ ...ontology, relationships: ontology.relationships.filter((x) => x.id !== r.id) });
                  if (selectedRelId === r.id) setSelectedRelId(null);
                }}>删</button>
              </li>
            ))}
          </ul>
          <button
            onClick={() => {
              const id = `rel${ontology.relationships.length + 1}`;
              const from = ontology.entityTypes[0]?.id ?? '';
              const to = ontology.entityTypes[1]?.id ?? from;
              const rel: Relationship = { id, name: id, from, to, cardinality: 'one-to-many' };
              commit({ ...ontology, relationships: [...ontology.relationships, rel] });
              setSelectedRelId(id);
            }}
          >
            + 新增关系
          </button>
          {selectedRel && (
            <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <input placeholder="关系名（动词）" value={selectedRel.name} onChange={(e) => updateRel(selectedRel.id, { name: e.target.value })} />
              <select value={selectedRel.from} onChange={(e) => updateRel(selectedRel.id, { from: e.target.value })}>
                {ontology.entityTypes.map((e) => <option key={e.id} value={e.id}>{e.name} ({e.id})</option>)}
              </select>
              <select value={selectedRel.to} onChange={(e) => updateRel(selectedRel.id, { to: e.target.value })}>
                {ontology.entityTypes.map((e) => <option key={e.id} value={e.id}>{e.name} ({e.id})</option>)}
              </select>
              <select value={selectedRel.cardinality} onChange={(e) => updateRel(selectedRel.id, { cardinality: e.target.value as Relationship['cardinality'] })}>
                {CARDINALITIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <input placeholder="描述" value={selectedRel.description ?? ''} onChange={(e) => updateRel(selectedRel.id, { description: e.target.value })} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
