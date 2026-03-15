# 스케줄 작업 (Cron / 서버 스케줄러)

서버에서 주기적으로 실행할 관리 명령을 cron 또는 시스템 스케줄러로 등록할 수 있습니다.

## 설문 리마인드 이메일 (24시간마다)

미제출 DRAFT 설문이 24시간 이상 갱신되지 않은 사용자에게 하루 1회 리마인드 이메일을 보냅니다.

### 명령

```bash
python manage.py send_survey_reminders
```

### 옵션

| 옵션 | 설명 |
|------|------|
| `--dry-run` | 실제 발송 없이 대상만 조회·출력 |
| `--verbose`, `-v` | 대상 목록 및 발송 결과 상세 출력 |

### 조건 (대상 선정)

- `status=DRAFT`
- `updated_at`이 24시간 이상 경과
- 이메일 주소 존재
- `last_reminded_at`이 없거나 24시간 이상 경과 (하루 1회 제한, 스팸 방지)

### 환경 변수

- **이메일 발송**: `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` (SMTP 사용 시)
- **이메일 링크**: `SITE_URL` (예: `https://yoursite.com`) — 미설정 시 이메일 본문에 상대 경로만 포함될 수 있음

### Cron 예시 (매일 10시)

```cron
0 10 * * * cd /path/to/landinghelp_server && /path/to/venv/bin/python manage.py send_survey_reminders >> /var/log/survey_reminders.log 2>&1
```

### Windows 작업 스케줄러

1. **작업 스케줄러** → 작업 만들기
2. **일반**: 이름 예) `Survey reminder`
3. **트리거**: 매일, 원하는 시간(예: 10:00)
4. **동작**: 프로그램 시작
   - 프로그램: `C:\path\to\venv\Scripts\python.exe`
   - 인수: `manage.py send_survey_reminders`
   - 시작 위치: `C:\path\to\landinghelp_server`

### Docker 환경

컨테이너 내부에서 주기 실행이 필요하면 호스트의 cron에서 `docker compose exec`로 실행할 수 있습니다.

```cron
0 10 * * * cd /path/to/landinghelp_server && docker compose exec -T web python manage.py send_survey_reminders
```

또는 전용 스케줄러 컨테이너(cron 이미지)를 두고 위와 동일한 명령을 등록하는 방식도 가능합니다.

### 실패 시 동작

이메일 발송이 실패한 경우 해당 건만 로그에 기록하고, 나머지 대상에는 계속 발송을 시도합니다. 앱은 중단되지 않습니다.
