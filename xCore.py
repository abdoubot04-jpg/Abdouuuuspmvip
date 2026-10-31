# xCore.py - updated from xAyOuB.py working logic
import asyncio, random, uuid, time, json, binascii, ssl, gzip, http.client, os, re
from io import BytesIO
from datetime import datetime
import httpx
from urllib.parse import urlsplit
from google_play_scraper import app as play_scraper
from protobuf_decoder.protobuf_decoder import Parser
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from Pb2 import MajoRLoGinrEs_pb2, PorTs_pb2, MajoRLoGinrEq_pb2

AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV = b'6oyZDr22E3ychjM%'

REGION_LANG = {'BD': 'bn', 'IND': 'hi', 'PK': 'ur', 'SG': 'en', 'ID': 'id', 'ME': 'ar',
               'VN': 'vi', 'TW': 'zh', 'CIS': 'ru', 'TH': 'th', 'EU': 'en', 'US': 'en',
               'SAC': 'es', 'LK': 'en', 'BR': 'pt'}

DEFAULT_HEADERS = {
    'User-Agent': 'UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)',
    'Connection': 'Keep-Alive', 'Accept-Encoding': 'gzip',
    'Content-Type': 'application/x-www-form-urlencoded', 'Expect': '100-continue',
    'X-Unity-Version': '2018.4.12f1', 'X-GA-SV': '1789535859', 'X-GA': 'v1 1',
    'ReleaseVersion': 'OB55'
}


# ============= Protobuf helpers =============
def _pb_varint(n):
    if n < 0:
        n = (1 << 64) + n
    out = bytearray()
    while True:
        b = n & 127
        n >>= 7
        if n:
            b |= 128
        out.append(b)
        if not n:
            break
    return bytes(out)


def _pb_tag(f, w):
    return _pb_varint(f << 3 | w)


def _pb_field(f, v):
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, int):
        return _pb_tag(f, 0) + _pb_varint(v)
    if isinstance(v, str):
        d = v.encode('utf-8')
        return _pb_tag(f, 2) + _pb_varint(len(d)) + d
    if isinstance(v, (bytes, bytearray)):
        d = bytes(v)
        return _pb_tag(f, 2) + _pb_varint(len(d)) + d
    return b''


# ============= AES helpers =============
async def aes_encrypt(payload, key, iv):
    return AES.new(key, AES.MODE_CBC, iv).encrypt(pad(payload, AES.block_size))


def EnC_PacKeT_sync(HeX, K, V):
    return AES.new(K, AES.MODE_CBC, V).encrypt(pad(bytes.fromhex(HeX), 16)).hex()


def EnC_Uid(H, Tp):
    e, H = [], int(H)
    while H:
        e.append((H & 0x7F) | (0x80 if H > 0x7F else 0))
        H >>= 7
    return bytes(e).hex() if Tp == 'Uid' else None


def EnC_Vr(N):
    if N < 0:
        return b''
    H = []
    while True:
        BesTo = N & 0x7F
        N >>= 7
        if N:
            BesTo |= 0x80
        H.append(BesTo)
        if not N:
            break
    return bytes(H)


def CrEaTe_VarianT(field_number, value):
    return EnC_Vr(field_number << 3 | 0) + EnC_Vr(value)


def CrEaTe_LenGTh(field_number, value):
    encoded = value.encode() if isinstance(value, str) else value
    return EnC_Vr(field_number << 3 | 2) + EnC_Vr(len(encoded)) + encoded


def CrEaTe_ProTo(fields):
    packet = bytearray()
    for field, value in fields.items():
        if isinstance(value, dict):
            packet.extend(CrEaTe_LenGTh(field, bytes(CrEaTe_ProTo(value))))
        elif isinstance(value, int):
            packet.extend(CrEaTe_VarianT(field, value))
        elif isinstance(value, str) or isinstance(value, bytes):
            packet.extend(CrEaTe_LenGTh(field, value))
    return packet


