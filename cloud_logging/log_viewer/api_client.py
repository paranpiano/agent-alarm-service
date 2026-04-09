"""Cloud log API client - queries DynamoDB logs via API Gateway."""

import logging
from datetime import date, timedelta

import requests

logger = logging.getLogger(__name__)

# Private API (VPC Endpoint DNS 방식) - dev/prod 공통
DEFAULT_API_URL = "https://j28ud38ww4-vpce-0ad8bea3eea59f0ed.execute-api.eu-central-1.amazonaws.com/prod/logs"


class LogApiClient:
    def __init__(self, api_url: str = DEFAULT_API_URL) -> None:
        self._url = api_url

    def get_logs(self, log_date: str | None = None, limit: int = 200) -> list[dict]:
        """날짜별 로그 조회. log_date 미입력 시 오늘."""
        params: dict = {"limit": limit}
        if log_date:
            params["date"] = log_date
        resp = requests.get(self._url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("logs", [])

    def get_logs_range(self, days: int = 3) -> list[dict]:
        """최근 N일 로그를 합쳐서 반환 (최신순)."""
        all_logs: list[dict] = []
        for i in range(days):
            d = (date.today() - timedelta(days=i)).strftime("%Y-%m-%d")
            try:
                all_logs.extend(self.get_logs(log_date=d))
            except Exception as exc:
                logger.warning("날짜 %s 로그 조회 실패: %s", d, exc)
        return sorted(all_logs, key=lambda l: str(l.get("timestamp", "")), reverse=True)
