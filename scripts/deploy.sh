#!/usr/bin/env bash
# Cloud Run 배포 스크립트 (ADC 인증)
# 사용법: ./scripts/deploy_cloud_run.sh
# set -euo pipefail

# ─── 설정 ────────────────────────────────────────────────
SERVICE_NAME="metric-bot"
REGION="asia-northeast3"
IMAGE_TAG="latest"

# .env 파일 로드 (프로젝트 루트)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"
if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
  echo "  .env 로드됨: ${ENV_FILE}"
fi

# 필수 환경변수 (미설정 시 스크립트가 종료됨)
: "${GCP_PROJECT_ID:?GCP_PROJECT_ID 환경변수를 설정하세요}"
: "${GEMINI_API_KEY:?GEMINI_API_KEY 환경변수를 설정하세요}"
: "${SLACK_BOT_TOKEN:?SLACK_BOT_TOKEN 환경변수를 설정하세요}"
: "${SLACK_APP_TOKEN:?SLACK_APP_TOKEN 환경변수를 설정하세요}"

# 선택 환경변수 (기본값)
BQ_DATASET="${BQ_DATASET:-onboarding_agent}"
SLACK_WORKSPACE="${SLACK_WORKSPACE:-}"

IMAGE="gcr.io/${GCP_PROJECT_ID}/${SERVICE_NAME}:${IMAGE_TAG}"
# ─────────────────────────────────────────────────────────

echo "=== Cloud Run 배포: ${SERVICE_NAME} ==="
echo "  프로젝트: ${GCP_PROJECT_ID}"
echo "  리전:     ${REGION}"
echo "  이미지:   ${IMAGE}"
echo ""

# ─── 이미지 빌드 & 푸시 ───────────────────────────────────
echo "[1/2] 이미지 빌드 & 푸시 (Cloud Build)..."
gcloud builds submit \
  --tag "${IMAGE}" \
  --project "${GCP_PROJECT_ID}" \
  .
echo "  완료: ${IMAGE}"
echo ""

# ─── Cloud Run 배포 ───────────────────────────────────────
echo "[2/2] Cloud Run 배포..."

ENV_VARS="GCP_PROJECT_ID=${GCP_PROJECT_ID}"
ENV_VARS+=",BQ_DATASET=${BQ_DATASET}"
ENV_VARS+=",GEMINI_API_KEY=${GEMINI_API_KEY}"
ENV_VARS+=",SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN}"
ENV_VARS+=",SLACK_APP_TOKEN=${SLACK_APP_TOKEN}"
if [[ -n "${SLACK_WORKSPACE}" ]]; then
  ENV_VARS+=",SLACK_WORKSPACE=${SLACK_WORKSPACE}"
fi
if [[ -n "${RERANKER_ENABLED}" ]]; then
  ENV_VARS+=",RERANKER_ENABLED=${RERANKER_ENABLED}"
fi

if gcloud run services describe "${SERVICE_NAME}" \
    --region "${REGION}" \
    --project "${GCP_PROJECT_ID}" &>/dev/null; then
  echo "  기존 서비스 감지 → 이미지 + 환경변수 업데이트"
  gcloud run deploy "${SERVICE_NAME}" \
    --image "${IMAGE}" \
    --region "${REGION}" \
    --project "${GCP_PROJECT_ID}" \
    --update-env-vars "${ENV_VARS}"
else
  echo "  신규 서비스 생성"
  gcloud run deploy "${SERVICE_NAME}" \
    --image "${IMAGE}" \
    --region "${REGION}" \
    --project "${GCP_PROJECT_ID}" \
    --set-env-vars "${ENV_VARS}" \
    --cpu 1 \
    --memory 512Mi \
    --min-instances 1 \
    --max-instances 3 \
    --timeout 60 \
    --concurrency 80 \
    --labels=run_service_name=${SERVICE_NAME} \
    --no-allow-unauthenticated
fi

echo ""
echo "=== 배포 완료 ==="
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region "${REGION}" \
  --project "${GCP_PROJECT_ID}" \
  --format "value(status.url)")
echo "  URL: ${SERVICE_URL}"
echo "  헬스체크: curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" ${SERVICE_URL}/health"
