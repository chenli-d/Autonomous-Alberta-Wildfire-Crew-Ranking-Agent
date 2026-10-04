import copy
import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.review_service import load_allocation_context, attach_allocation_context, select_review_candidates
from app.ranking_service import load_rankings
import test_ui as ui_fixtures


def fire(rank, distance=None, H=10, cut=8, identifier=None):
    return {"fire_id": identifier or f"fire:{rank}", "rank": rank+100, "rf_probability": .5,
            "allocation_rank": rank, "status": "kept" if rank <= cut else "displaced" if rank <= H else "no_crew",
            "nearest_community": "Example" if distance is not None else None,
            "nearest_community_distance_km": distance, "y":1, "CURRENT_SIZE":500,
            "future_outcome":"secret"}


class ReviewTests(unittest.TestCase):
    def test_rules_order_no_mutation_and_safety(self):
        records = [fire(8, .1),fire(9,10),fire(10,12),fire(11,3),fire(12,1)]
        before = copy.deepcopy(records)
        result = select_review_candidates(records,10,8)
        self.assertEqual([r["allocation_rank"] for r in result], [8,9,10,12,11])
        self.assertEqual([r["review_reason"] for r in result], [["last_kept"],["cutoff_boundary"],["cutoff_boundary"],["proximity_exception"],["proximity_exception"]])
        self.assertEqual(records, before)
        self.assertEqual([r["rank"] for r in result], [108,109,110,112,111])
        self.assertTrue(all(not {"y","CURRENT_SIZE","future_outcome"}.intersection(r) for r in result))

    def test_overlap_and_distance_ties(self):
        result = select_review_candidates([fire(8),fire(9,0,identifier="B"),fire(10,0,identifier="A"),fire(11,4)],10,8)
        self.assertEqual(len(result),3)
        self.assertEqual(result[1]["review_reason"], ["cutoff_boundary","proximity_exception"])
        self.assertEqual(result[2]["review_reason"], ["cutoff_boundary","proximity_exception"])
        result = select_review_candidates([fire(11,0,identifier="Z"),fire(12,0,identifier="B"),fire(13,0,identifier="A")],10,8)
        self.assertEqual([r["fire_id"] for r in result], ["A","B"])

    def test_missing_invalid_distances_and_short_boundaries(self):
        result = select_review_candidates([fire(8),fire(9,float("nan")),fire(11,-1),fire(12,float("inf")),fire(13,2)],10,8)
        self.assertEqual([r["allocation_rank"] for r in result], [8,9,13])
        self.assertEqual(select_review_candidates([],10,8),[])
        self.assertEqual(len(select_review_candidates([fire(1,cut=1)],1,1)),1)
        self.assertEqual(select_review_candidates([fire(1,cut=4)],5,4),[])
        zero = select_review_candidates([fire(1,1,H=0,cut=0),fire(2,None,H=0,cut=0)],0,0)
        self.assertEqual([r["review_reason"] for r in zero], [["cutoff_boundary","proximity_exception"],["cutoff_boundary"]])

    def test_validation(self):
        for H, cut in [(1,2),(-1,0),(True,0),(3,1.5)]:
            with self.assertRaises(ValueError):
                select_review_candidates([],H,cut)
        with self.assertRaises(ValueError):
            select_review_candidates([fire(8),fire(8)],10,8)
        with self.assertRaises(ValueError):
            attach_allocation_context([fire(8)],{"allocations":{}})

    def test_context_loader(self):
        with tempfile.TemporaryDirectory() as folder:
            allocation, metadata = Path(folder)/"allocation.csv", Path(folder)/"metrics.json"
            with allocation.open("w",newline="") as file:
                writer=csv.DictWriter(file,fieldnames=["fire_id","rank","status","y","CURRENT_SIZE"])
                writer.writeheader()
                for rank in range(1,5):
                    record=fire(rank,H=3,cut=1)
                    writer.writerow({key: record[key] for key in ("fire_id","status","y","CURRENT_SIZE")} | {"rank":rank})
            metadata.write_text(json.dumps({"allocation_date":"2024-07-16","H":3,"H_cut":1,"allocation_large":999}),encoding="utf-8")
            context=load_allocation_context(allocation,metadata)
            self.assertEqual(set(context), {"allocation_date","H","H_cut","allocations"})
            self.assertTrue(all(set(row)=={"allocation_rank","status"} for row in context["allocations"].values()))
            with self.assertRaises(ValueError):
                load_allocation_context(allocation,metadata,date(2024,7,17))
            metadata.write_text(json.dumps({"allocation_date":"2024-07-16","H":3,"H_cut":2}),encoding="utf-8")
            with self.assertRaises(ValueError):
                load_allocation_context(allocation,metadata)

    def test_current_real_context_and_boundary_candidates(self):
        root=Path(__file__).resolve().parents[1]
        rows,_=load_rankings(root/"outputs/dev_recent/ranking_2024.csv",root/"data/raw/fp-historical-wildfire-data-2006-2025.csv")
        context=load_allocation_context(root/"outputs/dev_recent/allocation_2024-07-16.csv",root/"outputs/dev_recent/metrics.json")
        snapshot=copy.deepcopy(rows)
        result=select_review_candidates(attach_allocation_context(rows,context),context["H"],context["H_cut"])
        self.assertEqual([r["fire_id"] for r in result], ["2024:LWF156","2024:LWF140","2024:RWF050"])
        self.assertEqual([r["rank"] for r in result],[107,108,109])
        self.assertEqual(rows,snapshot)


class ReviewUITests(unittest.TestCase):
    run_app=ui_fixtures.UITests.run_app

    def test_review_section_and_proximity_failure_boundary_fallback(self):
        rows,_=ui_fixtures.join_rankings([ui_fixtures.ranking()], [ui_fixtures.official()])
        context={"H":10,"H_cut":8,"allocation_date":"2024-07-16", "allocations":{"2024:TEST":{"allocation_rank":8,"status":"kept"}}}
        with patch("app.review_service.load_allocation_context",return_value=context):
            app=self.run_app(rows)
        self.assertEqual(len(app.exception),0)
        self.assertIn("Crew-cut review candidates",[h.value for h in app.subheader])
        table=app.dataframe[1].value
        self.assertEqual(table.iloc[0]["Review reasons"],"last_kept")
        self.assertEqual(table.iloc[0]["Annual RF rank"],21)
        self.assertEqual(table.iloc[0]["Daily allocation RF rank"],8)
        self.assertNotIn("y",table.columns)
        self.assertNotIn("CURRENT_SIZE",repr(table.to_dict()))
        from app.community_service import CommunityFetch
        app.session_state["community_point_fetch"] = CommunityFetch(errors=["Community source unavailable"])
        with patch("app.ranking_service.load_rankings",return_value=(rows,{"unmatched":0,"invalid_dates":0})), patch("app.review_service.load_allocation_context",return_value=context):
            app.run(timeout=30)
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.dataframe[1].value.iloc[0]["Review reasons"],"last_kept")
        self.assertEqual(app.dataframe[1].value.iloc[0]["Distance (km)"],"N/A")

    def test_missing_context_keeps_fire_ui(self):
        rows,_=ui_fixtures.join_rankings([ui_fixtures.ranking()], [ui_fixtures.official()])
        with patch("app.review_service.load_allocation_context",side_effect=OSError("Missing context")):
            app=self.run_app(rows)
        self.assertEqual(len(app.exception),0)
        self.assertTrue(any("Review shortlist unavailable" in warning.value for warning in app.warning))
        self.assertIn("Fire details: 2024:TEST",[h.value for h in app.subheader])


if __name__ == "__main__":
    unittest.main()
