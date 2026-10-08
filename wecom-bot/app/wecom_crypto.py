"""企业微信回调加解密（JSON 数据格式，官方 WXBizMsgCrypt 的精简实现）"""
import base64
import hashlib
import json
import os
import struct
import time
import xml.etree.ElementTree as ET

from Crypto.Cipher import AES


class WeComCrypto:
    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self.token = token
        self.corp_id = corp_id
        self.aes_key = base64.b64decode(encoding_aes_key + "=")

    def signature(self, timestamp: str, nonce: str, encrypt: str) -> str:
        raw = "".join(sorted([self.token, timestamp, nonce, encrypt]))
        return hashlib.sha1(raw.encode()).hexdigest()

    def decrypt(self, encrypt_b64: str) -> str:
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
        plain = cipher.decrypt(base64.b64decode(encrypt_b64))
        # 去 PKCS7 填充
        pad = plain[-1]
        plain = plain[:-pad]
        # 结构: 16字节随机串 + 4字节消息长度 + 消息 + corp_id
        size = struct.unpack(">I", plain[16:20])[0]
        return plain[20:20 + size].decode("utf-8")

    def encrypt(self, plain_msg: str) -> str:
        rnd = os.urandom(16)
        size = struct.pack(">I", len(plain_msg.encode()))
        raw = rnd + size + plain_msg.encode() + self.corp_id.encode()
        pad = 32 - len(raw) % 32
        raw += bytes([pad]) * pad
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
        return base64.b64encode(cipher.encrypt(raw)).decode()

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        """GET 验证回调：校验签名并返回解密后的明文 echostr"""
        assert self.signature(timestamp, nonce, echostr) == msg_signature, "签名校验失败"
        return self.decrypt(echostr)

    def decrypt_message(self, msg_signature: str, timestamp: str, nonce: str, body: bytes) -> dict:
        """POST 消息：解密并返回消息字典（兼容 JSON 和 XML 数据格式）"""
        root = ET.fromstring(body)
        encrypt = root.find("Encrypt").text
        assert self.signature(timestamp, nonce, encrypt) == msg_signature, "签名校验失败"
        plain = self.decrypt(encrypt)
        try:
            return json.loads(plain)
        except json.JSONDecodeError:
            xml = ET.fromstring(plain)
            return {child.tag: (child.text or "") for child in xml}
