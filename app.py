# app.py
from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_cors import CORS
import requests
import os
from datetime import datetime
import threading
import time

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

# Configurações
NEWS_API_KEY = os.getenv('NEWS_API_KEY', '')
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY', '')

# Dados em memória (agenda e tarefas)
tasks = [
    {"id": 1, "text": "Comprar mantimentos", "done": False},
    {"id": 2, "text": "Pagar conta de luz", "done": False},
    {"id": 3, "text": "Levar cachorro ao veterinário", "done": True}
]

agenda = [
    {"id": 1, "time": "14:00", "event": "Reunião de trabalho", "date": "Hoje"},
    {"id": 2, "time": "18:30", "event": "Jantar em família", "date": "Hoje"},
    {"id": 3, "time": "10:00", "event": "Consulta médica", "date": "Amanhã"}
]

@app.route('/')
def index():
    """Serve a página principal"""
    return send_from_directory('static', 'index.html')

@app.route('/api/weather', methods=['GET'])
def get_weather():
    """Retorna dados do clima para Santa Cruz do Sul"""
    try:
        if not WEATHER_API_KEY:
            raise Exception("API key não configurada")
            
        lat, lon = -29.7177, -52.4258  # Santa Cruz do Sul
        url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=pt_br"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            return jsonify({
                "temp": round(data['main']['temp']),
                "condition": data['weather'][0]['description'].capitalize(),
                "humidity": data['main']['humidity'],
                "wind": round(data['wind']['speed'] * 3.6)  # m/s para km/h
            })
    except Exception as e:
        print(f"Erro ao buscar clima: {e}")
    
    # Dados padrão caso a API falhe
    return jsonify({
        "temp": 24,
        "condition": "Parcialmente nublado",
        "humidity": 65,
        "wind": 12
    })

@app.route('/api/news', methods=['GET'])
def get_news():
    """Retorna notícias locais do Brasil"""
    try:
        if not NEWS_API_KEY:
            raise Exception("API key não configurada")
            
        url = f"https://newsapi.org/v2/top-headlines?country=br&apiKey={NEWS_API_KEY}&pageSize=5"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            articles = data.get('articles', [])
            news = []
            
            for i, article in enumerate(articles):
                news.append({
                    "id": i + 1,
                    "title": article['title'],
                    "source": article['source']['name'],
                    "time": "Recente",
                    "url": article.get('url', '#')
                })
            
            return jsonify(news if news else get_default_news())
    except Exception as e:
        print(f"Erro ao buscar notícias: {e}")
    
    return jsonify(get_default_news())

def get_default_news():
    """Notícias padrão quando a API não está disponível"""
    return [
        {"id": 1, "title": "Configure NEWS_API_KEY para ver notícias reais", "source": "Sistema", "time": ""},
        {"id": 2, "title": "Temperatura agradável na região", "source": "Clima Local", "time": "2h atrás"},
        {"id": 3, "title": "Tráfego normal nas principais vias", "source": "Trânsito RS", "time": "1h atrás"}
    ]

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """Retorna lista de tarefas"""
    return jsonify(tasks)

@app.route('/api/tasks/<int:task_id>/toggle', methods=['POST'])
def toggle_task(task_id):
    """Marca/desmarca uma tarefa como concluída"""
    for task in tasks:
        if task['id'] == task_id:
            task['done'] = not task['done']
            return jsonify(task)
    return jsonify({"error": "Task not found"}), 404

@app.route('/api/tasks', methods=['POST'])
def add_task():
    """Adiciona nova tarefa"""
    data = request.json
    new_task = {
        "id": max([t['id'] for t in tasks]) + 1 if tasks else 1,
        "text": data.get('text', ''),
        "done": False
    }
    tasks.append(new_task)
    return jsonify(new_task), 201

@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    """Remove uma tarefa"""
    global tasks
    tasks = [t for t in tasks if t['id'] != task_id]
    return jsonify({"success": True})

@app.route('/api/agenda', methods=['GET'])
def get_agenda():
    """Retorna agenda"""
    return jsonify(agenda)

@app.route('/api/agenda', methods=['POST'])
def add_agenda():
    """Adiciona evento na agenda"""
    data = request.json
    new_event = {
        "id": max([e['id'] for e in agenda]) + 1 if agenda else 1,
        "time": data.get('time', ''),
        "event": data.get('event', ''),
        "date": data.get('date', 'Hoje')
    }
    agenda.append(new_event)
    return jsonify(new_event), 201

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint para keep-alive e monitoramento"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "uptime": "online"
    })

def keep_alive():
    """Sistema de keep-alive interno - ping a cada 10 minutos"""
    while True:
        try:
            time.sleep(600)  # 10 minutos
            
            # URL do próprio serviço no Render
            url = os.getenv('RENDER_EXTERNAL_URL')
            if url:
                requests.get(f"{url}/health", timeout=5)
                print(f"✓ Keep-alive ping enviado em {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"✗ Erro no keep-alive: {e}")

if __name__ == '__main__':
    # Inicia thread de keep-alive apenas em produção (Render)
    if os.getenv('RENDER_EXTERNAL_URL'):
        print("🚀 Keep-alive ativado!")
        threading.Thread(target=keep_alive, daemon=True).start()
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)