#!/usr/bin/env python3
"""Test for the general ability seed."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_seed_general_exists():
    """Test that the general seed TSV file exists and has content."""
    tsv_path = ROOT / "data" / "seed-general.tsv"
    assert tsv_path.exists(), "seed-general.tsv should exist"
    
    content = tsv_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    assert len(lines) >= 45, f"Expected at least 45 records, got {len(lines)}"
    
    # Check format: topic\theader\note
    for line in lines:
        parts = line.split("\t", 2)
        assert len(parts) == 3, f"Line should have 3 tab-separated parts: {line}"
        topic, header, note = parts
        assert topic, f"Topic should not be empty: {line}"
        assert header, f"Header should not be empty: {line}"
        assert note, f"Note should not be empty: {line}"


def test_seed_general_builds_db():
    """Test that building the seed general DB works and creates records."""
    # Run the builder script
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_seed_general.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    
    # Should succeed (exit code 0) or report nothing added (exit code 1 with specific message)
    assert result.returncode in [0, 1], f"Builder script failed: {result.stderr}"
    
    if result.returncode == 1:
        # If it says nothing added, that's OK if records already exist
        assert "NOTHING ADDED: no card could be ingested" in result.stdout or \
               "curated rows:" in result.stdout, f"Unexpected output: {result.stdout}"
    
    # Check that the general DB exists and has the seed provenance
    # Uses the same DBS_ROOT as the launcher: $HOME/.greymicroagent/dbs
    db_dir = Path(os.environ.get("HOME", "/home/grey")) / ".greymicroagent" / "dbs" / "general"
    assert db_dir.exists(), f"General DB directory should exist at {db_dir}"
    
    prov_path = db_dir / "seed-provenance.json"
    assert prov_path.exists(), f"Seed provenance file should exist at {prov_path}"
    
    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    assert prov["name"] == "general", "Provenance should be for general DB"
    assert "general-ability seed cards" in prov["note"], "Should mention general-ability seed"
    assert prov["src"] == "greymicroagent product seed (own-written)", "Should own-written source"


def test_seed_general_has_writing_reasoning_browser():
    """Test that the seed contains writing, reasoning, and browser records."""
    tsv_path = ROOT / "data" / "seed-general.tsv"
    content = tsv_path.read_text(encoding="utf-8")
    
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    topics = [line.split("\t")[0] for line in lines if "\t" in line]
    
    assert "writing" in topics, "Should have writing topic records"
    assert "reasoning" in topics, "Should have reasoning topic records"  
    assert "browser" in topics, "Should have browser topic records"
    
    # Count each type
    writing_count = topics.count("writing")
    reasoning_count = topics.count("reasoning")
    browser_count = topics.count("browser")
    
    assert writing_count >= 10, f"Should have adequate writing records, got {writing_count}"
    assert reasoning_count >= 10, f"Should have adequate reasoning records, got {reasoning_count}"
    assert browser_count >= 5, f"Should have adequate browser records, got {browser_count}"


if __name__ == "__main__":
    test_seed_general_exists()
    test_seed_general_builds_db()
    test_seed_general_has_writing_reasoning_browser()
    print("All tests passed!")
