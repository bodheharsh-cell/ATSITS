"""Unit and functional tests for ATSITS Interactive CLI and Teaching Review Workflow."""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from atsits.cli import ATSITSCLI, build_parser
from atsits.gemini.config import GeminiConfig
from atsits.teaching.models import DraftStatus, ReviewAction


def test_cli_parser_commands():
    parser = build_parser()
    args_status = parser.parse_args(["status"])
    assert args_status.command == "status"

    args_bt = parser.parse_args(["backtest", "--equity", "20000"])
    assert args_bt.command == "backtest"
    assert args_bt.equity == 20000.0

    args_teach = parser.parse_args(["teach", "--text", "Sample strategy notes"])
    assert args_teach.command == "teach"
    assert args_teach.text == "Sample strategy notes"

    args_chat = parser.parse_args(["chat", "Explain", "EMA", "Pullback"])
    assert args_chat.command == "chat"
    assert args_chat.prompt == ["Explain", "EMA", "Pullback"]


def test_cli_status_output(capsys):
    cfg = GeminiConfig(api_key=None)
    cli = ATSITSCLI(gemini_config=cfg)
    cli.status()

    captured = capsys.readouterr().out
    assert "ATSITS SYSTEM STATUS" in captured
    assert "EMA_Pullback_v1.0 [PRODUCTION LOCKED]" in captured
    assert "HUMAN OPERATOR" in captured
    assert "Gemini Status: [OFFLINE]" in captured


def test_cli_backtest_baseline_metrics(capsys):
    cli = ATSITSCLI()
    cli.backtest(strategy_name="EMA_Pullback_v1.0")

    captured = capsys.readouterr().out
    assert "BACKTEST EXECUTION RESULTS" in captured
    assert "EMA_Pullback_v1.0" in captured
    assert "Total Trades:     201" in captured
    assert "Winning Trades:   67" in captured
    assert "Losing Trades:    134" in captured
    assert "Win Rate:         33.33%" in captured
    assert "Total Net PnL:    $-306.09" in captured


def test_cli_experiments_and_journal(capsys):
    cli = ATSITSCLI()
    cli.show_experiments()
    captured = capsys.readouterr().out
    assert "EXPERIMENT REGISTRY" in captured

    cli.show_journal()
    captured_j = capsys.readouterr().out
    assert "TRADING JOURNAL" in captured_j


def test_cli_strategy_list_and_show(capsys):
    cli = ATSITSCLI()
    cli.show_strategy(action="list")
    captured = capsys.readouterr().out
    assert "STRATEGIES & DRAFTS" in captured
    assert "EMA_Pullback_v1.0" in captured


def test_cli_teach_workflow_skip(capsys):
    cfg = GeminiConfig(api_key=None)
    cli = ATSITSCLI(gemini_config=cfg)
    text = "Strategy: Enter long when EMA 20 crosses EMA 50 on 1h timeframe with TP at 2.0R."

    with patch("builtins.input", side_effect=["S"]):
        cli.teach(teaching_text=text)

    captured = capsys.readouterr().out
    assert "ATSITS STRATEGY TEACHING PIPELINE" in captured
    assert "Ingesting teaching material" in captured
    assert "Running deterministic Strategy Extraction" in captured
    assert "Extracted Strategy Draft Summary" in captured
    assert "preserved in registry" in captured


def test_cli_teach_workflow_approval(capsys):
    cfg = GeminiConfig(api_key=None)
    cli = ATSITSCLI(gemini_config=cfg)
    text = "Strategy: Enter long when EMA 20 crosses EMA 50 on 1h timeframe with TP at 2.0R."

    with patch("builtins.input", side_effect=["A"]):
        cli.teach(teaching_text=text)

    captured = capsys.readouterr().out
    assert "Successfully approved" in captured


def test_cli_teach_workflow_rejection(capsys):
    cfg = GeminiConfig(api_key=None)
    cli = ATSITSCLI(gemini_config=cfg)
    text = "Strategy: Random buy rules."

    with patch("builtins.input", side_effect=["R", "Not valid rules"]):
        cli.teach(teaching_text=text)

    captured = capsys.readouterr().out
    assert "marked as REJECTED" in captured


def test_cli_chat_offline_guidance(capsys):
    cfg = GeminiConfig(api_key=None)
    cli = ATSITSCLI(gemini_config=cfg)
    cli.chat()

    captured = capsys.readouterr().out
    assert "[GEMINI OFFLINE]" in captured
    assert "GEMINI_API_KEY is not configured" in captured


def test_cli_repl_loop(capsys):
    cfg = GeminiConfig(api_key=None)
    cli = ATSITSCLI(gemini_config=cfg)
    # Simulate typing 'status', then '/help', then 'exit'
    with patch("builtins.input", side_effect=["status", "/help", "exit"]):
        cli.repl()

    captured = capsys.readouterr().out
    assert "ATSITS -- Algorithmic Trading Strategy Iteration & Teaching System" in captured
    assert "ATSITS SYSTEM STATUS" in captured
    assert "Available Commands" in captured
    assert "Exiting ATSITS" in captured
