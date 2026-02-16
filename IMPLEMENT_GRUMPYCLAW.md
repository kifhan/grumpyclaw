# OpenClaw: 강력한 기능과 직접 구축하는 방법

**(What Makes OpenClaw Powerful & How to Build It Yourself)**

## 1. 아키텍처 비교 (Architecture Comparison)

이미지는 OpenClaw의 원래 구조(상단)와 작성자가 직접 커스텀하여 구축한 구조(하단)를 4가지 핵심 영역으로 나누어 비교합니다.

### ① 메모리 시스템 (Memory System)

* **OpenClaw (Original):**
* **파일 구조:** `SOUL.md` (정체성), `USER.md` (사용자 정보), `MEMORY.md` (장기 기억), `AGENTS.md` (행동 양식), `HEARTBEAT.md`, `daily/` (로그).
* **검색:** 하이브리드 벡터 + 키워드 검색 (`sqlite-vec` 또는 `pgvector`).


* **나만의 구축 (My Build):**
* **기술 스택:** SQLite + Markdown.
* **구조:** OpenAI API + OpenCode Zen (GLM, Kimi, GPT 등 단일 게이트웨이).
* **검색:** 하이브리드 검색 (0.7 벡터 + 0.3 키워드 BM25).
* **특징:** SQLite + FastEmbed (384-dim, ONNX) 로컬 검색; LLM은 OpenCode Zen(`opencode.ai/zen`) 또는 OpenAI로 API 호출.
* **철학:** **Markdown이 곧 데이터베이스다.**



### ② 하트비트 (Heartbeat - 주기적 실행)

* **OpenClaw (Original):**
* **작동:** Cron 기반 스케줄링.
* **기능:** 사전 예방적(Proactive) 행동, 통합 서비스 확인, 게이트웨이 이벤트 처리.
* **특징:** 사용자 프롬프트 없이 실행됨.


* **나만의 구축 (My Build):**
* **기술:** OpenAI / OpenCode Zen + Python APIs.
* **주기:** **30분마다 실행.**
* **기능:** Python이 Gmail, Calendar, Slack, **Google Docs(저널)** 에서 직접 데이터를 수집. LLM(OpenAI 또는 OpenCode Zen의 GLM/Kimi 등)이 데이터를 추론하여 알림 여부 결정.
* **알림 예시:** "15분 뒤 미팅 있음 - 준비 문서가 비어있음" 또는 "HEARTBEAT_OK (보고할 것 없음)".



### ③ 채널 어댑터 (Channel Adapters)

* **OpenClaw (Original):**
* **지원:** WhatsApp, Telegram, Slack, Discord, Signal, iMessage, Email 등.
* **구조:** 게이트웨이 중심 아키텍처 (WebSocket 제어).


* **나만의 구축 (My Build):**
* **지원:** **Slack (Socket Mode) + Terminal.**
* **특징:** 퍼블릭 URL 필요 없음. 각 스레드가 영구적인 대화 유지.
* **Terminal:** OpenAI / OpenCode Zen을 통한 직접 상호작용.
* **확장:** Discord, Teams 등은 필요할 때 추가 (One-shot with OpenAI/OpenCode Zen).



### ④ 스킬 레지스트리 (Skills Registry)

* **OpenClaw (Original):**
* **규모:** ClawHub 레지스트리에 5,700+ 개 스킬.
* **형태:** 커뮤니티 확장 프로그램, 플러그인 마켓플레이스.
* **위험:** 230개 이상의 악성 패키지 발견, 13.4%가 치명적 취약점 보유.


* **나만의 구축 (My Build):**
* **경로:** 로컬 `skills/` (예: `.cursor/skills/` 또는 프로젝트 내 `skills/`).
* **기능:** 콘텐츠 엔진, 직접 통합, YouTube 스크립트, PPT 생성, Excalidraw 다이어그램 등 15+ 개.
* **방식:** `SKILL.md` 파일을 넣으면 즉시 사용 가능.
* **보안:** **로컬 파일만 사용 (공개 레지스트리 없음). 공급망 공격 표면 제거.**



---

## 2. 초개인화된 AI 에이전트의 특징

**(Your Ultra-Personalized AI Agent)**

* 🔵 **기억:** 당신의 결정, 선호도, 맥락(Context)을 기억함.
* 🔵 **사전 확인:** 당신이 묻기 전에 이메일과 캘린더를 확인.
* 🟢 **어디서나 대화:** Slack, 터미널 등 어디서든 대화 가능.
* 🟠 **확장성:** 단일 파일 추가만으로 모든 기능 확장 가능.
* **핵심 가치:** 당신을 대신하여 행동하고, 필요한 것을 예측함. 매일 당신을 더 잘 알게 됨.

---

## 3. 직접 구축하기 (Build It Yourself)

### 기술 스택 파이프라인

