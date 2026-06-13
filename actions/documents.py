"""
Document generation tools for JARVIS.

Wraps the zenskill CLI to create PDF, DOCX, XLSX, and PPTX documents.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _zenskill_command() -> str:
    """Return the zenskill command path."""
    return "zenskill"


def _run_zenskill(args: list[str], timeout: int = 60) -> dict[str, Any]:
    """Run a zenskill command and return the parsed JSON result."""
    cmd = [_zenskill_command()] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr.strip() or f"Exit code: {result.returncode}",
            }
        # Try to parse JSON from stdout
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"success": True, "output": result.stdout.strip()}
    except FileNotFoundError:
        return {
            "success": False,
            "error": (
                "zenskill CLI not found. Install it and ensure it is in PATH. "
                "See: https://github.com/zenskill/zenskill"
            ),
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_pdf(
    descriptor: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Any]:
    """
    Create a PDF document from a JSON descriptor.

    Args:
        descriptor: JSON descriptor matching zenskill PDF format.
        output_path: Path where the .pdf file will be saved.

    Returns:
        Dict with 'success' bool and either 'output' path or 'error' message.
    """
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(descriptor, f, ensure_ascii=False, indent=2)
        temp_path = f.name

    try:
        result = _run_zenskill([
            "office", "pdf", "create",
            "--input", temp_path,
            "--output", str(output_path),
        ])
        if result.get("success"):
            result["output"] = str(output_path)
        return result
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def create_docx(
    descriptor: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Any]:
    """
    Create a Word document (.docx) from a JSON descriptor.

    Args:
        descriptor: JSON descriptor matching zenskill DOCX format.
        output_path: Path where the .docx file will be saved.

    Returns:
        Dict with 'success' bool and either 'output' path or 'error' message.
    """
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(descriptor, f, ensure_ascii=False, indent=2)
        temp_path = f.name

    try:
        result = _run_zenskill([
            "office", "document", "create",
            "--input", temp_path,
            "--output", str(output_path),
        ])
        if result.get("success"):
            result["output"] = str(output_path)
        return result
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def create_xlsx(
    descriptor: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Any]:
    """
    Create an Excel spreadsheet (.xlsx) from a JSON descriptor.

    Args:
        descriptor: JSON descriptor matching zenskill XLSX format.
        output_path: Path where the .xlsx file will be saved.

    Returns:
        Dict with 'success' bool and either 'output' path or 'error' message.
    """
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(descriptor, f, ensure_ascii=False, indent=2)
        temp_path = f.name

    try:
        result = _run_zenskill([
            "office", "spreadsheet", "create",
            "--input", temp_path,
            "--output", str(output_path),
        ])
        if result.get("success"):
            result["output"] = str(output_path)
        return result
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def create_pptx(
    descriptor: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Any]:
    """
    Create a PowerPoint presentation (.pptx) from a JSON descriptor.

    Args:
        descriptor: JSON descriptor matching zenskill PPTX format.
        output_path: Path where the .pptx file will be saved.

    Returns:
        Dict with 'success' bool and either 'output' path or 'error' message.
    """
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(descriptor, f, ensure_ascii=False, indent=2)
        temp_path = f.name

    try:
        result = _run_zenskill([
            "office", "presentation", "create",
            "--input", temp_path,
            "--output", str(output_path),
        ])
        if result.get("success"):
            result["output"] = str(output_path)
        return result
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def document_status() -> dict[str, Any]:
    """Check if zenskill is available."""
    try:
        result = subprocess.run(
            ["zenskill", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            version = result.stdout.strip() or result.stderr.strip()
            return {"available": True, "version": version}
        return {"available": False, "error": result.stderr.strip()}
    except FileNotFoundError:
        return {"available": False, "error": "zenskill CLI not found in PATH"}
    except Exception as e:
        return {"available": False, "error": str(e)}
