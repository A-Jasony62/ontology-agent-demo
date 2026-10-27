/**
 * 后端 REST 封装：本体推理 API（ontology-agent-demo · FastAPI :8000）
 * 开发期经 Vite proxy 转发（/api → http://127.0.0.1:8000）。
 */

export interface GraphNode {
  id: string;
  label: string;
  type: 'class' | 'individual' | 'property' | string;
  /** 个体 → 所属类型（rdf:type）；类 → 父类（rdfs:subClassOf）的短名列表 */
  types?: string[];
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  provenance?: 'asserted' | 'inferred';
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface MaterializedResponse {
  stats: { triples_asserted: number; triples_materialized: number; inferred_added: number };
  asserted: GraphData;
  inferred: GraphData;
}

export interface InferStats {
  triples_before: number;
  triples_after: number;
  added: number;
  classes: number;
  individuals: number;
}

/** 在线编辑模型（与后端 EditModel 对齐） */
export interface EditModelPayload {
  ontologyName: string;
  namespace: string;
  classes: { id: string; label: string; parent: string | null; description: string }[];
  objectProps: { id: string; label: string; domain: string | null; range: string | null; characteristics: string[] }[];
  dataProps: { id: string; label: string; domain: string | null; range: string | null }[];
  individuals: { id: string; label: string; types: string[]; assertions: { prop: string; value: string; isObject: boolean }[] }[];
}

export interface SaveModelResponse {
  status: string;
  path: string;
  filename: string;
  mode: 'new' | 'overwrite';
  stats: { triples_before: number; triples_after: number; inferred_added: number; classes: number; individuals: number };
  materialized: MaterializedResponse;
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* 非 JSON 响应 */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<Record<string, unknown>>('/api/health'),

  /** 本体状态（含 mode: default | generic，供前端判断领域推理可用性） */
  status: () => request<{ mode: 'default' | 'generic'; ontology: string; dirty: boolean; pending_changes: number }>('/api/ontology/status'),

  /** 领域图数据（图谱渲染） */
  ontology: () => request<GraphData>('/api/ontology'),

  /** 物化 diff：原始断言 / 推理新增 */
  materialized: () => request<MaterializedResponse>('/api/ontology/materialized'),

  /** 当前本体原始 RDF/XML 文本 */
  source: () => request<{ filename: string; content: string }>('/api/ontology/source'),

  /** 上传并加载本体到推理引擎（进入通用模式） */
  loadOntology: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<{ status: string; path: string; triples_before: number; classes: number; individuals: number }>(
      '/api/ontology/load',
      { method: 'POST', body: form },
    );
  },

  /** 重新推理统计 */
  infer: () => request<InferStats>('/api/infer'),

  /** 导出物化本体（Turtle 或 RDF/XML），返回 Blob */
  async exportMaterialized(format: 'turtle' | 'rdfxml'): Promise<Blob> {
    const res = await fetch(`/api/ontology/export?format=${format}`);
    if (!res.ok) throw new Error(`导出失败: ${res.status} ${res.statusText}`);
    return res.blob();
  },

  /** 当前本体 → 结构化编辑模型（在线编辑） */
  editModel: () => request<EditModelPayload>('/api/ontology/edit-model'),

  /** 保存编辑结果（另存 / 覆盖），返回落盘路径与重推理 stats */
  saveModel: (model: unknown, filename: string, mode: 'new' | 'overwrite') =>
    request<SaveModelResponse>('/api/ontology/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model, filename, mode }),
    }),

  /** 下载保存的本体文件 */
  downloadUrl: (name: string) => `/api/ontology/download?name=${encodeURIComponent(name)}`,
};
