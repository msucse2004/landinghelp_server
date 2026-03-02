# DEEPL_AUTH_KEY 존재 여부 및 Ollama 연결 가능 여부 확인
# 실행: python manage.py check_translation_env
# 키 값은 출력하지 않음 (보안)
import json
import os
import urllib.error
import urllib.request

from django.core.management.base import BaseCommand


def _get_deepl_key():
    """환경변수 및 config.deepl_env 순서로 조회 (값은 반환하지 않고 길이만 사용)."""
    try:
        from config.deepl_env import get_deepl_auth_key
        key = (get_deepl_auth_key() or '').strip()
    except Exception:
        key = (os.environ.get('DEEPL_AUTH_KEY') or '').strip()
    if not key:
        from django.conf import settings
        key = (getattr(settings, 'DEEPL_AUTH_KEY', None) or '').strip()
    return key


def _ollama_base_url():
    return (os.environ.get('OLLAMA_URL') or 'http://localhost:11434').strip().rstrip('/')


def _check_ollama(endpoint: str) -> tuple[bool, str]:
    """Ollama endpoint 요청. (성공 여부, 메시지)."""
    base = _ollama_base_url()
    url = base + endpoint if not endpoint.startswith('http') else endpoint
    req = urllib.request.Request(url, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode()
            if endpoint == '/api/version':
                return True, (json.loads(data).get('version', '') or data.strip() or 'ok')
            return True, 'ok'
    except urllib.error.HTTPError as e:
        return False, f'HTTP {e.code}'
    except urllib.error.URLError as e:
        return False, str(e.reason or 'connection failed')
    except (OSError, json.JSONDecodeError) as e:
        return False, str(e)


class Command(BaseCommand):
    help = (
        '번역 환경 확인: DEEPL_AUTH_KEY 존재 여부, Ollama 연결 가능 여부(/api/tags 또는 /api/version). '
        '키 값은 출력하지 않음.'
    )

    def handle(self, *args, **options):
        self.stdout.write('--- 번역 환경 (check_translation_env) ---')
        self.stdout.write('')

        # 1) DEEPL_AUTH_KEY
        key = _get_deepl_key()
        if key:
            self.stdout.write(
                self.style.SUCCESS(f'  DEEPL_AUTH_KEY: 설정됨 (길이 {len(key)}, 값 미노출)')
            )
        else:
            self.stdout.write(
                self.style.WARNING('  DEEPL_AUTH_KEY: 없음 (환경변수 또는 .env에서 설정)')
            )
        self.stdout.write('')

        # 2) Ollama
        base = _ollama_base_url()
        self.stdout.write(f'  OLLAMA_URL: {base}')
        ok_ver, msg_ver = _check_ollama('/api/version')
        if ok_ver:
            self.stdout.write(
                self.style.SUCCESS(f'  Ollama /api/version: 연결됨 (version: {msg_ver})')
            )
        else:
            ok_tags, msg_tags = _check_ollama('/api/tags')
            if ok_tags:
                self.stdout.write(self.style.SUCCESS('  Ollama /api/tags: 연결됨'))
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f'  Ollama: 연결 실패 — {msg_ver or msg_tags} (로컬에서 ollama 서버 기동 필요)'
                    )
                )
        self.stdout.write('')
        self.stdout.write('완료. 키는 코드/깃에 넣지 말고 환경변수로만 전달하세요.')
