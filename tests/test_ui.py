import time
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.community_service import CommunityFetch
from test_proximity import community


class UITests(unittest.TestCase):
    def app(self, fetched):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "streamlit_app.py"))
        app.session_state["community_fetch"] = fetched
        app.session_state["community_fetch_time"] = time.time()
        return app.run(timeout=30)

    def test_sample_and_table(self):
        app = self.app(CommunityFetch(communities=[community()]))
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["fire"]["fire_id"], "2024:PWF076")
        self.assertIsNone(app.session_state["fire"]["hazard_score"])
        self.assertEqual(len(app.dataframe), 1)
        self.assertEqual(app.dataframe[0].value.iloc[0]["Community"], "Example")
        app.number_input[0].set_value(91)
        app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertGreater(len(app.error), 0)

    def test_failure_keeps_fire_map(self):
        app = self.app(CommunityFetch(errors=["City: unavailable"]))
        self.assertEqual(len(app.exception), 0)
        self.assertGreater(len(app.warning), 0)
        self.assertGreater(len(app.info), 0)


if __name__ == "__main__":
    unittest.main()
