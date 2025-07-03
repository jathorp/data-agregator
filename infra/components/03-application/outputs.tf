# components/03-application/outputs.tf

output "lambda_function_name" {
  value = aws_lambda_function.processor.function_name
}

output "lambda_function_arn" {
  value = aws_lambda_function.processor.arn
}

output "lambda_iam_role_arn" {
  value = aws_iam_role.lambda_exec.arn
}