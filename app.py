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
    "modo_agendado": True,      # Espera até 14h
    "modo_reserva": True,        # Reserva imediatamente
}

# ===== CONFIG =====
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
        timestamp = datetime.now().strftime('%H:%M:%S')
        user_logs[session_id].append(f"[{timestamp}] {msg}")
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
    headers = {
        "Content-Type": "application/json",
        "Origin": "https://uniaocorinthians.areadosocio.com.br",
        "Referer": "https://uniaocorinthians.areadosocio.com.br/",
        "tenant": "uniaocorinthians",
        "Accept": "application/json"
    }
    r = requests.post(url, json=payload, headers=headers)
    r.raise_for_status()
    data = r.json()
    
    # Valida resposta como no seu código
    if data.get("ehSucesso") and data.get("retorno", {}).get("token", {}).get("valor"):
        return data["retorno"]["token"]["valor"]
    else:
        # Retorna erro detalhado
        raise Exception(f"Falha no login: {str(data)}")

def buscar_horarios(token, data):
    """
    data deve estar no formato YYYY-MM-DD (ex: 2026-01-05)
    """
    grupo_id = "01"
    data_completa = f"{data}T00:00:00"
    url = f"https://api-associados.areadosocio.com.br/api/GruposDeDependencia/{grupo_id}/Horarios?data={data_completa}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Origin": "https://uniaocorinthians.areadosocio.com.br",
        "Referer": "https://uniaocorinthians.areadosocio.com.br/",
        "tenant": "uniaocorinthians"
    }
    r = requests.get(url, headers=headers)
    
    if r.status_code == 401:
        raise PermissionError("Token expirado ou inválido")
    
    r.raise_for_status()
    return r.json().get("gradeHorarios", [])

def reservar(token, horario, quadra, matricula, data):
    """
    data: YYYY-MM-DD
    horario: HH:MM (ex: 14:30)
    matricula: matrícula do usuário
    """
    url = "https://api-associados.areadosocio.com.br/api/Reservas"
    
    # Calcula hora fim (75 minutos depois)
    hora_fim = (datetime.strptime(horario, "%H:%M") + timedelta(minutes=75)).strftime("%H:%M")
    
    payload = {
        "codigoDependencia": quadra,
        "dia": f"{data}T00:00:00",
        "horaInicio": horario,
        "horaFim": hora_fim,
        "matricula": matricula,
        "idModalidadeReserva": 1,
        "convidados": [],
        "haveraNaoSociosPresentes": False,
        "captcha": "qualquerValor"  # Igual ao seu código
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Origin": "https://uniaocorinthians.areadosocio.com.br",
        "Referer": "https://uniaocorinthians.areadosocio.com.br/",
        "tenant": "uniaocorinthians"
    }
    
    r = requests.post(url, json=payload, headers=headers)
    
    if r.status_code == 401:
        raise PermissionError("Token expirado")
    
    if r.status_code == 200:
        json_resp = r.json()
        if json_resp.get("ehSucesso"):
            return True
        # Se falhou, não é erro de código, só não conseguiu reservar
        return False
    
    return False

