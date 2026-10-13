import { useAppStore } from '../store/appStore';
import type { ViewMode } from '../store/appStore';

const MODES: { key: ViewMode; label: string; hint: string }[] = [
  { key: 'asserted', label: '原始断言', hint: '仅原始 OWL 声明' },
  { key: 'materialized', label: '物化后（并集）', hint: '原始 + 推理新增' },
  { key: 'diff', label: '仅差异', hint: '只显示推理新增' },
];

export default function MaterializedPanel() {
  const stats = useAppStore((s) => s.materialized.stats);
  const viewMode = useAppStore((s) => s.viewMode);
  const setViewMode = useAppStore((s) => s.setViewMode);
  const synced = useAppStore((s) => s.syncedToBackend);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div className="view-toggle">
        {MODES.map((m) => (
          <button key={m.key} className={viewMode === m.key ? 'active' : ''} title={m.hint} onClick={() => setViewMode(m.key)}>
            {m.label}
          </button>
        ))}
      </div>
      {stats && (
        <div className="stats-cards">
          <div className="stats-card">
            <div className="num">{stats.triples_asserted}</div>
            <div className="label">原始三元组</div>
          </div>
          <div className="stats-card">
            <div className="num">{stats.triples_materialized}</div>
            <div className="label">物化后三元组</div>
          </div>
          <div className="stats-card">
            <div className="num" style={{ color: '#2f8f6b' }}>{stats.inferred_added}</div>
            <div className="label">推理新增</div>
          </div>
        </div>
      )}
      {!synced && (
        <div style={{ fontSize: 12, color: '#8a94a6' }}>
          提示：导入自定义本体后，点击「同步到推理引擎」即可查看该本体的物化结果。
        </div>
      )}
    </div>
  );
}
