# landinghelp_server

Django 백엔드 서버 (랜딩헬프)

**v0.1** (2026-02-18)

## v0.1 구현 사항

| 구분 | 내용 |
|------|------|
| **인증** | 회원가입, 로그인, 비밀번호 재설정, 이메일 인증 |
| **역할** | CUSTOMER, AGENT, ADMIN (Provider→Agent 전환 완료) |
| **결제** | Plan, Subscription, C_BASIC~C_PREMIUM, P_BASIC~P_PREMIUM |
| **컨텐츠** | allowed_roles, min_tier 기반 접근 제어, 403 업그레이드 안내 |
| **캐러셀** | 홈 인트로 슬라이드, Admin에서 드래그 정렬, 순서(1-based) 표시, 무한 루프 전환 |
| **관리** | Admin 커스텀 인덱스, 캐러셀 관리 UI (슬라이드 추가 버튼 위치) |
| **로컬 실행** | venv, setup_venv.ps1/sh, run_local.ps1/sh |

## 실행 가이드

### A. venv (로컬 개발)

로컬에 Python이 설치된 경우 venv로 실행 가능합니다.

#### 1. venv 생성 및 의존성 설치

```powershell
# Windows PowerShell
.\setup_venv.ps1
```

```bash
# Bash (Git Bash, WSL, Mac, Linux)
chmod +x setup_venv.sh run_local.sh
./setup_venv.sh
```

#### 2. DB 실행

PostgreSQL이 필요합니다. Docker로 DB만 띄우려면:

```bash
docker compose up -d db
```

#### 3. 마이그레이션 (최초 1회)

```bash
# venv 활성화 후, DB_HOST 설정
# PowerShell: $env:DB_HOST = "localhost"
# Bash:       export DB_HOST=localhost

python manage.py migrate
python manage.py createsuperuser
python manage.py seed_plans
```

#### 4. 실행

```powershell
# Windows PowerShell
.\run_local.ps1
```

```bash
# Bash (Git Bash, WSL, Mac, Linux)
./run_local.sh
```

| 스크립트 | 용도 | 환경 |
|----------|------|------|
| `setup_venv.ps1` | venv 생성 + 의존성 설치 | Windows PowerShell |
| `setup_venv.sh` | venv 생성 + 의존성 설치 | Bash (Git Bash, WSL, Mac, Linux) |
| `run_local.ps1` | 서버 실행 | Windows PowerShell |
| `run_local.sh` | 서버 실행 | Bash (Git Bash, WSL, Mac, Linux) |

`run_local.*` 스크립트는 `DB_HOST=localhost`로 설정 후 venv를 활성화하고 서버를 실행합니다.

#### 5. 이메일 환경변수 (SMTP 사용 시)

`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`은 `.env`에 두지 않고 시스템 환경변수로 설정합니다.

**Windows:**
```powershell
.\set_email_env.ps1
# 프롬프트에 따라 이메일 주소, 비밀번호 입력 (사용자 수준에 영구 등록)
```

**수동 설정:** 제어판 → 시스템 → 고급 시스템 설정 → 환경 변수 → 사용자 변수에서 추가

**확인:** `python manage.py check_email_env` 로 설정 여부 확인

---

### B. Docker (전체 컨테이너)

### 1. 환경 설정

```bash
# .env 파일이 없다면 .env.example을 복사
copy .env.example .env
```

### 2. Docker 실행 / 중지

```bash
# 빌드 및 백그라운드 실행
docker compose up -d --build

# 중지
docker compose down

# 볼륨까지 삭제 (DB 초기화)
docker compose down -v
```

### 3. DB 마이그레이션 & 초기 설정

```bash
# 마이그레이션 적용
docker compose exec web python manage.py migrate

# 슈퍼유저 생성 (Admin 접근용)
docker compose exec web python manage.py createsuperuser

# 플랜 6개 시드 (C_BASIC~C_PREMIUM, P_BASIC~P_PREMIUM)
docker compose exec web python manage.py seed_plans
```

### 4. 포그라운드 실행 (로그 확인용)

```bash
docker compose up --build
```

### 5. 접속 주소

| 용도 | URL |
|------|-----|
| 홈 | http://localhost:8000 |
| Admin | http://localhost:8000/admin |
| App 진입 | http://localhost:8000/app (로그인 필요) |
| 컨텐츠 | http://localhost:8000/content/ |

---

## 테스트 시나리오

### 1. 회원가입 → CUSTOMER + C_BASIC 자동 할당

1. http://localhost:8000 에서 **회원가입** 클릭
2. 아이디, 이메일, 비밀번호 입력 후 가입
3. **Admin** → 사용자(User) → 방금 가입한 유저 선택
   - `role`: CUSTOMER
   - **Admin** → 구독(Subscription)에서 해당 유저의 `plan`이 **C_BASIC** 인지 확인

### 2. AGENT 전환 & P_BASIC 할당

1. **Admin** → 사용자(User) → 해당 유저 선택
2. `role`을 **AGENT**로 변경 후 저장
3. **Admin** → 구독(Subscription)에서:
   - 기존 C_BASIC 구독을 CANCELED 처리하거나
   - 새 구독 추가: user 선택, plan=P_BASIC, status=ACTIVE
4. http://localhost:8000/app 접속 → 에이전트 대시보드, tier=P_BASIC 확인

### 3. Content 접근 차이 확인