# ===== MODO RESERVA (Reserva imediatamente) =====
def reservar_agora(session_id, dados):
    user_cancel[session_id] = False
    log(session_id, "⚡ Modo Reserva - Tentando agendar AGORA")
    
    try:
        log(session_id, "Realizando login...")
        log(session_id, f"Usuário: {dados['user']}")
        
        token = login(dados["user"], dados["senha"])
        log(session_id, "✅ Login realizado com sucesso")
        log(session_id, f"Token obtido: {token[:20]}...")
        
        data = dados.get("data", "")
        if not data:
            data = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        log(session_id, f"📅 Data: {data}")
        log(session_id, f"🎾 Quadras: {', '.join(dados['quadras'])}")
        log(session_id, f"🕐 Horários: {', '.join(dados['horarios'])}")
        log(session_id, f"📋 Matrícula: {dados['matricula']}")
        log(session_id, "")
        log(session_id, "🚀 Iniciando tentativas...")
        
        # Tenta por 10 segundos
        fim = datetime.now() + timedelta(seconds=10)
        tentativa = 0
        
        while datetime.now() < fim:
            tentativa += 1
            
            if user_cancel.get(session_id, False):
                log(session_id, "Cancelado")
                return
            
            try:
                grade = buscar_horarios(token, data)
                log(session_id, f"Tentativa {tentativa}: {len(grade)} dependências encontradas")
            except PermissionError:
                log(session_id, "⚠️ Token expirado, refazendo login...")
                token = login(dados["user"], dados["senha"])
                continue
            except Exception as e:
                log(session_id, f"⚠️ Erro ao buscar horários: {e}")
                time.sleep(1)
                continue
            
            # Itera pelos horários (na ordem de prioridade)
            for horario in dados["horarios"]:
                if user_cancel.get(session_id, False):
                    return
                
                for quadra in grade:
                    codigo = quadra["dependencia"]["codigo"].strip()
                    nome = quadra["dependencia"]["descricao"]
                    
                    if codigo not in dados["quadras"]:
                        continue
                    
                    for item in quadra.get("horarios", []):
                        hora_inicio = item.get("horaInicial")
                        status = item.get("status", "").lower() if item.get("status") else ""
                        
                        if hora_inicio == horario and status == "livre":
                            log(session_id, f"Encontrado horário livre: {nome} ({codigo}) - {horario}")
                            log(session_id, f"⚡ Tentando reservar...")
                            try:
                                if reservar(token, horario, codigo, dados["matricula"], data):
                                    log(session_id, f"")
                                    log(session_id, f"✅✅✅ RESERVA CONFIRMADA!")
                                    log(session_id, f"📍 Quadra: {nome} ({codigo})")
                                    log(session_id, f"🕐 Horário: {horario}")
                                    log(session_id, f"📅 Data: {data}")
                                    return
                                else:
                                    log(session_id, f"❌ Falhou ao reservar: {nome} ({codigo}) às {horario}")
                            except PermissionError:
                                log(session_id, "⚠️ Token expirado durante reserva, refazendo login...")
                                token = login(dados["user"], dados["senha"])
                                break
                            except Exception as e:
                                log(session_id, f"❌ Erro ao reservar: {e}")
            
            time.sleep(0.5)
        
        log(session_id, "")
        log(session_id, f"❌ Tempo esgotado após {tentativa} tentativas")
        log(session_id, "Nenhuma reserva realizada")
        
    except Exception as e:
        log(session_id, f"❌ ERRO FATAL: {str(e)}")
        import traceback
        log(session_id, f"Detalhes: {traceback.format_exc()}")

# ===== MODO AGENDADO (14h - COM ESPERA) =====
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
        
        # Se não passou data, usa amanhã
        data = dados.get("data", "")
        if not data:
            data = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        log(session_id, f"🚀 Iniciando tentativas para {data}")
        log(session_id, f"🎾 Quadras: {', '.join(dados['quadras'])}")
        log(session_id, f"🕐 Horários: {', '.join(dados['horarios'])}")
        
        fim = datetime.strptime(FIM_EXECUCAO, "%H:%M:%S").time()
        
        while datetime.now().time() < fim:
            if user_cancel.get(session_id, False):
                log(session_id, "Cancelado pelo usuário")
                return
            
            try:
                grade = buscar_horarios(token, data)
            except PermissionError:
                log(session_id, "⚠️ Token expirado, refazendo login...")
                token = login(dados["user"], dados["senha"])
                continue
            
            # Itera pelos horários desejados (na ordem de prioridade)
            for horario in dados["horarios"]:
                if user_cancel.get(session_id, False):
                    return
                
                # Itera pelas quadras
                for quadra in grade:
                    codigo = quadra["dependencia"]["codigo"].strip()
                    nome = quadra["dependencia"]["descricao"]
                    
                    # Filtra apenas quadras desejadas
                    if codigo not in dados["quadras"]:
                        continue
                    
                    # Procura o horário específico nesta quadra
                    for item in quadra.get("horarios", []):
                        hora_inicio = item.get("horaInicial")
                        status = item.get("status", "").lower() if item.get("status") else ""
                        
                        if hora_inicio == horario:
                            if status == "livre":
                                log(session_id, f"⚡ Tentando {nome} ({codigo}) às {horario}")
                                try:
                                    if reservar(token, horario, codigo, data):
                                        log(session_id, f"✅✅✅ RESERVA CONFIRMADA: {nome} ({codigo}) às {horario}")
                                        return
                                    else:
                                        log(session_id, f"❌ Falhou: {nome} ({codigo}) às {horario}")
                                except PermissionError:
                                    log(session_id, "⚠️ Token expirado, refazendo login...")
                                    token = login(dados["user"], dados["senha"])
                            else:
                                log(session_id, f"⏭️ {nome} ({codigo}) às {horario} - {status.upper()}")
            
            time.sleep(0.5)
        
        log(session_id, "❌ Tempo esgotado - Nenhuma reserva realizada")
        
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
    
    # Valida campos obrigatórios
    if not dados.get("user") or not dados.get("senha") or not dados.get("matricula"):
        return jsonify({"status": "erro", "msg": "Preencha usuário, senha e matrícula"})
    
    if not dados.get("quadras") or not dados.get("horarios"):
        return jsonify({"status": "erro", "msg": "Selecione quadras e horários"})
    
    # Mapeia modos
    funcoes = {
        "reserva": reservar_agora,
        "agendado": processo_agendado,
    }
    
    if modo not in funcoes:
        return jsonify({"status": "erro", "msg": "Modo inválido"})
    
    func = funcoes[modo]
    
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

@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)