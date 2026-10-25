import { useState } from 'react';
import { useEditorStore } from '../store/editorStore';
import { useAppStore } from '../store/appStore';
import { api } from '../api/client';
import { PROPERTY_CHARACTERISTICS, XSD_DATATYPES } from '../data/editModel';
import type { EditModel, EditModelAssertion } from '../data/editModel';
import { validateEditModel } from '../data/validateEditModel';

interface Props {
  onClose: () => void;
}

/** 通用小部件：带标签的输入行 */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="ef-field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export default function OntologyEditor({ onClose }: Props) {
  const {
    model, history, future, dirty, loading, error, savedFilename,
    commit, undo, redo, resetTo, setError, markSaved, closeEditor,
  } = useEditorStore();
  const setMaterialized = useAppStore((s) => s.setMaterialized);
  const setSource = useAppStore((s) => s.setSource);
  const setGraphData = useAppStore((s) => s.setGraphData);
  const [filename, setFilename] = useState('');
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  if (!model) {
    return (
      <div className="panel">
        <h2>在线编辑本体定义</h2>
        <div style={{ fontSize: 13, color: '#5a6b7f' }}>正在加载编辑模型…（若持续显示，请检查后端连接）</div>
      </div>
    );
  }

  const errors = validateEditModel(model);
  const classIds = new Set(model.classes.map((c) => c.id));
  const indIds = new Set(model.individuals.map((i) => i.id));

  /** 类层次树：按 parent 建立（无环前提下深度有限） */
  const roots = model.classes.filter((c) => !c.parent || !classIds.has(c.parent));
  const childrenOf = (pid: string) => model.classes.filter((c) => c.parent === pid && c.parent !== c.id);

  const renderClassNode = (c: { id: string; label: string; parent: string | null; description: string }, depth: number) => (
    <div key={c.id}>
      <div className="ef-tree-row" style={{ paddingLeft: depth * 18 }}>
        <Field label="id">
          <input value={c.id} disabled />
        </Field>
        <Field label="名称">
          <input value={c.label} onChange={(e) => commit({ ...model, classes: model.classes.map((x) => (x.id === c.id ? { ...x, label: e.target.value } : x)) })} />
        </Field>
        <Field label="父类">
          <select
            value={c.parent ?? ''}
            onChange={(e) => commit({ ...model, classes: model.classes.map((x) => (x.id === c.id ? { ...x, parent: e.target.value || null } : x)) })}
          >
            <option value="">（无）</option>
            {model.classes.filter((x) => x.id !== c.id).map((x) => <option key={x.id} value={x.id}>{x.label || x.id}</option>)}
          </select>
        </Field>
        <Field label="描述">
          <input value={c.description} onChange={(e) => commit({ ...model, classes: model.classes.map((x) => (x.id === c.id ? { ...x, description: e.target.value } : x)) })} />
        </Field>
        <button
          className="secondary"
          onClick={() => {
            const next = { ...model, classes: model.classes.filter((x) => x.id !== c.id) };
            commit(next);
          }}
        >
          删除
        </button>
      </div>
      {childrenOf(c.id).map((child) => renderClassNode(child, depth + 1))}
    </div>
  );

  const save = async (mode: 'new' | 'overwrite') => {
    if (errors.length > 0) {
      setError(`存在 ${errors.length} 项校验错误，请先修复：\n${errors.join('\n')}`);
      return;
    }
    if (mode === 'overwrite' && !window.confirm('将覆盖当前已加载的本体文件（默认本体覆盖后领域推理保留）。确定继续？')) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const name = filename.trim() || `${model.ontologyName || 'edited'}-edited.owl`;
      const res = await api.saveModel(model, name, mode);
      markSaved(res.filename, res.stats);
      // 刷新全局：物化 / 源码 / 图谱（断言视图）
      setMaterialized(res.materialized);
      const src = await api.source();
      setSource(src.content, src.filename);
      setGraphData(res.materialized.asserted);
      setNotice(
        `已保存（${mode === 'overwrite' ? '覆盖' : '另存'}）：${res.filename} · 三元组 ${res.stats.triples_before} → ${res.stats.triples_after}（推理新增 ${res.stats.inferred_added}）`,
      );
    } catch (e) {
      setError(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="panel">
      <div className="editor-toolbar">
        <h2>在线编辑本体定义 · {model.ontologyName || '—'}</h2>
        <div className="editor-actions">
          <span className={`dirty-dot ${dirty ? 'on' : ''}`} title={dirty ? '有未保存修改' : '已保存'} />
          <button className="secondary" onClick={undo} disabled={history.length === 0}>撤销</button>
          <button className="secondary" onClick={redo} disabled={future.length === 0}>重做</button>
          <button className="secondary" onClick={() => resetTo(model)} disabled={!dirty}>重置</button>
          <input
            className="ef-filename"
            placeholder="保存文件名"
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            title="另存文件名（默认 本体名-edited.owl）"
          />
          <button onClick={() => save('new')} disabled={saving || loading}>
            {saving ? '保存中…' : '另存为新本体'}
          </button>
          <button className="danger" onClick={() => save('overwrite')} disabled={saving || loading}>
            覆盖当前本体
          </button>
          {savedFilename && (
            <a className="secondary download-link" href={api.downloadUrl(savedFilename)} download={savedFilename}>
              下载 {savedFilename}
            </a>
          )}
          <button className="secondary" onClick={() => { closeEditor(); onClose(); }}>关闭</button>
        </div>
      </div>

      {loading && <div className="error-banner">正在载入编辑模型…</div>}
      {error && <div className="error-banner" style={{ whiteSpace: 'pre-wrap' }}>{error}</div>}
      {notice && <div className="notice-banner">{notice}</div>}
      {errors.length > 0 && !error && (
        <div className="error-banner" style={{ whiteSpace: 'pre-wrap' }}>
          {errors.length} 项校验提示：{errors.join('；')}
        </div>
      )}

      <div className="editor-grid ef-grid">
        {/* 类层次 */}
        <div className="col">
          <h4>类层次（{model.classes.length}）</h4>
          <div className="ef-tree">
            {roots.length === 0 && model.classes.map((c) => renderClassNode(c, 0))}
            {roots.map((c) => renderClassNode(c, 0))}
          </div>
          <button
            onClick={() => {
              const id = `NewClass${model.classes.length + 1}`;
              commit({ ...model, classes: [...model.classes, { id, label: `新类${model.classes.length + 1}`, parent: null, description: '' }] });
            }}
          >
            + 新增类
          </button>
        </div>

        {/* 对象属性 */}
        <div className="col">
          <h4>对象属性（{model.objectProps.length}）</h4>
          {model.objectProps.map((p) => (
            <div key={p.id} className="ef-row">
              <div className="ef-row-head">
                <input value={p.id} onChange={(e) => commit({ ...model, objectProps: model.objectProps.map((x) => (x.id === p.id ? { ...x, id: e.target.value } : x)) })} />
                <input value={p.label} placeholder="标签" onChange={(e) => commit({ ...model, objectProps: model.objectProps.map((x) => (x.id === p.id ? { ...x, label: e.target.value } : x)) })} />
                <button className="secondary" onClick={() => commit({ ...model, objectProps: model.objectProps.filter((x) => x.id !== p.id) })}>删</button>
              </div>
              <div className="ef-row-sub">
                <Field label="domain">
                  <select value={p.domain ?? ''} onChange={(e) => commit({ ...model, objectProps: model.objectProps.map((x) => (x.id === p.id ? { ...x, domain: e.target.value || null } : x)) })}>
                    <option value="">（无）</option>
                    {model.classes.map((c) => <option key={c.id} value={c.id}>{c.label || c.id}</option>)}
                  </select>
                </Field>
                <Field label="range">
                  <select value={p.range ?? ''} onChange={(e) => commit({ ...model, objectProps: model.objectProps.map((x) => (x.id === p.id ? { ...x, range: e.target.value || null } : x)) })}>
                    <option value="">（无）</option>
                    {model.classes.map((c) => <option key={c.id} value={c.id}>{c.label || c.id}</option>)}
                  </select>
                </Field>
              </div>
              <div className="ef-chars">
                {PROPERTY_CHARACTERISTICS.map((c) => (
                  <label key={c} style={{ fontSize: 11 }}>
                    <input
                      type="checkbox"
                      checked={p.characteristics.includes(c)}
                      onChange={(e) => commit({
                        ...model,
                        objectProps: model.objectProps.map((x) => x.id === p.id
                          ? { ...x, characteristics: e.target.checked ? [...x.characteristics, c] : x.characteristics.filter((v) => v !== c) }
                          : x),
                      })}
                    />
                    {c.replace('Property', '')}
                  </label>
                ))}
              </div>
            </div>
          ))}
          <button
            onClick={() => {
              const id = `newProp${model.objectProps.length + 1}`;
              commit({ ...model, objectProps: [...model.objectProps, { id, label: '', domain: null, range: null, characteristics: [] }] });
            }}
          >
            + 新增对象属性
          </button>
        </div>

        {/* 数据属性 */}
        <div className="col">
          <h4>数据属性（{model.dataProps.length}）</h4>
          {model.dataProps.map((p) => (
            <div key={p.id} className="ef-row">
              <div className="ef-row-head">
                <input value={p.id} onChange={(e) => commit({ ...model, dataProps: model.dataProps.map((x) => (x.id === p.id ? { ...x, id: e.target.value } : x)) })} />
                <input value={p.label} placeholder="标签" onChange={(e) => commit({ ...model, dataProps: model.dataProps.map((x) => (x.id === p.id ? { ...x, label: e.target.value } : x)) })} />
                <button className="secondary" onClick={() => commit({ ...model, dataProps: model.dataProps.filter((x) => x.id !== p.id) })}>删</button>
              </div>
              <div className="ef-row-sub">
                <Field label="domain">
                  <select value={p.domain ?? ''} onChange={(e) => commit({ ...model, dataProps: model.dataProps.map((x) => (x.id === p.id ? { ...x, domain: e.target.value || null } : x)) })}>
                    <option value="">（无）</option>
                    {model.classes.map((c) => <option key={c.id} value={c.id}>{c.label || c.id}</option>)}
                  </select>
                </Field>
                <Field label="range">
                  <select value={p.range ?? ''} onChange={(e) => commit({ ...model, dataProps: model.dataProps.map((x) => (x.id === p.id ? { ...x, range: e.target.value || null } : x)) })}>
                    <option value="">（无）</option>
                    {XSD_DATATYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </Field>
              </div>
            </div>
          ))}
          <button
            onClick={() => {
              const id = `newData${model.dataProps.length + 1}`;
              commit({ ...model, dataProps: [...model.dataProps, { id, label: '', domain: null, range: 'string' }] });
            }}
          >
            + 新增数据属性
          </button>
        </div>

        {/* 实例 */}
        <div className="col">
          <h4>实例（{model.individuals.length}）</h4>
          {model.individuals.map((ind) => (
            <div key={ind.id} className="ef-row">
              <div className="ef-row-head">
                <input value={ind.id} onChange={(e) => commit({ ...model, individuals: model.individuals.map((x) => (x.id === ind.id ? { ...x, id: e.target.value } : x)) })} />
                <input value={ind.label} placeholder="标签" onChange={(e) => commit({ ...model, individuals: model.individuals.map((x) => (x.id === ind.id ? { ...x, label: e.target.value } : x)) })} />
                <button className="secondary" onClick={() => commit({ ...model, individuals: model.individuals.filter((x) => x.id !== ind.id) })}>删</button>
              </div>
              <Field label="类型断言">
                <select
                  value={ind.types[0] ?? ''}
                  onChange={(e) => {
                    const types = e.target.value ? [e.target.value] : [];
                    commit({ ...model, individuals: model.individuals.map((x) => (x.id === ind.id ? { ...x, types } : x)) });
                  }}
                >
                  <option value="">（无）</option>
                  {model.classes.map((c) => <option key={c.id} value={c.id}>{c.label || c.id}</option>)}
                </select>
              </Field>
              <div className="ef-assertions">
                {ind.assertions.map((a, idx) => (
                  <AssertionRow
                    key={idx}
                    a={a}
                    model={model}
                    classIds={classIds}
                    indIds={indIds}
                    onChange={(next) => {
                      const assertions = [...ind.assertions];
                      assertions[idx] = next;
                      commit({ ...model, individuals: model.individuals.map((x) => (x.id === ind.id ? { ...x, assertions } : x)) });
                    }}
                    onRemove={() => {
                      const assertions = ind.assertions.filter((_, i) => i !== idx);
                      commit({ ...model, individuals: model.individuals.map((x) => (x.id === ind.id ? { ...x, assertions } : x)) });
                    }}
                  />
                ))}
                {ind.assertions.length === 0 && <div style={{ fontSize: 12, color: '#8a94a6' }}>无属性断言</div>}
                <button
                  className="secondary"
                  onClick={() => {
                    const firstObj = model.objectProps[0]?.id ?? '';
                    const assertion: EditModelAssertion = { prop: firstObj, value: '', isObject: !!firstObj };
                    commit({ ...model, individuals: model.individuals.map((x) => (x.id === ind.id ? { ...x, assertions: [...x.assertions, assertion] } : x)) });
                  }}
                >
                  + 断言
                </button>
              </div>
            </div>
          ))}
          <button
            onClick={() => {
              const id = `ind${model.individuals.length + 1}`;
              commit({ ...model, individuals: [...model.individuals, { id, label: `个体${model.individuals.length + 1}`, types: [], assertions: [] }] });
            }}
          >
            + 新增实例
          </button>
        </div>
      </div>

      <div style={{ fontSize: 12, color: '#8a94a6', marginTop: 8 }}>
        编辑模型由后端 rdflib 从当前本体提取（任意 OWL 可编辑）；保存后后端重建引擎并自动重推理，物化三视图与图谱随之刷新。
      </div>
    </div>
  );
}

function AssertionRow({
  a, model, classIds, indIds, onChange, onRemove,
}: {
  a: EditModelAssertion;
  model: EditModel;
  classIds: Set<string>;
  indIds: Set<string>;
  onChange: (next: EditModelAssertion) => void;
  onRemove: () => void;
}) {
  const objectValues = new Set<string>([...indIds, ...classIds]);
  return (
    <div className="ef-assertion">
      <select
        value={a.prop}
        onChange={(e) => {
          const prop = e.target.value;
          const isObject = model.objectProps.some((p) => p.id === prop);
          onChange({ ...a, prop, isObject, value: '' });
        }}
      >
        <option value="">（选择属性）</option>
        {[...model.objectProps, ...model.dataProps].map((p) => (
          <option key={p.id} value={p.id}>{p.id}</option>
        ))}
      </select>
      {a.isObject ? (
        <select value={a.value} onChange={(e) => onChange({ ...a, value: e.target.value })}>
          <option value="">（选择取值）</option>
          {[...objectValues].sort().map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
      ) : (
        <input value={a.value} placeholder="字面量取值" onChange={(e) => onChange({ ...a, value: e.target.value })} />
      )}
      <button className="secondary" onClick={onRemove}>✕</button>
    </div>
  );
}
