import os, asyncio, threading, time, json, socket, sys
from flask import Flask, jsonify, request
from flask_cors import CORS

from xCore import (
    do_login, build_ob55_online_auth, create_auth_token_chat,
    SPamSqForSpm, GeT_PLayer_InFo
)

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS_FILE = os.path.join(BASE_DIR, 'accounts.json')

connected_clients = {}
connected_clients_lock = threading.Lock()
all_accounts = {}
all_accounts_lock = threading.Lock()
ACCOUNTS = []

spam_speed = 0.5
spam_count = 1
spam_running = False
spam_targets = set()
current_target_info = {}
target_info_lock = threading.Lock()
state_lock = threading.Lock()

GREEN = '\033[92m'; YELLOW = '\033[93m'; RED = '\033[91m'; RESET = '\033[0m'


def set_acc_status(acc_id, status):
    with all_accounts_lock:
        if acc_id in all_accounts:
            all_accounts[acc_id]['status'] = status


class FF_CLient:
    def __init__(self, id, password):
        self.id = id
        self.password = password
        self.key = None
        self.iv = None
        self.token = None
        self.account_uid = None
        self.online_sock = None
        self.chat_sock = None
        self.running = True
        self.targets = set()
        self.spam_thread_started = False
        self.send_lock = threading.Lock()
        self.jwt_token = None
        threading.Thread(target=self._boot, daemon=True).start()

    def _boot(self):
        while self.running:
            set_acc_status(self.id, 'connecting')
            try:
                res = asyncio.run(do_login(self.id, self.password, 'ME'))
            except Exception as e:
                print(f"{RED}[{self.id}] login error: {e}{RESET}")
                res = None
            if not res:
                time.sleep(3)
                continue
            self.key = res['key']
            self.iv = res['iv']
            self.token = res['token']
            self.account_uid = res['bot_uid']
            self.jwt_token = res['token']
            try:
                self._connect(res)
            except Exception as e:
                print(f"{RED}[{self.id}] connect error: {e}{RESET}")
            time.sleep(3)

    def _connect(self, res):
        online_auth = build_ob55_online_auth(
            int(res['bot_uid']), res['token'], int(res['timestamp']),
            res['key'], res['iv']
        )
        online_sock = socket.create_connection(
            (res['online_ip'], int(res['online_port'])), timeout=15)
        online_sock.settimeout(20)
        online_sock.sendall(online_auth)
        self.online_sock = online_sock
        print(f"{GREEN}[{self.id}] Online connected{RESET}")

        chat_auth_hex = create_auth_token_chat(
            int(res['bot_uid']), res['token'], int(res['timestamp']),
            res['key'], res['iv']
        )
        if not chat_auth_hex:
            raise RuntimeError('chat auth build failed')
        chat_sock = socket.create_connection(
            (res['chat_ip'], int(res['chat_port'])), timeout=15)
        chat_sock.settimeout(20)
        chat_sock.sendall(bytes.fromhex(chat_auth_hex))
        self.chat_sock = chat_sock
        print(f"{GREEN}[{self.id}] Chat connected{RESET}")

        with connected_clients_lock:
            connected_clients[self.id] = self
        set_acc_status(self.id, 'online')

        self._start_spam()
        self._chat_reader(chat_sock)

    def _chat_reader(self, sock):
        try:
            while self.running:
                try:
                    data = sock.recv(65536)
                    if not data:
                        break
                except socket.timeout:
                    continue
                except Exception:
                    break
        finally:
            with connected_clients_lock:
                connected_clients.pop(self.id, None)
            set_acc_status(self.id, 'connecting')
            try:
                sock.close()
            except Exception:
                pass
            try:
                if self.online_sock:
                    self.online_sock.close()
            except Exception:
                pass
            self.online_sock = None
            self.chat_sock = None

    def _start_spam(self):
        if self.spam_thread_started:
            return
        self.spam_thread_started = True

        def loop():
            while self.running:
                with state_lock:
                    running = spam_running
                if not running or not self.targets:
                    time.sleep(0.1)
                    continue
                current = list(self.targets)
                sock = self.online_sock
                if not sock:
                    time.sleep(0.5)
                    continue
                try:
                    with self.send_lock:
                        for target in current:
                            with state_lock:
                                if target not in spam_targets:
                                    self.targets.discard(target)
                                    continue
                            for _ in range(spam_count):
                                sock.sendall(SPamSqForSpm(target, self.key, self.iv))
                            print(f"{YELLOW}[{self.id}] => {target} x{spam_count}{RESET}")
                except Exception as e:
                    print(f"{RED}[{self.id}] spam error: {e}{RESET}")
                    time.sleep(0.5)
                    continue
                with state_lock:
                    sp = spam_speed
                time.sleep(sp)

        threading.Thread(target=loop, daemon=True).start()

    def add_target(self, t):
        self.targets.add(t)

    def remove_target(self, t):
        self.targets.discard(t)

    def clear_targets(self):
        self.targets.clear()


