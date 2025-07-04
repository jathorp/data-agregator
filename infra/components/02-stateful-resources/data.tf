# components/02-stateful-resources/data.tf

# Data source for the KMS policy.
data "aws_caller_identity" "current" {}