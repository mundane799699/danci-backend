import secrets

# 生成一个32字节的随机密钥
secret_key = secrets.token_hex(32)
print(f"生成的SECRET_KEY: {secret_key}") 