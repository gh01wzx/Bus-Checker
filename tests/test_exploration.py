import unittest
import pandas as pd
from bus_checker.ui.data import heatmap_data, composition


class ChartSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame(
            [
                dict(
                    observation_date="2026-07-06",
                    local_hour=8,
                    route_id="a",
                    sample_count=10,
                    on_time_count=10,
                    late_count=0,
                    early_count=0,
                    total_delay_sec=0,
                ),
                dict(
                    observation_date="2026-07-06",
                    local_hour=8,
                    route_id="b",
                    sample_count=90,
                    on_time_count=0,
                    late_count=60,
                    early_count=30,
                    total_delay_sec=900,
                ),
                dict(
                    observation_date="2026-07-07",
                    local_hour=9,
                    route_id="a",
                    sample_count=1,
                    on_time_count=1,
                    late_count=0,
                    early_count=0,
                    total_delay_sec=0,
                ),
            ]
        )

    def test_heatmap_weights_by_observations_and_masks_missing_and_small_groups(self):
        rates, counts = heatmap_data(self.frame, 10)
        self.assertEqual(rates.loc[0, 8], 10)
        self.assertEqual(counts.loc[0, 8], 100)
        self.assertTrue(pd.isna(rates.loc[1, 9]))
        self.assertTrue(pd.isna(rates.loc[6, 8]))

    def test_composition_reconciles_to_sample_count(self):
        split = composition(self.frame)
        self.assertEqual(
            int(split.Observations.sum()), int(self.frame.sample_count.sum())
        )
        self.assertEqual(
            int(split.loc[split.Status == "Late", "Observations"].iloc[0]), 60
        )


if __name__ == "__main__":
    unittest.main()
