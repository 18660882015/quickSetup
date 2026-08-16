"""
AES 加解密工具函数

使用 cryptography.fernet.Fernet（基于 AES-128-CBC + HMAC）
提供 encrypt_value / decrypt_value 便捷函数。
"""
import os

from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import get_settings


def _get_fernet() -> Fernet:
    """获取 Fernet 实例"""
    settings = get_settings()
    key = settings.aes_secret_key

    if not key:
        # 如果未配置密钥，生成一个并缓存到单例
        # 注意：每次重启后会不同，已加密数据将无法解密
        # 生产环境必须在 .env 中配置固定的 AES_SECRET_KEY
        key = Fernet.generate_key().decode()
        settings.aes_secret_key = key
        print("[crypto] 警告: 未配置 AES_SECRET_KEY，已生成临时密钥。"
              "请在 .env 中配置固定密钥以保证数据持久化。")

    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        raise ValueError(f"AES_SECRET_KEY 格式无效: {e}") from e


def encrypt_value(plaintext: str) -> str:
    """加密字符串，返回 base64 编码的密文"""
    if not plaintext:
        return ""
    f = _get_fernet()
    encrypted = f.encrypt(plaintext.encode("utf-8"))
    return encrypted.decode("utf-8")


def decrypt_value(ciphertext: str) -> str:
    """解密 base64 编码的密文，返回明文"""
    if not ciphertext:
        return ""
    f = _get_fernet()
    try:
        decrypted = f.decrypt(ciphertext.encode("utf-8"))
        return decrypted.decode("utf-8")
    except InvalidToken:
        return ""


def generate_key() -> str:
    """生成新的 Fernet 密钥（用于初始化）"""
    return Fernet.generate_key().decode("utf-8")


if __name__ == "__main__":
    # 生成密钥的命令行工具
    print("生成的 AES_SECRET_KEY:")
    print(generate_key())
    print("\n请将此值复制到 .env 文件中。")