def load_accounts_from_file(filename=None):
    filename = filename or ACCOUNTS_FILE
    accounts = []
    try:
        if not os.path.exists(filename):
            return accounts
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            for uid, pw in data.items():
                if pw:
                    accounts.append({'id': uid, 'password': pw})
        return accounts
    except Exception:
        return accounts


def start_account(acc):
    try:
        FF_CLient(acc['id'], acc['password'])
    except Exception as e:
        print(f"{RED}start_account {acc['id']}: {e}{RESET}")
        set_acc_status(acc['id'], 'offline')


def start_accounts():
    global ACCOUNTS
    time.sleep(1)
    print(f"Loading accounts from: {ACCOUNTS_FILE}")
    ACCOUNTS = load_accounts_from_file()
    if not ACCOUNTS:
        print(f"{RED}No accounts found in accounts.json{RESET}")
        return
    with all_accounts_lock:
        for a in ACCOUNTS:
            all_accounts[a['id']] = {'id': a['id'], 'password': a['password'], 'status': 'offline'}
    for a in ACCOUNTS:
        threading.Thread(target=start_account, args=(a,), daemon=True).start()
        time.sleep(0.1)


def fetch_target_info(uid):
    token = None
    with connected_clients_lock:
        for _, c in connected_clients.items():
            if getattr(c, 'jwt_token', None):
                token = c.jwt_token
                break
    if token:
        info = GeT_PLayer_InFo(uid, token)
        if info:
            with target_info_lock:
                current_target_info[uid] = info
    return info


def add_target_for_all(tid):
    global spam_running
    with state_lock:
        spam_running = True
        spam_targets.add(tid)
    with connected_clients_lock:
        for _, c in connected_clients.items():
            c.add_target(tid)
    threading.Thread(target=fetch_target_info, args=(tid,), daemon=True).start()


def remove_target_for_all(tid):
    with state_lock:
        spam_targets.discard(tid)
    with connected_clients_lock:
        for _, c in connected_clients.items():
            c.remove_target(tid)
    with target_info_lock:
        current_target_info.pop(tid, None)


def clear_all_targets():
    global spam_running
    with state_lock:
        spam_running = False
        spam_targets.clear()
    with connected_clients_lock:
        for _, c in connected_clients.items():
            c.clear_targets()
    with target_info_lock:
        current_target_info.clear()


@app.route('/spm', methods=['GET'])
def api_spam():
    uid = request.args.get('uid', '').strip()
    if not uid or not uid.isdigit():
        return jsonify({"success": False, "message": "uid الهدف", "code": 400}), 400
    with connected_clients_lock:
        if not connected_clients:
            return jsonify({"success": False, "message": "للاسف مفيش حسابات متصله", "code": 400}), 400
    with state_lock:
        if uid in spam_targets:
            return jsonify({"success": True, "message": f"موجود ف الاسبام قبل كده",
                            "active_targets": list(spam_targets), "code": 200})
    add_target_for_all(uid)
    with state_lock:
        active = list(spam_targets)
    return jsonify({
        "success": True, "message": f"تم وضع في الاسبام {uid}",
        "target": uid, "active_targets": active,
        "bots_count": len(connected_clients),
        "spam_speed": spam_speed, "spam_count": spam_count, "code": 200
    })


@app.route('/remove', methods=['GET'])
def api_remove():
    uid = request.args.get('uid', '').strip()
    if not uid or not uid.isdigit():
        return jsonify({"success": False, "message": "uid الهدف", "code": 400}), 400
    with state_lock:
        if uid not in spam_targets:
            return jsonify({"success": True, "message": f"مش موجود ",
                            "active_targets": list(spam_targets), "code": 200})
    remove_target_for_all(uid)
    with state_lock:
        active = list(spam_targets)
    return jsonify({"success": True, "message": f"تم الحذف",
                    "active_targets": active, "code": 200})


