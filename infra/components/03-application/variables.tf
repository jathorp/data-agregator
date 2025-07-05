# components/03-application/variables.tf

variable "project_name" {
  description = "The name of the project."
  type        = string
}

variable "environment_name" {
  description = "The name of the environment."
  type        = string
}

variable "aws_region" {
  description = "The AWS region to deploy resources into."
  type        = string
}


variable "lambda_function_name" {
  description = "The name of the Lambda function."
  type        = string
}

variable "lambda_handler" {
  description = "The handler for the Lambda function (e.g., 'app.handler')."
  type        = string
  default     = "app.handler"
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

variable "lambda_ephemeral_storage_size" {
  description = "The size of the Lambda function's /tmp directory in MB. Min 512, Max 10240."
  type        = number
  default     = 2048 # A sensible default for the streaming architecture.
}

variable "idempotency_ttl_days" {
  description = "The number of days to retain the idempotency key in DynamoDB."
  type        = number
  default     = 7
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

variable "nifi_connect_timeout_seconds" {
  description = "The timeout in seconds for establishing a connection to NiFi."
  type        = number
  default     = 5
}

variable "circuit_breaker_failure_threshold" {
  description = "The number of consecutive failures needed to open the circuit."
  type        = number
  default     = 3
}

variable "circuit_breaker_open_seconds" {
  description = "The duration in seconds the circuit remains open before moving to half-open."
  type        = number
  default     = 300
}