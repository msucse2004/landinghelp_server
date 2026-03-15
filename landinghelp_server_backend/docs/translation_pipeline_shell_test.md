# 번역 파이프라인 Shell 테스트

단위 테스트 없이 `python manage.py shell`에서 동작 확인용 예시.

## 사전 조건

- `DEEPL_AUTH_KEY` 환경변수 설정 (DeepL 사용 시)
- Ollama 사용 시: 로컬에서 `ollama run llama3.1:8b` 등으로 서버 기동, 기본 `http://localhost:11434`

## Shell에서 실행

```bash
python manage.py shell
```

```python
from translations.translation_pipeline import translate_deepl, post_edit_ollama, translate_pipeline

# 1) DeepL만
translate_deepl('저장되었습니다.', 'en', 'ko')
# 예: 'It has been saved.'

# 2) Ollama 후편집만 (Ollama 서버 기동 시)
post_edit_ollama('저장되었습니다.', 'It has been saved.', 'en')
# 예: 'Saved.'

# 3) 파이프라인 전체 (DeepL → Ollama, Ollama 실패 시 DeepL 결과 반환)
translate_pipeline('저장되었습니다.', 'en')
# 예: 'Saved.' 또는 DeepL 결과

# 4) placeholder 보호
translate_pipeline('%(count)s개의 메시지가 있습니다.', 'en')
# 예: 'You have %(count)s messages.'  (%(count)s 유지)
```

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| DEEPL_AUTH_KEY | (없음) | DeepL API 키 |
| OLLAMA_URL | http://localhost:11434 | Ollama 서버 주소 |
| OLLAMA_MODEL | llama3.1:8b | 채팅용 모델 |