def GeneRaTePk(Pk_hex, N, K, V):
    """N = hex opcode string like '0515'. Returns full packet bytes."""
    payload = bytes.fromhex(EnC_PacKeT_sync(Pk_hex, K, V))
    return bytes.fromhex(N) + len(payload).to_bytes(4, 'big') + payload


# ============= Parsing =============
def Fix_PackEt(parsed_results):
    result_dict = {}
    for result in parsed_results:
        field_data = {'wire_type': result.wire_type}
        if result.wire_type in ('varint', 'string', 'bytes'):
            field_data['data'] = result.data
        elif result.wire_type == 'length_delimited':
            field_data['data'] = Fix_PackEt(result.data.results)
        result_dict[str(result.field)] = field_data
    return result_dict


def DeCode_PackEt(input_text):
    try:
        return json.dumps(Fix_PackEt(Parser().parse(input_text)))
    except Exception:
        return None


def get_proto_field(d, key, default=None):
    if not d or not isinstance(d, dict):
        return default
    if key in d:
        return d[key].get('data', default)
    if str(key) in d:
        return d[str(key)].get('data', default)
    return default


# ============= Login flow =============
async def get_playstore_version():
    loop = asyncio.get_event_loop()
    try:
        res = await loop.run_in_executor(
            None, lambda: play_scraper('com.dts.freefireth', lang='hi', country='id'))
        return res.get('version', '1.132.8')
    except Exception:
        return '1.132.8'


async def version_config(client_http, region='ME'):
    app_version = await get_playstore_version()
    lang = REGION_LANG.get(region, 'ar')
    url = (f'https://version.ggwhitehawk.com/live/ver.php?version={app_version}'
           f'&lang={lang}&device=android&channel=android&appstore=googleplay'
           f'&region={region}&whitelist_version=1.3.0&whitelist_sp_version=1.0.0')
    try:
        res = await client_http.get(url)
        data = res.json()
        values = (data.get('latest_release_version'),
                  data.get('remote_version'), data.get('server_url'))
        return values if all(values) else None
    except Exception:
        return None


async def get_access_token(client_http, uid, password):
    url = 'https://100067.connect.garena.com/oauth/guest/token/grant'
    hdrs = {
        'Host': '100067.connect.garena.com',
        'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 12; SM-G998B Build/SP1A.210812.016)',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept-Encoding': 'gzip, deflate, br', 'Connection': 'close'
    }
    data = {
        'uid': str(uid), 'password': str(password), 'response_type': 'token',
        'client_type': '2',
        'client_secret': '2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3',
        'client_id': '100067'
    }
    for _ in range(3):
        try:
            r = await client_http.post(url, headers=hdrs, data=data)
            if r.status_code == 200:
                rd = r.json()
                if rd.get('open_id') and rd.get('access_token'):
                    return (rd['open_id'], rd['access_token'], rd.get('platform', 4))
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return None


