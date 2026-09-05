from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from swe_chat_analysis.cli import (
    _packet_fingerprint, _resume_rows, _run_concurrent_jobs,
    build_parser, judge_study1, judge_study2, summarize_study1, summarize_study2,
)
from swe_chat_analysis.io import read_user_prompt_counts, sample_sessions, write_jsonl
from swe_chat_analysis.packet import behavior_episode_prefixes, build_packet, compact_event, packet_as_text
from swe_chat_analysis.study1 import STUDY1_REQUIREMENTS_RUBRIC_VERSION, STUDY1_RUBRIC_VERSION


class StudyOperationsTests(unittest.TestCase):
    def test_continuations_are_context_not_instruction_episodes(self) -> None:
        events = [
            {"turn_number": 0, "turn_type": "user_prompt", "is_continuation": True, "content": "Earlier context"},
            {"turn_number": 1, "turn_type": "user_prompt", "content": "Real instruction"},
        ]
        direct = build_packet({"session_id": "s"}, events)
        compacted = build_packet({"session_id": "s"}, [compact_event(event) for event in events])
        self.assertEqual(direct, compacted)
        self.assertIn("T0 continuation_context:", direct["transcript"])
        self.assertEqual([view[0] for view in behavior_episode_prefixes(direct)], [1])

    def test_clipped_text_is_reported_even_without_dropped_events(self) -> None:
        event = {"turn_number": 0, "turn_type": "user_prompt", "content": "x" * 5000}
        packet = build_packet({"session_id": "s"}, [event])
        self.assertTrue(packet["packet_truncated"])
        self.assertEqual(packet["packet_diagnostics"]["text_clipped_event_count"], 1)
        self.assertEqual(packet, build_packet({"session_id": "s"}, [compact_event(event)]))

    def test_duplicate_turns_receive_unique_auditable_labels(self) -> None:
        packet = build_packet({"session_id": "s"}, [
            {"turn_number": 2, "turn_type": "user_prompt", "content": "one"},
            {"turn_number": 2, "turn_type": "user_prompt", "content": "two"},
        ])
        self.assertTrue(packet["packet_diagnostics"]["turn_numbers_reindexed"])
        self.assertEqual([view[0] for view in behavior_episode_prefixes(packet)], [0, 1])

    def test_commit_costs_deduplicated_and_hidden_from_judge(self) -> None:
        commit = {"commit_sha": "abc", "total_deletions": 7}
        packet = build_packet({"session_id": "s", "checkpoint_ids": ["a", "b"], "agent_percentage": 99}, [], {"a": [commit], "b": [commit]})
        self.assertEqual(packet["session"]["observed_costs"]["linked_commit_deletions"], 7)
        self.assertNotIn("agent_percentage", packet_as_text(packet))

    def test_real_prompt_filter_is_applied_before_sampling(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pq.write_table(pa.Table.from_pylist([
                {"session_id": "valid", "prompt_count": 2},
                {"session_id": "missing", "prompt_count": 2},
            ]), root / "sessions.parquet")
            pq.write_table(pa.Table.from_pylist([
                {"session_id": "valid", "turn_type": "user_prompt", "is_continuation": False},
                {"session_id": "valid", "turn_type": "user_prompt", "is_continuation": False},
                {"session_id": "missing", "turn_type": "user_prompt", "is_continuation": True},
            ]), root / "conversations.parquet")
            counts = read_user_prompt_counts(root / "conversations.parquet")
            rows = sample_sessions(root / "sessions.parquet", 1, 42, prompt_counts=counts)
            self.assertEqual([row["session_id"] for row in rows], ["valid"])

    def test_resume_requires_matching_input_model_and_version(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "annotations.jsonl"
            base = {"session_id": "s", "rubric_version": "v", "model": "model", "input_fingerprint": "hash"}
            write_jsonl(path, [base, base, {**base, "input_fingerprint": "old"}, {**base, "model": "other"}])
            rows = _resume_rows(path, {"s"}, lambda row: row["session_id"], set(), True, "v", {"s": "hash"}, "model")
            self.assertEqual(rows, [base])

    def test_concurrent_scheduler_does_not_eagerly_consume_generator(self) -> None:
        consumed = []

        def jobs():
            for number in range(30):
                consumed.append(number)
                yield number

        results = _run_concurrent_jobs(jobs(), lambda value: value, workers=3)
        next(results)
        self.assertEqual(len(consumed), 3)
        self.assertEqual(len(list(results)), 29)

    def test_study1_incomplete_behavior_and_duplicate_rows_are_visible(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            packet = build_packet({"session_id": "s"}, [
                {"turn_number": 0, "turn_type": "user_prompt", "content": "first"},
                {"turn_number": 2, "turn_type": "user_prompt", "content": "second"},
            ])
            write_jsonl(root / "packets.jsonl", [packet])
            base = {"session_id": "s", "input_fingerprint": _packet_fingerprint(packet), "annotation": {"task_threads": []}}
            requirement = {**base, "rubric_version": STUDY1_REQUIREMENTS_RUBRIC_VERSION}
            write_jsonl(root / "requirement_annotations.jsonl", [requirement, requirement])
            write_jsonl(root / "behavior_annotations.jsonl", [{**base, "rubric_version": STUDY1_RUBRIC_VERSION, "instruction_turn": 0}])
            summarize_study1(argparse.Namespace(output_dir=directory))
            result = json.loads((root / "summary.json").read_text())["run_completeness"]
            self.assertEqual(result["requirement_annotated_session_count"], 1)
            self.assertEqual(result["pending_or_failed_behavior_episode_count"], 1)
            self.assertEqual(result["annotated_session_count"], 0)

    def test_all_failed_study2_still_writes_completeness(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_jsonl(root / "packets.jsonl", [build_packet({"session_id": "s"}, [])])
            summarize_study2(argparse.Namespace(output_dir=directory))
            summary = json.loads((root / "summary.json").read_text())
            self.assertEqual(summary["run_completeness"]["pending_or_failed_session_count"], 1)
            self.assertIsNone(summary["material_instruction_reality_mismatch_rate"]["estimate"])

    def test_both_judges_complete_and_resume_without_duplicate_requests(self) -> None:
        for study, judge, summarize in ((1, judge_study1, summarize_study1), (2, judge_study2, summarize_study2)):
            with self.subTest(study=study), TemporaryDirectory() as directory:
                root = Path(directory)
                packet = build_packet({"session_id": "s"}, [
                    {"turn_number": 0, "turn_type": "user_prompt", "content": "first"},
                    {"turn_number": 2, "turn_type": "user_prompt", "content": "second"},
                ])
                write_jsonl(root / "packets.jsonl", [packet])
                args = build_parser().parse_args([f"judge-study{study}", "--output-dir", directory, "--workers", "2"])
                with patch("swe_chat_analysis.cli._study_client", return_value=(object(), "test-model")), patch(
                    "swe_chat_analysis.cli._complete_validated_json", return_value=({"task_threads": []}, {})
                ) as complete:
                    judge(args)
                    judge(args)
                    self.assertEqual(complete.call_count, 3 if study == 1 else 1)
                summarize(args)
                summary = json.loads((root / "summary.json").read_text())
                self.assertEqual(summary["run_completeness"]["completion_rate"], 1)


if __name__ == "__main__":
    unittest.main()
