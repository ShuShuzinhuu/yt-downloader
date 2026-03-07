from dotenv import load_dotenv
load_dotenv()
import subprocess
import sys
import os
import requests
import shutil
from flask import Flask, request, jsonify, render_template, send_file, after_this_request, session, redirect, url_for
from apscheduler.schedulers.background import BackgroundScheduler
import yt_dlp

app = Flask(__name__)

# --- CONFIGURAÇÕES ---
app.secret_key = os.getenv("FLASK_SECRET_KEY", "chave_secreta_aleatoria_para_sessao")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123") 
CF_SECRET_KEY = os.getenv("CF_SECRET_KEY")
PORT = int(os.getenv("FLASK_PORT", 8022))

progress_store = {}

# --- UPDATER ---
def update_yt_dlp():
    print("🔄 Verificando atualizações do yt-dlp...")
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp'], 
            capture_output=True, text=True
        )
        if "Successfully installed" in result.stdout:
            print("✅ yt-dlp atualizado com sucesso! Reiniciando o servidor para aplicar...")
            os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            print("⚡ yt-dlp já está na versão mais recente.")
    except Exception as e:
        print(f"❌ Erro ao atualizar: {e}")

# --- FUNÇÕES AUXILIARES ---
def validate_turnstile(token, ip):
    if not CF_SECRET_KEY: return True, "Sucesso"
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
        'remote_components': ['ejs:github'],   # Mantido o seu original
        'js_runtimes': {
            'node': {}                         # Mantido o seu original
        },
        'cachedir': os.path.join(os.getcwd(), '.yt-dlp-cache'),
        'force_ipv4': True,
        'extractor_retries': 5,
        'fragment_retries': 5,
        'retries': 5,
        'noplaylist': True, # Essencial para o check ser instantâneo!
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
        return jsonify({'error': f'Falha ao obter info: {str(e)}'}), 500

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
    dl_mode = request.form.get('dl_mode', 'video') # Recebe se é vídeo ou playlist
    task_id = request.form.get('task_id')

    os.makedirs('downloads', exist_ok=True)
    task_dir = os.path.join('downloads', task_id)

    def progress_hook(d):
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%').replace('\x1b[0;94m', '').replace('\x1b[0m', '')
            progress_store[task_id] = {'percent': p, 'status': 'downloading'}
        elif d['status'] == 'error':
            progress_store[task_id] = {'percent': '0%', 'status': 'error'}
        elif d['status'] == 'finished':
            progress_store[task_id] = {'percent': '100%', 'status': 'converting'}

    opts = get_ydl_opts()
    opts.update({'progress_hooks': [progress_hook]})

    # Lógica de Playlist
    if dl_mode == 'playlist':
        opts['noplaylist'] = False
        opts['playlistend'] = 50 
        os.makedirs(task_dir, exist_ok=True)
        opts['outtmpl'] = os.path.join(task_dir, '%(playlist_index)02d - %(title)s.%(ext)s')
    else:
        opts['noplaylist'] = True
        opts['outtmpl'] = 'downloads/%(title)s.%(ext)s'

    if quality == 'audio':
        opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}]
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
            
            if dl_mode == 'playlist':
                progress_store[task_id] = {'percent': '100%', 'status': 'zipping'}
                shutil.make_archive(task_dir, 'zip', task_dir)
                filename_to_send = f"{task_dir}.zip"
            else:
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
                    if dl_mode == 'playlist':
                        if os.path.exists(filename_to_send): os.remove(filename_to_send)
                        if os.path.exists(task_dir): shutil.rmtree(task_dir)
                    else:
                        if os.path.exists(filename_to_send): os.remove(filename_to_send)
                        if os.path.exists(fname) and fname != filename_to_send: os.remove(fname)
                except: pass
                return res

            return send_file(filename_to_send, as_attachment=True)

    except Exception as e:
        progress_store[task_id] = {'percent': '0%', 'status': 'error'}
        return str(e), 500

if __name__ == '__main__':
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)