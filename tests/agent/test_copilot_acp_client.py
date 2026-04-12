from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

from agent.copilot_acp_client import CopilotACPClient, probe_copilot_acp


def _write_fake_server(tmp_path: Path, name: str, body: str) -> Path:
	script_path = tmp_path / f"{name}.py"
	script_path.write_text(textwrap.dedent(body))
	return script_path


def test_probe_copilot_acp_reports_ready_session(tmp_path: Path):
	script = _write_fake_server(
		tmp_path,
		"ready_server",
		"""
		import json
		import sys

		def send(payload):
			sys.stdout.write(json.dumps(payload) + "\\n")
			sys.stdout.flush()

		while True:
			line = sys.stdin.readline()
			if not line:
				break
			message = json.loads(line)
			method = message.get("method")
			if method == "initialize":
				send({"jsonrpc": "2.0", "id": message["id"], "result": {"capabilities": {}}})
			elif method == "session/new":
				send({"jsonrpc": "2.0", "id": message["id"], "result": {"sessionId": "ready-session"}})
				break
		""",
	)

	result = probe_copilot_acp(
		command=sys.executable,
		args=[str(script)],
		cwd=str(tmp_path),
		timeout_seconds=1.0,
	)

	assert result["ok"] is True
	assert result["session_id"] == "ready-session"
	assert result["error"] == ""


def test_probe_copilot_acp_reports_timeout(tmp_path: Path):
	script = _write_fake_server(
		tmp_path,
		"timeout_server",
		"""
		import sys
		import time

		# Keep the process alive but never answer the initialize request.
		sys.stdin.readline()
		time.sleep(60)
		""",
	)

	result = probe_copilot_acp(
		command=sys.executable,
		args=[str(script)],
		cwd=str(tmp_path),
		timeout_seconds=0.2,
	)

	assert result["ok"] is False
	assert result["error_code"] == "timeout"
	assert "Timed out waiting for Copilot ACP response to initialize" in result["error"]


def test_probe_copilot_acp_captures_stderr_on_early_exit(tmp_path: Path):
	script = _write_fake_server(
		tmp_path,
		"stderr_server",
		"""
		import sys

		print("copilot: login required", file=sys.stderr, flush=True)
		raise SystemExit(1)
		""",
	)

	result = probe_copilot_acp(
		command=sys.executable,
		args=[str(script)],
		cwd=str(tmp_path),
		timeout_seconds=0.5,
	)

	assert result["ok"] is False
	assert result["error_code"] == "runtime_error"
	assert "login required" in result["stderr_tail"]
	assert "Copilot ACP process exited" in result["error"]


def test_copilot_acp_client_handles_prompt_fs_callbacks_and_tool_calls(tmp_path: Path):
	read_path = tmp_path / "input.txt"
	read_path.write_text("hello from file")
	write_path = tmp_path / "output.txt"

	script = _write_fake_server(
		tmp_path,
		"prompt_server",
		f"""
		import json
		import sys

		READ_PATH = {json.dumps(str(read_path))}
		WRITE_PATH = {json.dumps(str(write_path))}

		def send(payload):
			sys.stdout.write(json.dumps(payload) + "\\n")
			sys.stdout.flush()

		def recv(expected_id):
			message = json.loads(sys.stdin.readline())
			assert message["id"] == expected_id
			return message

		while True:
			line = sys.stdin.readline()
			if not line:
				break
			message = json.loads(line)
			method = message.get("method")

			if method == "initialize":
				send({{"jsonrpc": "2.0", "id": message["id"], "result": {{"capabilities": {{}}}}}})
			elif method == "session/new":
				send({{"jsonrpc": "2.0", "id": message["id"], "result": {{"sessionId": "prompt-session"}}}})
			elif method == "session/prompt":
				prompt_text = message["params"]["prompt"][0]["text"]
				assert "Henio requested model hint:" not in prompt_text
				send({{
					"jsonrpc": "2.0",
					"method": "session/update",
					"params": {{
						"update": {{
							"sessionUpdate": "agent_thought_chunk",
							"content": {{"text": "thinking..."}},
						}}
					}},
				}})
				send({{"jsonrpc": "2.0", "id": 900, "method": "session/request_permission", "params": {{"kind": "file"}}}})
				permission = recv(900)
				assert permission["result"]["outcome"]["outcome"] == "allow_once"

				send({{"jsonrpc": "2.0", "id": 901, "method": "fs/read_text_file", "params": {{"path": READ_PATH}}}})
				read_response = recv(901)
				file_text = read_response["result"]["content"]

				send({{"jsonrpc": "2.0", "id": 902, "method": "fs/write_text_file", "params": {{"path": WRITE_PATH, "content": "copied:" + file_text}}}})
				recv(902)

				tool_call = {{
					"id": "tool-1",
					"type": "function",
					"function": {{
						"name": "read_file",
						"arguments": json.dumps({{"path": "README.md"}}),
					}},
				}}
				send({{
					"jsonrpc": "2.0",
					"method": "session/update",
					"params": {{
						"update": {{
							"sessionUpdate": "agent_message_chunk",
							"content": {{"text": f"Read content: {{file_text}}\\n<tool_call>{{json.dumps(tool_call)}}</tool_call>"}},
						}}
					}},
				}})
				send({{"jsonrpc": "2.0", "id": message["id"], "result": {{"ok": True}}}})
				break
		""",
	)

	client = CopilotACPClient(
		command=sys.executable,
		args=[str(script)],
		acp_cwd=str(tmp_path),
	)

	response = client.chat.completions.create(
		model="gpt-5.4",
		messages=[{"role": "user", "content": "Inspect the file and continue."}],
		timeout=1.0,
	)

	message = response.choices[0].message
	assert message.content == "Read content: hello from file"
	assert message.reasoning == "thinking..."
	assert response.choices[0].finish_reason == "tool_calls"
	assert len(message.tool_calls) == 1
	assert message.tool_calls[0].function.name == "read_file"
	assert json.loads(message.tool_calls[0].function.arguments) == {"path": "README.md"}
	assert write_path.read_text() == "copied:hello from file"
	assert client.is_closed is True

