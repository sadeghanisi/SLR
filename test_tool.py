#!/usr/bin/env python3
"""
Local smoke tests for the generic SLR automation tool.

The functions named ``test_*`` are pytest tests and must not return booleans.
The ``main()`` entry point keeps this file usable as a standalone smoke script.
"""

import sys
import tempfile
from pathlib import Path

# Add current directory to path when the file is run directly.
sys.path.insert(0, str(Path(__file__).parent))


def _check_imports():
    """Import the main modules used by the desktop workflow."""
    from housing_enhanced import SystematicReviewAutomation
    from slr_gui import SLRAutomationGUI
    from prompt_editor import show_prompt_editor
    from advanced_config import show_advanced_config

    assert SystematicReviewAutomation is not None
    assert SLRAutomationGUI is not None
    assert show_prompt_editor is not None
    assert show_advanced_config is not None


def _check_automation_class(output_dir):
    """Verify custom prompts are preserved on the automation object."""
    from housing_enhanced import SystematicReviewAutomation

    custom_screening = "Custom screening prompt with {text} placeholder"
    custom_extraction = "Custom extraction prompt with {text} placeholder"

    automation = SystematicReviewAutomation(
        api_key="test_key",
        pdf_folder="test_folder",
        output_folder=str(output_dir),
        screening_prompt=custom_screening,
        extraction_prompt=custom_extraction,
    )

    assert automation.screening_prompt == custom_screening
    assert automation.extraction_prompt == custom_extraction


def _check_default_prompts(output_dir):
    """Verify default prompts are present when no custom prompt is supplied."""
    from housing_enhanced import SystematicReviewAutomation

    automation = SystematicReviewAutomation(
        api_key="test_key",
        pdf_folder="test_folder",
        output_folder=str(output_dir),
    )

    assert automation.screening_prompt
    assert "{text}" in automation.screening_prompt
    assert automation.extraction_prompt
    assert "{text}" in automation.extraction_prompt


def _check_gui_startup():
    """Create the GUI without displaying it."""
    import tkinter as tk

    from slr_gui import SLRAutomationGUI

    root = tk.Tk()
    root.withdraw()
    try:
        gui = SLRAutomationGUI(root)
        assert hasattr(gui, "screening_prompt")
        assert hasattr(gui, "extraction_prompt")
        assert hasattr(gui, "criteria_status")
    finally:
        root.destroy()


def test_imports():
    _check_imports()


def test_automation_class(tmp_path):
    _check_automation_class(tmp_path)


def test_default_prompts(tmp_path):
    _check_default_prompts(tmp_path)


def test_gui_startup():
    _check_gui_startup()


def main():
    """Run the smoke checks as a standalone script."""
    print("=" * 50)
    print("Generic SLR Automation Tool - Smoke Test Suite")
    print("=" * 50)

    checks = [
        ("imports", lambda tmp_dir: _check_imports()),
        ("automation class", _check_automation_class),
        ("default prompts", _check_default_prompts),
        ("GUI startup", lambda tmp_dir: _check_gui_startup()),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp)
        for name, check in checks:
            print(f"Running {name}...")
            try:
                check(output_dir)
            except Exception as exc:
                print(f"FAILED: {name}: {exc}")
                return 1
            print(f"PASSED: {name}")

    print("=" * 50)
    print("All smoke checks passed. To run the tool: python slr_gui.py")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
