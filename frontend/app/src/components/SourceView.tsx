import { useState } from 'react';
import { highlightRdf, RDF_HIGHLIGHT_DARK } from '../lib/rdf/highlighter';
import { parseRDF, RDFParseError } from '../lib/rdf/parser';
import { useAppStore } from '../store/appStore';
import { ontologyToGraphData } from '../data/toGraphData';

interface Props {
  mode: 'view' | 'edit';
  onClose: () => void;
  onSwitchToEdit: () => void;
}

export default function SourceView({ mode, onClose, onSwitchToEdit }: Props) {
  const sourceXml = useAppStore((s) => s.sourceXml);
  const sourceName = useAppStore((s) => s.sourceName);
  const setOntology = useAppStore((s) => s.setOntology);
  const setSource = useAppStore((s) => s.setSource);
  const setGraphData = useAppStore((s) => s.setGraphData);
  const setError = useAppStore((s) => s.setError);
  const error = useAppStore((s) => s.error);

  const [draft, setDraft] = useState(sourceXml);
  const [localError, setLocalError] = useState<string | null>(null);

  const handleSave = () => {
    try {
      const { ontology } = parseRDF(draft);
      setOntology(ontology);
      setGraphData(ontologyToGraphData(ontology));
      setSource(draft, sourceName);
      setError(null);
      setLocalError(null);
      onClose();
    } catch (e) {
      const msg = e instanceof RDFParseError ? e.message : String(e);
      setLocalError(`解析失败：${msg}\n请修正 RDF/XML 后再保存。`);
    }
  };

  const handleDownload = () => {
    const blob = new Blob([sourceXml], { type: 'application/rdf+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = sourceName || 'ontology.owl';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>OWL 源码 · {sourceName || 'ontology.owl'}</h3>
        {mode === 'view' ? (
          <>
            <div className="source-view">{highlightRdf(sourceXml, RDF_HIGHLIGHT_DARK)}</div>
            <div className="actions">
              <button className="secondary" onClick={onSwitchToEdit}>编辑源码</button>
              <button className="secondary" onClick={handleDownload}>下载原始文件</button>
              <button onClick={onClose}>关闭</button>
            </div>
          </>
        ) : (
          <>
            <textarea
              className="source-editor"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              spellCheck={false}
            />
            {(localError || error) && <div className="error-banner">{localError ?? error}</div>}
            <div className="actions">
              <button className="secondary" onClick={onClose}>取消</button>
              <button onClick={handleSave}>保存并回读校验</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
