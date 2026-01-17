from flask import Flask, render_template, request, jsonify, session
import threading
import time
from datetime import datetime, timedelta
import requests
import hashlib
import uuid

app = Flask(__name__)
app.secret_key = "uma_chave_super_secreta_qualquer"

# ===== FEATURE FLAGS =====
FEATURES = {
    "modo_agendado": True,      # Executa às 14h (programado)
    "modo_instantaneo": True,   # Busca imediata ao clicar
}

# ===== CONFIG FIXA =====
LOGIN_ANTECIPADO = "13:59:50"
INICIO_TENTATIVAS = "13:59:59"
FIM_EXECUCAO = "14:00:10"

# ===== SESSÕES =====
user_threads = {}
user_logs = {}
user_cancel = {}
lock = threading.Lock()

# ===== UTIL =====
def log(session_id, msg):
    with lock:
        if session_id not in user_logs:
            user_logs[session_id] = []
        user_logs[session_id].append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        if len(user_logs[session_id]) > 200:
            user_logs[session_id] = user_logs[session_id][-200:]

def gerar_md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def esperar(session_id, hora):
    while datetime.now().strftime("%H:%M:%S") < hora:
        if user_cancel.get(session_id, False):
            return False
        time.sleep(0.3)
    return True

# ===== API =====
def login(username, senha):
    url = "https://api-associados.areadosocio.com.br/api/Logins"
    senha_md5 = gerar_md5(senha)
    payload = {
        "modoAutenticacao": "username",
        "modulo": "portal-associados",
        "username": username,
        "senha": senha_md5,
        "senhaSociety": senha_md5
    }
    headers = {"Content-Type": "application/json", "tenant": "uniaocorinthians"}
    r = requests.post(url, json=payload, headers=headers)
    r.raise_for_status()
    return r.json()["retorno"]["token"]["valor"]

def buscar_horarios(token, data):
    url = f"https://api-associados.areadosocio.com.br/api/GruposDeDependencia/01/Horarios?data={data}T00:00:00"
    headers = {"Authorization": f"Bearer {token}", "tenant": "uniaocorinthians"}
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json().get("gradeHorarios", [])

def reservar(token, horario, quadra, matricula, data):
    url = "https://api-associados.areadosocio.com.br/api/Reservas"
    payload = {
        "codigoDependencia": quadra,
        "dia": f"{data}T00:00:00",
        "horaInicio": horario,
        "horaFim": (datetime.strptime(horario, "%H:%M") + timedelta(minutes=75)).strftime("%H:%M"),
        "matricula": matricula,
        "idModalidadeReserva": 1,
        "convidados": [],
        "haveraNaoSociosPresentes": False,
        "captcha": "ok"
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "tenant": "uniaocorinthians",
        "Content-Type": "application/json"
    }
    r = requests.post(url, json=payload, headers=headers)
    return r.json().get("ehSucesso", False)

# ===== MODO INSTANTÂNEO =====
def buscar_instantaneo(session_id, dados):
    user_cancel[session_id] = False
    log(session_id, "🔍 Modo Instantâneo - Iniciando busca")
    
    try:
        log(session_id, "Realizando login...")
        token = login(dados["user"], dados["senha"])
        log(session_id, "✅ Login realizado")
        
        data = dados.get("data", (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"))
        log(session_id, f"📅 Buscando horários para {data}")
        
        grade = buscar_horarios(token, data)
        
        encontrados = []
        for h in dados["horarios"]:
            for q in grade:
                codigo = q["dependencia"]["codigo"]
                if codigo not in dados["quadras"]:
                    continue
                
                for item in q["horarios"]:
                    if item["horaInicial"] == h:
                        status = item["status"].lower()
                        if status == "livre":
                            encontrados.append(f"✅ {codigo} às {h} - LIVRE")
                        else:
                            encontrados.append(f"❌ {codigo} às {h} - OCUPADO")
        
        if encontrados:
            log(session_id, "📋 Quadras encontradas:")
            for e in encontrados:
                log(session_id, e)
        else:
            log(session_id, "❌ Nenhuma quadra disponível nos horários selecionados")
            
    except Exception as e:
        log(session_id, f"❌ Erro: {e}")

# ===== MODO AGENDADO (14h) =====
def processo_agendado(session_id, dados):
    user_cancel[session_id] = False
    log(session_id, "⏰ Modo Agendado - Bot iniciado")
    log(session_id, "Aguardando horário de login...")
    
    try:
        if not esperar(session_id, LOGIN_ANTECIPADO):
            log(session_id, "Cancelado antes do login")
            return
        
        log(session_id, "Realizando login...")
        token = login(dados["user"], dados["senha"])
        log(session_id, "✅ Login realizado")
        
        if not esperar(session_id, INICIO_TENTATIVAS):
            log(session_id, "Cancelado antes das tentativas")
            return
        
        data = dados.get("data", (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"))
        log(session_id, "🚀 Iniciando tentativas de reserva")
        fim = datetime.strptime(FIM_EXECUCAO, "%H:%M:%S").time()
        
        while datetime.now().time() < fim:
            if user_cancel.get(session_id, False):
                log(session_id, "Cancelado pelo usuário")
                return
            
            grade = buscar_horarios(token, data)
            
            for h in dados["horarios"]:
                for q in grade:
                    codigo = q["dependencia"]["codigo"]
                    if codigo not in dados["quadras"]:
                        continue
                    
                    for item in q["horarios"]:
                        if item["horaInicial"] == h:
                            if item["status"].lower() == "livre":
                                log(session_id, f"⚡ Tentando {codigo} às {h}")
                                if reservar(token, h, codigo, dados["matricula"], data):
                                    log(session_id, f"✅ RESERVA CONFIRMADA: {codigo} às {h}")
                                    return
                                else:
                                    log(session_id, f"❌ Tentativa falhou: {codigo} às {h}")
                            else:
                                log(session_id, f"❌ Já reservado: {codigo} às {h}")
            time.sleep(0.7)
        
        log(session_id, "❌ Tempo esgotado - Nenhuma quadra disponível")
        
    except Exception as e:
        log(session_id, f"❌ Erro: {e}")

# ===== ROTAS =====
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/features")
def get_features():
    return jsonify(FEATURES)

@app.route("/start", methods=["POST"])
def start():
    dados = request.json
    modo = dados.get("modo", "agendado")
    
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())
    session_id = session["session_id"]
    
    # Verifica se feature está habilitada
    if modo == "instantaneo" and not FEATURES["modo_instantaneo"]:
        return jsonify({"status": "erro", "msg": "Modo instantâneo desabilitado"})
    if modo == "agendado" and not FEATURES["modo_agendado"]:
        return jsonify({"status": "erro", "msg": "Modo agendado desabilitado"})
    
    # Seleciona função baseada no modo
    func = buscar_instantaneo if modo == "instantaneo" else processo_agendado
    
    thread = threading.Thread(target=func, args=(session_id, dados), daemon=True)
    user_threads[session_id] = thread
    thread.start()
    return jsonify({"status": "ok", "modo": modo})

@app.route("/cancel", methods=["POST"])
def cancel():
    if "session_id" not in session:
        return jsonify({"status": "erro", "msg": "sessão não encontrada"})
    session_id = session["session_id"]
    user_cancel[session_id] = True
    log(session_id, "🛑 Cancelamento solicitado")
    return jsonify({"status": "cancelado"})

@app.route("/logs")
def get_logs():
    if "session_id" not in session:
        return jsonify([])
    session_id = session["session_id"]
    with lock:
        return jsonify(user_logs.get(session_id, []))

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)