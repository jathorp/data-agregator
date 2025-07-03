# in components/03-application

terraform init -backend-config="../../environments/dev/03-application.backend.tfvars"
terraform plan -var-file="../../environments/dev/pipeline.tfvars"