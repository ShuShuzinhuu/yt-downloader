import subprocess
import sys
import os
import requests
from flask import Flask, request, jsonify, render_template, send_file, after_this_request, session, redirect, url_for
from apscheduler.schedulers.background import BackgroundScheduler
import yt_dlp
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# --- CONFIGURAÇÕES ---
app.secret_key = os.getenv("FLASK_SECRET_KEY", "chave_secreta_aleatoria_para_sessao")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123") 
CF_SECRET_KEY = os.getenv("CF_SECRET_KEY")
EXPECTED_HOSTNAME = os.getenv("EXPECTED_HOSTNAME", "127.0.0.1")
PORT = int(os.getenv("FLASK_PORT", 8022))

progress_store = {}

# --- UPDATER ---
def update_yt_dlp():
    try: subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp'])
    except: pass

scheduler = BackgroundScheduler()
scheduler.add_job(func=update_yt_dlp, trigger="interval", hours=24)
scheduler.start()

# --- FUNÇÕES AUXILIARES ---
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
    opts = {
        'quiet': True, 
        'no_warnings': True, 
        'remote_components': 'ejs:github', 
        'source_address': '0.0.0.0',
        
        # --- SOLUÇÃO ANTI-BLOQUEIO ---
        # 1. Tenta simular um navegador desktop (web) primeiro, depois android
        'extractor_args': {
            'youtube': {
                'player_client': ['web', 'android']
            }
        },
        # 2. Adiciona um User-Agent de navegador real
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        # 3. Garante que na verificação de info ele pegue qualquer coisa que tiver
        'format': 'best/bestvideo+bestaudio',
    }
    
    # Prioridade máxima para os cookies se o arquivo existir
    if os.path.exists('cookies.txt'):
        opts['cookiefile'] = 'cookies.txt'
        
    return opts

# --- ROTAS DE NAVEGAÇÃO ---

@app.route('/')
def homepage():
    if not session.get('logged_in'):
        return redirect(url_for('login_page'))
    return render_template("index.html")

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if session.get('logged_in'):
        return redirect(url_for('homepage'))
        
    if request.method == 'POST':
        data = request.json
        if data.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Senha incorreta'}), 401
    
    return render_template("login.html")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

# --- ROTAS DA API (PROTEGIDAS) ---

@app.route('/info', methods=['POST'])
def info():
    if not session.get('logged_in'): return jsonify({'error': 'Unauthorized'}), 401
    
    url = request.form.get('url')
    if not url: return jsonify({'error': 'URL vazia'}), 400

    try:
        # Usa as opções padrão com o fix do Android
        with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({'title': info.get('title'), 'thumbnail': info.get('thumbnail')})
    except Exception as e:
        print(f"Erro no /info: {e}")
        return jsonify({'error': f"Erro ao obter info: {str(e)}"}), 500

@app.route('/progress/<task_id>', methods=['GET'])
def get_progress(task_id):
    return jsonify(progress_store.get(task_id, {'percent': '0%', 'status': 'waiting'}))

@app.route('/download', methods=['POST'])
def download():
    if not session.get('logged_in'): return "Unauthorized", 401

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
    
    opts.update({
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'cachedir': False,
        'progress_hooks': [progress_hook]
    })

    if quality == 'audio':
        opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320'
            }]
        })
    else:
        # Lógica de vídeo com fallback (/best) e conversão forçada para MP4
        opts.update({
            'format': f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best',
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
        })

    try:
        progress_store[task_id] = {'percent': '0%', 'status': 'starting'}
        filename_to_send = None
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename_original = ydl.prepare_filename(info)
            
            base_name = os.path.splitext(filename_original)[0]
            if quality == 'audio':
                filename_to_send = base_name + ".mp3"
            else:
                filename_to_send = base_name + ".mp4"
            
            progress_store[task_id] = {'percent': '100%', 'status': 'completed'}

            @after_this_request
            def remove_file(res):
                try: 
                    if filename_to_send and os.path.exists(filename_to_send): 
                        os.remove(filename_to_send)
                except: pass
                return res
            
            return send_file(filename_to_send, as_attachment=True)
            
    except Exception as e:
        progress_store[task_id] = {'percent': '0%', 'status': 'error'}
        print(f"ERRO DOWNLOAD: {e}")
        return str(e), 500

if __name__ == '__main__':
    app.run(host="127.0.0.1", port=PORT, debug=True, threaded=True)