async def build_majorlogin_payload(open_id, access_token, platform, client_version):
    try:
        proto = MajoRLoGinrEq_pb2.MajorLogin()
        proto.event_time = str(datetime.now())[:-7]
        proto.game_name = 'free fire'
        proto.platform_id = 1
        proto.client_version = str(client_version)
        proto.client_version_code = '2019121229'
        proto.system_software = 'Android OS 15 / API-35 (AP3A.240905.015.A2/185014)'
        proto.system_hardware = 'Handheld'
        proto.device_type = 'Handheld'
        proto.screen_width = 1600
        proto.screen_height = 719
        proto.screen_dpi = '234'
        proto.processor_details = 'ARM64 FP ASIMD AES | 1820 | 8'
        proto.memory = 2798
        proto.gpu_renderer = 'Mali-G57'
        proto.gpu_version = 'OpenGL ES 3.2 v1.r49p1-04eac0.2848c17a2fd4e9340e06555168eaa3c9'
        proto.unique_device_id = f'Google|{uuid.uuid4()}'
        proto.client_ip = (f'{random.randint(103,223)}.{random.randint(10,250)}.'
                           f'{random.randint(10,250)}.{random.randint(10,250)}')
        proto.language = 'ar'
        proto.open_id = str(open_id)
        proto.open_id_type = '4'
        proto.login_open_id_type = 4
        proto.access_token = str(access_token)
        proto.login_by = 2
        proto.platform_sdk_id = 1
        proto.origin_platform_type = '4'
        proto.primary_platform_type = '4'
        proto.reg_avatar = 1
        proto.channel_type = 3
        proto.telecom_operator = 'JIO'
        proto.network_operator_a = 'JIO'
        proto.network_type = 'WIFI'
        proto.network_type_a = 'WIFI'
        proto.cpu_type = 2
        proto.cpu_architecture = '64'
        proto.graphics_api = 'OpenGLES2'
        proto.supported_astc_bitset = 8191
        proto.client_using_version = '7428b253defc164018c604a1ebbfebdf'
        proto.loading_time = 15078
        proto.release_channel = 'android'
        proto.extra_info = ('KqsHTx3+QOmBRR1WKvaWewlcpqJBfjki+PPHQoQG8+0yV+Uos7gUFFjHMQ/e7u6'
                            'han6Fl77r7c3vMN3p8UbKgN+nfycQCgwBmWgBzomx2gj84c+p')
        proto.android_engine_init_flag = 111207
        proto.if_push = 1
        proto.is_vpn = 0
        proto.memory_available.version = 55
        proto.memory_available.hidden_value = 81
        proto.external_storage_total = 49973
        proto.external_storage_available = 11338
        proto.internal_storage_total = 854
        proto.internal_storage_available = 11466
        proto.game_disk_storage_total = 49973
        proto.game_disk_storage_available = 11466
        proto.external_sdcard_total_storage = 49973
        proto.external_sdcard_avail_storage = 11466
        proto.library_path = ('/data/app/~~lHFxTCCbupG2QVJmsURtZw==/'
                              'com.dts.freefireth-N3aCHpHNXpdxjD80uIIbww==/lib/arm64')
        proto.library_token = ('b8e0cd5e295eee42f5860d3c86e483dd|/data/app/'
                               '~~lHFxTCCbupG2QVJmsURtZw==/'
                               'com.dts.freefireth-N3aCHpHNXpdxjD80uIIbww==/base.apk')
        base = proto.SerializeToString()
        extra = b''
        extra += _pb_field(96, '{"cur_rate":[90,60,120],"support_etc2":false}')
        extra += _pb_field(97, 1)
        extra += _pb_field(99, '4')
        extra += _pb_field(100, '4')
        extra += _pb_field(102, b'\x17]ENWU\x0eR5')
        extra += _pb_field(104, 52882)
        extra += _pb_field(105, 1)
        extra += _pb_field(106, ('https://dl.ak.freefiremobile.com/live/ABHotUpdates/|'
                                 'https://core-ak.freefiremobile.com/live/ABHotUpdates/|'
                                 '6b2078db9d22dd98f8e9386a39af8462'))
        extra += _pb_field(107, 'c8e41b7a93f02d56e1a94c7b8203f5d1')
        return await aes_encrypt(base + extra, AES_KEY, AES_IV)
    except Exception:
        return None


async def send_majorlogin(client_http, data, release_version, server_url):
    try:
        url = (f'{server_url}MajorLogin' if server_url.endswith('/')
               else f'{server_url}/MajorLogin')
        req_headers = DEFAULT_HEADERS.copy()
        req_headers['ReleaseVersion'] = str(release_version)
        response = await client_http.post(url, headers=req_headers, data=data)
        if response.status_code != 200 or len(response.content) < 40:
            return None
        res = MajoRLoGinrEs_pb2.MajorLoginRes()
        try:
            res.ParseFromString(response.content)
        except Exception:
            pass
        if not (res.account_uid and res.token):
            for off in range(min(128, len(response.content))):
                try:
                    c = MajoRLoGinrEs_pb2.MajorLoginRes()
                    c.ParseFromString(response.content[off:])
                    if c.account_uid and c.token:
                        res = c
                        break
                except Exception:
                    pass
        if not (res.account_uid and res.token):
            return None
        if not res.key:
            res.key = AES_KEY
        if not res.iv:
            res.iv = AES_IV
        if len(res.key) not in (16, 24, 32) or len(res.iv) != 16:
            return None
        if not res.url:
            res.url = server_url
        return res
    except Exception:
        return None


