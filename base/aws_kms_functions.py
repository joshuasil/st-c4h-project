from django.conf import settings
import base64
from cryptography.fernet import Fernet
key_id = settings.AWS_KMS_ARN
import boto3


kms_client = boto3.client('kms',
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    region_name='us-east-1')

def encrypt_data(plaintext):
    key = kms_client.generate_data_key(
        KeyId=settings.AWS_KMS_ARN, 
        KeySpec="AES_256"
    )
    f = Fernet(base64.urlsafe_b64encode(key['Plaintext']))
    encrypted_data = f.encrypt(plaintext.encode())
    return encrypted_data, key['CiphertextBlob']

import ast

def decrypt_data(encrypted_data, encrypted_key):
    # Convert string representation of bytes back to bytes if necessary
    if isinstance(encrypted_data, str):
        encrypted_data = ast.literal_eval(encrypted_data)
    
    decrypted_key = kms_client.decrypt(
        CiphertextBlob=bytes(encrypted_key), 
        KeyId=settings.AWS_KMS_ARN
    )['Plaintext']
    f = Fernet(base64.urlsafe_b64encode(decrypted_key))
    decrypted_data = f.decrypt(encrypted_data)
    return decrypted_data.decode()