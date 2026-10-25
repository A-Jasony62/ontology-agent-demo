import { describe, it, expect } from 'vitest';
import { useEditorStore } from '../store/editorStore';
import { validateEditModel } from '../data/validateEditModel';
import { editModelToGraphData, emptyEditModel } from '../data/editModel';
import type { EditModelAssertion } from '../data/editModel';

function sample() {
  return {
    ontologyName: 't',
    namespace: 'http://example.org/t#',
    classes: [
      { id: 'Person', label: '人员', parent: null, description: '' },
      { id: 'Employee', label: '员工', parent: 'Person', description: '' },
    ],
    objectProps: [{ id: 'worksFor', label: '', domain: 'Employee', range: 'Person', characteristics: [] }],
    dataProps: [{ id: 'salary', label: '', domain: 'Employee', range: 'integer' }],
    individuals: [{ id: 'alice', label: '', types: ['Employee'], assertions: [] as EditModelAssertion[] }],
  };
}

describe('editorStore undo/redo', () => {
  it('commit 推进 history 并置 dirty', () => {
    const s = useEditorStore.getState();
    s.open(sample());
    s.commit({ ...sample(), classes: [...sample().classes, { id: 'X', label: '', parent: null, description: '' }] });
    const st = useEditorStore.getState();
    expect(st.dirty).toBe(true);
    expect(st.history.length).toBe(1);
    expect(st.future.length).toBe(0);
  });

  it('undo 回退、redo 前进', () => {
    const s = useEditorStore.getState();
    const base = sample();
    s.open(base);
    const next = { ...base, classes: [...base.classes, { id: 'X', label: '', parent: null, description: '' }] };
    s.commit(next);
    s.undo();
    let st = useEditorStore.getState();
    expect(st.model!.classes.length).toBe(2);
    expect(st.future.length).toBe(1);
    s.redo();
    st = useEditorStore.getState();
    expect(st.model!.classes.length).toBe(3);
    expect(st.history.length).toBe(1);
  });

  it('空栈时 undo/redo 为 no-op', () => {
    const s = useEditorStore.getState();
    s.open(sample());
    s.undo();
    expect(useEditorStore.getState().model!.classes.length).toBe(2);
    s.redo();
    expect(useEditorStore.getState().model!.classes.length).toBe(2);
  });

  it('history 上限 20', () => {
    const s = useEditorStore.getState();
    const base = sample();
    s.open(base);
    for (let i = 0; i < 30; i++) {
      s.commit({ ...base, classes: [...base.classes, { id: `C${i}`, label: '', parent: null, description: '' }] });
    }
    expect(useEditorStore.getState().history.length).toBe(20);
  });

  it('markSaved 清 dirty 并记录文件名', () => {
    const s = useEditorStore.getState();
    s.open(sample());
    s.commit({ ...sample(), classes: [] });
    s.markSaved('out.owl', { triples_before: 1, triples_after: 2, inferred_added: 1, classes: 1, individuals: 0 });
    const st = useEditorStore.getState();
    expect(st.dirty).toBe(false);
    expect(st.savedFilename).toBe('out.owl');
  });

  it('closeEditor 清空全部状态', () => {
    const s = useEditorStore.getState();
    s.open(sample());
    s.commit({ ...sample(), classes: [] });
    s.closeEditor();
    const st = useEditorStore.getState();
    expect(st.model).toBeNull();
    expect(st.dirty).toBe(false);
    expect(st.history.length).toBe(0);
  });
});

describe('validateEditModel', () => {
  it('合法模型无错误', () => {
    expect(validateEditModel(sample())).toEqual([]);
  });

  it('父类不存在报错', () => {
    const m = sample();
    m.classes[1].parent = 'Ghost';
    expect(validateEditModel(m).join(' ')).toContain('父类不存在: Ghost');
  });

  it('父类环检测', () => {
    const m = sample();
    m.classes = [
      { id: 'A', label: '', parent: 'B', description: '' },
      { id: 'B', label: '', parent: 'A', description: '' },
    ];
    const errs = validateEditModel(m);
    expect(errs.some((e) => e.includes('环'))).toBe(true);
  });

  it('属性 domain/range 引用不存在类报错', () => {
    const m = sample();
    m.objectProps[0].domain = 'Nope';
    expect(validateEditModel(m).join(' ')).toContain('domain');
  });

  it('类 id 重复报错', () => {
    const m = sample();
    m.classes.push({ id: 'Person', label: '', parent: null, description: '' });
    expect(validateEditModel(m)).toContain('类 id 重复: Person');
  });

  it('个体类型引用不存在类报错', () => {
    const m = sample();
    m.individuals[0].types = ['Ghost'];
    expect(validateEditModel(m).join(' ')).toContain('类型类不存在: Ghost');
  });

  it('断言属性不存在报错', () => {
    const m = sample();
    m.individuals[0].assertions = [{ prop: 'nope', value: 'x', isObject: false }];
    expect(validateEditModel(m).join(' ')).toContain('断言属性不存在: nope');
  });

  it('数据断言缺取值报错', () => {
    const m = sample();
    m.individuals[0].assertions = [{ prop: 'salary', value: '  ', isObject: false }];
    expect(validateEditModel(m).join(' ')).toContain('缺少取值');
  });
});

describe('editModelToGraphData', () => {
  it('类节点 + subClassOf 边 + 个体与类型边', () => {
    const g = editModelToGraphData(sample());
    expect(g.nodes).toHaveLength(3);
    expect(g.nodes.some((n) => n.type === 'class' && n.id === 'Employee')).toBe(true);
    expect(g.edges.some((e) => e.label === 'subClassOf' && e.source === 'Employee' && e.target === 'Person')).toBe(true);
    expect(g.edges.some((e) => e.label === 'rdf:type' && e.source === 'alice' && e.target === 'Employee')).toBe(true);
  });

  it('空模型输出空图', () => {
    const g = editModelToGraphData(emptyEditModel());
    expect(g.nodes).toEqual([]);
    expect(g.edges).toEqual([]);
  });
});
