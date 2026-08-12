"""Crash-repro diagnostics for macOS Streamlit segfaults.

Enable with ``INTENTION_DEBUG=1`` (``make run`` sets this). Writes line-buffered,
fsync'd checkpoints to ``logs/crash-repro.log`` and mirrors to stderr so the
last checkpoint before ``Segmentation fault: 11`` is recoverable.

Also arms ``faulthandler`` for SIGSEGV/SIGBUS/SIGABRT Python-level dumps.
"""

from __future__ import annotations

import atexit
import faulthandler
import os
import platform
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_LOG = _ROOT / "logs" / "crash-repro.log"
_DEFAULT_FAULT = _ROOT / "logs" / "faulthandler.dump"

_enabled: bool | None = None
_log_path: Path | None = None
_fault_path: Path | None = None
_log_fp: Any = None
_fault_fp: Any = None
_seq = 0
_lock = threading.Lock()
_installed = False


def enabled() -> bool:
    global _enabled
    if _enabled is None:
        raw = (os.getenv("INTENTION_DEBUG") or "").strip().lower()
        _enabled = raw in {"1", "true", "yes", "on"}
    return _enabled


def log_path() -> Path:
    global _log_path
    if _log_path is None:
        override = (os.getenv("INTENTION_DEBUG_LOG") or "").strip()
        _log_path = Path(override) if override else _DEFAULT_LOG
    return _log_path


def fault_path() -> Path:
    global _fault_path
    if _fault_path is None:
        override = (os.getenv("INTENTION_DEBUG_FAULT") or "").strip()
        _fault_path = Path(override) if override else _DEFAULT_FAULT
    return _fault_path


def _open_log() -> Any:
    global _log_fp
    if _log_fp is not None:
        return _log_fp
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Line-buffered text; we still fsync after each checkpoint.
    _log_fp = path.open("a", encoding="utf-8", buffering=1)
    return _log_fp


def _write_raw(line: str) -> None:
    fp = _open_log()
    fp.write(line)
    if not line.endswith("\n"):
        fp.write("\n")
    fp.flush()
    try:
        os.fsync(fp.fileno())
    except OSError:
        pass
    # Mirror to stderr so the terminal session captures the trail too.
    try:
        sys.stderr.write(line if line.endswith("\n") else line + "\n")
        sys.stderr.flush()
    except OSError:
        pass


def checkpoint(step: str, **fields: Any) -> None:
    """Record a durable checkpoint. No-op unless INTENTION_DEBUG is on."""
    if not enabled():
        return
    global _seq
    with _lock:
        _seq += 1
        seq = _seq
    parts = [
        f"ts={time.time():.6f}",
        f"iso={time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())}",
        f"seq={seq}",
        f"pid={os.getpid()}",
        f"tid={threading.get_ident()}",
        f"step={step}",
    ]
    for key, value in fields.items():
        if value is None:
            continue
        text = str(value).replace("\n", "\\n")
        if len(text) > 500:
            text = text[:500] + "…"
        parts.append(f"{key}={text}")
    _write_raw("[crash-repro] " + " ".join(parts))


def install_crash_diagnostics(*, where: str = "unknown") -> None:
    """Idempotent: faulthandler + session banner. Safe to call from app entry."""
    global _installed, _fault_fp
    if not enabled():
        return
    if _installed:
        checkpoint("diagnostics.already_installed", where=where)
        return
    _installed = True

    fault = fault_path()
    fault.parent.mkdir(parents=True, exist_ok=True)
    _fault_fp = fault.open("a", encoding="utf-8", buffering=1)
    faulthandler.enable(file=_fault_fp, all_threads=True)
    # Extra: dump all threads on SIGUSR1 if user sends it while hung.
    try:
        import signal

        if hasattr(signal, "SIGUSR1"):
            faulthandler.register(signal.SIGUSR1, file=_fault_fp, all_threads=True)
    except Exception:
        pass

    atexit.register(_on_exit)

    checkpoint(
        "diagnostics.installed",
        where=where,
        log=str(log_path()),
        fault=str(fault_path()),
        python=sys.version.split()[0],
        platform=platform.platform(),
        executable=sys.executable,
        cwd=os.getcwd(),
        streamlit_env_file_watcher=os.getenv("STREAMLIT_SERVER_FILE_WATCHER_TYPE"),
        objc_fork=os.getenv("OBJC_DISABLE_INITIALIZE_FORK_SAFETY"),
        omp=os.getenv("OMP_NUM_THREADS"),
        tokenizers=os.getenv("TOKENIZERS_PARALLELISM"),
        protobuf=os.getenv("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"),
        gemini_model=os.getenv("GEMINI_MODEL"),
        has_gemini_key=bool((os.getenv("GEMINI_API_KEY") or "").strip()),
        has_openai_key=bool((os.getenv("OPENAI_API_KEY") or "").strip()),
    )


def _on_exit() -> None:
    if not enabled():
        return
    checkpoint("process.atexit", note="clean Python exit (segfault skips this)")


def summarize_gemini_response(response: Any) -> dict[str, Any]:
    """Inspect Gemini response parts without calling ``response.text`` (avoids SDK warn)."""
    summary: dict[str, Any] = {
        "type": type(response).__name__,
        "n_candidates": 0,
        "parts": [],
    }
    try:
        candidates = getattr(response, "candidates", None) or []
        summary["n_candidates"] = len(candidates)
        for ci, candidate in enumerate(candidates):
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) if content is not None else None
            if not parts:
                summary["parts"].append({"candidate": ci, "empty": True})
                continue
            for pi, part in enumerate(parts):
                text = getattr(part, "text", None)
                thought = getattr(part, "thought", None)
                sig = getattr(part, "thought_signature", None)
                summary["parts"].append(
                    {
                        "candidate": ci,
                        "part": pi,
                        "has_text": bool(text),
                        "text_len": len(text) if isinstance(text, str) else 0,
                        "thought": bool(thought),
                        "has_thought_signature": sig is not None,
                        "sig_len": len(sig) if isinstance(sig, (bytes, bytearray)) else 0,
                        "keys": [
                            name
                            for name in (
                                "text",
                                "thought",
                                "thought_signature",
                                "function_call",
                                "inline_data",
                            )
                            if getattr(part, name, None) is not None
                        ],
                    }
                )
        meta = getattr(response, "usage_metadata", None)
        if meta is not None:
            summary["usage"] = {
                "prompt": getattr(meta, "prompt_token_count", None),
                "candidates": getattr(meta, "candidates_token_count", None),
                "total": getattr(meta, "total_token_count", None),
            }
    except Exception as exc:
        summary["inspect_error"] = f"{type(exc).__name__}: {exc}"
    return summary


def checkpoint_exception(step: str, exc: BaseException) -> None:
    checkpoint(
        step,
        exc_type=type(exc).__name__,
        exc=str(exc),
        tb=" | ".join(traceback.format_exception_only(type(exc), exc)).strip(),
    )