1. **OpenAI API + OpenCode Zen:** 스킬 + 훅(Hooks) 작성. OpenAI api 사용. Zen으로 GLM, Kimi 등 엔드포인트(`opencode.ai/zen/v1/chat/completions`) 사용.
2. **AI SDK / 에이전트 프레임워크:** 하트비트 + 백그라운드 프로세스 (OpenAI 호환 API).
3. **SQLite + Markdown:** 하이브리드 검색, 완전 로컬 환경.
> **규모:** 약 2,000줄의 Python 코드 + Markdown. 며칠 만에 구축 가능. **OpenCode Zen:** [opencode.ai/auth](https://opencode.ai/auth)에서 API 키 발급, 모델 ID는 `opencode/glm-4.7`, `opencode/kimi-k2.5` 등.

### 구축 프로세스 (The Process)

OpenClaw를 의존성(Dependency)이 아닌 **청사진(Blueprint)**으로 사용하세요.

1. **Clone:** OpenClaw 저장소 복제 (MIT 라이선스, 100% 오픈소스).
2. **Analyze:** 코딩 에이전트에게 "메모리 시스템이 어떻게 작동하는지 설명해줘"라고 요청.
3. **Build:** "그걸 내 시스템에 맞게 구축해줘 (옵션: XYZ 커스터마이징 포함)"라고 명령.
4. **Repeat:** 하트비트, 어댑터, 스킬에 대해 위 과정을 반복.

> **핵심 팁:** OpenClaw 저장소를 읽고 메모리 시스템 구현 방식을 파악하되, **SQLite + Markdown을 사용하여 단순하게 유지(Keep it simple)하세요.**

---

## Raspberry Pi 4B (4GB) 설치 계획 (Installation Plan)

**대상:** Raspberry Pi 4 Model B, 4GB RAM. LLM은 API(OpenAI/OpenCode Zen)만 사용하므로 Pi에서는 메모리·검색·스케줄만 실행.

| 단계 | 내용 |
|------|------|
| **1. OS** | Raspberry Pi OS **64-bit** (Bullseye/Bookworm) 권장. 32-bit는 ONNX/FastEmbed에서 메모리 제한 가능. |
| **2. 시스템 준비** | `sudo apt update && sudo apt install -y sqlite3 curl`. uv 설치: `curl -LsSf https://astral.sh/uv/install.sh \| sh` 후 터미널 재시작 또는 `source $HOME/.local/bin/env`. 필요 시 스왑 1GB 추가: `sudo dphys-swapfile swapoff`, 편집 후 `swapsize=1024`, `sudo dphys-swapfile setup && sudo dphys-swapfile swapon`. |
| **3. 프로젝트 디렉터리** | `mkdir -p ~/grumpyClaw && cd ~/grumpyClaw`. 프로젝트가 이미 있으면 클론/복사 후 `uv sync`로 가상환경 생성 및 의존성 설치. 새로 시작 시 `uv init` 후 의존성 추가. |
| **4. Python 의존성** | `uv sync` (pyproject.toml + uv.lock 기준) 또는 `uv pip install -r requirements.txt`. SQLite 드라이버·FastEmbed(ONNX)·OpenAI 호환 클라이언트·Slack SDK·**Google Docs API 클라이언트** 등. FastEmbed는 ARM용으로 작은 임베딩 모델(예: 384-dim) 사용 시 4GB에서 동작 가능. |
| **5. API 키** | OpenCode Zen 또는 OpenAI API 키를 `.env` 또는 설정 파일에 저장. Pi는 클라이언트만 하므로 키만 있으면 됨. |
| **6. 메모리·검색** | SQLite DB 및 Markdown 파일을 `~/grumpyClaw` 내에 두고, 하이브리드 검색 스크립트가 로컬에서만 실행되도록 구성. 인덱싱/임베딩은 배치 크기 작게 해서 RAM 절약. |
| **7. 하트비트** | cron: `crontab -e`에 `*/30 * * * * cd /home/pi/grumpyClaw && uv run heartbeat.py` 형태로 30분 주기 등록. (uv가 PATH에 있어야 함; 필요 시 `PATH=$HOME/.local/bin:$PATH`를 crontab 상단에 추가.) |
| **8. Slack (선택)** | Socket Mode 봇으로 실행 시 `uv run slack_bot.py`를 systemd 서비스로 등록해 부팅 시 자동 기동. |
| **9. 확인** | 터미널에서 `uv run`으로 대화 클라이언트 실행, 하트비트 1회 수동 실행, Slack 메시지 수신 테스트. |

> **요약:** 64-bit OS + **uv** + API 전용 LLM + 로컬 FastEmbed/SQLite만 Pi에서 실행. 4GB면 FastEmbed 경량 모델과 적당한 스왑으로 안정 동작 가능.

---

## Google Docs 저널 연동 (Option 1)

**목적:** Google Docs에 적은 저널(작업 로그)을 지식 베이스(SQLite + 임베딩)로 동기화해 검색·LLM 컨텍스트에 활용.

| 항목 | 내용 |
|------|------|
| **어댑터** | `grumpyclaw.adapters.google_docs.GoogleDocsAdapter` — OAuth2로 Docs/Drive API 호출, 문서 본문 추출 후 청크·임베딩·SQLite 저장. |
| **설정** | `.env` 또는 환경변수: `GOOGLE_CREDENTIALS_PATH`(OAuth 클라이언트 JSON 경로), 선택 `GOOGLE_DOCS_FOLDER_ID`(해당 폴더 내 문서만 동기화). |
| **동기화** | `uv run sync-google-docs` 또는 `uv run python -m grumpyclaw.scripts.sync_google_docs`. 최초 실행 시 브라우저로 로그인하여 토큰 발급. |
| **저장 위치** | `data/grumpyclaw.db`(기본) 또는 `GRUMPYCLAW_DB_PATH`. 동일 문서 재동기화 시 기존 청크 삭제 후 재인덱싱. |
| **하트비트 연동** | 30분 주기 하트비트에서 `sync_google_docs`를 호출하거나, cron에 별도 `*/30 * * * * cd ~/grumpyClaw && uv run sync-google-docs` 추가. |