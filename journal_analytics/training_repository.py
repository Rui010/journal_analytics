"""Read-only DynamoDB access for training records."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from .training import local_date_from_raw_datetime


DEFAULT_REGION = "ap-northeast-1"
DEFAULT_TABLE = "Trainings"
_PROJECTION = "create_datetime, menu, part, #weight, rep, #set"
_NAMES = {"#weight": "weight", "#set": "set"}
_DELETE_FILTER = "attribute_not_exists(delete_date) OR delete_date = :empty"


def fetch_training_records(start_date: date, end_date: date) -> list[dict[str, Any]]:
    """Scan only non-deleted, non-identifying fields and filter the date locally."""
    import boto3

    resource = boto3.resource(
        "dynamodb", region_name=os.getenv("TRAINING_AWS_REGION", DEFAULT_REGION)
    )
    table = resource.Table(os.getenv("TRAINING_DYNAMODB_TABLE", DEFAULT_TABLE))
    scan_args: dict[str, Any] = {
        "ProjectionExpression": _PROJECTION,
        "ExpressionAttributeNames": _NAMES,
        "FilterExpression": _DELETE_FILTER,
        "ExpressionAttributeValues": {":empty": ""},
    }
    records: list[dict[str, Any]] = []
    while True:
        response = table.scan(**scan_args)
        for item in response.get("Items", []):
            item_date = local_date_from_raw_datetime(item.get("create_datetime"))
            if item_date and start_date <= item_date <= end_date:
                records.append(item)
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return records
        scan_args["ExclusiveStartKey"] = last_key
