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
  description = "The handler for the Lambda function (e.g., 'handler.lambda_handler')."
  type        = string
  default     = "handler.lambda_handler"
}

variable "lambda_runtime" {
  description = "The runtime for the Lambda function."
  type        = string
  default     = "python3.13"
}

variable "lambda_timeout" {
  description = "The timeout in seconds for the Lambda function."
  type        = number
  default     = 60
}

variable "lambda_memory_size" {
  description = "The amount of memory in MB to allocate to the Lambda function."
  type        = number
  default     = 512
}

variable "nifi_endpoint_url" {
  description = "The full HTTPS URL for the on-premise NiFi ingest endpoint."
  type        = string
  # No default value, as this is environment-specific and must be provided.
}

# --- NEW: Variable for the NiFi Endpoint CIDR Block ---
variable "nifi_endpoint_cidr" {
  description = "The source IP/CIDR block of the on-premise NiFi endpoint for the Lambda's Security Group."
  type        = string
  # No default value, as this is environment-specific and must be provided.
}