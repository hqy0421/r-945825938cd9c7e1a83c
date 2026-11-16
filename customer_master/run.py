"""命令行入口：从 JSON/JSONL 读资料与订单，输出归并结果。

用法（仓库根目录）：
    python -m customer_master.run --profiles profiles.jsonl --orders orders.jsonl \
        --out-dir out [--threshold 0.5] [--num-perm 128]

输出到 --out-dir：
    master_table.json      主表
    profile_mapping.json   资料 -> 主客户映射
    matches.json           匹配依据（确认边 + 精确 Jaccard）
    orders_enriched.json   重挂后的订单（行数与输入一致）
"""

import argparse
import json
import os

from customer_master.pipeline import (
    DEFAULT_NUM_PERM,
    DEFAULT_THRESHOLD,
    build_master_table,
    resolve_orders,
)


def _read_records(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        return []
    if path.endswith(".jsonl"):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError(f"{path} 应是 JSON 数组或 JSONL")
    return data


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    ap = argparse.ArgumentParser(description="多渠道客户资料归并 + 订单重挂")
    ap.add_argument("--profiles", required=True, help="资料文件 (.json 数组 / .jsonl)")
    ap.add_argument("--orders", required=True, help="订单文件 (.json 数组 / .jsonl)")
    ap.add_argument("--out-dir", required=True, help="输出目录")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help=f"Jaccard 确认阈值（默认 {DEFAULT_THRESHOLD}）")
    ap.add_argument("--num-perm", type=int, default=DEFAULT_NUM_PERM,
                    help=f"MinHash 排列数（默认 {DEFAULT_NUM_PERM}）")
    args = ap.parse_args()

    profiles = _read_records(args.profiles)
    orders = _read_records(args.orders)

    master_table, profile_to_master, matches = build_master_table(
        profiles, threshold=args.threshold, num_perm=args.num_perm
    )
    resolved = resolve_orders(orders, profile_to_master, master_table)
    assert len(resolved) == len(orders), "订单行数必须不变"

    os.makedirs(args.out_dir, exist_ok=True)
    _write_json(os.path.join(args.out_dir, "master_table.json"), master_table)
    _write_json(os.path.join(args.out_dir, "profile_mapping.json"), profile_to_master)
    _write_json(os.path.join(args.out_dir, "matches.json"), matches)
    _write_json(os.path.join(args.out_dir, "orders_enriched.json"), resolved)

    n_resolved = sum(1 for o in resolved if o["resolved"])
    print(f"资料 {len(profiles)} 份 -> 主客户 {len(master_table)} 个；"
          f"确认匹配边 {len(matches)} 条")
    print(f"订单 {len(orders)} 行 -> {len(resolved)} 行；"
          f"已解析 {n_resolved}，未解析 {len(resolved) - n_resolved}")
    print(f"输出目录: {args.out_dir}")


if __name__ == "__main__":
    main()
