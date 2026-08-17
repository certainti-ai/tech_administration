"""Audit records — written on every outcome, never carrying credentials."""

import json

import pytest

from trd365_core.audit import (
    AuditedRun,
    JsonlAuditSink,
    MemoryAuditSink,
    read_records,
    redact_arguments,
)
from trd365_core.environments import Environment


class TestRedaction:
    def test_credential_shaped_keys_are_replaced(self):
        cleaned = redact_arguments(
            {"account_id": "A-1", "password": "hunter2", "ssh_password": "x", "api_token": "t"}
        )
        assert cleaned["account_id"] == "A-1"
        assert cleaned["password"] == "***"
        assert cleaned["ssh_password"] == "***"
        assert cleaned["api_token"] == "***"

    def test_matching_is_case_insensitive(self):
        assert redact_arguments({"DB_PASSWORD": "x"})["DB_PASSWORD"] == "***"

    def test_ordinary_arguments_survive(self):
        assert redact_arguments({"chunk_size": 500}) == {"chunk_size": 500}


class TestAuditedRun:
    def test_success_is_recorded(self):
        sink = MemoryAuditSink()
        with AuditedRun("purge-account", Environment.DEV, applied=True, sink=sink) as run:
            run.record_rows("trd365_00042.project", 3)

        record = sink.records[0]
        assert record.outcome == "success"
        assert record.applied is True
        assert record.mode == "apply"
        assert record.environment == "dev"
        assert record.rows_affected == {"trd365_00042.project": 3}
        assert record.finished_at is not None

    def test_failure_is_recorded_and_the_exception_still_propagates(self):
        sink = MemoryAuditSink()
        with (
            pytest.raises(ValueError),
            AuditedRun("purge-account", Environment.PROD, applied=True, sink=sink),
        ):
            raise ValueError("constraint violation")

        record = sink.records[0]
        assert record.outcome == "failed"
        assert "ValueError: constraint violation" in record.error

    def test_cancellation_is_distinguished_from_failure(self):
        # A purge interrupted halfway is exactly the run you need a record of.
        sink = MemoryAuditSink()
        with (
            pytest.raises(KeyboardInterrupt),
            AuditedRun("purge-account", Environment.PROD, applied=True, sink=sink) as run,
        ):
            run.record_rows("trd365_00042.project", 5)
            raise KeyboardInterrupt

        record = sink.records[0]
        assert record.outcome == "cancelled"
        assert record.rows_affected == {"trd365_00042.project": 5}

    def test_row_counts_accumulate_per_table(self):
        sink = MemoryAuditSink()
        with AuditedRun("purge", Environment.DEV, applied=True, sink=sink) as run:
            run.record_rows("s.project", 2)
            run.record_rows("s.project", 3)
            run.record_rows("s.task", 1)
            assert run.total_rows == 6
        assert sink.records[0].rows_affected == {"s.project": 5, "s.task": 1}

    def test_arguments_are_redacted_before_they_reach_the_sink(self):
        sink = MemoryAuditSink()
        with AuditedRun(
            "purge", Environment.DEV, applied=False, arguments={"password": "hunter2"}, sink=sink
        ):
            pass
        assert sink.records[0].arguments == {"password": "***"}

    def test_dry_runs_are_recorded_too(self):
        sink = MemoryAuditSink()
        with AuditedRun("purge", Environment.PROD, applied=False, sink=sink):
            pass
        assert sink.records[0].mode == "dry-run"

    def test_actor_defaults_but_can_be_supplied(self):
        sink = MemoryAuditSink()
        with AuditedRun("purge", Environment.DEV, applied=False, actor="alice", sink=sink):
            pass
        assert sink.records[0].actor == "alice"

        with AuditedRun("purge", Environment.DEV, applied=False, sink=sink):
            pass
        assert sink.records[1].actor

    def test_each_run_gets_its_own_id(self):
        sink = MemoryAuditSink()
        for _ in range(2):
            with AuditedRun("purge", Environment.DEV, applied=False, sink=sink):
                pass
        assert sink.records[0].run_id != sink.records[1].run_id


class TestJsonlSink:
    def test_appends_one_line_per_run(self, tmp_path):
        path = tmp_path / "nested" / "runs.jsonl"
        sink = JsonlAuditSink(path)

        for name in ("first", "second"):
            with AuditedRun(name, Environment.DEV, applied=False, sink=sink):
                pass

        lines = path.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["utility"] == "first"

    def test_records_round_trip(self, tmp_path):
        path = tmp_path / "runs.jsonl"
        sink = JsonlAuditSink(path)
        with AuditedRun("purge", Environment.STAGE, applied=True, sink=sink) as run:
            run.record_rows("s.t", 7)
            run.note("chunked in 3 batches")

        (record,) = read_records(path)
        assert record.utility == "purge"
        assert record.rows_affected == {"s.t": 7}
        assert record.notes == ["chunked in 3 batches"]

    def test_missing_file_reads_as_empty(self, tmp_path):
        assert read_records(tmp_path / "absent.jsonl") == []

    def test_a_malformed_line_does_not_lose_the_rest(self, tmp_path):
        path = tmp_path / "runs.jsonl"
        sink = JsonlAuditSink(path)
        with AuditedRun("good", Environment.DEV, applied=False, sink=sink):
            pass
        with open(path, "a") as handle:
            handle.write("{not json\n")

        assert [r.utility for r in read_records(path)] == ["good"]
