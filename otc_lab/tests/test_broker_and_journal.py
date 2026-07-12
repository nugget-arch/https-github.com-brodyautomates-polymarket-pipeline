import json

import pytest

import otc_lab
from otc_lab.broker.adapter import (
    BrokerAdapter,
    ExecutionDisabledError,
    OrderRequest,
    PaperBrokerAdapter,
)
from otc_lab.paper_trading.journal import Journal


def test_execution_globally_disabled():
    assert otc_lab.EXECUTION_ENABLED is False


def test_live_adapter_guard_raises():
    class FakeLive(BrokerAdapter):
        def get_balance(self):
            return 0.0

        def get_payout(self, asset, expiry_seconds):
            return 0.8

        def place_order(self, request):
            self._guard_execution()  # any real implementation must call this
            return None

    with pytest.raises(ExecutionDisabledError):
        FakeLive().place_order(OrderRequest("X", "CALL", 1.0, 60))


def test_paper_adapter_checks_balance():
    b = PaperBrokerAdapter(balance=10.0, payout=0.8)
    assert not b.place_order(OrderRequest("X", "CALL", 100.0, 60)).accepted
    assert b.place_order(OrderRequest("X", "CALL", 5.0, 60)).accepted


def test_journal_hash_chain_detects_tampering(tmp_path):
    path = tmp_path / "journal.jsonl"
    j = Journal(path)
    j.append("signal", {"p_up": 0.61})
    j.append("decision", {"action": "shadow_only"})
    j.append("settlement", {"outcome": "loss", "pnl": -1.0})
    assert j.verify()

    # tamper: flip the recorded outcome from loss to win
    lines = path.read_text().splitlines()
    rec = json.loads(lines[2])
    rec["payload"]["outcome"] = "win"
    lines[2] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n")
    assert not Journal(path).verify(), "tampered journal passed verification"


def test_journal_append_after_reopen(tmp_path):
    path = tmp_path / "journal.jsonl"
    Journal(path).append("a", {})
    j2 = Journal(path)
    j2.append("b", {})
    assert j2.verify()
