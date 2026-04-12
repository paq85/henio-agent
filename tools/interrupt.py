"""Interrupt signaling for all tools.

Henio needs two interrupt modes:

* Thread-targeted interrupts for concurrent gateway sessions.
* Legacy/global interrupts for simpler call sites and tests that call
    ``set_interrupt(True)`` in one thread and expect work running in another
    thread to notice it.

Rules:

* ``set_interrupt(True, thread_id=...)`` targets exactly that thread.
* ``set_interrupt(True)`` enables a process-wide interrupt flag.
* ``is_interrupted()`` returns ``True`` when either the global flag is set or
    the current thread has been targeted explicitly.
"""

import threading

# Set of thread idents that have been interrupted.
_interrupted_threads: set[int] = set()
_global_interrupted = False
_lock = threading.Lock()


def set_interrupt(active: bool, thread_id: int | None = None) -> None:
    """Set or clear interrupt state.

    Args:
        active: True to signal interrupt, False to clear it.
        thread_id: Target thread ident. When provided, only that thread is
            affected. When None, toggles the legacy global interrupt flag.
    """
    global _global_interrupted
    with _lock:
        if thread_id is None:
            _global_interrupted = active
            if not active:
                current_tid = threading.current_thread().ident
                if current_tid is not None:
                    _interrupted_threads.discard(current_tid)
            return

        if active:
            _interrupted_threads.add(thread_id)
        else:
            _interrupted_threads.discard(thread_id)


def is_interrupted() -> bool:
    """Check if an interrupt has been requested for the current thread."""
    tid = threading.current_thread().ident
    with _lock:
        return _global_interrupted or (tid in _interrupted_threads if tid is not None else False)


# ---------------------------------------------------------------------------
# Backward-compatible _interrupt_event proxy
# ---------------------------------------------------------------------------
# Some legacy call sites (code_execution_tool, process_registry, tests)
# import _interrupt_event directly and call .is_set() / .set() / .clear().
# This shim maps those calls to the per-thread functions above so existing
# code keeps working while the underlying mechanism is thread-scoped.

class _ThreadAwareEventProxy:
    """Drop-in proxy that maps threading.Event methods to per-thread state."""

    def is_set(self) -> bool:
        return is_interrupted()

    def set(self) -> None:  # noqa: A003
        set_interrupt(True)

    def clear(self) -> None:
        set_interrupt(False)

    def wait(self, timeout: float | None = None) -> bool:
        """Not truly supported — returns current state immediately."""
        return self.is_set()


_interrupt_event = _ThreadAwareEventProxy()
