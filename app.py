import subprocess
import sys
import os
import uuid
import requests
from flask import Flask, request, jsonify, render_template, send_file, after_this_request, session
from apscheduler.schedulers.background import BackgroundScheduler
import yt_dlp
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# --- CONFIGURAÇÕES DE SEGURANÇA ---
# Gere uma chave aleatória para encriptar os cookies da sessão
app.secret_key = os.getenv("FLASK_SECRET_KEY", "uma_chave_muito_secreta_e_aleatoria")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123") # Senha padrão

CF_SECRET_KEY = os.getenv("CF_SECRET_KEY")
EXPECTED_HOSTNAME = os.getenv("EXPECTED_HOSTNAME", "127.0.0.1")
PORT = int(os.getenv("FLASK_PORT", 8022))

progress_store = {}

# ... (Mantenha as funções update_yt_dlp e validate_turnstile iguais) ...
def update_yt_dlp():
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp'])
        print("yt-dlp atualizado.")
    except Exception as e: print(e)

scheduler = BackgroundScheduler()
scheduler.add_job(func=update_yt_dlp, trigger="interval", hours=24)
scheduler.start()

def validate_turnstile(token, ip):
    url = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
    data = {'secret': CF_SECRET_KEY, 'response': token, 'remoteip': ip}
    try:
        res = requests.post(url, data=data, timeout=5).json()
        if not res.get('success'): return False, "Captcha inválido"
        if res.get('action') != 'download': return False, "Ação inválida"
        return True, "Sucesso"
    except: return False, "Erro conexão"

def get_ydl_opts():
    opts = {'quiet': True, 'no_warnings': True, 'remote_components': 'ejs:github', 'source_address': '0.0.0.0'}
    if os.path.exists('cookies.txt'): opts['cookiefile'] = 'cookies.txt'
    return opts

# --- ROTAS ---

@app.route('/')
def homepage():
    return render_template("index.html")

# Rota de Login (NOVO)
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    if data.get('password') == ADMIN_PASSWORD:
        session['logged_in'] = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Senha incorreta'}), 401

@app.route('/info', methods=['POST'])
def info():
    if not session.get('logged_in'): return jsonify({'error': 'Acesso negado. Faça login.'}), 403
    
    url = request.form.get('url')
    try:
        with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({'title': info.get('title'), 'thumbnail': info.get('thumbnail')})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/progress/<task_id>', methods=['GET'])
def get_progress(task_id):
    # Progresso pode ser público ou protegido, deixei público para não quebrar o polling
    return jsonify(progress_store.get(task_id, {'percent': '0%', 'status': 'waiting'}))

@app.route('/download', methods=['POST'])
def download():
    if not session.get('logged_in'): return "Não autorizado", 403

    # ... (Mantenha toda a lógica de download, validação de captcha e hooks iguais ao anterior) ...
    # Vou resumir para caber na resposta, mas use a lógica completa da resposta anterior aqui
    
    token = request.form.get('cf-turnstile-response')
    ip = request.headers.get('CF-Connecting-IP') or request.remote_addr
    valid, msg = validate_turnstile(token, ip)
    if not valid: return f"Erro: {msg}", 403

    url = request.form.get('url')
    quality = request.form.get('quality')
    task_id = request.form.get('task_id')
    
    if not os.path.exists('downloads'): os.makedirs('downloads')

    def progress_hook(d):
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%').replace('\x1b[0;94m', '').replace('\x1b[0m', '')
            progress_store[task_id] = {'percent': p, 'status': 'downloading'}
        elif d['status'] == 'finished':
            progress_store[task_id] = {'percent': '100%', 'status': 'converting'}

    opts = get_ydl_opts()
    opts.update({'outtmpl': 'downloads/%(title)s.%(ext)s', 'cachedir': False, 'progress_hooks': [progress_hook]})

    if quality == 'audio':
        opts.update({'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}]})
    elif quality == 'best':
        opts['format'] = 'bestvideo+bestaudio/best'
    else:
        opts['format'] = f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]'

    try:
        progress_store[task_id] = {'percent': '0%', 'status': 'starting'}
        filename_to_send = None
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            fname = ydl.prepare_filename(info)
            filename_to_send = os.path.splitext(fname)[0] + ".mp3" if quality == 'audio' else fname
            
            progress_store[task_id] = {'percent': '100%', 'status': 'completed'}

            @after_this_request
            def remove_file(res):
                try:
                    if filename_to_send and os.path.exists(filename_to_send): os.remove(filename_to_send)
                except: pass
                return res
            return send_file(filename_to_send, as_attachment=True)
    except Exception as e:
        progress_store[task_id] = {'percent': '0%', 'status': 'error'}
        return str(e), 500

if __name__ == '__main__':
    app.run(host="127.0.0.1", port=PORT, debug=True, threaded=True)