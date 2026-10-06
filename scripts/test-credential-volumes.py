"""Docker integration test. Only uniquely named disposable synthetic volumes are removed."""
from pathlib import Path
import subprocess
import uuid

IMAGE = 'postgres:17.7-alpine@sha256:bb377b7239d2774ac8cc76f481596ce96c5a6b5e9d141f6d0a0ee371a6e7c0f2'
SCRIPT = Path(__file__).with_name('credential-volumes.sh').resolve()


def docker(*args, ok=True):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=60)
    if ok != (result.returncode == 0):
        raise AssertionError('Synthetic Docker volume assertion failed (output withheld)')
    return result.stdout


def run(master, cipher, user, command, ok=True):
    args = ['run', '--rm', '--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
            '--user', user, '--mount', f'type=volume,source={master},target=/master',
            '--mount', f'type=volume,source={cipher},target=/ciphertext',
            '--mount', f'type=bind,source={SCRIPT},target=/script.sh,readonly', '--entrypoint', '/bin/sh']
    if user == '0:0':
        args += ['--cap-add=CHOWN']
    return docker(*args, IMAGE, '-ec', command, ok=ok)


def main():
    prefix = 'archguard-credential-test-' + uuid.uuid4().hex
    master, cipher = prefix + '-master', prefix + '-cipher'
    try:
        docker('volume', 'create', master)
        docker('volume', 'create', cipher)
        run(master, cipher, '0:0', 'umask 077; touch /master/synthetic-sentinel')
        run(master, cipher, '0:0', '/bin/sh /script.sh initialize', ok=False)
        run(master, cipher, '0:0', 'test -f /master/synthetic-sentinel; test ! -e /master/master.key; rm /master/synthetic-sentinel')
        run(master, cipher, '0:0', '/bin/sh /script.sh initialize')
        run(master, cipher, '10001:10001', '/bin/sh /script.sh verify')
        digest = run(master, cipher, '10001:10001', 'sha256sum /master/master.key')
        run(master, cipher, '0:0', '/bin/sh /script.sh initialize')
        assert digest == run(master, cipher, '10001:10001', 'sha256sum /master/master.key')
        run(master, cipher, '10001:10001', 'ln -s /master/master.key /ciphertext/deepseek.credential')
        run(master, cipher, '10001:10001', '/bin/sh /script.sh verify', ok=False)
        run(master, cipher, '10001:10001', 'rm /ciphertext/deepseek.credential; chmod 777 /ciphertext')
        run(master, cipher, '0:0', '/bin/sh /script.sh initialize', ok=False)
        run(master, cipher, '10001:10001', '/bin/sh /script.sh verify', ok=False)
        run(master, cipher, '10001:10001', 'chmod 700 /ciphertext; rm /master/master.key')
        run(master, cipher, '0:0', '/bin/sh /script.sh initialize')
        run(master, cipher, '10001:10001', '/bin/sh /script.sh verify', ok=False)
        # Confirm bootstrap did not regenerate a missing master in initialized volumes.
        run(master, cipher, '10001:10001', 'test ! -e /master/master.key')
        print('Synthetic volumes: bootstrap/reuse/symlink/modes/missing-master refusal PASS')
    finally:
        for name in (master, cipher):
            assert name.startswith('archguard-credential-test-') and name.startswith(prefix)
            docker('volume', 'rm', name)


if __name__ == '__main__':
    main()
