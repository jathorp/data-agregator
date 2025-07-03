# # app.py
# """
# Main AWS Lambda handler for the Data Aggregation Pipeline.
# ... (docstring is the same) ...
# """
#
# import json
# import os
# import queue
# import tarfile
# import tempfile
# import threading
# from concurrent.futures import ThreadPoolExecutor
# from datetime import datetime, timezone
# from typing import Dict, Optional
# from urllib.parse import unquote
#
# import requests
# from aws_lambda_powertools import Logger, Metrics, Tracer
# from aws_lambda_powertools.metrics import MetricUnit
# from aws_lambda_powertools.utilities.data_classes import SQSRecord
# from aws_lambda_powertools.utilities.parameters import SecretsProvider
# from aws_lambda_powertools.utilities.typing import LambdaContext
#
# from . import clients, core
#
#
# # --- 1. SETUP: Configuration (No changes here) ---
#
# def get_env_var(name: str, default: Optional[str] = None) -> str:
#     value = os.environ.get(name, default)
#     if value is None:
#         raise ValueError(f"FATAL: Environment variable '{name}' is not set.")
#     return value
#
#
# # ... (all environment variable declarations are the same) ...
# POWERTOOLS_SERVICE_NAME = get_env_var("POWERTOOLS_SERVICE_NAME", "DataAggregator")
# POWERTOOLS_METRICS_NAMESPACE = get_env_var("POWERTOOLS_METRICS_NAMESPACE", "DataMovePipeline")
# LANDING_BUCKET = get_env_var("LANDING_BUCKET")
# QUEUE_URL = get_env_var("QUEUE_URL")
# IDEMPOTENCY_TABLE = get_env_var("IDEMPOTENCY_TABLE")
# ENVIRONMENT = get_env_var("ENVIRONMENT", "dev")
# SECRET_CACHE_TTL_SECONDS = int(get_env_var("SECRET_CACHE_TTL_SECONDS", "300"))
# MAX_FETCH_WORKERS = int(get_env_var("MAX_FETCH_WORKERS", "8"))
# SPOOL_MAX_MEMORY_BYTES = int(get_env_var("SPOOL_MAX_MEMORY_BYTES", "268435456"))
# ARCHIVE_TIMEOUT_SECONDS = int(get_env_var("ARCHIVE_TIMEOUT_SECONDS", "300"))
# QUEUE_PUT_TIMEOUT_SECONDS = int(get_env_var("QUEUE_PUT_TIMEOUT_SECONDS", "5"))
# MAX_FILE_SIZE_BYTES = int(get_env_var("MAX_FILE_SIZE_BYTES", "5242880"))
# IDEMPOTENCY_TTL_HOURS = int(get_env_var("IDEMPOTENCY_TTL_HOURS", "192"))
# NIFI_SECRET_ID = get_env_var("NIFI_SECRET_ID")
# NIFI_ENDPOINT_URL = get_env_var("NIFI_ENDPOINT_URL")
# NIFI_REQUEST_TIMEOUT_SECONDS = int(get_env_var("NIFI_REQUEST_TIMEOUT_SECONDS", "60"))
#
# logger = Logger(service=POWERTOOLS_SERVICE_NAME)
# metrics = Metrics(namespace=POWERTOOLS_METRICS_NAMESPACE)
# tracer = Tracer(service=POWERTOOLS_SERVICE_NAME)
# secrets_provider = SecretsProvider()
# S3, SQS, DDB, _ = clients.get_boto_clients()
#
#
# # --- 2. STATEFUL & ORCHESTRATION LOGIC ---
#
# @tracer.capture_method
# def post_archive_to_nifi(
#         s3_keys: list[str], archive_filename: str, context: LambdaContext
# ) -> None:
#     # ... (This function remains mostly the same, but with the _writer fix) ...
#     data_queue: queue.Queue = queue.Queue(maxsize=MAX_FETCH_WORKERS)
#     error_queue: queue.Queue = queue.Queue()
#     error_event = threading.Event()
#
#     @tracer.capture_method
#     def _fetcher(key: str):
#         # This function is unchanged
#         s3_obj = None
#         try:
#             s3_obj = S3.get_object(Bucket=LANDING_BUCKET, Key=key)
#             content_length = s3_obj["ContentLength"]
#             if content_length > MAX_FILE_SIZE_BYTES:
#                 raise ValueError(f"File {key} ({content_length} bytes) exceeds max size.")
#             data_queue.put(
#                 (key, s3_obj["Body"], content_length), timeout=QUEUE_PUT_TIMEOUT_SECONDS
#             )
#         except queue.Full:
#             err = RuntimeError("Queue full; writer thread may be stalled or too slow.")
#             logger.warning("Back-pressure detected.", extra={"error": str(err), "key": key})
#             metrics.add_metric(name="QueuePutStalled", unit=MetricUnit.Count, value=1)
#             if s3_obj and s3_obj.get("Body"):
#                 try:
#                     s3_obj["Body"].close()
#                 except Exception as close_exc:
#                     logger.warning("Failed to close S3 stream.", extra={"exc": str(close_exc)})
#             error_queue.put(err)
#             error_event.set()
#         except Exception as fetch_err:
#             if s3_obj and s3_obj.get("Body"):
#                 try:
#                     s3_obj["Body"].close()
#                 except Exception as close_exc:
#                     logger.warning("Failed to close S3 stream.", extra={"exc": str(close_exc)})
#             logger.exception(f"Fetcher thread failed for key {key}")
#             error_queue.put(fetch_err)
#             error_event.set()
#
#     @tracer.capture_method
#     def _writer(spooled_file: tempfile.SpooledTemporaryFile):
#         seen_base_names: Dict[str, int] = {}
#         try:
#             with tarfile.open(fileobj=spooled_file, mode="w:gz") as tar:
#                 # The loop correctly relies on the sentinel (None) to terminate.
#                 while True:
#                     try:
#                         item = data_queue.get(block=True, timeout=0.1)
#                         if item is None:  # Sentinel value received
#                             break
#                         key, body_stream, size = item
#                         try:
#                             basename = os.path.basename(key)
#                             if basename in seen_base_names:
#                                 seen_base_names[basename] += 1
#                                 name, ext = os.path.splitext(basename)
#                                 unique_name = f"{name}({seen_base_names[basename]}){ext}"
#                             else:
#                                 seen_base_names[basename] = 0
#                                 unique_name = basename
#
#                             tarinfo = tarfile.TarInfo(name=unique_name)
#                             tarinfo.size = size
#                             tar.addfile(tarinfo, body_stream)
#                         finally:
#                             body_stream.close()
#                             data_queue.task_done()
#                     except queue.Empty:
#                         # FIX #1: The incorrect 'executor.done()' check is removed.
#                         # If the queue is empty, we just continue waiting for more items
#                         # or the sentinel value. This is expected behavior.
#                         if error_event.is_set():
#                             break  # An error in a fetcher occurred, exit early.
#                         continue
#         except Exception as writer_err:
#             logger.exception("Writer thread failed")
#             error_queue.put(writer_err)
#             error_event.set()
#
#     executor = ThreadPoolExecutor(max_workers=MAX_FETCH_WORKERS)
#     try:
#         with tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_MEMORY_BYTES, mode="w+b") as spooled_archive:
#             writer_thread = threading.Thread(name="tar-writer", target=_writer, args=(spooled_archive,))
#             writer_thread.start()
#
#             for s3_key in s3_keys:
#                 if error_event.is_set(): break
#                 executor.submit(_fetcher, s3_key)
#
#             # This blocks until all fetcher tasks are complete.
#             executor.shutdown(wait=True)
#             # Only after all fetchers are done, we signal the writer to finish.
#             data_queue.put(None)
#
#             join_timeout = (context.get_remaining_time_in_millis() / 1000.0) - 5.0
#             writer_thread.join(timeout=join_timeout)
#
#             if not error_queue.empty():
#                 raise error_queue.get()
#
#             if writer_thread.is_alive():
#                 error_event.set()
#                 raise TimeoutError("Archive writer thread timed out.")
#
#             spooled_archive.flush()
#             archive_size_bytes = spooled_archive.tell()
#             metrics.add_metric(name="ArchiveSizeBytes", unit=MetricUnit.Bytes, value=archive_size_bytes)
#
#             spooled_archive.seek(0)
#             try:
#                 secret_data: dict = secrets_provider.get(
#                     NIFI_SECRET_ID, max_age=SECRET_CACHE_TTL_SECONDS, transform="json"
#                 )
#                 api_key = secret_data.get("api_key")
#                 if not api_key:
#                     raise ValueError(f"Secret {NIFI_SECRET_ID} is missing 'api_key' field.")
#
#                 headers = {
#                     "Content-Type": "application/gzip",
#                     "Authorization": f"Bearer {api_key}",
#                     "X-Filename": archive_filename,
#                 }
#                 logger.info(f"Posting archive to NiFi endpoint: {NIFI_ENDPOINT_URL}")
#                 response = requests.post(
#                     NIFI_ENDPOINT_URL, data=spooled_archive, headers=headers, timeout=NIFI_REQUEST_TIMEOUT_SECONDS
#                 )
#                 response.raise_for_status()
#                 logger.info(
#                     "Successfully posted archive to NiFi.",
#                     extra={"status_code": response.status_code, "response": response.text},
#                 )
#             except requests.exceptions.RequestException:
#                 logger.exception("Failed to post archive to NiFi endpoint.")
#                 metrics.add_metric(name="NiFiUploadFailed", unit=MetricUnit.Count, value=1)
#                 raise
#     finally:
#         executor.shutdown(wait=False, cancel_futures=True)
#
#
# # --- 3. LAMBDA HANDLER ---
#
# @tracer.capture_lambda_handler
# @logger.inject_lambda_context(log_event=False)
# @metrics.log_metrics(capture_cold_start_metric=True)
# def handler(event: dict, context: LambdaContext):
#     metrics.add_dimension(name="Environment", value=ENVIRONMENT)
#
#     records_to_process = []
#     failed_message_ids = []
#     for record_data in event.get("Records", []):
#         try:
#             sqs_record = SQSRecord(record_data)
#             message_content = json.loads(sqs_record.body)
#             s3_key = unquote(message_content['Records'][0]['s3']['object']['key'])
#             records_to_process.append({'s3_key': s3_key, 'message_id': sqs_record.message_id})
#         except (json.JSONDecodeError, KeyError, IndexError, TypeError):
#             logger.exception("Failed to parse SQS message.", extra={"record": record_data})
#             failed_message_ids.append(record_data.get("messageId"))
#
#     # FIX #2: Use the new functions from the corrected core.py
#     idempotency_table = DDB.Table(IDEMPOTENCY_TABLE)
#     unique_records = core.filter_out_processed_keys(records_to_process, idempotency_table, logger)
#
#     if not unique_records:
#         logger.info("No new unique files to process in this batch.")
#         return {"batchItemFailures": []}
#
#     s3_keys = [rec['s3_key'] for rec in unique_records]
#     try:
#         logger.info(f"Starting archive for {len(unique_records)} unique files.")
#         archive_filename = f"archive-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{context.aws_request_id}.tar.gz"
#
#         post_archive_to_nifi(s3_keys, archive_filename, context)
#
#         logger.info("Successfully processed batch.", extra={"output_filename": archive_filename})
#
#         # COMMIT STATE only after the NiFi post succeeds
#         core.commit_processed_keys(unique_records, idempotency_table, IDEMPOTENCY_TTL_HOURS, logger)
#
#     except Exception:
#         logger.exception("Failed to create or post archive. Reporting batch failure.")
#         # Add message IDs from unique (but failed) records to the failure list
#         for record in unique_records:
#             failed_message_ids.append(record['message_id'])
#
#     return {
#         "batchItemFailures": [{"itemIdentifier": mid} for mid in failed_message_ids if mid]
#     }