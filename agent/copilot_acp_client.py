"""OpenAI-compatible shim that forwards Henio requests to `copilot --acp`.

This adapter lets Henio treat the GitHub Copilot ACP server as a chat-style
backend. Each request starts a short-lived ACP session, sends the formatted
conversation as a single prompt, collects text chunks, and converts the result
back into the minimal shape Henio expects from an OpenAI client.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shlex
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ACP_MARKER_BASE_URL = "acp://copilot"
_DEFAULT_TIMEOUT_SECONDS = 900.0
_DEFAULT_PROBE_TIMEOUT_SECONDS = 15.0
_STDERR_TAIL_MAX_LINES = 40

_TOOL_CALL_BLOCK_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_TOOL_CALL_JSON_RE = re.compile(r"\{\s*\"id\"\s*:\s*\"[^\"]+\"\s*,\s*\"type\"\s*:\s*\"function\"\s*,\s*\"function\"\s*:\s*\{.*?\}\s*\}", re.DOTALL)


def _default_client_capabilities() -> dict[str, Any]:
    return {
        "fs": {
            "readTextFile": True,
            "writeTextFile": True,
        }
    }


def _resolve_command() -> str:
    return (
        os.getenv("HENIO_COPILOT_ACP_COMMAND", "").strip()
        or os.getenv("COPILOT_CLI_PATH", "").strip()
        or "copilot"
    )


def _resolve_args() -> list[str]:
    raw = os.getenv("HENIO_COPILOT_ACP_ARGS", "").strip()
    if not raw:
        return ["--acp", "--stdio"]
    return shlex.split(raw)


def _jsonrpc_error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def _format_messages_as_prompt(
    messages: list[dict[str, Any]],
    model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
) -> str:
    # Henio must not tell Copilot CLI which model to use. Keep the local
    # model selection inside Henio and let the Copilot client/editor decide
    # the active model for ACP sessions.
    del model

    sections: list[str] = [
        "You are being used as the active ACP agent backend for Henio.",
        "Use ACP capabilities to complete tasks.",
        "When the user asks for workspace or file changes, you MUST perform the ACP action instead of only describing your plan or intent.",
        "Do not stop after reporting intent, progress, or a planned action. Complete the requested ACP operation before replying.",
        "Prefer ACP filesystem capabilities for reading and writing files inside the workspace. Only use Henio tool-call blocks when ACP itself cannot complete the requested action.",
        "IMPORTANT: If you take an action with a Henio tool, you MUST output tool calls using <tool_call>{...}</tool_call> blocks with JSON exactly in OpenAI function-call shape.",
        "If no tool is needed, answer normally.",
    ]

    if isinstance(tools, list) and tools:
        tool_specs: list[dict[str, Any]] = []
        for t in tools:
            if not isinstance(t, dict):
                continue
            fn = t.get("function") or {}
            if not isinstance(fn, dict):
                continue
            name = fn.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            tool_specs.append(
                {
                    "name": name.strip(),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {}),
                }
            )
        if tool_specs:
            sections.append(
                "Available tools (OpenAI function schema). "
                "When using a tool, emit ONLY <tool_call>{...}</tool_call> with one JSON object "
                "containing id/type/function{name,arguments}. arguments must be a JSON string.\n"
                + json.dumps(tool_specs, ensure_ascii=False)
            )

    if tool_choice is not None:
        sections.append(f"Tool choice hint: {json.dumps(tool_choice, ensure_ascii=False)}")

    transcript: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "unknown").strip().lower()
        if role == "tool":
            role = "tool"
        elif role not in {"system", "user", "assistant"}:
            role = "context"

        content = message.get("content")
        rendered = _render_message_content(content)
        if not rendered:
            continue

        label = {
            "system": "System",
            "user": "User",
            "assistant": "Assistant",
            "tool": "Tool",
            "context": "Context",
        }.get(role, role.title())
        transcript.append(f"{label}:\n{rendered}")

    if transcript:
        sections.append("Conversation transcript:\n\n" + "\n\n".join(transcript))

    sections.append("Continue the conversation from the latest user request.")
    return "\n\n".join(section.strip() for section in sections if section and section.strip())


def _render_message_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        if "text" in content:
            return str(content.get("text") or "").strip()
        if "content" in content and isinstance(content.get("content"), str):
            return str(content.get("content") or "").strip()
        return json.dumps(content, ensure_ascii=True)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts).strip()
    return str(content).strip()


def _extract_tool_calls_from_text(text: str) -> tuple[list[SimpleNamespace], str]:
    if not isinstance(text, str) or not text.strip():
        return [], ""

    extracted: list[SimpleNamespace] = []
    consumed_spans: list[tuple[int, int]] = []

    def _try_add_tool_call(raw_json: str) -> None:
        try:
            obj = json.loads(raw_json)
        except Exception:
            return
        if not isinstance(obj, dict):
            return
        fn = obj.get("function")
        if not isinstance(fn, dict):
            return
        fn_name = fn.get("name")
        if not isinstance(fn_name, str) or not fn_name.strip():
            return
        fn_args = fn.get("arguments", "{}")
        if not isinstance(fn_args, str):
            fn_args = json.dumps(fn_args, ensure_ascii=False)
        call_id = obj.get("id")
        if not isinstance(call_id, str) or not call_id.strip():
            call_id = f"acp_call_{len(extracted)+1}"

        extracted.append(
            SimpleNamespace(
                id=call_id,
                call_id=call_id,
                response_item_id=None,
                type="function",
                function=SimpleNamespace(name=fn_name.strip(), arguments=fn_args),
            )
        )

    for m in _TOOL_CALL_BLOCK_RE.finditer(text):
        raw = m.group(1)
        _try_add_tool_call(raw)
        consumed_spans.append((m.start(), m.end()))

    # Only try bare-JSON fallback when no XML blocks were found.
    if not extracted:
        for m in _TOOL_CALL_JSON_RE.finditer(text):
            raw = m.group(0)
            _try_add_tool_call(raw)
            consumed_spans.append((m.start(), m.end()))

    if not consumed_spans:
        return extracted, text.strip()

    consumed_spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in consumed_spans:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))

    parts: list[str] = []
    cursor = 0
    for start, end in merged:
        if cursor < start:
            parts.append(text[cursor:start])
        cursor = max(cursor, end)
    if cursor < len(text):
        parts.append(text[cursor:])

    cleaned = "\n".join(p.strip() for p in parts if p and p.strip()).strip()
    return extracted, cleaned



def _ensure_path_within_cwd(path_text: str, cwd: str) -> Path:
    candidate = Path(path_text)
    if not candidate.is_absolute():
        raise PermissionError("ACP file-system paths must be absolute.")
    resolved = candidate.resolve()
    root = Path(cwd).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"Path '{resolved}' is outside the session cwd '{root}'.") from exc
    return resolved


class _ACPProcessSession:
    def __init__(
        self,
        *,
        command: str,
        args: list[str],
        cwd: str,
        timeout_seconds: float,
    ):
        self._command = command
        self._args = list(args)
        self._cwd = str(Path(cwd).resolve())
        self._timeout_seconds = float(timeout_seconds)
        self._inbox: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr_tail: deque[str] = deque(maxlen=_STDERR_TAIL_MAX_LINES)
        self._next_id = 0
        self.process: subprocess.Popen[str] | None = None

    @property
    def cwd(self) -> str:
        return self._cwd

    def stderr_text(self) -> str:
        return "\n".join(self._stderr_tail).strip()

    def start(self) -> "_ACPProcessSession":
        try:
            proc = subprocess.Popen(
                [self._command] + self._args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=self._cwd,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Could not start Copilot ACP command '{self._command}'. "
                "Install GitHub Copilot CLI or set HENIO_COPILOT_ACP_COMMAND/COPILOT_CLI_PATH."
            ) from exc

        if proc.stdin is None or proc.stdout is None:
            proc.kill()
            raise RuntimeError("Copilot ACP process did not expose stdin/stdout pipes.")

        self.process = proc

        def _stdout_reader() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                try:
                    self._inbox.put(json.loads(line))
                except Exception:
                    self._inbox.put({"raw": line.rstrip("\n")})

        def _stderr_reader() -> None:
            if proc.stderr is None:
                return
            for line in proc.stderr:
                self._stderr_tail.append(line.rstrip("\n"))

        threading.Thread(target=_stdout_reader, daemon=True).start()
        threading.Thread(target=_stderr_reader, daemon=True).start()
        return self

    def close(self) -> None:
        proc = self.process
        self.process = None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def __enter__(self) -> "_ACPProcessSession":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _format_process_failure(self, prefix: str) -> RuntimeError:
        stderr_text = self.stderr_text()
        if stderr_text:
            return RuntimeError(f"{prefix}: {stderr_text}")
        return RuntimeError(prefix)

    def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        server_message_handler=None,
    ) -> Any:
        proc = self.process
        if proc is None or proc.stdin is None:
            raise RuntimeError("Copilot ACP process is not running.")

        self._next_id += 1
        request_id = self._next_id
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        try:
            proc.stdin.write(json.dumps(payload) + "\n")
            proc.stdin.flush()
        except BrokenPipeError as exc:
            raise self._format_process_failure(
                f"Copilot ACP process exited before handling {method}"
            ) from exc

        deadline = time.time() + self._timeout_seconds
        while time.time() < deadline:
            if proc.poll() is not None and self._inbox.empty():
                break
            try:
                msg = self._inbox.get(timeout=0.1)
            except queue.Empty:
                continue

            if server_message_handler and server_message_handler(msg):
                continue

            if isinstance(msg.get("method"), str):
                continue

            if msg.get("id") != request_id:
                continue
            if "error" in msg:
                err = msg.get("error") or {}
                raise RuntimeError(
                    f"Copilot ACP {method} failed: {err.get('message') or err}"
                )
            return msg.get("result")

        if proc.poll() is not None:
            raise self._format_process_failure(
                f"Copilot ACP process exited before responding to {method}"
            )
        raise TimeoutError(f"Timed out waiting for Copilot ACP response to {method}.")


def probe_copilot_acp(
    *,
    command: str | None = None,
    args: list[str] | None = None,
    cwd: str | None = None,
    timeout_seconds: float = _DEFAULT_PROBE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    effective_command = command or _resolve_command()
    effective_args = list(args or _resolve_args())
    effective_cwd = str(Path(cwd or os.getcwd()).resolve())
    result: dict[str, Any] = {
        "ok": False,
        "command": effective_command,
        "args": effective_args,
        "cwd": effective_cwd,
        "session_id": "",
        "error": "",
        "error_code": "",
        "stderr_tail": "",
    }
    session = _ACPProcessSession(
        command=effective_command,
        args=effective_args,
        cwd=effective_cwd,
        timeout_seconds=timeout_seconds,
    )

    try:
        with session:
            session.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": _default_client_capabilities(),
                    "clientInfo": {
                        "name": "henio-agent",
                        "title": "Henio Agent",
                        "version": "0.0.0",
                    },
                },
            )
            session_data = session.request(
                "session/new",
                {
                    "cwd": effective_cwd,
                    "mcpServers": [],
                },
            ) or {}
            session_id = str(session_data.get("sessionId") or "").strip()
            if not session_id:
                raise RuntimeError(
                    "Copilot ACP readiness probe did not return a sessionId."
                )
            result["ok"] = True
            result["session_id"] = session_id
            result["stderr_tail"] = session.stderr_text()
            return result
    except TimeoutError as exc:
        result["error"] = str(exc)
        result["error_code"] = "timeout"
    except RuntimeError as exc:
        result["error"] = str(exc)
        result["error_code"] = "runtime_error"
    result["stderr_tail"] = session.stderr_text()

    return result


class _ACPChatCompletions:
    def __init__(self, client: "CopilotACPClient"):
        self._client = client

    def create(self, **kwargs: Any) -> Any:
        return self._client._create_chat_completion(**kwargs)


class _ACPChatNamespace:
    def __init__(self, client: "CopilotACPClient"):
        self.completions = _ACPChatCompletions(client)


class CopilotACPClient:
    """Minimal OpenAI-client-compatible facade for Copilot ACP."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        default_headers: dict[str, str] | None = None,
        acp_command: str | None = None,
        acp_args: list[str] | None = None,
        acp_cwd: str | None = None,
        command: str | None = None,
        args: list[str] | None = None,
        **_: Any,
    ):
        self.api_key = api_key or "copilot-acp"
        self.base_url = base_url or ACP_MARKER_BASE_URL
        self._default_headers = dict(default_headers or {})
        self._acp_command = acp_command or command or _resolve_command()
        self._acp_args = list(acp_args or args or _resolve_args())
        self._acp_cwd = str(Path(acp_cwd or os.getcwd()).resolve())
        self.chat = _ACPChatNamespace(self)
        self.is_closed = False
        self._active_process: subprocess.Popen[str] | None = None
        self._active_process_lock = threading.Lock()

    def close(self) -> None:
        proc: subprocess.Popen[str] | None
        with self._active_process_lock:
            proc = self._active_process
            self._active_process = None
        self.is_closed = True
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _create_chat_completion(
        self,
        *,
        model: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        **_: Any,
    ) -> Any:
        prompt_text = _format_messages_as_prompt(
            messages or [],
            model=model,
            tools=tools,
            tool_choice=tool_choice,
        )
        response_text, reasoning_text = self._run_prompt(
            prompt_text,
            timeout_seconds=float(timeout or _DEFAULT_TIMEOUT_SECONDS),
        )

        tool_calls, cleaned_text = _extract_tool_calls_from_text(response_text)

        usage = SimpleNamespace(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        )
        assistant_message = SimpleNamespace(
            content=cleaned_text,
            tool_calls=tool_calls,
            reasoning=reasoning_text or None,
            reasoning_content=reasoning_text or None,
            reasoning_details=None,
        )
        finish_reason = "tool_calls" if tool_calls else "stop"
        choice = SimpleNamespace(message=assistant_message, finish_reason=finish_reason)
        return SimpleNamespace(
            choices=[choice],
            usage=usage,
            model=model or "copilot-acp",
        )

    def _run_prompt(self, prompt_text: str, *, timeout_seconds: float) -> tuple[str, str]:
        with _ACPProcessSession(
            command=self._acp_command,
            args=self._acp_args,
            cwd=self._acp_cwd,
            timeout_seconds=timeout_seconds,
        ) as session:
            self.is_closed = False
            with self._active_process_lock:
                self._active_process = session.process

            try:
                session.request(
                    "initialize",
                    {
                        "protocolVersion": 1,
                        "clientCapabilities": _default_client_capabilities(),
                        "clientInfo": {
                            "name": "henio-agent",
                            "title": "Henio Agent",
                            "version": "0.0.0",
                        },
                    },
                )
                session_data = session.request(
                    "session/new",
                    {
                        "cwd": self._acp_cwd,
                        "mcpServers": [],
                    },
                ) or {}
                session_id = str(session_data.get("sessionId") or "").strip()
                if not session_id:
                    raise RuntimeError("Copilot ACP did not return a sessionId.")

                text_parts: list[str] = []
                reasoning_parts: list[str] = []
                session.request(
                    "session/prompt",
                    {
                        "sessionId": session_id,
                        "prompt": [
                            {
                                "type": "text",
                                "text": prompt_text,
                            }
                        ],
                    },
                    server_message_handler=lambda msg: self._handle_server_message(
                        msg,
                        process=session.process,
                        cwd=self._acp_cwd,
                        text_parts=text_parts,
                        reasoning_parts=reasoning_parts,
                    ),
                )
                return "".join(text_parts), "".join(reasoning_parts)
            finally:
                with self._active_process_lock:
                    if self._active_process is session.process:
                        self._active_process = None
                self.is_closed = True
        

    def _handle_server_message(
        self,
        msg: dict[str, Any],
        *,
        process: subprocess.Popen[str],
        cwd: str,
        text_parts: list[str] | None,
        reasoning_parts: list[str] | None,
    ) -> bool:
        method = msg.get("method")
        if not isinstance(method, str):
            return False

        if method == "session/update":
            params = msg.get("params") or {}
            update = params.get("update") or {}
            kind = str(update.get("sessionUpdate") or "").strip()
            content = update.get("content") or {}
            chunk_text = ""
            if isinstance(content, dict):
                chunk_text = str(content.get("text") or "")
            if kind == "agent_message_chunk" and chunk_text and text_parts is not None:
                text_parts.append(chunk_text)
            elif kind == "agent_thought_chunk" and chunk_text and reasoning_parts is not None:
                reasoning_parts.append(chunk_text)
            return True

        if process.stdin is None:
            return True

        message_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "session/request_permission":
            response = {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "outcome": {
                        "outcome": "allow_once",
                    }
                },
            }
        elif method == "fs/read_text_file":
            try:
                path = _ensure_path_within_cwd(str(params.get("path") or ""), cwd)
                content = path.read_text() if path.exists() else ""
                line = params.get("line")
                limit = params.get("limit")
                if isinstance(line, int) and line > 1:
                    lines = content.splitlines(keepends=True)
                    start = line - 1
                    end = start + limit if isinstance(limit, int) and limit > 0 else None
                    content = "".join(lines[start:end])
                response = {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "result": {
                        "content": content,
                    },
                }
            except Exception as exc:
                response = _jsonrpc_error(message_id, -32602, str(exc))
        elif method == "fs/write_text_file":
            try:
                path = _ensure_path_within_cwd(str(params.get("path") or ""), cwd)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(params.get("content") or ""))
                response = {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "result": None,
                }
            except Exception as exc:
                response = _jsonrpc_error(message_id, -32602, str(exc))
        else:
            response = _jsonrpc_error(
                message_id,
                -32601,
                f"ACP client method '{method}' is not supported by Henio yet.",
            )

        process.stdin.write(json.dumps(response) + "\n")
        process.stdin.flush()
        return True
