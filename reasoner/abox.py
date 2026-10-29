"""ABox 事务层：断言级增删改 + 增量持久化（框架能力，领域无关）。

这些能力此前躺在领域适配器里（`examples/agent_task/adapter.py` 约 205 行），
但只用到引擎原语与 rdflib，没有任何领域词汇——除了几个"哪些谓词算引用"
的业务判断。P1-2 把它们上移到这里，业务谓词由领域在构造时传入。

分层边界：
    框架负责   事务性（先全量校验再应用）、内存/落盘一致性、原子写、
               变更计数与 changelog、reload 可恢复的增量文件命名
    领域负责   校验什么算合法（capabilities 是否存在于本体）、
               哪些谓词构成引用（reference_predicates）、
               导入时生成哪些断言（planner 回调）

因此本模块**不猜业务**：delete 不知道什么是"任务"，import 不知道什么是
"能力类"，它只保证"要么全成、要么全不成"。

增量文件协议（与 reasoner.engine 的 extensions/ 加载对应）：
    YYYYMMDD-HHMMSS-<op>-<name>.ttl       新增/修改断言
    YYYYMMDD-HHMMSS-del-<op>-<name>.ttl   删除断言（reload 时反向移除）
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Callable, Iterable, Sequence

from rdflib import Graph, Literal, RDF, URIRef

from reasoner.engine import local

__all__ = ["AboxStore"]


class AboxStore:
    """一个领域适配器的 ABox 事务状态（变更计数 / changelog / 增量落盘）。

    参数：
        engine                OntologyEngine（或其等价实现：需要 g / raw /
                              NS / extensions_dir / add_type / add_triple /
                              add_literal / remove_triples / reparse）
        resolve_predicate     语义键 → 属性 IRI 的解析函数（领域提供，通常是
                              适配器的 `_p`）。缺省则把键名当作短名处理。
        reference_predicates  被视为"引用"的属性短名/键名：删除个体时被这些
                              属性的入边引用即拒绝（除非 cascade）
        assignment_predicate  "分配"关系属性：revoke 移除的就是它
        operator              changelog 里的操作者标识（002 批次接入真实身份）
        clock                 注入时间源，便于测试确定化
    """

    def __init__(
        self,
        engine: Any,
        *,
        resolve_predicate: Callable[[str], Any] | None = None,
        reference_predicates: Sequence[str] = (),
        assignment_predicate: str | None = None,
        operator: str = "ontology-service",
        clock: Callable[[], datetime] = datetime.now,
    ):
        self.engine = engine
        self.NS = engine.NS
        self._resolve = resolve_predicate or (lambda key: self.NS[key])
        self.reference_predicates = tuple(reference_predicates)
        self.assignment_predicate = assignment_predicate
        self.operator = operator
        self._clock = clock

        # 未提交变更数（persist 成功后归零）/ 变更记录 / 最近落盘路径
        self.change_count = 0
        self.changelog: list[dict] = []
        self.last_commit: str | None = None

    # ------------------------------------------------------------ 谓词与三元组

    def _p(self, key: str) -> URIRef:
        return self._resolve(key)

    @staticmethod
    def _pname(p: Any) -> str:
        """三元组里的谓词 → 引擎要的短名（URIRef 取 short name）。"""
        return local(p) if isinstance(p, URIRef) else str(p)

    def apply_triples(self, triples: Iterable[tuple]) -> None:
        """把 (主语, 谓词, 宾语) 断言写进引擎（不推理、不落盘）。

        主语/宾语可给短名或 IRI，谓词可给短名 / 语义键 / URIRef——
        同一个三元组清单既用于内存应用，也用于增量落盘，避免两处各写一遍
        而悄悄漂移（这是原实现里真实存在的重复）。
        """
        for s, p, o in triples:
            subject = local(s) if isinstance(s, URIRef) else str(s)
            prop = self._pname(p)
            if prop == "type":
                # 类型断言：宾语可能是类短名或类 IRI，统一交给 add_type（短名）
                self.engine.add_type(subject, local(o))
            elif isinstance(o, bool) or (isinstance(o, int) and not isinstance(o, str)):
                self.engine.add_literal(subject, prop, o)
            elif isinstance(o, URIRef):
                self.engine.add_triple(subject, prop, local(o))
            else:
                self.engine.add_triple(subject, prop, str(o))

    # ------------------------------------------------------------ 变更记录与落盘

    def note_change(self, op: str, detail: dict, persisted: dict | None) -> None:
        """记录变更（dirty 计数 + changelog）；persist 成功后 pending 计数归零。"""
        self.change_count += 1
        self.changelog.append({
            "time": self._clock().isoformat(timespec="seconds"),
            "op": op,
            "operator": self.operator,
            "detail": detail,
        })
        if persisted:
            self.change_count = 0
            self.last_commit = persisted["path"]

    def write_increment(self, op: str, name: str, triples: list, is_del: bool = False) -> dict:
        """将断言级增量写为扩展 ttl 文件（原子：临时文件 + rename）。

        序列化源 = 本次操作的断言参数（不依赖图 diff，天然排除推理物化噪音）；
        is_del=True 时文件名带 -del-，reload 时反向移除其中三元组。
        写入失败不影响内存状态（已生效变更回退为"未持久化"并抛错）。
        """
        exts = self.engine.extensions_dir
        if not exts:
            raise ValueError("persist=true 需要引擎启用 extensions/ 扩展目录（本体同目录建 extensions/）")
        os.makedirs(exts, exist_ok=True)
        g = Graph()
        for s, p, o in triples:
            subj = URIRef(s) if str(s).startswith("http") else self.NS[str(s)]
            pred = p if isinstance(p, URIRef) else self._p(str(p))
            if isinstance(o, Literal):
                obj = o
            elif isinstance(o, bool) or isinstance(o, int):
                obj = Literal(o)
            elif isinstance(o, URIRef):
                obj = o
            elif str(o).startswith("http"):
                obj = URIRef(o)
            else:
                obj = self.NS[str(o)]
            g.add((subj, pred, obj))
        ts = self._clock().strftime("%Y%m%d-%H%M%S")
        marker = "-del-" if is_del else "-"
        path = os.path.join(exts, f"{ts}{marker}{op}-{name}.ttl")
        tmp = path + ".tmp"
        g.serialize(destination=tmp, format="turtle")
        os.replace(tmp, path)                # 原子替换（无半文件）
        return {"path": path, "triples": len(triples)}

    # ------------------------------------------------------------ ABox 操作

    def delete(
        self,
        name: str,
        *,
        persist: bool = False,
        cascade: bool = False,
        on_deleted: Callable[[str], None] | None = None,
        after_reparse: Callable[[], None] | None = None,
    ) -> dict:
        """删除个体（A-box 断言：类型/属性/数据）。

        引用保护：被 reference_predicates 入边引用时拒绝（cascade=true 连带清理）。
        推理入边（required_by / can_execute 等）**始终**一并删除——否则 reparse
        时推理器会借这些边重新推出已删断言（实测证实）；持久化快照仅含 A-box
        断言（reload 后推理边随个体消失自然清理）。

        on_deleted  领域清理自身缓存（分配缓存 / R2 断言集合）的钩子
        after_reparse 重推理后的钩子（领域重放业务规则，如 R2）
        """
        engine = self.engine
        iri = self.NS[name]
        if (iri, None, None) not in engine.g:
            raise ValueError(f"个体不存在: {name}")

        biz = [self._p(key) for key in self.reference_predicates]
        ref = [(local(s), local(p)) for s, p, o in engine.g if o == iri and p in biz]
        if ref and not cascade:
            raise ValueError(
                f"「{name}」被 {len(ref)} 处引用不可删除"
                f"（来源: {ref[:3]}；如需连带清理请用 cascade=true）"
            )

        # 快照（持久化用，仅 A-box 断言）：出边 + cascade 业务反边
        del_triples: list = []
        for s, p, o in list(engine.g.triples((iri, None, None))):
            del_triples.append((local(s), p, local(o) if isinstance(o, URIRef) else o))
        if cascade:
            for s, p, o in list(engine.g.triples((None, None, iri))):
                if p in biz:
                    del_triples.append((local(s), p, local(o)))

        # 内存删除：出边 + 全部入边（业务边与推理边，g 与 raw 同步；raw 无对应时 no-op）
        for s, p, o in list(engine.g.triples((iri, None, None))):
            engine.g.remove((s, p, o))
            engine.raw.remove((s, p, o))
        for s, p, o in list(engine.g.triples((None, None, iri))):
            engine.g.remove((s, p, o))
            engine.raw.remove((s, p, o))

        if on_deleted:
            on_deleted(name)

        engine.reparse()                     # 推理边（can_execute 等）随个体消失自动清理
        if after_reparse:
            after_reparse()

        persisted = self.write_increment("del", name, del_triples, is_del=True) if persist else None
        self.note_change("delete", {"individual": name, "cascade": cascade}, persisted)
        return {"individual": name, "deleted": True, "removed_triples": len(del_triples),
                "cascade": cascade, "persisted": persisted}

    def revoke(
        self,
        task: str,
        agent: str,
        *,
        persist: bool = False,
        on_revoked: Callable[[str], None] | None = None,
    ) -> dict:
        """撤回一条分配关系（移除 assignment_predicate 边）。"""
        if not self.assignment_predicate:
            raise ValueError("未配置 assignment_predicate，无法撤回分配")
        a_pred = self._p(self.assignment_predicate)
        if (self.NS[task], a_pred, self.NS[agent]) not in self.engine.g:
            raise ValueError(f"不存在分配: {task} → {agent}")
        self.engine.remove_triples(task, self._pname(a_pred), agent)
        if on_revoked:
            on_revoked(task)

        persisted = None
        if persist:
            persisted = self.write_increment("revoke", task, [(task, a_pred, agent)], is_del=True)
        self.note_change("revoke", {"task": task, "agent": agent}, persisted)
        return {"task": task, "agent": agent, "revoked": True, "persisted": persisted}

    def import_individuals(
        self,
        items: list,
        *,
        planner: Callable[[list], tuple[list[tuple], list[str]]],
        persist: bool = False,
        op: str = "import",
        after_reparse: Callable[[], None] | None = None,
    ) -> dict:
        """批量导入（事务：先全量校验 → 全部通过才应用 → 一次推理 → 一次落盘）。

        planner(items) 由领域提供，返回 (三元组清单, 个体名清单)；
        它抛异常即整体拒绝，此时内存与磁盘都不留半套数据。
        空列表视为无操作：不 reparse、不写 changelog、不置 dirty（issue #7）。
        """
        if not items:
            return {"imported": 0, "individuals": [], "persisted": None}

        triples, names = planner(items)       # 校验阶段：任何一条不合格都抛错
        self.apply_triples(triples)
        self.engine.reparse()                 # 一次推理（事务整体）
        if after_reparse:
            after_reparse()

        persisted = None
        if persist:
            persisted = self.write_increment(op, f"batch{len(names)}", triples)
        self.note_change(op, {"count": len(names), "names": names}, persisted)
        return {"imported": len(names), "individuals": names, "persisted": persisted}
