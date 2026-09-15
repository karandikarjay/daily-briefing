"""Pinned, non-interactive Codex with an explicit tool boundary per role."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'future-appetite'


def strict_schema(model):
    schema = model.model_json_schema()
    def visit(node):
        if isinstance(node, dict):
            node.pop('default', None)
            if 'properties' in node:
                node['required'] = list(node['properties'])
                node['additionalProperties'] = False
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)
    visit(schema)
    return schema


def run_agent(role, model, data, directory, *, web=False, seconds=900):
    from config import OPENAI_API_KEY
    binary = os.environ.get('CODEX_BINARY') or shutil.which('codex')
    if not binary:
        raise RuntimeError('Codex CLI not installed; set CODEX_BINARY to the pinned executable')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    schema_path = directory / f'{role}-schema.json'
    result_path = directory / f'{role}-result.json'
    schema_path.write_text(json.dumps(strict_schema(model)))
    prompt = (SKILL.joinpath('SKILL.md').read_text() + '\n' +
              SKILL.joinpath('references/writing.md').read_text() +
              '\nYour assigned role: ' + role + '\nReturn the required JSON artifact.\n' +
              'Use only supplied evidence in private editor/reviewer roles.\n' +
              json.dumps(data, ensure_ascii=False))
    (directory / f'{role}-input.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
    chosen = os.environ.get('CODEX_MODEL', 'gpt-5.6-sol')
    # A fresh HOME/CODEX_HOME prevents host skills, plugins, account sessions or MCP
    # configuration being inherited. No shell, browser, app, image, or agent tools.
    with tempfile.TemporaryDirectory(prefix='future-appetite-') as isolated:
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': isolated,
               'CODEX_HOME': isolated, 'CODEX_API_KEY': OPENAI_API_KEY or '',
               'LANG': 'C.UTF-8'}
        command = [binary, 'exec', '--ignore-user-config', '--skip-git-repo-check',
                   '--ephemeral', '--sandbox', 'read-only', '--model', chosen,
                   '--json', '--output-schema', str(schema_path.resolve()),
                   '--output-last-message', str(result_path.resolve()),
                   '-C', isolated, '-c', 'approval_policy="never"',
                   '-c', 'model_reasoning_effort="medium"',
                   '-c', 'web_search="live"' if web else 'web_search="disabled"',
                   '-c', 'shell_environment_policy.inherit="none"',
                   '-c', 'tools.view_image=false',
                   '--enable', 'skip_host_skill_discovery']
        for feature in ('shell_tool', 'apps', 'plugins', 'hooks', 'multi_agent',
                        'browser_use', 'computer_use', 'image_generation', 'memories',
                        'workspace_dependencies', 'code_mode_host', 'unified_exec'):
            command.extend(['--disable', feature])
        command.append('-')
        started = time.monotonic()
        with (directory / f'{role}-events.jsonl').open('w') as out, (directory / f'{role}-stderr.log').open('w') as err:
            proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                    text=True, env=env, start_new_session=True)
            try:
                proc.communicate(prompt, timeout=seconds)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
                raise TimeoutError(f'Codex {role} exceeded its {seconds}s deadline')
        if proc.returncode:
            raise RuntimeError(f'Codex {role} failed with exit {proc.returncode}; inspect its private stderr log')
        result = model.model_validate_json(result_path.read_text())
        usage = []
        for line in (directory / f'{role}-events.jsonl').read_text().splitlines():
            event = json.loads(line)
            if event.get('type') == 'turn.completed':
                usage.append(event.get('usage', {}))
        (directory / f'{role}-usage.json').write_text(json.dumps({
            'model': chosen, 'cli_version': subprocess.check_output([binary, '--version'], text=True, env=env).strip(), 'seconds': round(time.monotonic()-started, 2), 'usage': usage}))
        return result
