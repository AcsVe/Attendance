"""Pure-Python (stdlib-only) RS256 JWT signing from a PKCS8 PEM private key.
No 'cryptography' / 'rsa' / 'pyjwt' dependency - avoids native-build issues
on constrained platforms (e.g. Termux/Android) where 'cryptography' has no
prebuilt wheel and needs a Rust toolchain to compile from source."""
import base64
import hashlib
import json
import time


def _read_der_length(data, idx):
    first = data[idx]
    idx += 1
    if first < 0x80:
        return first, idx
    num_bytes = first & 0x7F
    length = int.from_bytes(data[idx:idx + num_bytes], 'big')
    idx += num_bytes
    return length, idx


def _read_der_tlv(data, idx):
    tag = data[idx]
    idx += 1
    length, idx = _read_der_length(data, idx)
    value = data[idx:idx + length]
    idx += length
    return tag, value, idx


def _read_der_integer(data, idx):
    tag, value, idx = _read_der_tlv(data, idx)
    assert tag == 0x02, f'expected INTEGER tag, got {tag:#x}'
    return int.from_bytes(value, 'big'), idx


def parse_pkcs8_rsa_private_key(pem_text):
    """يستخرج (n, d) من مفتاح RSA خاص بصيغة PKCS8 PEM (نفس صيغة حقل
    private_key بملف JSON الخاص بـService Account من Google) - بدون أي
    مكتبة تشفير خارجية، فقط تفكيك DER/ASN.1 يدوي."""
    lines = [l.strip() for l in pem_text.strip().splitlines()
             if l.strip() and not l.startswith('-----')]
    der = base64.b64decode(''.join(lines))

    idx = 0
    tag, _, idx = _read_der_tlv(der, 0)
    assert tag == 0x30, 'PKCS8 envelope: expected outer SEQUENCE'
    # الآن idx يشير لبداية محتوى الـSEQUENCE الخارجية - نعيد القراءة من الصفر
    # داخل هذا المحتوى بدل استخدام offset مطلق، فنبني مؤشراً محلياً:
    tag, outer_value, _ = _read_der_tlv(der, 0)
    pos = 0
    # version INTEGER
    _, pos = _read_der_integer(outer_value, pos)
    # privateKeyAlgorithm SEQUENCE (نتجاوزه بدون تفكيك تفاصيله)
    _, _, pos = _read_der_tlv(outer_value, pos)
    # privateKey OCTET STRING (يحوي DER لمفتاح RSAPrivateKey بصيغة PKCS1)
    tag, pkcs1_der, pos = _read_der_tlv(outer_value, pos)
    assert tag == 0x04, 'expected OCTET STRING for privateKey'

    # ===== الآن نفكّك RSAPrivateKey (PKCS1) الموجود داخل الـOCTET STRING =====
    tag, inner_value, _ = _read_der_tlv(pkcs1_der, 0)
    assert tag == 0x30, 'RSAPrivateKey: expected SEQUENCE'
    p = 0
    _, p = _read_der_integer(inner_value, p)  # version
    n, p = _read_der_integer(inner_value, p)  # modulus
    _, p = _read_der_integer(inner_value, p)  # publicExponent
    d, p = _read_der_integer(inner_value, p)  # privateExponent
    return n, d


# ===== بادئة DigestInfo الثابتة لـSHA-256 حسب RFC 3447 (PKCS#1 v1.5) =====
_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex('3031300d060960864801650304020105000420')


def _rsa_sign_sha256(message_bytes, n, d):
    """توقيع RSASSA-PKCS1-v1_5 مع SHA-256 يدوياً (تعليم modular exponentiation
    فقط من Python الأساسي - int.pow ثلاثي الوسائط بديل مضمَّن وسريع)."""
    digest = hashlib.sha256(message_bytes).digest()
    t = _SHA256_DIGEST_INFO_PREFIX + digest
    k = (n.bit_length() + 7) // 8  # طول المعامل بالبايت
    ps_len = k - len(t) - 3
    if ps_len < 8:
        raise ValueError('مفتاح RSA قصير جداً لتوقيع SHA-256 بأمان')
    em = b'\x00\x01' + b'\xff' * ps_len + b'\x00' + t
    m_int = int.from_bytes(em, 'big')
    s_int = pow(m_int, d, n)
    return s_int.to_bytes(k, 'big')


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=')


def make_signed_jwt(service_account_info, scope, audience=None, lifetime_seconds=3600):
    """يبني ويوقّع JWT بذاته لتبادله بـaccess token من Google OAuth2 -
    نفس تدفق 'Service Account' الرسمي (RFC 7523)، بدون أي حزمة خارجية."""
    n, d = parse_pkcs8_rsa_private_key(service_account_info['private_key'])
    now = int(time.time())
    header = {'alg': 'RS256', 'typ': 'JWT'}
    if 'private_key_id' in service_account_info:
        header['kid'] = service_account_info['private_key_id']
    payload = {
        'iss': service_account_info['client_email'],
        'scope': scope,
        'aud': audience or service_account_info.get('token_uri', 'https://oauth2.googleapis.com/token'),
        'iat': now,
        'exp': now + lifetime_seconds,
    }
    signing_input = _b64url(json.dumps(header, separators=(',', ':')).encode()) + b'.' + \
        _b64url(json.dumps(payload, separators=(',', ':')).encode())
    signature = _rsa_sign_sha256(signing_input, n, d)
    return (signing_input + b'.' + _b64url(signature)).decode('ascii')