async def send_getlogin(client_http, data, base_url, token, release_version):
    try:
        url = f"{base_url.rstrip('/')}/GetLoginData"
        req_headers = DEFAULT_HEADERS.copy()
        req_headers['ReleaseVersion'] = str(release_version)
        req_headers['Authorization'] = f'Bearer {token}'
        response = await client_http.post(url, headers=req_headers, data=data)
        if response.status_code != 200:
            return None
        res = PorTs_pb2.GetLoginData()
        try:
            res.ParseFromString(response.content)
        except Exception:
            pass
        if res.Online_IP_Port:
            return (res, {})
        parsed = Parser().parse(response.content.hex())
        return (res, Fix_PackEt(parsed))
    except Exception:
        return None


async def do_login(uid, password, region_pref='ME'):
    async with httpx.AsyncClient(verify=True, timeout=15.0) as client_http:
        vc = await version_config(client_http, region_pref)
        if not vc:
            return None
        release_version, client_version, server_url = vc
        tg = await get_access_token(client_http, uid, password)
        if not tg:
            return None
        open_id, access_token, platform = tg
        payload = await build_majorlogin_payload(open_id, access_token, platform, client_version)
        if not payload:
            return None
        major_res = await send_majorlogin(client_http, payload, release_version, server_url)
        if not major_res or not major_res.account_uid:
            return None
        gl = await send_getlogin(client_http, payload, major_res.url, major_res.token, release_version)
        if not gl:
            return None
        res_proto, dict_res = gl
        online_addr = res_proto.Online_IP_Port or get_proto_field(dict_res, 14, '0.0.0.0:0')
        online_ip, online_port = (online_addr.rsplit(':', 1) if ':' in online_addr
                                  else ('0.0.0.0', '0'))
        chat_addr = res_proto.AccountIP_Port or get_proto_field(dict_res, 32, online_addr)
        chat_ip, chat_port = (chat_addr.rsplit(':', 1) if ':' in chat_addr
                              else (online_ip, online_port))
        if not (online_ip and chat_ip and online_port.isdigit() and chat_port.isdigit()):
            return None
        if not (0 < int(online_port) < 65536 and 0 < int(chat_port) < 65536):
            return None
        return {
            'bot_uid': str(major_res.account_uid),
            'token': major_res.token,
            'region': major_res.region or region_pref,
            'key': major_res.key or AES_KEY,
            'iv': major_res.iv or AES_IV,
            'timestamp': major_res.timestamp or int(time.time()),
            'online_ip': online_ip, 'online_port': online_port,
            'chat_ip': chat_ip, 'chat_port': chat_port,
            'account_name': res_proto.AccountName or 'Unknown',
            'server_url': major_res.url,
            'release_version': str(release_version),
        }


# ============= Auth builders =============
def build_ob55_online_auth(account_uid, token, kts, key, iv):
    token_bytes = token.encode('utf-8')
    enc_token = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(token_bytes, 16))
    opcode = bytes.fromhex('830c')
    uid_bytes = int(account_uid).to_bytes(8, byteorder='big')
    kts_bytes = int(kts).to_bytes(4, byteorder='big')
    len_bytes = len(enc_token).to_bytes(8, byteorder='big')
    return opcode + uid_bytes + kts_bytes + len_bytes + enc_token


