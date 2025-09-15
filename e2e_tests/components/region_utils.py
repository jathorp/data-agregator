"""
Region detection utilities for e2e tests.

This module provides automatic region detection for boto3 clients,
specifically designed to work with AWS Lab credentials and other
setups where no region is explicitly configured.
"""

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from typing import Optional
import logging

logger = logging.getLogger(__name__)

def detect_bucket_region(bucket_name: str, session: Optional[boto3.Session] = None) -> Optional[str]:
    """
    Detect the region of an S3 bucket using the GetBucketLocation API.
    
    Args:
        bucket_name: The name of the S3 bucket
        session: Optional boto3 session to use
        
    Returns:
        The region name if detected, None if detection fails
    """
    if session is None:
        session = boto3.Session()
    
    try:
        # Use a region-agnostic S3 client to detect bucket region
        # We use us-east-1 as the initial region since it can access buckets in any region
        s3_client = session.client('s3', region_name='us-east-1')
        
        response = s3_client.get_bucket_location(Bucket=bucket_name)
        region = response.get('LocationConstraint')
        
        # AWS returns None for us-east-1 buckets
        if region is None:
            region = 'us-east-1'
            
        logger.debug(f"Detected region '{region}' for bucket '{bucket_name}'")
        return region
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        if error_code == 'NoSuchBucket':
            logger.warning(f"Bucket '{bucket_name}' does not exist")
        elif error_code == 'AccessDenied':
            logger.warning(f"Access denied when trying to detect region for bucket '{bucket_name}'")
        else:
            logger.warning(f"Failed to detect region for bucket '{bucket_name}': {e}")
        return None
        
    except Exception as e:
        logger.warning(f"Unexpected error detecting region for bucket '{bucket_name}': {e}")
        return None


def get_smart_region(bucket_names: list[str], session: Optional[boto3.Session] = None, default_region: str = 'us-east-1') -> str:
    """
    Intelligently determine the best region to use for boto3 clients.
    
    This function tries multiple approaches in order:
    1. Try to detect the region from the first accessible bucket
    2. Fall back to the default region
    
    Args:
        bucket_names: List of bucket names to try for region detection
        session: Optional boto3 session to use
        default_region: Default region to use if detection fails
        
    Returns:
        The region name to use for boto3 clients
    """
    if session is None:
        session = boto3.Session()
    
    # Try to detect region from buckets
    for bucket_name in bucket_names:
        if bucket_name:  # Skip empty bucket names
            detected_region = detect_bucket_region(bucket_name, session)
            if detected_region:
                logger.info(f"Using detected region '{detected_region}' from bucket '{bucket_name}'")
                return detected_region
    
    # Fall back to default region
    logger.info(f"Could not detect region from buckets, using default region '{default_region}'")
    return default_region


def create_boto3_clients_with_region_detection(bucket_names: list[str], lambda_client_config=None):
    """
    Create boto3 clients with automatic region detection.
    
    Args:
        bucket_names: List of bucket names to use for region detection
        lambda_client_config: Optional botocore config for Lambda client
        
    Returns:
        Tuple of (session, s3_client, lambda_client, detected_region)
    """
    # Create session using boto3's default credential resolution
    session = boto3.Session()
    
    # Detect the best region to use
    region = get_smart_region(bucket_names, session)
    
    # Create clients with the detected region
    s3_client = session.client('s3', region_name=region)
    lambda_client = session.client('lambda', region_name=region, config=lambda_client_config)
    
    return session, s3_client, lambda_client, region