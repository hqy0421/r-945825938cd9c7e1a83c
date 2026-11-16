"""流水线行为测试。运行（仓库根目录）：
    python -m pytest customer_master/test_pipeline.py -q
或  python -m unittest customer_master.test_pipeline -v
"""

import copy
import random
import unittest

from customer_master.demo import ORDERS, PROFILES
from customer_master.pipeline import build_master_table, resolve_orders

THRESHOLD = 0.5


class BuildMasterTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.master_table, cls.mapping, cls.matches = build_master_table(PROFILES)
        cls.by_master = {m["master_id"]: m for m in cls.master_table}

    def test_transitive_group_not_first_representative(self):
        # P3 只与 P2 直接匹配，靠传递连通进入 {P1,P2,P3}；
        # 枢纽是 P2，但主客户必须是组内最小 ID 的 P1。
        self.assertEqual(self.mapping["P1"], "P1")
        self.assertEqual(self.mapping["P2"], "P1")
        self.assertEqual(self.mapping["P3"], "P1")
        self.assertEqual(self.by_master["P1"]["member_profile_ids"], ["P1", "P2", "P3"])

    def test_match_evidence_exact_jaccard(self):
        edges = {(m["profile_a"], m["profile_b"]): m["jaccard"] for m in self.matches}
        self.assertAlmostEqual(edges[("P1", "P2")], 3 / 4)
        self.assertAlmostEqual(edges[("P2", "P3")], 3 / 5)
        self.assertNotIn(("P1", "P3"), edges)  # 0.4 < 阈值，未确认
        self.assertAlmostEqual(edges[("P6", "P7")], 1.0)
        self.assertAlmostEqual(edges[("P8", "P9")], 1.0)

    def test_empty_tokens_never_match(self):
        # 两个空 token 资料互不匹配，各自单元素组
        self.assertEqual(self.mapping["P4"], "P4")
        self.assertEqual(self.mapping["P5"], "P5")
        for m in self.matches:
            self.assertNotIn(m["profile_a"], ("P4", "P5"))
            self.assertNotIn(m["profile_b"], ("P4", "P5"))

    def test_field_merge_priority_and_none_skipped(self):
        f = self.by_master["P1"]["fields"]
        self.assertEqual(f["name"], "Alice A.")      # P2 priority=3 最大
        self.assertEqual(f["email"], "alice@x.com")  # P2 为 None 被跳过，取 P1(prio 2)
        self.assertEqual(f["phone"], "1380001")      # P2/P3 同值，P2 优先
        self.assertEqual(f["city"], "Hangzhou")      # P1(prio 2) 压过 P3(prio 1)

    def test_empty_string_is_a_valid_value(self):
        # P7(prio 3) 的 name 是 ""，空字符串有效，压过 P6(prio 2) 的 "Bob"
        self.assertEqual(self.by_master["P6"]["fields"]["name"], "")
        self.assertEqual(self.by_master["P6"]["fields"]["phone"], "1390002")

    def test_tie_break_by_smaller_profile_id(self):
        # P8/P9 同 priority=2，city 冲突取较小 ID 的 P8
        self.assertEqual(self.by_master["P8"]["fields"]["city"], "Shanghai")

    def test_mapping_covers_every_profile(self):
        self.assertEqual(set(self.mapping), {p["profile_id"] for p in PROFILES})

    def test_input_order_does_not_change_result(self):
        # 打乱输入顺序，分组/主表/映射/匹配边必须不变（非顺序扫描首个代表）
        for seed in (1, 2, 3):
            shuffled = copy.deepcopy(PROFILES)
            random.Random(seed).shuffle(shuffled)
            mt, mp, ma = build_master_table(shuffled)
            self.assertEqual(mt, self.master_table)
            self.assertEqual(mp, self.mapping)
            self.assertEqual(ma, self.matches)

    def test_duplicate_profile_id_rejected(self):
        with self.assertRaises(ValueError):
            build_master_table([{"profile_id": "X"}, {"profile_id": "X"}])


class ResolveOrdersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.master_table, cls.mapping, _ = build_master_table(PROFILES)
        cls.orders = resolve_orders(ORDERS, cls.mapping, cls.master_table)

    def test_no_rows_lost_or_added_and_order_kept(self):
        self.assertEqual(len(self.orders), len(ORDERS))
        self.assertEqual([o["order_id"] for o in self.orders],
                         [o["order_id"] for o in ORDERS])

    def test_known_refs_repointed_to_master_with_attributes(self):
        o1, o2, o3 = self.orders[0], self.orders[1], self.orders[2]
        self.assertEqual((o1["profile_ref"], o1["resolved"]), ("P1", True))
        self.assertEqual((o2["profile_ref"], o2["resolved"]), ("P1", True))
        self.assertEqual((o3["profile_ref"], o3["resolved"]), ("P8", True))
        self.assertEqual(o1["customer"]["master_id"], "P1")
        self.assertEqual(o1["customer"]["name"], "Alice A.")
        self.assertEqual(o1["customer"]["city"], "Hangzhou")
        self.assertEqual(o1["amount"], 100)  # 原字段保留

    def test_unknown_and_null_refs_stay_unresolved(self):
        o4, o6 = self.orders[3], self.orders[5]
        self.assertEqual((o4["profile_ref"], o4["resolved"]), ("P_UNKNOWN", False))
        self.assertIsNone(o4["customer"])
        self.assertEqual((o6["profile_ref"], o6["resolved"]), (None, False))
        self.assertIsNone(o6["customer"])

    def test_singleton_profile_resolves_to_itself(self):
        o5 = self.orders[4]
        self.assertEqual((o5["profile_ref"], o5["resolved"]), ("P5", True))
        self.assertEqual(o5["customer"]["phone"], "1350000")

    def test_inputs_not_mutated(self):
        self.assertEqual(ORDERS[0]["profile_ref"], "P2")
        self.assertNotIn("customer", ORDERS[0])


if __name__ == "__main__":
    unittest.main()
