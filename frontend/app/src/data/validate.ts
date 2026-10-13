import type { Ontology } from '../data/ontology';

/**
 * 本体结构校验（自 Ontology-Playground designerStore 校验逻辑提炼）。
 * 返回错误列表；空数组 = 通过。
 */
export function validateOntology(o: Ontology): string[] {
  const errors: string[] = [];
  const ids = new Set<string>();

  for (const e of o.entityTypes) {
    if (!e.id || !/^[a-z0-9][a-z0-9-]*$/.test(e.id)) {
      errors.push(`实体 "${e.name || '(未命名)'}" 的 id 必须是小写 slug（如 customer、work-order）`);
    }
    if (ids.has(e.id)) errors.push(`实体 id 重复: ${e.id}`);
    ids.add(e.id);

    if (!e.name) errors.push('存在未命名实体');
    if (!e.description) errors.push(`实体 "${e.name}" 缺少描述`);

    const propNames = new Set<string>();
    const identifierProps = e.properties.filter((p) => p.isIdentifier);
    if (identifierProps.length !== 1) {
      errors.push(`实体 "${e.name}" 需要恰一个标识属性（当前 ${identifierProps.length} 个）`);
    }
    for (const p of e.properties) {
      if (!p.name) {
        errors.push(`实体 "${e.name}" 存在未命名属性`);
        continue;
      }
      if (propNames.has(p.name)) errors.push(`实体 "${e.name}" 属性名重复: ${p.name}`);
      propNames.add(p.name);
      const validTypes = ['string', 'integer', 'decimal', 'double', 'date', 'datetime', 'boolean', 'enum'];
      if (!validTypes.includes(p.type)) {
        errors.push(`实体 "${e.name}" 属性 "${p.name}" 类型非法: ${p.type}`);
      }
      if (p.type === 'enum' && (!p.values || p.values.length === 0)) {
        errors.push(`实体 "${e.name}" 枚举属性 "${p.name}" 缺少取值`);
      }
    }
  }

  const relIds = new Set<string>();
  for (const r of o.relationships) {
    if (!r.id || !/^[a-z0-9][a-z0-9-]*$/.test(r.id)) {
      errors.push(`关系 "${r.name || '(未命名)'}" 的 id 必须是小写 slug`);
    }
    if (relIds.has(r.id)) errors.push(`关系 id 重复: ${r.id}`);
    relIds.add(r.id);
    if (!o.entityTypes.some((e) => e.id === r.from)) {
      errors.push(`关系 "${r.name}" 的 from 实体不存在: ${r.from}`);
    }
    if (!o.entityTypes.some((e) => e.id === r.to)) {
      errors.push(`关系 "${r.name}" 的 to 实体不存在: ${r.to}`);
    }
    const validCard = ['one-to-one', 'one-to-many', 'many-to-one', 'many-to-many'];
    if (!validCard.includes(r.cardinality)) {
      errors.push(`关系 "${r.name}" 基数非法: ${r.cardinality}`);
    }
  }

  return errors;
}
