# components/03-application/variables.tf

variable "project_name" {
  description = "The name of the project."
  type        = string
}

variable "environment_name" {
  description = "The name of the environment."
  type        = string
}

variable "lambda_function_name" {
  description = "The name of the Lambda function."
  type        = string
}

variable "lambda_handler" {
  description = "The handler for the Lambda function."
  type        = string
}

variable "lambda_runtime" {
  description = "The runtime for the Lambda function."
  type        = string
}

variable "lambda_timeout" {
  description = "The timeout in seconds for the Lambda function."
  type        = number
  default     = 30
}

variable "lambda_memory_size" {
  description = "The amount of memory in MB to allocate to the Lambda function."
  type        = number
  default     = 512
}