def create_auth_token_chat(account_id, jwt_token, timestamp, key, iv):
    try:
        K = bytes.fromhex(key) if isinstance(key, str) else key
        V = bytes.fromhex(iv) if isinstance(iv, str) else iv
        ct = AES.new(K, AES.MODE_CBC, V).encrypt(pad(jwt_token.encode('utf-8'), AES.block_size))
        return (bytes.fromhex('6d19')
                + int(account_id).to_bytes(8, 'big')
                + int(timestamp).to_bytes(4, 'big')
                + len(ct).to_bytes(4, 'big') + ct).hex()
    except Exception:
        return None


# ============= Spam packet =============
def SPamSqForSpm(Uid, K, V):
    uid = int(Uid)
    if not 0 < uid < 2 ** 64:
        raise ValueError('Invalid UID')
    same_value = random.choice([4096, 16384, 8192])
    fields = {
        1: 33,
        2: {
            1: uid, 2: 'ME', 3: 1, 4: 1,
            5: bytes([1, 7, 9, 10, 11, 18, 25, 26, 32]),
            6: 'iG:[C][B][FF0000] @ZrZBaN',
            7: 330, 8: 1000, 10: 'ME',
            11: bytes([49, 97, 99, 52, 98, 56, 48, 101, 99, 102, 48, 52, 55, 56,
                       97, 52, 52, 50, 48, 51, 98, 102, 56, 102, 97, 99, 54, 49,
                       50, 48, 102, 53]),
            12: 1, 13: uid,
            14: {1: 2203434355, 2: 8,
                 3: bytes([16, 21, 8, 10, 11, 19, 12, 15, 17, 4, 7, 2, 3, 13,
                           14, 18, 1, 5, 6])},
            16: 1, 17: 1, 18: 312, 19: 46,
            23: bytes([16, 1, 24, 1]),
            26: '', 28: '',
            31: {1: 1, 2: same_value}, 32: same_value,
            34: {1: uid, 2: 8,
                 3: bytes([15, 6, 21, 8, 10, 11, 19, 12, 17, 4, 14, 20, 7, 2,
                           1, 5, 16, 3, 13, 18])},
        },
        10: 'en',
        13: {2: 1, 3: 1}
    }
    return GeneRaTePk(bytes(CrEaTe_ProTo(fields)).hex(), '0515', K, V)


# ============= Player info =============
def GeT_PLayer_InFo(uid, Token):
    try:
        data = bytes.fromhex(EnC_PacKeT_sync(f"08{EnC_Uid(uid, Tp='Uid')}1007", AES_KEY, AES_IV))
        url = "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow"
        headers = {
            'X-Unity-Version': '2022.3.47f1', 'ReleaseVersion': 'OB54',
            'Content-Type': 'application/x-www-form-urlencoded', 'X-GA': 'v1 1',
            'Authorization': f'Bearer {Token}',
            'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 7.1.2; ASUS_Z01QD Build/QKQ1.190825.002)',
            'Host': 'clientbp.ggpolarbear.com', 'Connection': 'close',
            'Accept-Encoding': 'gzip'
        }
        import requests, urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.post(url, headers=headers, data=data, verify=False, timeout=10)
        if response.status_code not in (200, 201):
            return None
        packet = binascii.hexlify(response.content).decode('utf-8')
        besto = json.loads(DeCode_PackEt(packet))
        d = besto["1"]["data"]
        info = {
            "nickname": str(d["3"]["data"]),
            "uid": str(d["1"]["data"]),
            "level": d.get("6", {}).get("data"),
            "likes": d.get("21", {}).get("data"),
            "server": d.get("5", {}).get("data"),
        }
        try:
            info["last_login"] = datetime.fromtimestamp(d["24"]["data"]).strftime("%d/%m/%y %I:%M %p")
        except Exception:
            info["last_login"] = None
        try:
            info["created"] = datetime.fromtimestamp(d["44"]["data"]).strftime("%d/%m/%y")
        except Exception:
            info["created"] = None
        try:
            info["bio"] = besto["9"]["data"]["9"]["data"]
        except Exception:
            info["bio"] = None
        return info
    except Exception:
        return None