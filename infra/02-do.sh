# Must be in components/02-stateful-resources

terraform init -backend-config="../../environments/dev/02-pipeline.backend.tfvars"
terraform plan -var-file="../../environments/dev/pipeline.tfvars"