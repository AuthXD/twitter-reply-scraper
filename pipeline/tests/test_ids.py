"""Snowflake-id comparison must be numeric, not lexicographic."""
import unittest
from reply_pipeline.ids import id_leq, max_id


class TestIds(unittest.TestCase):
    def test_shorter_id_is_smaller_despite_lexicographic_order(self):
        # "999" > "1000" as strings, but 999 < 1000 as numbers.
        self.assertTrue(id_leq("999", "1000"))

    def test_max_id_picks_numerically_largest(self):
        self.assertEqual(max_id(["999", "1000", "12"]), "1000")

    def test_max_id_of_empty_is_none(self):
        self.assertIsNone(max_id([]))

    def test_equal_ids_are_leq(self):
        self.assertTrue(id_leq("1800000000000000000", "1800000000000000000"))

    def test_non_numeric_falls_back_to_string_compare(self):
        self.assertTrue(id_leq("abc", "abd"))


if __name__ == "__main__":
    unittest.main()