@app.route('/stop', methods=['GET'])
def api_stop():
    clear_all_targets()
    return jsonify({"success": True, "message": "تم إيقاف الاسبام", "code": 200})


@app.route('/targets', methods=['GET'])
def api_targets():
    with state_lock:
        active = list(spam_targets)
    with target_info_lock:
        info = {uid: current_target_info.get(uid) for uid in active}
    return jsonify({"success": True, "active_targets": active,
                    "count": len(active), "targets_info": info, "code": 200})


@app.route('/status', methods=['GET'])
def api_status():
    with connected_clients_lock:
        online_ids = set(connected_clients.keys())
        online_list = [
            {'id': c.id, 'player_uid': getattr(c, 'account_uid', None),
             'targets': list(c.targets), 'status': 'online'}
            for c in connected_clients.values()
        ]
    with all_accounts_lock:
        offline_list = [
            {'id': a['id'], 'status': a['status']}
            for a in all_accounts.values() if a['id'] not in online_ids
        ]
        total = len(all_accounts)
    with state_lock:
        running = spam_running
        active = list(spam_targets)
    with target_info_lock:
        info = {uid: current_target_info.get(uid) for uid in active}
    return jsonify({
        "success": True, "online": online_list, "online_count": len(online_list),
        "offline": offline_list, "offline_count": len(offline_list),
        "total": total, "spam_running": running,
        "active_targets": active, "targets_info": info,
        "spam_speed": spam_speed, "spam_count": spam_count, "code": 200
    })


@app.route('/info', methods=['GET'])
def api_info():
    uid = request.args.get('uid', '').strip()
    if not uid or not uid.isdigit():
        return jsonify({"success": False, "message": "uid مطلوب", "code": 400}), 400
    token = None
    with connected_clients_lock:
        for _, c in connected_clients.items():
            if getattr(c, 'jwt_token', None):
                token = c.jwt_token
                break
    if not token:
        return jsonify({"success": False, "message": "مفيش حساب متصل", "code": 400}), 400
    info = GeT_PLayer_InFo(uid, token)
    if info:
        with target_info_lock:
            current_target_info[uid] = info
        return jsonify({"success": True, "data": info, "code": 200})
    return jsonify({"success": False, "message": "تعذر جلب المعلومات", "code": 404}), 404


@app.route('/bots', methods=['GET'])
def api_bots():
    with connected_clients_lock:
        bots = [
            {'id': c.id, 'player_uid': getattr(c, 'account_uid', None),
             'targets': list(c.targets), 'status': 'online'}
            for c in connected_clients.values()
        ]
    return jsonify({"success": True, "bots": bots, "count": len(bots), "code": 200})


@app.route('/health', methods=['GET'])
def api_health():
    with connected_clients_lock:
        online = len(connected_clients)
    with all_accounts_lock:
        total = len(all_accounts)
    with state_lock:
        running = spam_running
        targets = len(spam_targets)
    return jsonify({
        "success": True, "status": "running",
        "bots_online": online, "bots_total": total,
        "spam_running": running, "active_targets": targets, "code": 200
    })


@app.route('/settings', methods=['GET'])
def api_settings():
    global spam_speed, spam_count
    speed = request.args.get('speed')
    count = request.args.get('count')
    if speed is not None:
        try:
            v = float(speed)
            if v < 0.05:
                return jsonify({"success": False, "message": "السرعة لا تقل عن 0.05", "code": 400}), 400
            spam_speed = v
        except ValueError:
            return jsonify({"success": False, "message": "سرعة غير صحيحة", "code": 400}), 400
    if count is not None:
        try:
            c = int(count)
            if c < 1:
                return jsonify({"success": False, "message": "عدد لا يقل عن 1", "code": 400}), 400
            spam_count = c
        except ValueError:
            return jsonify({"success": False, "message": "عدد غير صحيح", "code": 400}), 400
    return jsonify({"success": True, "spam_speed": spam_speed,
                    "spam_count": spam_count, "code": 200})


def run_api():
    print(f"{GREEN}[START]{RESET} Akk Spam API")
    print(f"  speed={spam_speed}s  count={spam_count}")
    threading.Thread(target=start_accounts, daemon=True).start()
    app.run(host='0.0.0.0', port=5029, debug=False, threaded=True)


if __name__ == "__main__":
    run_api()