**컨텐츠 2개 생성 (Admin → 컨텐츠):**

| 제목 | slug | status | is_public | allowed_roles | min_tier |
|------|------|--------|-----------|---------------|----------|
| 공개 글 | public-sample | PUBLISHED | ✓ | - | BASIC |
| 프리미엄 글 | premium-sample | PUBLISHED | ✗ | CUSTOMER,AGENT | STANDARD |

1. **로그아웃** 상태 → http://localhost:8000/content/
   - 공개 글 1개만 보임
2. **CUSTOMER(BASIC)** 로그인 → /content/
   - 공개 글만 보임 (프리미엄 글은 STANDARD 필요)
3. **STANDARD** 플랜으로 업그레이드 후
   - 두 글 모두 보임
4. 프리미엄 글 상세 직접 접근 (/content/premium-sample/)
   - 권한 없으면 403 + "업그레이드 필요" 안내

### 4. 번역 파이프라인 (DeepL → Ollama) 로컬 확인

로컬에서 파이프라인이 동작하는지 아래 순서로 확인합니다.

#### 1) Ollama 실행 확인

```bash
# 설치된 모델 목록 (기본 모델 예: llama3.1:8b)
ollama list

# 서버 포트 확인 (기본 11434)
# Windows: netstat -an | findstr 11434
# Mac/Linux: lsof -i :11434
```

Ollama가 안 떠 있으면 터미널에서 `ollama serve` 또는 `ollama run llama3.1:8b` 로 기동합니다.

#### 2) DeepL 키 확인 (환경변수)

```bash
# Windows PowerShell (값은 출력하지 말 것)
$env:DEEPL_AUTH_KEY.Length

# 또는 .env에 설정했다면 프로젝트 루트에서
# DEEPL_AUTH_KEY=... 가 있는지 확인 (키 값은 터미널에 붙여넣지 말 것)
```

키가 없으면 [DeepL API](https://www.deepl.com/pro-api)에서 발급 후 시스템 환경변수 또는 `.env`에 설정합니다.

#### 3) Django에서 check_translation_env 실행

```bash
python manage.py check_translation_env
```

- **DEEPL_AUTH_KEY**: 설정됨(길이 N) 또는 없음
- **Ollama /api/version**: 연결됨(version: x.y.z) 또는 연결 실패

둘 다 정상이면 파이프라인 사용 가능합니다.

#### 4) 특정 문장 1개를 translate_pipeline()로 번역해 결과 확인

```bash
python manage.py shell
```

```python
from translations.translation_pipeline import translate_pipeline

# 한 문장만 파이프라인(DeepL → Ollama)으로 번역
out = translate_pipeline('저장되었습니다.', 'en')
print(out)  # 예: 'Saved.' (Ollama 기동 시) 또는 DeepL 결과만
```

Ollama가 꺼져 있으면 DeepL 결과만 반환되고, 서버 로그에 Ollama 연결 실패 경고가 남습니다.

#### 5) 메시지함 접속 후 “translation failures” 노출 확인

1. 로그인한 뒤 **메시지 함** (또는 언어가 다른 화면) 접속
2. **확인 사항**
   - 번역이 불가능해도 앱은 정상 동작하고, 원문이 표시됨
   - 번역 실패 시 팝업이 뜨더라도 **"원문 표시 중"** / **"Showing original"** 같은 **짧은 안내만** 보이고, **실패한 키 목록이 길게 나오지 않음**
3. 서버 로그에는 `번역 실패(원문 폴백) N건` 경고가 남고, 상세 키/에러는 로그에만 출력됩니다.

---

## 폰(모바일) 접속 방법

### 준비

1. **노트북 IP 확인**
   - Windows: `ipconfig` → IPv4 주소 (예: 192.168.0.10)
   - Mac/Linux: `ifconfig` 또는 `ip addr`

2. **.env 수정**
   ```env
   DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0,192.168.0.10
   ```
   (192.168.0.10을 본인 노트북 IP로 변경)

3. **Docker 재시작**
   ```bash
   docker compose down
   docker compose up -d
   ```

### 접속

- 폰과 노트북이 **같은 와이파이**에 연결된 상태에서
- 브라우저에 `http://<노트북IP>:8000` 입력  
  예: `http://192.168.0.10:8000`

### 주의사항

| 항목 | 설명 |
|------|------|
| ALLOWED_HOSTS | `.env`에 노트북 IP 추가 필수 |
| 방화벽 | Windows 방화벽에서 8000 포트 허용 필요할 수 있음 |
| 같은 네트워크 | 폰과 PC가 같은 Wi‑Fi |

---

## 앱 구성

| 앱 | 설명 |
|---|---|
| `accounts` | 인증, 역할(role), 상태(status) |
| `billing` | Plan, Subscription, tier |
| `content` | 컨텐츠 (allowed_roles + min_tier) |

## URL 구조

| 경로 | 설명 |
|------|------|
| `/` | 홈 (Hero, CTA) |
| `/app/` | 앱 진입점 (role별 대시보드 리다이렉트) |
| `/admin/dashboard/` | 관리자 대시보드 |
| `/agent/dashboard/` | 에이전트 대시보드 |
| `/customer/dashboard/` | 고객 대시보드 |
| `/content/` | 컨텐츠 목록 |
| `/content/<slug>/` | 컨텐츠 상세 |
