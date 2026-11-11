import json
import sys
import pytest
from merge_traces import main

def test_output_failure_is_a_cli_error(tmp_path, monkeypatch, capsys):
    source = tmp_path / "spans.jsonl"
    source.write_text(json.dumps({"trace_id": "test", "name": "span"}) + "\n")
    monkeypatch.setattr(sys, "argv", ["merge_traces", "--files", str(source), "-o", str(tmp_path)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "could not write output" in capsys.readouterr().err
