"""演示：多渠道资料归并 + 订单重挂。

运行（在仓库根目录）：
    python -m customer_master.demo
"""

import json

from customer_master.pipeline import build_master_table, resolve_orders

# 三个渠道：crm(priority=3) / web(2) / offline(1)
PROFILES = [
    # Alice：P1~P2 直接匹配(J=0.75)，P3 只与 P2 匹配(J=0.6)，与 P1 仅 0.4
    # —— 靠传递连通进入同一组；枢纽是 P2，但主客户应是最小 ID 的 P1。
    {"profile_id": "P1", "priority": 2,
     "tokens": ["alice", "alice@x.com", "1380001"],
     "fields": {"name": "Alice", "email": "alice@x.com", "phone": None, "city": "Hangzhou"}},
    {"profile_id": "P2", "priority": 3,
     "tokens": ["alice", "alice@x.com", "1380001", "4201"],
     "fields": {"name": "Alice A.", "email": None, "phone": "1380001", "city": None}},
    {"profile_id": "P3", "priority": 1,
     "tokens": ["alice@x.com", "1380001", "4201", "addr1"],
     "fields": {"name": "Alice", "email": "alice@x.com", "phone": "1380001", "city": "HZ"}},
    # 空 tokens：P4、P5 互不匹配，各自单元素组
    {"profile_id": "P4", "priority": 2, "tokens": [],
     "fields": {"name": "Dan"}},
    {"profile_id": "P5", "priority": 3, "tokens": [],
     "fields": {"name": "Dan", "phone": "1350000"}},
    # Bob：P7 的 name 是空字符串 —— 空字符串是有效值，应压过 P6 的 "Bob"
    {"profile_id": "P6", "priority": 2,
     "tokens": ["bob", "bob@y.com"],
     "fields": {"name": "Bob", "email": "bob@y.com"}},
    {"profile_id": "P7", "priority": 3,
     "tokens": ["bob", "bob@y.com"],
     "fields": {"name": "", "email": "bob@y.com", "phone": "1390002"}},
    # Carol：同优先级，字段冲突按较小资料 ID（P8）决定
    {"profile_id": "P8", "priority": 2,
     "tokens": ["carol", "carol@z.com"],
     "fields": {"name": "Carol", "city": "Shanghai"}},
    {"profile_id": "P9", "priority": 2,
     "tokens": ["carol", "carol@z.com"],
     "fields": {"name": "Carol", "city": "SH"}},
]

ORDERS = [
    {"order_id": "O1", "profile_ref": "P2", "amount": 100},
    {"order_id": "O2", "profile_ref": "P3", "amount": 200},
    {"order_id": "O3", "profile_ref": "P9", "amount": 50},
    {"order_id": "O4", "profile_ref": "P_UNKNOWN", "amount": 75},
    {"order_id": "O5", "profile_ref": "P5", "amount": 30},
    {"order_id": "O6", "profile_ref": None, "amount": 10},
]


def main():
    master_table, profile_to_master, matches = build_master_table(PROFILES)
    orders = resolve_orders(ORDERS, profile_to_master, master_table)

    print("=== 主表 ===")
    print(json.dumps(master_table, ensure_ascii=False, indent=2))
    print("\n=== 资料 -> 主客户 映射 ===")
    print(json.dumps(profile_to_master, ensure_ascii=False, indent=2))
    print("\n=== 匹配依据（确认边 + 精确 Jaccard） ===")
    print(json.dumps(matches, ensure_ascii=False, indent=2))
    print("\n=== 订单（重挂后） ===")
    print(json.dumps(orders, ensure_ascii=False, indent=2))
    assert len(orders) == len(ORDERS), "订单行数必须不变"
    print(f"\n订单: {len(ORDERS)} -> {len(orders)} 行（不丢不增）")


if __name__ == "__main__":
    main()
