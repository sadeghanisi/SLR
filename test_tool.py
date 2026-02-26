#!/usr/bin/env python3
"""
Test script for the generic SLR automation tool
"""

import sys
import os
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all modules can be imported successfully"""
    print("Testing imports...")
    
    try:
        from housing_enhanced import SystematicReviewAutomation
        print("✓ housing_enhanced imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import housing_enhanced: {e}")
        return False
    
    try:
        from slr_gui import SLRAutomationGUI
        print("✓ slr_gui imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import slr_gui: {e}")
        return False
    
    try:
        from prompt_editor import show_prompt_editor
        print("✓ prompt_editor imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import prompt_editor: {e}")
        return False
    
    try:
        from advanced_config import show_advanced_config
        print("✓ advanced_config imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import advanced_config: {e}")
        return False
    
    return True

def test_automation_class():
    """Test that the automation class accepts custom prompts"""
    print("\nTesting automation class with custom prompts...")
    
    try:
        from housing_enhanced import SystematicReviewAutomation
        
        # Create test output directory
        test_output_dir = Path("test_output")
        test_output_dir.mkdir(exist_ok=True)
        
        # Test custom prompts
        custom_screening = "Custom screening prompt with {text} placeholder"
        custom_extraction = "Custom extraction prompt with {text} placeholder"
        
        # Create instance (without actually running it)
        automation = SystematicReviewAutomation(
            api_key="test_key",
            pdf_folder="test_folder",
            output_folder=str(test_output_dir),
            screening_prompt=custom_screening,
            extraction_prompt=custom_extraction
        )
        
        # Check that prompts are set correctly
        if automation.screening_prompt == custom_screening:
            print("✓ Custom screening prompt set correctly")
        else:
            print("✗ Custom screening prompt not set correctly")
            return False
        
        if automation.extraction_prompt == custom_extraction:
            print("✓ Custom extraction prompt set correctly")
        else:
            print("✗ Custom extraction prompt not set correctly")
            return False
        
        print("✓ Automation class accepts custom prompts successfully")
        return True
        
    except Exception as e:
        print(f"✗ Error testing automation class: {e}")
        return False

def test_default_prompts():
    """Test that default prompts are used when none provided"""
    print("\nTesting default prompts...")
    
    try:
        from housing_enhanced import SystematicReviewAutomation
        
        # Create test output directory
        test_output_dir = Path("test_output")
        test_output_dir.mkdir(exist_ok=True)
        
        # Create instance without custom prompts
        automation = SystematicReviewAutomation(
            api_key="test_key",
            pdf_folder="test_folder",
            output_folder=str(test_output_dir)
        )
        
        # Check that default prompts are used
        if automation.screening_prompt and "{text}" in automation.screening_prompt:
            print("✓ Default screening prompt is set and contains {text}")
        else:
            print("✗ Default screening prompt is not properly set")
            return False
        
        if automation.extraction_prompt and "{text}" in automation.extraction_prompt:
            print("✓ Default extraction prompt is set and contains {text}")
        else:
            print("✗ Default extraction prompt is not properly set")
            return False
        
        print("✓ Default prompts work correctly")
        return True
        
    except Exception as e:
        print(f"✗ Error testing default prompts: {e}")
        return False

def test_gui_startup():
    """Test that the GUI can be created (but not displayed)"""
    print("\nTesting GUI startup...")
    
    try:
        import tkinter as tk
        from slr_gui import SLRAutomationGUI
        
        # Create root window but don't display it
        root = tk.Tk()
        root.withdraw()  # Hide the window
        
        # Create GUI instance
        gui = SLRAutomationGUI(root)
        
        # Check that prompt variables are initialized
        if hasattr(gui, 'screening_prompt') and hasattr(gui, 'extraction_prompt'):
            print("✓ GUI has prompt variables")
        else:
            print("✗ GUI missing prompt variables")
            return False
        
        if hasattr(gui, 'criteria_status'):
            print("✓ GUI has criteria status variable")
        else:
            print("✗ GUI missing criteria status variable")
            return False
        
        # Clean up
        root.destroy()
        
        print("✓ GUI can be created successfully")
        return True
        
    except Exception as e:
        print(f"✗ Error testing GUI: {e}")
        return False

def main():
    """Run all tests"""
    print("=" * 50)
    print("Generic SLR Automation Tool - Test Suite")
    print("=" * 50)
    
    tests = [
        test_imports,
        test_automation_class,
        test_default_prompts,
        test_gui_startup
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        print()
    
    print("=" * 50)
    print(f"Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! The tool is ready to use.")
        print("\nTo run the tool:")
        print("python slr_gui.py")
    else:
        print("❌ Some tests failed. Please check the errors above.")
        return 1
    
    print("=" * 50)
    return 0

if __name__ == "__main__":
    sys.exit(main())
