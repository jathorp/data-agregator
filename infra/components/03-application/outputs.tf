# components/03-application/outputs.tf

output "lambda_function_name" {
  description = "The name of the aggregator Lambda function."
  value       = aws_lambda_function.aggregator.function_name
}

output "lambda_function_arn" {
  description = "The ARN of the aggregator Lambda function."
  value       = aws_lambda_function.aggregator.arn
}
