import subprocess
import sys
import os
import uuid
import requests
from flask import Flask, request, jsonify, render_template, send_file, after_this_request
from apscheduler.schedulers.background import BackgroundScheduler
import yt_dlp
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

CF_SECRET_KEY = os.getenv("CF_SECRET_KEY")
EXPECTED_HOSTNAME = os.getenv("EXPECTED_HOSTNAME", "127.0.0.1")
PORT = int(os.getenv("FLASK_PORT", 8022))
DEBUG_MODE = os.getenv("FLASK_DEBUG", "True").lower() == "true"

progress_store = {}

def update_yt_dlp():
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp'])
        print("yt-dlp atualizado.")
    except Exception as e:
        print(f"Erro update: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(func=update_yt_dlp, trigger="interval", hours=24)
scheduler.start()

def validate_turnstile(token, ip):
    url = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
    data = {
        'secret': CF_SECRET_KEY,
        'response': token,
        'remoteip': ip
    }

    try:
        response = requests.post(url, data=data, timeout=5)
        result = response.json()

        if not result.get('success'):
            return False, f"Captcha inválido: {result.get('error-codes')}"

        if result.get('action') != 'download':
            return False, "Ação do Captcha incorreta."

        if EXPECTED_HOSTNAME and result.get('hostname') not in [EXPECTED_HOSTNAME, 'localhost']:
             print(f"Aviso: Hostname diferente. Esperado: {EXPECTED_HOSTNAME}, Recebido: {result.get('hostname')}")
        
        return True, "Sucesso"

    except requests.RequestException as e:
        print(f"Erro de conexão Turnstile: {e}")
        return False, "Erro interno na validação do robô"

def get_ydl_opts():
    opts = {
        'quiet': True, 
        'no_warnings': True, 
        'remote_components': 'ejs:github', 
        'source_address': '0.0.0.0'
    }
    if os.path.exists('cookies.txt'):
        opts['cookiefile'] = 'cookies.txt'
    return opts

@app.route('/')
def homepage():
    return render_template("index.html")

@app.route('/info', methods=['POST'])
def info():
    url = request.form.get('url')
    if not url:
        return jsonify({'error': 'URL vazia'}), 400
    
    try:
        opts = get_ydl_opts()
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({'title': info.get('title'), 'thumbnail': info.get('thumbnail')})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/progress/<task_id>', methods=['GET'])
def get_progress(task_id):
    return jsonify(progress_store.get(task_id, {'percent': '0%', 'status': 'waiting'}))

@app.route('/download', methods=['POST'])
def download():
    token = request.form.get('cf-turnstile-response')
    ip = request.headers.get('CF-Connecting-IP') or request.remote_addr
    
    if not token:
        return "Erro: Complete o desafio 'Não sou um robô'", 400
        
    is_valid, error_msg = validate_turnstile(token, ip)
    
    if not is_valid:
        return f"Erro de Segurança: {error_msg}", 403

    url = request.form.get('url')
    quality = request.form.get('quality')
    task_id = request.form.get('task_id')
    
    if not os.path.exists('downloads'):
        os.makedirs('downloads')

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
        'progress_hooks': [progress_hook],
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
    elif quality == 'best':
        opts['format'] = 'bestvideo+bestaudio/best'
    else:
        opts['format'] = f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]'

    try:
        progress_store[task_id] = {'percent': '0%', 'status': 'starting'}
        filename_to_send = None
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename_original = ydl.prepare_filename(info)
            filename_to_send = os.path.splitext(filename_original)[0] + ".mp3" if quality == 'audio' else filename_original

            # --- MUDANÇA AQUI ---
            # 1. Avisamos que completou ANTES de apagar
            progress_store[task_id] = {'percent': '100%', 'status': 'completed'}

            @after_this_request
            def remove_file_and_memory(response):
                try:
                    # Deleta o arquivo do disco
                    if filename_to_send and os.path.exists(filename_to_send):
                        os.remove(filename_to_send)
                    
                    # Deleta o progresso da memória SÓ AGORA
                    if task_id in progress_store:
                        del progress_store[task_id]
                        
                except Exception as error:
                    print(f"Erro na limpeza: {error}")
                return response

            return send_file(filename_to_send, as_attachment=True)
            
    except Exception as e:
        print(f"ERRO: {e}")
        # Em caso de erro, avisa o front para parar de carregar
        progress_store[task_id] = {'percent': '0%', 'status': 'error', 'msg': str(e)}
        return f"Erro: {str(e)}", 500

if __name__ == '__main__':
    app.run(host="127.0.0.1", port=PORT, debug=DEBUG_MODE, threaded=True)