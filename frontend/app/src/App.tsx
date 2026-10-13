import { useEffect, useState } from 'react';
import { useAppStore } from './store/appStore';
import { api } from './api/client';
import { parseRDF } from './lib/rdf/parser';
import GraphView from './components/GraphView';
import Inspector from './components/Inspector';
import SourceView from './components/SourceView';
import ImportModal from './components/ImportModal';
import ExportDialog from './components/ExportDialog';
import Designer from './components/Designer';
import MaterializedPanel from './components/MaterializedPanel';

type SourceMode = 'closed' | 'view' | 'edit';

export default function App() {
  const backendOk = useAppStore((s) => s.backendOk);
  const setBackendOk = useAppStore((s) => s.setBackendOk);
  const setMaterialized = useAppStore((s) => s.setMaterialized);
  const setSource = useAppStore((s) => s.setSource);
  const setOntology = useAppStore((s) => s.setOntology);
  const setGraphData = useAppStore((s) => s.setGraphData);
  const setError = useAppStore((s) => s.setError);
  const error = useAppStore((s) => s.error);
  const materialized = useAppStore((s) => s.materialized);
  const graphData = useAppStore((s) => s.graphData);
  const viewMode = useAppStore((s) => s.viewMode);
  const sourceName = useAppStore((s) => s.sourceName);

  const [importOpen, setImportOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [sourceMode, setSourceMode] = useState<SourceMode>('closed');
  const [designerOpen, setDesignerOpen] = useState(false);

  // 挂载初始化：健康检查 + 物化数据 + 源码解析为可编辑模型
  useEffect(() => {
    (async () => {
      try {
        const health = await api.health();
        setBackendOk(true, health);
        const mat = await api.materialized();
        setMaterialized(mat);
        const src = await api.source();
        setSource(src.content, src.filename);
        try {
          const { ontology } = parseRDF(src.content);
          setOntology(ontology);
        } catch {
          // 默认本体含 parser 未覆盖的公理时：保留后端图数据，模型置空
          setOntology(null);
        }
        setGraphData(mat.asserted);
      } catch (e) {
        setBackendOk(false);
        setError(
          `后端连接失败：${e instanceof Error ? e.message : String(e)}\n请先启动推理 API（cd ontology-agent-demo && make run，或 uvicorn api.main:app --port 8000）。`,
        );
      }
    })();
  }, [setBackendOk, setMaterialized, setSource, setOntology, setGraphData, setError]);

  return (
    <div className="app">
      <header className="app-header">
        <h1>本体图谱工作台</h1>
        <span className="app-sub">ontology-agent-demo · OWL 2 RL 推理 API</span>
        <div className="toolbar" style={{ marginLeft: 'auto' }}>
          <button onClick={() => setImportOpen(true)}>导入</button>
          <button onClick={() => setExportOpen(true)}>导出</button>
          <button onClick={() => setSourceMode('view')} disabled={!sourceName}>OWL 源码</button>
          <button onClick={() => setSourceMode('edit')} disabled={!sourceName}>源码编辑</button>
          <button className={designerOpen ? '' : 'secondary'} onClick={() => setDesignerOpen((v) => !v)}>
            {designerOpen ? '关闭编辑器' : '可视化编辑'}
          </button>
        </div>
        <span className={`health ${backendOk ? 'ok' : ''}`}>{backendOk ? '后端已连接' : '后端未连接'}</span>
      </header>

      <main className="app-main">
        {error && <div className="error-banner">{error}</div>}

        <div className="panel">
          <h2>本体图谱 · {sourceName || '—'}</h2>
          <MaterializedPanel />
          <div className="legend">
            <span className="item"><span className="line" style={{ borderColor: '#4a90a4' }}></span> 类（Class）</span>
            <span className="item"><span className="line" style={{ borderColor: '#c98a3d' }}></span> 个体（Individual）</span>
            <span className="item"><span className="line"></span> 原始断言边</span>
            <span className="item"><span className="line dashed" style={{ borderColor: '#2f8f6b' }}></span> 推理新增边（物化）</span>
          </div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 480px', minWidth: 320 }}>
              <GraphView
                viewMode={viewMode}
                asserted={viewMode === 'diff' ? null : graphData ?? materialized.asserted}
                inferred={materialized.inferred}
              />
            </div>
            <div style={{ flex: '0 1 300px', minWidth: 260 }}>
              <Inspector />
            </div>
          </div>
        </div>

        {designerOpen && <Designer />}
      </main>

      {importOpen && <ImportModal onClose={() => setImportOpen(false)} />}
      {exportOpen && <ExportDialog onClose={() => setExportOpen(false)} />}
      {sourceMode !== 'closed' && (
        <SourceView mode={sourceMode} onClose={() => setSourceMode('closed')} onSwitchToEdit={() => setSourceMode('edit')} />
      )}
    </div>
  );
}
