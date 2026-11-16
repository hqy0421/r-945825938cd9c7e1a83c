"""多渠道客户资料归并（entity resolution）流水线，基于 datasketch MinHashLSH。

流程与语义约定
--------------
1. 候选召回：为每份资料的 token 集合构建 MinHash，全部插入同一个
   MinHashLSH，再逐份查询得到候选对（保留 LSH 原生的近似召回含义，
   不做全量两两比对）。
2. 精确确认：对每个候选对，用**原始 token 集合**计算精确 Jaccard，
   >= threshold 才记为一条匹配边。
3. 归并：对所有匹配边做传递连通（并查集连通分量）分组 —— 不是顺序
   扫描时"首个代表"说了算；分组结果与资料输入顺序无关。
4. 主客户 ID = 组内最小资料 ID。
5. 字段级合并：每个字段独立地在组内选取 priority 最大的非空值；
   同优先级时取资料 ID 较小者。只有 None（缺失）算"空"，空字符串 ""
   仍是有效值。
6. 空 token 集合的资料不参与索引与匹配（彼此之间也不匹配），各自成
   为单元素组。

输入约定
--------
profile: {"profile_id": <可比较且可哈希, 非 None>,
          "priority": <数字, 缺省 0>,
          "tokens": [<token>, ...],          # 缺省 []
          "fields": {<字段名>: <值 或 None>}  # 缺省 {}
          }
order:   {"profile_ref": <profile_id 或未知引用>, ...任意其他字段}

profile_id 必须互相可比较（通常全为 str 或全为 int）。
token 在入组前统一 str() 归一化。
"""

from __future__ import annotations

from datasketch import MinHash, MinHashLSH

DEFAULT_THRESHOLD = 0.5
DEFAULT_NUM_PERM = 128


def _norm_tokens(tokens):
    """归一化 token 集合：去 None/空，统一为 str 并去重。"""
    return {str(t) for t in (tokens or [])}


def _exact_jaccard(a: set, b: set) -> float:
    union = len(a | b)
    return len(a & b) / union if union else 0.0


class _UnionFind:
    def __init__(self):
        self._parent = {}

    def find(self, x):
        parent = self._parent.setdefault(x, x)
        if parent != x:
            self._parent[x] = parent = self.find(parent)
        return parent

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


def _validate_profiles(profiles):
    by_id = {}
    for p in profiles:
        pid = p.get("profile_id")
        if pid is None:
            raise ValueError(f"资料缺少 profile_id: {p!r}")
        if pid in by_id:
            raise ValueError(f"profile_id 重复: {pid!r}")
        prio = p.get("priority", 0)
        if not isinstance(prio, (int, float)) or isinstance(prio, bool):
            raise TypeError(f"priority 必须是数字: {pid!r} -> {prio!r}")
        by_id[pid] = p
    return by_id


def find_matches(token_sets, threshold=DEFAULT_THRESHOLD, num_perm=DEFAULT_NUM_PERM):
    """MinHashLSH 候选 + 原始 token 集合精确 Jaccard 确认。

    返回 {(id_a, id_b): jaccard}，id_a < id_b。空 token 集合不参与。
    """
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    minhashes = {}
    for pid, toks in token_sets.items():
        if not toks:
            continue  # 空 tokens：不自动匹配，保留原生近似召回语义
        m = MinHash(num_perm=num_perm)
        for t in toks:
            m.update(t.encode("utf-8"))
        minhashes[pid] = m
        lsh.insert(pid, m)

    edges = {}
    for pid, m in minhashes.items():
        for cand in lsh.query(m):
            if cand == pid:
                continue
            a, b = sorted((pid, cand))
            if (a, b) in edges:
                continue
            j = _exact_jaccard(token_sets[a], token_sets[b])
            if j >= threshold:
                edges[(a, b)] = j
    return edges


def _merge_field(candidates):
    """candidates: [(priority, profile_id, value)]。

    非 None 即有效（空字符串有效）；priority 最大者胜，同优先级取
    资料 ID 较小者；全部缺失返回 None。
    """
    present = [(prio, pid, v) for prio, pid, v in candidates if v is not None]
    if not present:
        return None
    return min(present, key=lambda t: (-t[0], t[1]))[2]


def build_master_table(profiles, threshold=DEFAULT_THRESHOLD, num_perm=DEFAULT_NUM_PERM):
    """归并资料，返回 (master_table, profile_to_master, matches)。

    master_table: [{"master_id", "member_profile_ids", "fields"}]，按 master_id 排序
    profile_to_master: {profile_id: master_id}，覆盖全部资料（含单元素组）
    matches: [{"profile_a", "profile_b", "jaccard"}]，确认过的匹配边，按 (a, b) 排序
    """
    profiles = [dict(p) for p in profiles]
    by_id = _validate_profiles(profiles)
    token_sets = {pid: _norm_tokens(p.get("tokens")) for pid, p in by_id.items()}

    edges = find_matches(token_sets, threshold=threshold, num_perm=num_perm)

    # 传递连通分组（并查集），而非顺序扫描的首个代表
    uf = _UnionFind()
    for pid in by_id:
        uf.find(pid)
    for a, b in edges:
        uf.union(a, b)
    groups = {}
    for pid in by_id:
        groups.setdefault(uf.find(pid), []).append(pid)

    master_table = []
    profile_to_master = {}
    for members in groups.values():
        members.sort()
        master_id = members[0]  # 组内最小资料 ID
        field_names = sorted(
            {fn for pid in members for fn in (by_id[pid].get("fields") or {})}
        )
        fields = {}
        for fn in field_names:
            candidates = [
                (by_id[pid].get("priority", 0), pid, (by_id[pid].get("fields") or {}).get(fn))
                for pid in members
            ]
            fields[fn] = _merge_field(candidates)
        master_table.append(
            {
                "master_id": master_id,
                "member_profile_ids": members,
                "fields": fields,
            }
        )
        for pid in members:
            profile_to_master[pid] = master_id

    master_table.sort(key=lambda row: row["master_id"])
    matches = [
        {"profile_a": a, "profile_b": b, "jaccard": j}
        for (a, b), j in sorted(edges.items())
    ]
    return master_table, profile_to_master, matches


def resolve_orders(orders, profile_to_master, master_table, ref_field="profile_ref"):
    """把订单的 profile_ref 重挂到主客户并附上属性。

    - 输出行数与输入完全一致，顺序不变，不丢行不增行，不修改原 dict。
    - 可解析：profile_ref 改写为 master_id，resolved=True，customer 附
      上主客户属性。
    - 未知引用（含 None）：profile_ref 原样保留，resolved=False，
      customer=None。
    """
    master_by_id = {row["master_id"]: row for row in master_table}
    resolved_orders = []
    for order in orders:
        o = dict(order)
        ref = o.get(ref_field)
        try:
            master_id = profile_to_master.get(ref) if ref is not None else None
        except TypeError:  # 不可哈希的引用值，按未知处理
            master_id = None
        if master_id is None:
            o["resolved"] = False
            o["customer"] = None
        else:
            master = master_by_id[master_id]
            o[ref_field] = master_id
            o["resolved"] = True
            o["customer"] = {"master_id": master_id, **master["fields"]}
        resolved_orders.append(o)
    return resolved_orders
