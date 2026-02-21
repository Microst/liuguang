import os
import hashlib
import json
import re
import threading
import requests
from http.cookies import SimpleCookie
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# ==================== 工具函数 ====================
def calc_file_md5(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def parse_cookie_string(cookie_str):
    cookie = SimpleCookie()
    cookie.load(cookie_str)
    return {key: morsel.value for key, morsel in cookie.items()}

def extract_ltoken_ltuid(text):
    ltoken = re.search(r'ltoken=([^;\s]+)', text)
    ltuid = re.search(r'ltuid=([^;\s]+)', text)
    return (ltoken.group(1) if ltoken else None,
            ltuid.group(1) if ltuid else None)

# ==================== 上传核心 ====================
def upload_file(file_data, filename, cookie_str):
    # 保存临时文件
    temp_dir = '/tmp' if os.path.exists('/tmp') else '.'
    temp_path = os.path.join(temp_dir, filename)
    file_data.save(temp_path)
    try:
        md5 = calc_file_md5(temp_path)
        ext = filename.split('.')[-1].lower()

        # 获取上传参数
        url1 = "https://bbs-api.miyoushe.com/apihub/wapi/getUploadParams"
        headers1 = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Trident/7.0; rv:11.0) like Gecko",
            "x-rpc-app_version": "2.96.0",
            "Content-Type": "application/json",
            "Origin": "https://www.miyoushe.com",
            "Referer": "https://www.miyoushe.com/",
        }
        payload1 = {
            "md5": md5,
            "ext": ext,
            "biz": "community",
            "support_content_type": True,
            "support_extra_form_data": True,
            "extra": {"upload_source": "UPLOAD_SOURCE_COMMUNITY"}
        }
        cookies = parse_cookie_string(cookie_str)

        resp1 = requests.post(url1, json=payload1, headers=headers1, cookies=cookies, timeout=30)
        if resp1.status_code != 200:
            return False, f"HTTP错误: {resp1.status_code}"
        data1 = resp1.json()
        if data1.get("retcode") != 0:
            return False, f"获取参数失败: {data1.get('message', '未知错误')}"

        params = data1["data"]["params"]

        # 上传到 OSS
        fields_list = [
            ("name", params["name"]),
            ("key", params["dir"] + params["name"]),
            ("callback", params["callback"]),
            ("success_action_status", "200"),
            ("x:extra", params["callback_var"]["x:extra"]),
            ("x-oss-content-type", params.get("x_oss_content_type", f"image/{ext}")),
        ]
        for item in params.get("extra_form_data", []):
            fields_list.append((item["key"], item["value"]))
        fields_list.extend([
            ("OSSAccessKeyId", params["accessid"]),
            ("policy", params["policy"]),
            ("signature", params["signature"]),
        ])
        fields_list.append(("x-oss-object-acl", params.get("object_acl", "default")))

        host = params["host"]
        with open(temp_path, "rb") as f:
            file_bytes = f.read()
        files = {"file": (filename, file_bytes)}

        resp2 = requests.post(host, data=fields_list, files=files, timeout=60)
        if resp2.status_code != 200:
            return False, f"OSS HTTP错误: {resp2.status_code}"
        data2 = resp2.json()
        if data2.get("retcode") != 0:
            return False, f"上传失败: {data2.get('msg', '未知错误')}"

        url = data2["data"]["url"]
        return True, url
    finally:
        os.remove(temp_path)

# ==================== Flask 路由 ====================
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/upload', methods=['POST'])
def api_upload():
    file = request.files.get('file')
    cookie = request.form.get('cookie')
    if not file or not cookie:
        return jsonify({'success': False, 'error': '缺少文件或cookie'})
    success, result = upload_file(file, file.filename, cookie)
    if success:
        return jsonify({'success': True, 'url': result})
    else:
        return jsonify({'success': False, 'error': result})

# ==================== 启动 WebView（可选，用于调试） ====================
def open_browser():
    import webbrowser
    webbrowser.open('http://127.0.0.1:5000')

if __name__ == '__main__':
    # 在非 Android 环境下自动打开浏览器
    threading.Timer(1, open_browser).start()
    app.run(host='0.0.0.0', port=5000, debug=False)