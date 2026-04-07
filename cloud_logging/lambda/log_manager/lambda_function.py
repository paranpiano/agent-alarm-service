"""
AI Alarm Log Manager - Lambda Function
POST /logs  : Save a judgment log entry to DynamoDB
GET  /logs  : Query log entries (by date or request_id)
"""

import json
import os
from decimal import Decimal
import boto3
from datetime import datetime
from boto3.dynamodb.conditions import Key

TABLE_NAME = os.environ.get("TABLE_NAME", "ai-alarm-logs")
dynamodb = boto3.resource("dynamodb", region_name="eu-central-1")
table = dynamodb.Table(TABLE_NAME)


def _default(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, ensure_ascii=False, default=_default),
    }


def handle_post(body: dict) -> dict:
    """Save a log entry. Partition key: log_date (YYYY-MM-DD), Sort key: request_id"""
    required = ["request_id", "timestamp", "status"]
    for field in required:
        if field not in body:
            return _response(400, {"error": f"Missing required field: {field}"})

    timestamp = body["timestamp"]
    try:
        log_date = datetime.fromisoformat(timestamp).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        log_date = datetime.utcnow().strftime("%Y-%m-%d")

    item = {
        "log_date": log_date,
        "request_id": body["request_id"],
        "timestamp": timestamp,
        "status": body["status"],
        "reason": body.get("reason", ""),
        "image_name": body.get("image_name", ""),
        "processing_time_ms": body.get("processing_time_ms", 0),
        "equipment_data": json.dumps(body.get("equipment_data") or {}, ensure_ascii=False),
    }

    table.put_item(Item=item)
    return _response(200, {"message": "Log saved", "request_id": body["request_id"], "log_date": log_date})


def _parse_equipment_data(item: dict) -> dict:
    """equipment_data JSON 문자열을 dict로 파싱."""
    if "equipment_data" in item and isinstance(item["equipment_data"], str):
        try:
            item["equipment_data"] = json.loads(item["equipment_data"])
        except Exception:
            pass
    return item


def handle_get(params: dict) -> dict:
    """Query logs by date (required). Optionally filter by request_id."""
    log_date = params.get("date")
    if not log_date:
        # default: today
        log_date = datetime.utcnow().strftime("%Y-%m-%d")

    request_id = params.get("request_id")
    exclusive_start_key = params.get("last_key")

    if request_id:
        resp = table.get_item(Key={"log_date": log_date, "request_id": request_id})
        item = resp.get("Item")
        if not item:
            return _response(404, {"error": "Log not found"})
        return _response(200, {"logs": [_parse_equipment_data(item)]})

    query_kwargs = {
        "KeyConditionExpression": Key("log_date").eq(log_date),
        "ScanIndexForward": True,
    }
    if exclusive_start_key:
        try:
            query_kwargs["ExclusiveStartKey"] = json.loads(exclusive_start_key)
        except Exception:
            pass

    resp = table.query(**query_kwargs)
    items = [_parse_equipment_data(item) for item in resp.get("Items", [])]
    last_key = resp.get("LastEvaluatedKey")

    result = {"logs": items, "count": len(items), "date": log_date}
    if last_key:
        result["last_key"] = json.dumps(last_key, default=_default)
    return _response(200, result)


def lambda_handler(event, context):
    http_method = event.get("httpMethod", "")
    path = event.get("path", "")

    # CORS preflight
    if http_method == "OPTIONS":
        return _response(200, {})

    if http_method == "POST" and path.rstrip("/") in ("/logs", "/prod/logs"):
        try:
            body = json.loads(event.get("body") or "{}")
        except json.JSONDecodeError:
            return _response(400, {"error": "Invalid JSON body"})
        return handle_post(body)

    if http_method == "GET" and path.rstrip("/") in ("/logs", "/prod/logs"):
        params = event.get("queryStringParameters") or {}
        return handle_get(params)

    return _response(404, {"error": f"Not found: {http_method} {path}"})
