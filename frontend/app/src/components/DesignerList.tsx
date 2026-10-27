import { useMemo, useState } from 'react';
import type { EntityType, Relationship } from '../data/ontology';

export interface DesignerListProps {
  entityTypes: EntityType[];
  relationships: Relationship[];
  selectedEntityId: string | null;
  selectedRelId: string | null;
  onSelectEntity: (id: string) => void;
  onSelectRel: (id: string) => void;
  onAddEntity: () => void;
  onAddRel: () => void;
  onDeleteEntity: (id: string) => void;
  onDeleteRel: (id: string) => void;
}

function matches(q: string, ...fields: (string | undefined)[]): boolean {
  const k = q.trim().toLowerCase();
  if (!k) return true;
  return fields.some((f) => (f ?? '').toLowerCase().includes(k));
}

/** 左侧资源列表：实体与关系两个分组，含计数徽标、搜索、新增、删除二次确认 */
export default function DesignerList({
  entityTypes,
  relationships,
  selectedEntityId,
  selectedRelId,
  onSelectEntity,
  onSelectRel,
  onAddEntity,
  onAddRel,
  onDeleteEntity,
  onDeleteRel,
}: DesignerListProps) {
  const [entityQ, setEntityQ] = useState('');
  const [relQ, setRelQ] = useState('');
  const [confirmEntityId, setConfirmEntityId] = useState<string | null>(null);
  const [confirmRelId, setConfirmRelId] = useState<string | null>(null);

  const visibleEntities = useMemo(
    () => entityTypes.filter((e) => matches(entityQ, e.name, e.id)),
    [entityTypes, entityQ],
  );
  const visibleRels = useMemo(
    () => relationships.filter((r) => matches(relQ, r.name, r.from, r.to)),
    [relationships, relQ],
  );

  return (
    <div className="designer-list-col">
      <section className="designer-group">
        <header className="designer-group-head">
          <h4>
            实体类型 <span className="designer-count">{entityTypes.length}</span>
          </h4>
          <button type="button" className="btn icon" title="新增实体" onClick={onAddEntity}>
            ＋
          </button>
        </header>
        <div className="designer-search">
          <input value={entityQ} onChange={(e) => setEntityQ(e.target.value)} placeholder="搜索实体…" />
        </div>
        <ul className="designer-list">
          {visibleEntities.map((e) => {
            const selected = selectedEntityId === e.id;
            const confirming = confirmEntityId === e.id;
            return (
              <li
                key={e.id}
                className={`designer-item${selected ? ' selected' : ''}`}
                tabIndex={0}
                onClick={() => {
                  onSelectEntity(e.id);
                  setConfirmEntityId(null);
                }}
                onKeyDown={(ev) => {
                  if (ev.key === 'Enter') onSelectEntity(e.id);
                  else if (ev.key === 'Escape') setConfirmEntityId(null);
                }}
              >
                <span className="designer-dot" style={{ background: e.color }} />
                <span className="designer-item-icon">{e.icon}</span>
                <span className="designer-item-name">{e.name || '(未命名)'}</span>
                <span className="designer-id-badge">{e.id || '—'}</span>
                {confirming ? (
                  <span className="designer-confirm" onClick={(ev) => ev.stopPropagation()}>
                    <span className="designer-confirm-text">确认删除？</span>
                    <button
                      type="button"
                      className="btn ghost danger-text"
                      onClick={(ev) => {
                        ev.stopPropagation();
                        onDeleteEntity(e.id);
                        setConfirmEntityId(null);
                      }}
                    >
                      删除
                    </button>
                    <button
                      type="button"
                      className="btn ghost"
                      onClick={(ev) => {
                        ev.stopPropagation();
                        setConfirmEntityId(null);
                      }}
                    >
                      取消
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    className="btn ghost danger-text designer-item-del"
                    title="删除实体"
                    onClick={(ev) => {
                      ev.stopPropagation();
                      setConfirmEntityId(e.id);
                    }}
                  >
                    删
                  </button>
                )}
              </li>
            );
          })}
          {visibleEntities.length === 0 && (
            <li className="designer-list-empty">{entityQ ? '无匹配项' : '暂无实体，点击右上角 ＋ 新增'}</li>
          )}
        </ul>
      </section>

      <section className="designer-group">
        <header className="designer-group-head">
          <h4>
            关系 <span className="designer-count">{relationships.length}</span>
          </h4>
          <button type="button" className="btn icon" title="新增关系" onClick={onAddRel}>
            ＋
          </button>
        </header>
        <div className="designer-search">
          <input value={relQ} onChange={(e) => setRelQ(e.target.value)} placeholder="搜索关系…" />
        </div>
        <ul className="designer-list">
          {visibleRels.map((r) => {
            const selected = selectedRelId === r.id;
            const confirming = confirmRelId === r.id;
            return (
              <li
                key={r.id}
                className={`designer-item${selected ? ' selected' : ''}`}
                tabIndex={0}
                onClick={() => {
                  onSelectRel(r.id);
                  setConfirmRelId(null);
                }}
                onKeyDown={(ev) => {
                  if (ev.key === 'Enter') onSelectRel(r.id);
                  else if (ev.key === 'Escape') setConfirmRelId(null);
                }}
              >
                <span className="designer-item-name">{r.name || '(未命名)'}</span>
                <span className="designer-id-badge">
                  {r.from} → {r.to}
                </span>
                <span className="designer-card-badge">{r.cardinality}</span>
                {confirming ? (
                  <span className="designer-confirm" onClick={(ev) => ev.stopPropagation()}>
                    <span className="designer-confirm-text">确认删除？</span>
                    <button
                      type="button"
                      className="btn ghost danger-text"
                      onClick={(ev) => {
                        ev.stopPropagation();
                        onDeleteRel(r.id);
                        setConfirmRelId(null);
                      }}
                    >
                      删除
                    </button>
                    <button
                      type="button"
                      className="btn ghost"
                      onClick={(ev) => {
                        ev.stopPropagation();
                        setConfirmRelId(null);
                      }}
                    >
                      取消
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    className="btn ghost danger-text designer-item-del"
                    title="删除关系"
                    onClick={(ev) => {
                      ev.stopPropagation();
                      setConfirmRelId(r.id);
                    }}
                  >
                    删
                  </button>
                )}
              </li>
            );
          })}
          {visibleRels.length === 0 && (
            <li className="designer-list-empty">{relQ ? '无匹配项' : '暂无关系，点击右上角 ＋ 新增'}</li>
          )}
        </ul>
      </section>
    </div>
  );
}
