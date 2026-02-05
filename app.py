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
PORT = int(os.getenv("FLASK_PORT", 8022))

progress_store = {}

# --- UPDATER ---
def update_yt_dlp():
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp'])
    except:
        pass

scheduler = BackgroundScheduler()
scheduler.add_job(func=update_yt_dlp, trigger="interval", hours=24)
scheduler.start()

# --- FUNÇÕES AUXILIARES ---
def validate_turnstile(token, ip):
    url = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
    data = {'secret': CF_SECRET_KEY, 'response': token, 'remoteip': ip}
    try:
        res = requests.post(url, data=data, timeout=5).json()
        if not res.get('success'):
            return False, "Captcha inválido"
        return True, "Sucesso"
    except:
        return False, "Erro conexão"

def get_ydl_opts():
    opts = {
        'quiet': False,
        'no_warnings': False,

        # Solver de JS (SABR)
        'remote_components': ['ejs:github'],   # 👈 formato certo
        'js_runtimes': {
            'node': {}
        },

        'cachedir': os.path.join(os.getcwd(), '.yt-dlp-cache'),

        # Hardening contra falhas do YouTube
        'force_ipv4': True,
        'extractor_retries': 5,
        'fragment_retries': 5,
        'retries': 5,
    }

    if os.path.exists('cookies.txt'):
        opts['cookiefile'] = 'cookies.txt'

    return opts



# --- ROTAS ---

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

@app.route('/info', methods=['POST'])
def info():
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    url = request.form.get('url')
    try:
        with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({
                'title': info.get('title'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration'),
            })
    except Exception as e:
        return jsonify({'error': f'Falha ao obter info do vídeo: {str(e)}'}), 500

@app.route('/progress/<task_id>', methods=['GET'])
def get_progress(task_id):
    return jsonify(progress_store.get(task_id, {'percent': '0%', 'status': 'waiting'}))

@app.route('/download', methods=['POST'])
def download():
    if not session.get('logged_in'):
        return "Unauthorized", 401

    token = request.form.get('cf-turnstile-response')
    ip = request.headers.get('CF-Connecting-IP') or request.remote_addr
    valid, msg = validate_turnstile(token, ip)
    if not valid:
        return f"Erro: {msg}", 403

    url = request.form.get('url')
    quality = request.form.get('quality')
    task_id = request.form.get('task_id')

    os.makedirs('downloads', exist_ok=True)

    def progress_hook(d):
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%').replace('\x1b[0;94m', '').replace('\x1b[0m', '')
            progress_store[task_id] = {'percent': p, 'status': 'downloading'}
        elif d['status'] == 'finished':
            progress_store[task_id] = {'percent': '100%', 'status': 'converting'}

    opts = get_ydl_opts()
    opts.update({
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'progress_hooks': [progress_hook]
    })

    if quality == 'audio':
        opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}
            ]
        })
    else:
        opts.update({
            'format': 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best',
            'merge_output_format': 'mp4',
        })

    try:
        progress_store[task_id] = {'percent': '0%', 'status': 'starting'}

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            fname = ydl.prepare_filename(info)

            filename_to_send = (
                os.path.splitext(fname)[0] + ".mp3"
                if quality == 'audio'
                else os.path.splitext(fname)[0] + ".mp4"
            )

            progress_store[task_id] = {'percent': '100%', 'status': 'completed'}

            @after_this_request
            def remove_file(res):
                try:
                    if os.path.exists(filename_to_send):
                        os.remove(filename_to_send)
                except:
                    pass
                return res

            return send_file(filename_to_send, as_attachment=True)

    except Exception as e:
        progress_store[task_id] = {'percent': '0%', 'status': 'error'}
        return str(e), 500

if __name__ == '__main__':
    app.run(host="127.0.0.1", port=PORT, debug=True, threaded=True)
