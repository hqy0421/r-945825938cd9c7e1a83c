# customer_master — 多渠道客户资料归并

基于 `datasketch` 的 MinHashLSH 做候选召回、原始 token 集合精确 Jaccard 做确认，
按匹配关系的传递连通组归并资料，产出统一主表，并把订单重挂到主客户。

## 输入格式

资料（JSON 数组或 JSONL，每行一份）：

```json
{"profile_id": "P1", "priority": 2,
 "tokens": ["alice", "alice@x.com", "1380001"],
 "fields": {"name": "Alice", "email": "alice@x.com", "phone": null}}
```

- `profile_id`：必填，不可重复，互相可比较（全 str 或全 int）。
- `priority`：渠道优先级，数字，越大越权威，缺省 0。
- `tokens`：用于匹配的 token 集合，缺省 `[]`；内部统一 `str()` 归一化去重。
- `fields`：属性字段，缺省 `{}`；`null` 表示缺失。

订单：`{"profile_ref": "<profile_id 或未知引用>", ...任意其他字段}`。

## 归并语义

1. **候选召回**：全部非空 token 资料建 MinHash 插入同一个 `MinHashLSH`，
   逐份查询得候选对 —— 保留 LSH 原生近似召回，不做全量两两比对。
2. **精确确认**：候选对用原始 token 集合算精确 Jaccard，`>= threshold`
   （默认 0.5）才记为匹配边。
3. **传递连通分组**：并查集连通分量，结果与资料输入顺序无关 —— 不是
   顺序扫描时"首个代表"归并。
4. **主客户 ID** = 组内最小资料 ID。
5. **字段合并**：每字段独立取 priority 最大的非空值；同优先级取较小
   资料 ID。只有 `None` 算空，空字符串 `""` 是有效值。
6. **空 tokens**：不参与索引与匹配（彼此也不匹配），各自成单元素组。

## 输出

`build_master_table(profiles, threshold=0.5, num_perm=128)` 返回三元组：

- `master_table`：`[{master_id, member_profile_ids, fields}]`，按 master_id 排序
- `profile_to_master`：`{profile_id: master_id}`，覆盖全部资料
- `matches`：`[{profile_a, profile_b, jaccard}]`，确认过的匹配边（匹配依据）

`resolve_orders(orders, profile_to_master, master_table)`：

- 行数与输入完全一致、顺序不变、不改原 dict；
- 可解析：`profile_ref` 改写为 master_id，`resolved=True`，`customer` 附主客户属性；
- 未知引用（含 `null`）：`profile_ref` 原样保留，`resolved=False`，`customer=None`。

## 运行

```bash
# 演示（内置样例数据）
python -m customer_master.demo

# 测试
python -m unittest customer_master.test_pipeline -v

# 自己的数据
python -m customer_master.run --profiles profiles.jsonl --orders orders.jsonl \
    --out-dir out --threshold 0.5 --num-perm 128
```

CLI 在 `--out-dir` 下写出 `master_table.json`、`profile_mapping.json`、
`matches.json`、`orders_enriched.json`。
