"""Start owner-only Backspace access through an already signed-in Tailscale."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backspace_mvp.private_access import identity_hash, load_config
from scripts.start_backspace import main as start_local

CONFIG = ROOT / 'state/web/private_access.json'


def tailscale_path():
    path = shutil.which('tailscale') or str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Tailscale/tailscale.exe')
    if not Path(path).is_file():
        raise RuntimeError('Tailscale을 설치하고 PC 앱에서 먼저 로그인하세요.')
    return path


def ts_json(executable, *args):
    result = subprocess.run([executable, *args], capture_output=True, text=True,
                            encoding='utf-8', timeout=15, check=True)
    return json.loads(result.stdout)


def serve_conflicts(status, origin):
    """Never replace another service or reuse a publicly exposed listener."""
    if any(status.get('AllowFunnel', {}).values()):
        return True
    tcp = status.get('TCP', {}).get('443')
    if tcp and tcp != {'HTTPS': True}:
        return True
    expected_host = origin.removeprefix('https://') + ':443'
    for host, entry in status.get('Web', {}).items():
        if host.endswith(':443'):
            if host != expected_host or entry.get('Handlers') != {'/': {'Proxy': 'http://127.0.0.1:8788'}}:
                return True
    return False


def gateway_ready(login):
    request = urllib.request.Request('http://127.0.0.1:8788/app.js',
                                     headers={'Tailscale-User-Login': login})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.read() == (ROOT / 'backspace_mvp/web_static/app.js').read_bytes()
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    executable = tailscale_path()
    status = ts_json(executable, 'status', '--json')
    if status.get('BackendState') != 'Running' or not status.get('Self', {}).get('Online'):
        raise RuntimeError('Tailscale PC 앱에서 로그인하고 연결한 뒤 다시 실행하세요.')
    profile = status.get('User', {}).get(str(status['Self']['UserID']), {})
    login = profile.get('LoginName')
    dns = status['Self'].get('DNSName', '').rstrip('.')
    if not login or not dns:
        raise RuntimeError('Tailscale 계정과 개인 DNS 주소를 확인하지 못했습니다.')
    expected = {'origin': 'https://' + dns, 'owner_hash': identity_hash(login)}
    if CONFIG.exists():
        config = load_config(CONFIG)
        if config != expected:
            raise RuntimeError('기존 개인 접속 설정과 현재 Tailscale 계정/주소가 다릅니다. 기존 계정으로 연결하세요.')
    else:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation keeps another launch from overwriting the owner.
        with CONFIG.open('x', encoding='utf-8') as handle:
            json.dump(expected, handle, indent=2)
        config = load_config(CONFIG)
    if serve_conflicts(ts_json(executable, 'serve', 'status', '--json'), config['origin']):
        raise RuntimeError('기존 HTTPS 또는 Funnel 설정이 있어 자동 변경하지 않았습니다. Tailscale 설정을 확인하세요.')
    saved_argv = sys.argv
    try:
        sys.argv = [sys.argv[0], '--no-browser']
        start_local()
    finally:
        sys.argv = saved_argv
    if not gateway_ready(login):
        logs = ROOT / 'output'
        logs.mkdir(exist_ok=True)
        with (logs / 'private-access.stdout.log').open('ab') as out, (logs / 'private-access.stderr.log').open('ab') as err:
            process = subprocess.Popen([sys.executable, '-m', 'backspace_mvp.private_access', '--config', str(CONFIG)],
                cwd=ROOT, stdout=out, stderr=err, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 15
        while not gateway_ready(login):
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('개인 접속을 시작하지 못했습니다. output/private-access.stderr.log를 확인하세요.')
            time.sleep(0.2)
    try:
        subprocess.run([executable, 'serve', '--bg', 'http://127.0.0.1:8788'], check=True, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('위 Tailscale 안내 주소에서 HTTPS/Serve를 활성화한 뒤 다시 실행하세요.') from exc
    active = ts_json(executable, 'serve', 'status', '--json')
    if not active.get('Web') or serve_conflicts(active, config['origin']):
        raise RuntimeError('개인 HTTPS 연결 설정을 확인하지 못했습니다.')
    print('Backspace personal access: ' + config['origin'])
    print('다른 기기도 같은 Tailscale 계정으로 연결하세요. PC와 Backspace가 실행 중이어야 합니다.')
    if not args.no_browser:
        webbrowser.open(config['origin'])


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
