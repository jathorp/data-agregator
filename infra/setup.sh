aws s3api create-bucket \
  --bucket data-agregator-tfstate-dev \
  --region eu-west-2 \
  --create-bucket-configuration LocationConstraint=eu-west-2

  aws s3api put-public-access-block \
 --bucket data-agregator-tfstate-dev \
 --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"