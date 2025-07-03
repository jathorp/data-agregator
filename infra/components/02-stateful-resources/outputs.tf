output "landing_bucket_arn" {
  description = "The ARN of the S3 landing bucket."
  value       = aws_s3_bucket.landing.arn
}

output "landing_bucket_id" {
  description = "The ID (name) of the S3 landing bucket."
  value       = aws_s3_bucket.landing.id
}