# # tests/unit/test_app.py
# import json
# import time
# from unittest.mock import patch, MagicMock
#
# import pytest
#
# # Official Powertools constants for better test hygiene
# from aws_lambda_powertools.utilities.idempotency.persistence.base import (
#     STATUS_CONSTANTS,
# )
#
# # Botocore Stubber for strict, high-fidelity mocking of boto3
# from botocore.stub import Stubber, ANY
#
#
# # --- Fixtures (no changes here) ---
# @pytest.fixture(autouse=True)
# def set_env_vars(monkeypatch):
#     monkeypatch.setenv("IDEMPOTENCY_TABLE", "dummy-idempotency-table")
#     monkeypatch.setenv("TARGET_TABLE", "dummy-target-table")
#     monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
#
#
# @pytest.fixture
# def sqs_event():
#     return {
#         "Records": [
#             {
#                 "messageId": "12345-67890",
#                 "body": '{"product_id": "P123", "quantity": 10}',
#             }
#         ]
#     }
#
#
# @pytest.fixture
# def lambda_context():
#     context = MagicMock()
#     context.function_name = "test-function"
#     context.memory_limit_in_mb = 128
#     context.invoked_function_arn = "arn:aws:lambda:eu-west-1:809313241:function:test"
#     context.aws_request_id = "52fdfc07-2182-154f-163f-5f0f9a621d72"
#     context.get_remaining_time_in_millis.return_value = 100000
#     return context
#
#
# # --- Tests using the official patterns ---
#
#
# def test_handler_logic_with_idempotency_disabled(
#     sqs_event, lambda_context, monkeypatch
# ):
#     """(Priority 1 Suggestion) Tests business logic.
#     Pytest's monkeypatch fixture automatically handles teardown,
#     ensuring POWERTOOLS_IDEMPOTENCY_DISABLED is unset after this test,
#     preventing test pollution.
#     """
#     monkeypatch.setenv("POWERTOOLS_IDEMPOTENCY_DISABLED", "true")
#
#     mock_ddb_table = MagicMock()
#     with patch("data_aggregator.app.boto3.resource") as mock_boto3_resource:
#         mock_boto3_resource.return_value.Table.return_value = mock_ddb_table
#         from data_aggregator.app import lambda_handler
#
#         result = lambda_handler(sqs_event, lambda_context)
#
#     assert result["status"] == "processed"
#     mock_ddb_table.put_item.assert_called_once_with(Item=sqs_event["Records"][0])
#
#
# def test_handler_is_idempotent_with_stubber(sqs_event, lambda_context, mocker):
#     """(Priority 2 Suggestion) Tests idempotency using the strict Botocore Stubber."""
#     from data_aggregator.app import persistence_layer, lambda_handler
#
#     # The Stubber is stricter than MagicMock. It will only allow calls
#     # that match the exact parameters you define.
#     stubber = Stubber(persistence_layer.client)
#
#     saved_result = {"status": "processed", "messageId": "12345-67890"}
#     mocker.patch("data_aggregator.app.process_message", return_value=saved_result)
#
#     # --- SIMULATE THE FIRST CALL ---
#     # The Stubber has revealed the true internal calls:
#     # 1. A `put_item` call to save the "INPROGRESS" status.
#     # 2. An `update_item` call to set the status to "COMPLETED" and add the result.
#     stubber.add_response("put_item", {})
#     stubber.add_response("update_item", {})  # THIS IS THE FIX
#
#     with stubber:
#         lambda_handler(sqs_event, lambda_context)
#         stubber.assert_no_pending_responses()  # Ensure all expected calls were made
#
#     # --- SIMULATE THE SECOND CALL ---
#     # a) Simulate "item already exists" by making the 'put_item' call fail
#     #    with a ConditionalCheckFailedException.
#     stubber.add_client_error(
#         method="put_item", service_error_code="ConditionalCheckFailedException"
#     )
#
#     # b) Simulate the subsequent 'get_item' call, returning the saved record.
#     #    (Priority 1 Suggestion) Use the official constant for status.
#     future_timestamp = int(time.time()) + 3600
#     dynamodb_item_response = {
#         "Item": {
#             "id": {"S": "some-idempotency-key"},
#             "data": {"S": json.dumps(saved_result)},
#             "status": {"S": STATUS_CONSTANTS["COMPLETED"]},  # Using the constant
#             "expiration": {"N": str(future_timestamp)},
#         }
#     }
#     expected_get_params = {"TableName": ANY, "Key": ANY, "ConsistentRead": ANY}
#     stubber.add_response("get_item", dynamodb_item_response, expected_get_params)
#
#     with stubber:
#         second_call_result = lambda_handler(sqs_event, lambda_context)
#         stubber.assert_no_pending_responses()
#
#     assert second_call_result == saved_result
