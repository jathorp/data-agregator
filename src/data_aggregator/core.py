# # core.py
# """
# Core business logic for the Data Aggregation Pipeline.
#
# These functions are designed to be "pure" and testable. They handle the critical
# idempotency logic by interacting with DynamoDB.
# """
# import hashlib
# from datetime import datetime, timedelta, timezone
# from typing import Any, Dict, List
# from urllib.parse import unquote
#
# from aws_lambda_powertools import Logger
# from botocore.exceptions import ClientError
#
# # Import boto3 stubs for full type-safety in function signatures
# from mypy_boto3_dynamodb.service_resource import Table
# # --- FIX: Import only the type definition that actually exists and is needed. ---
# from mypy_boto3_dynamodb.type_defs import KeysAndAttributesTypeDef
#
# # DynamoDB BatchGetItem has a limit of 100 keys per request
# BATCH_GET_MAX_KEYS = 100
#
#
# def _get_sharded_object_id(s3_key: str) -> str:
#     """
#     Creates a sharded, unique ID for a given S3 key to ensure good
#     key distribution in DynamoDB.
#     """
#     object_id = unquote(s3_key)
#     hash_prefix = hashlib.sha1(object_id.encode()).hexdigest()[:4]
#     return f"{hash_prefix}#{object_id}"
#
#
# def filter_out_processed_keys(
#         records: List[Dict[str, Any]], ddb_table: Table, logger: Logger
# ) -> List[Dict[str, Any]]:
#     """
#     Checks a batch of S3 keys against DynamoDB to find which are new.
#     Uses BatchGetItem for efficiency.
#     ... (args and returns are the same) ...
#     """
#     if not records:
#         return []
#
#     unique_s3_keys = {rec["s3_key"] for rec in records}
#     sharded_keys_to_check = {
#         _get_sharded_object_id(key): key for key in unique_s3_keys
#     }
#     sharded_key_list = list(sharded_keys_to_check.keys())
#
#     found_keys = set()
#     for i in range(0, len(sharded_key_list), BATCH_GET_MAX_KEYS):
#         batch_keys = sharded_key_list[i: i + BATCH_GET_MAX_KEYS]
#         try:
#             # --- FIX: Construct the 'RequestItems' dictionary and pass it directly ---
#             # --- as a keyword argument to the function call. ---
#
#             keys_to_get = [{"ObjectID": key} for key in batch_keys]
#
#             # This structure explicitly matches the KeysAndAttributesTypeDef
#             keys_and_attributes: KeysAndAttributesTypeDef = {"Keys": keys_to_get}
#
#             # The 'RequestItems' dictionary maps table names to the keys we want to fetch.
#             request_items_dict = {
#                 ddb_table.name: keys_and_attributes
#             }
#
#             # Pass the dictionary directly to the 'RequestItems' keyword argument.
#             response = ddb_table.meta.client.batch_get_item(
#                 RequestItems=request_items_dict
#             )
#             # --- FIX END ---
#
#             responses = response.get("Responses", {}).get(ddb_table.name, [])
#             for item in responses:
#                 found_keys.add(item["ObjectID"])
#
#             unprocessed_keys = response.get("UnprocessedKeys", {}).get(ddb_table.name)
#             if unprocessed_keys:
#                 logger.warning(
#                     f"Found {len(unprocessed_keys['Keys'])} unprocessed keys in batch_get_item. "
#                     "These will be treated as 'not found' and may be reprocessed. "
#                     "Consider adding retry logic for production."
#                 )
#
#         except ClientError:
#             logger.exception("Failed to BatchGetItem from DynamoDB for idempotency check.")
#             raise
#
#     processed_s3_keys = {sharded_keys_to_check[sharded] for sharded in found_keys}
#     logger.info(
#         f"Idempotency check: Found {len(processed_s3_keys)} already processed keys "
#         f"out of {len(unique_s3_keys)} unique incoming keys."
#     )
#
#     unique_records = [
#         rec for rec in records if rec["s3_key"] not in processed_s3_keys
#     ]
#     return unique_records
#
#
# def commit_processed_keys(
#         records: List[Dict[str, Any]], ddb_table: Table, ttl_hours: int, logger: Logger
# ) -> None:
#     """
#     Writes idempotency keys for a batch of records to DynamoDB.
#     ... (This function is unchanged and correct) ...
#     """
#     if not records:
#         return
#
#     expires_at = int((datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).timestamp())
#
#     with ddb_table.batch_writer() as batch:
#         for record in records:
#             sharded_id = _get_sharded_object_id(record["s3_key"])
#             batch.put_item(
#                 Item={
#                     "ObjectID": sharded_id,
#                     "ExpiresAt": expires_at,
#                     "SQSMessageID": record["message_id"],
#                 }
#             )
#     logger.info(f"Successfully committed {len(records)} idempotency keys to DynamoDB.")