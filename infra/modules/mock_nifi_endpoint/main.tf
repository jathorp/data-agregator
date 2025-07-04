# modules/mock_nifi_endpoint/main.tf

locals {
  name_prefix = "${var.project_name}-mock-nifi-${var.environment_name}"
  common_tags = {
    Project     = var.project_name
    Environment = var.environment_name
    ManagedBy   = "Terraform"
    Purpose     = "Mock NiFi Endpoint"
  }
}

# 1. Security Group for the ALB, allowing inbound HTTPS from the Lambda
resource "aws_security_group" "alb_sg" {
  name        = "${local.name_prefix}-sg"
  description = "Allow inbound HTTPS for the mock NiFi ALB"
  vpc_id      = var.vpc_id
  tags        = local.common_tags

  # We will define the ingress rule in the main application component,
  # referencing the Lambda's security group ID for tight coupling.
}

# 2. The Application Load Balancer itself
resource "aws_lb" "mock_nifi" {
  name               = local.name_prefix
  internal           = true # IMPORTANT: This keeps the ALB private to the VPC
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets            = var.public_subnet_ids # Place ALB nodes in public subnets for resilience

  # Enable access logging to verify requests from the Lambda
  access_logs {
    bucket  = aws_s3_bucket.access_logs.id
    prefix  = "alb-logs"
    enabled = true
  }

  tags = local.common_tags
}

# 3. An S3 bucket to store the ALB access logs
resource "aws_s3_bucket" "access_logs" {
  bucket = "${local.name_prefix}-access-logs-${random_id.bucket_suffix.hex}"
  tags   = local.common_tags
}

resource "random_id" "bucket_suffix" {
  byte_length = 8
}

# Ensure the ALB can write to the S3 bucket
resource "aws_s3_bucket_policy" "access_logs_policy" {
  bucket = aws_s3_bucket.access_logs.id
  policy = data.aws_iam_policy_document.s3_policy.json
}

data "aws_iam_policy_document" "s3_policy" {
  statement {
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.access_logs.arn}/*"]
  }
}

data "aws_caller_identity" "current" {}


# 4. A "Fixed Response" Target Group
# This is the magic part. It tells the ALB to simply return a 200 OK
# without forwarding the request to any real backend server.
resource "aws_lb_target_group" "fixed_response" {
  name        = "${local.name_prefix}-tg"
  port        = 443
  protocol    = "HTTPS"
  vpc_id      = var.vpc_id
  target_type = "lambda" # Must be 'lambda' for fixed-response, even though we don't register one.
  tags        = local.common_tags
}

# 5. The HTTPS Listener
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.mock_nifi.arn
  port              = "443"
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-2016-08"
  certificate_arn   = aws_acm_certificate.self_signed.arn # Use a self-signed cert for dev

  # The default action is to use our fixed-response target group
  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Mock NiFi received the request successfully."
      status_code  = "200"
    }
  }
}

# 6. A self-signed certificate for the HTTPS listener (for dev/test only)
resource "tls_private_key" "self_signed" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "self_signed" {
  private_key_pem = tls_private_key.self_signed.private_key_pem

  subject {
    common_name  = "mock-nifi.dev.internal"
    organization = "Dev Environment"
  }

  validity_period_hours = 8760 # 1 year
  allowed_uses = [
    "key_encipherment",
    "digital_signature",
    "server_auth",
  ]
}

resource "aws_acm_certificate" "self_signed" {
  private_key      = tls_private_key.self_signed.private_key_pem
  certificate_body = tls_self_signed_cert.self_signed.cert_pem
  tags             = local.common_tags
}