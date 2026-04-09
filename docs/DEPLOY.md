# 배포 가이드

## 전체 구조

```
[Airflow 서버]  vCPU 2 / 16GB
  06:00  notion_extract_load   → Notion API → BigQuery raw
  06:30  slack_extract_load    → Slack API  → BigQuery raw
  완료 후 enterprise_embed    → dbt run → 임베딩 → BigQuery vectors

[Cloud Run Service: onboarding-agent]
  FastAPI → BigQuery Vector Search → 응답
```

두 컴포넌트는 BigQuery를 통해서만 연결되며 독립적으로 배포한다.

---

## 1. Airflow 서버 설정

Airflow를 별도 레포(`/opt/airflow/`)로 관리하는 환경 기준.

### 1-1. 파일 배포

onboarding-agent 레포에서 아래 3개 폴더를 Airflow 레포로 복사한다.

```bash
# DAG 파일 (4개)
cp dags/*.py /opt/airflow/dags/

# pipeline 모듈 → dags/ 하위에 배치 (Airflow가 dags/를 sys.path에 추가하므로 import 가능)
cp -r pipeline/ /opt/airflow/dags/pipeline/

# dbt 프로젝트 → Airflow 루트에 배치 (enterprise_embed DAG이 상대경로로 참조)
cp -r dbt_notion/ /opt/airflow/dbt_notion/
```

최종 구조:

```
/opt/airflow/
├── dags/
│   ├── notion_extract_load.py
│   ├── slack_extract_load.py
│   ├── enterprise_embed.py
│   ├── drip_campaign.py
│   └── pipeline/              # ← from pipeline.xxx import 가 동작하려면 여기
│       ├── __init__.py
│       ├── extract/
│       ├── embed/
│       └── drip/
├── dbt_notion/                # ← subprocess에서 상대경로 "dbt_notion"으로 접근
│   ├── dbt_project.yml
│   ├── profiles.yml
│   ├── seeds/
│   ├── macros/
│   └── models/
├── plugins/
├── data/
└── logs/
```

> **`app/`, `tests/`, `scripts/`는 배포 불필요** — 서빙 레이어(Cloud Run)와 개발용이다.

### 1-2. Python 의존성 설치

```bash
pip install notion-client slack-sdk slack-bolt google-cloud-bigquery google-genai dbt-bigquery tenacity
```

### 1-3. 환경변수 등록

Airflow UI → Admin → Variables:


| Key                 | 설명                                     |
| ------------------- | -------------------------------------- |
| `GCP_PROJECT_ID`    | GCP 프로젝트 ID                            |
| `BQ_DATASET`        | BigQuery 데이터셋 (기본: `onboarding_agent`) |
| `GEMINI_API_KEY`    | Gemini API 키                           |
| `NOTION_API_KEY`    | Notion 통합 토큰                           |
| `SLACK_BOT_TOKEN`   | Slack Bot 토큰                           |
| `SLACK_WORKSPACE`   | Slack 워크스페이스 서브도메인                     |
| `SLACK_CHANNEL_IDS` | 수집 대상 채널 ID (쉼표 구분, 선택)                |


### 1-4. BigQuery 인증

```bash
# 서비스 계정 키 방식
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json

# GCE 인스턴스라면 인스턴스 기반 인증 자동 적용
```

### 1-5. dbt profiles 확인

`enterprise_embed` DAG이 아래 경로에서 dbt를 실행한다.

```bash
dbt run --project-dir dbt_notion --profiles-dir dbt_notion
```

Airflow worker의 cwd가 `/opt/airflow/`가 아닌 경우, 환경변수 `DBT_PROJECT_DIR`을 절대 경로로 설정한다.

`dbt_notion/profiles.yml`의 BigQuery 인증 방식(oauth / service account)이 서버 환경과 맞는지 확인한다.

### 1-6. 스케줄


| DAG                   | 스케줄           | 실행 시각 (KST)         |
| --------------------- | ------------- | ------------------- |
| `notion_extract_load` | `0 21 * * *`  | 매일 06:00            |
| `slack_extract_load`  | `30 21 * * *` | 매일 06:30            |
| `enterprise_embed`    | trigger only  | 위 두 DAG 완료 후 자동 트리거 |


---

## 2. Cloud Run Service (FastAPI 서빙)

### 2-1. 이미지 빌드 & 푸시

```bash
gcloud builds submit \
  --tag gcr.io/<PROJECT_ID>/onboarding-agent \
  .
```

### 2-2. 배포

```bash
gcloud run deploy onboarding-agent \
  --image gcr.io/<PROJECT_ID>/onboarding-agent \
  --region asia-northeast3 \
  --service-account <SA>@<PROJECT_ID>.iam.gserviceaccount.com \
  --set-env-vars GCP_PROJECT_ID=<PROJECT_ID>,BQ_DATASET=onboarding_agent,GEMINI_API_KEY=<KEY>,SLACK_BOT_TOKEN=<TOKEN> \
  --allow-unauthenticated
```

내부망 전용이면 `--no-allow-unauthenticated` 후 IAP 또는 VPC Connector 설정.

업데이트 시:

```bash
gcloud builds submit --tag gcr.io/<PROJECT_ID>/onboarding-agent .
gcloud run deploy onboarding-agent \
  --image gcr.io/<PROJECT_ID>/onboarding-agent \
  --region asia-northeast3
```

---

## 3. 서비스 계정 권한


| 권한                          | 이유                 |
| --------------------------- | ------------------ |
| `roles/bigquery.dataEditor` | BigQuery 테이블 읽기/쓰기 |
| `roles/bigquery.jobUser`    | BigQuery 쿼리 실행     |


---

## 4. 배포 순서 (최초)

1. BigQuery 데이터셋 생성 (또는 dbt로 초기화)
2. Airflow 서버에 프로젝트 clone + 의존성 설치 + 환경변수 등록
3. Airflow에서 `notion_extract_load` 수동 트리거 → 초기 적재 확인
4. Cloud Run Service 이미지 빌드 & 배포
5. `POST /search` 호출로 동작 확인

---

## 5. 배포 대상 정리


| 컴포넌트       | 위치                | 포함 파일                               |
| ---------- | ----------------- | ----------------------------------- |
| 데이터 파이프라인  | Airflow 서버        | `dags/`, `pipeline/`, `dbt_notion/` |
| FastAPI 서빙 | Cloud Run Service | `app/`                              |


