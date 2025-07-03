locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment_name
    ManagedBy   = "Terraform"
  }
}

# We will define the S3 landing bucket here.
# For now, we are not using the 'modules/s3_bucket' yet, just showing the pattern.
resource "aws_s3_bucket" "landing" {
  bucket = var.landing_bucket_name
  tags   = merge(local.common_tags, { Name = var.landing_bucket_name })
}

resource "aws_s3_bucket_versioning" "landing" {
  bucket = aws_s3_bucket.landing.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Example of using data from the network component.
# We could use data.terraform_remote_state.network.outputs.vpc_id if needed.
# For now, we just prove it can be read.