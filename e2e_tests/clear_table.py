import boto3

# --- Configuration ---
TABLE_NAME = "data-aggregator-idempotency-dev"
REGION_NAME = "eu-west-2"  # e.g., 'eu-west-2'
# --------------------

dynamodb = boto3.resource("dynamodb", region_name=REGION_NAME)
table = dynamodb.Table(TABLE_NAME)

# Get the primary key name from the table schema
primary_key = table.key_schema[0]["AttributeName"]

# Use a paginator to handle tables of any size
paginator = table.meta.client.get_paginator("scan")
item_count = 0

print(f"Scanning table '{TABLE_NAME}' to find items to delete...")

# Use batch_writer to efficiently delete items in batches
with table.batch_writer() as batch:
    # Iterate through each page of scan results, only fetching the primary key
    for page in paginator.paginate(
        TableName=TABLE_NAME, ProjectionExpression=primary_key
    ):
        for item in page.get("Items", []):
            item_count += 1
            batch.delete_item(Key=item)
            # Optional: print progress
            if item_count % 100 == 0:
                print(f"Found {item_count} items so far...")

if item_count > 0:
    print(f"\nFinished scanning. Deleting a total of {item_count} items...")
    # The batch_writer automatically sends delete requests when the 'with' block exits.
    print("✅ All items deleted successfully.")
else:
    print("Table is already empty.")
