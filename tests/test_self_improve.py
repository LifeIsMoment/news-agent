import unittest

import self_improve


class SelfImproveTests(unittest.TestCase):
    def test_global_patch_is_exact_and_idempotent(self):
        source = '''            combined = f"{title} {summary} {url}"
            if not brand_relevant(combined, url, brand_cfg):
                continue
'''
        patched, changed = self_improve.patch_global_filter(source)
        self.assertTrue(changed)
        self.assertIn(self_improve.GLOBAL_FILTER_MARKER, patched)
        patched_again, changed_again = self_improve.patch_global_filter(patched)
        self.assertFalse(changed_again)
        self.assertEqual(patched, patched_again)

    def test_regulatory_patch_is_exact_and_idempotent(self):
        source = '''        category = "TAXiA·CLOA" if is_brand else classify_category(combined)
        score, importance = calculate_importance(
'''
        patched, changed = self_improve.patch_regulatory_filter(source)
        self.assertTrue(changed)
        self.assertIn(self_improve.REGULATORY_FILTER_MARKER, patched)
        patched_again, changed_again = self_improve.patch_regulatory_filter(patched)
        self.assertFalse(changed_again)
        self.assertEqual(patched, patched_again)


if __name__ == "__main__":
    unittest.main()
