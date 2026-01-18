from flask import Flask, render_template, request, jsonify, session
import threading
import time
from datetime import datetime, timedelta
import requests
import hashlib
import uuid
import os

app = Flask(__name__)
app.secret_key = "uma_chave_super_secreta_qualquer"

# ===== FEATURE FLAGS =====
FEATURES = {
    "modo_agendado": True,      # Espera até 14h
    "modo_reserva": True,        # Reserva imediatamente
}

# ===== CONFIG =====
LOGIN_ANTECIPADO = "13:59:57"  # Atualizado para 13:59:57
INICIO_TENTATIVAS = "13:59:57"  # Mesmo horário
FIM_EXECUCAO = "14:00:10"

# Keep-alive config
KEEP_ALIVE_URL = os.environ.get("RENDER_EXTERNAL_URL", "")  # URL do seu app no Render
KEEP_ALIVE_ATIVO = False

# ===== SESSÕES =====
user_threads = {}
user_logs = {}
user_cancel = {}
user_info = {}  # NOVO: Armazena info de cada sessão ativa
lock = threading.Lock()

# ===== KEEP-ALIVE AUTOMÁTICO =====
def keep_alive_worker():
    """Thread que mantém o app ativo fazendo ping em si mesmo"""
    global KEEP_ALIVE_ATIVO
    
    while KEEP_ALIVE_ATIVO:
        try:
            # Só mantém ativo entre 7h e 22h (horário de Brasília)
            hora_atual = datetime.now().hour
            
            if 7 <= hora_atual <= 22:
                if KEEP_ALIVE_URL:
                    # Faz ping em si mesmo
                    requests.get(f"{KEEP_ALIVE_URL}/health", timeout=5)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Keep-alive ping enviado")
            
            # Aguarda 10 minutos
            time.sleep(600)  # 600 segundos = 10 minutos
            
        except Exception as e:
            print(f"Erro no keep-alive: {e}")
            time.sleep(60)  # Se der erro, espera 1 minuto e tenta de novo

def iniciar_keep_alive():
    """Inicia o sistema de keep-alive"""
    global KEEP_ALIVE_ATIVO
    
    if not KEEP_ALIVE_URL:
        print("⚠️ RENDER_EXTERNAL_URL não configurada. Keep-alive desabilitado.")
        return
    
    KEEP_ALIVE_ATIVO = True
    thread = threading.Thread(target=keep_alive_worker, daemon=True)
    thread.start()
    print(f"✅ Keep-alive iniciado! Mantendo ativo das 7h às 22h")

# ===== UTIL =====
def log(session_id, msg):
    with lock:
        if session_id not in user_logs:
            user_logs[session_id] = []
        timestamp = datetime.now().strftime('%H:%M:%S')
        user_logs[session_id].append(f"[{timestamp}] {msg}")
        if len(user_logs[session_id]) > 200:
            user_logs[session_id] = user_logs[session_id][-200:]

def atualizar_status(session_id, status, detalhes=""):
    """Atualiza o status de uma sessão"""
    with lock:
        user_info[session_id]["status"] = status
        user_info[session_id]["detalhes"] = detalhes
        user_info[session_id]["ultimo_update"] = datetime.now().strftime('%H:%M:%S')

def gerar_md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def esperar(session_id, hora_alvo):
    """Aguarda até atingir o horário alvo (formato HH:MM:SS)"""
    log(session_id, f"⏳ Aguardando até {hora_alvo} para iniciar...")
    
    while True:
        if user_cancel.get(session_id, False):
            return False
        
        agora = datetime.now().strftime("%H:%M:%S")
        if agora >= hora_alvo:
            log(session_id, "▶️ Horário atingido! Iniciando processo...")
            return True
        
        time.sleep(0.5)

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
    atualizar_status(session_id, "iniciando", "Modo Reserva")
    log(session_id, "⚡ Modo Reserva - Tentando agendar AGORA")
    
    try:
        atualizar_status(session_id, "login", "Fazendo login...")
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
            atualizar_status(session_id, "tentando", f"Tentativa {tentativa}")
            
            if user_cancel.get(session_id, False):
                atualizar_status(session_id, "cancelado", "Usuário cancelou")
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
                                    atualizar_status(session_id, "sucesso", f"{nome} às {horario}")
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
        
        atualizar_status(session_id, "falhou", "Tempo esgotado")
        log(session_id, "")
        log(session_id, f"❌ Tempo esgotado após {tentativa} tentativas")
        log(session_id, "Nenhuma reserva realizada")
        
    except Exception as e:
        atualizar_status(session_id, "erro", str(e))
        log(session_id, f"❌ ERRO FATAL: {str(e)}")
        import traceback
        log(session_id, f"Detalhes: {traceback.format_exc()}")

# ===== MODO AGENDADO (14h - COM ESPERA) =====
def processo_agendado(session_id, dados):
    user_cancel[session_id] = False
    atualizar_status(session_id, "aguardando", f"Aguardando até {INICIO_TENTATIVAS}")
    log(session_id, "⏰ Modo Agendado - Bot iniciado")
    
    try:
        # AGUARDA até 13:59:57 para começar
        if not esperar(session_id, INICIO_TENTATIVAS):
            atualizar_status(session_id, "cancelado", "Cancelado antes do início")
            log(session_id, "Cancelado antes do início")
            return
        
        # Faz login assim que atinge o horário
        atualizar_status(session_id, "login", "Fazendo login...")
        log(session_id, "🔐 Fazendo login...")
        token = login(dados["user"], dados["senha"])
        log(session_id, "✅ Login realizado com sucesso!")
        
        # Se não passou data, usa amanhã
        data = dados.get("data", "")
        if not data:
            data = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        log(session_id, f"📅 Data: {data}")
        log(session_id, f"🎾 Quadras: {', '.join(dados['quadras'])}")
        log(session_id, f"🕐 Horários: {', '.join(dados['horarios'])}")
        log(session_id, "")
        log(session_id, "🚀 Iniciando tentativas de reserva...")
        
        # Define horário de fim
        fim_execucao_dt = datetime.strptime(FIM_EXECUCAO, "%H:%M:%S").time()
        sucesso = False
        tentativa = 0
        
        while datetime.now().time() < fim_execucao_dt and not sucesso:
            tentativa += 1
            atualizar_status(session_id, "tentando", f"Tentativa {tentativa}")
            
            if user_cancel.get(session_id, False):
                atualizar_status(session_id, "cancelado", "Usuário cancelou")
                log(session_id, "Cancelado pelo usuário")
                return
            
            try:
                grade = buscar_horarios(token, data)
            except PermissionError:
                log(session_id, "⚠️ Token expirado, refazendo login...")
                token = login(dados["user"], dados["senha"])
                continue
            except Exception as e:
                log(session_id, f"⚠️ Erro ao buscar horários: {e}")
                time.sleep(0.8)
                continue
            
            # Tenta cada horário, esgotando todas as quadras antes de passar pro próximo
            for horario_prioritario in dados["horarios"]:
                if sucesso or user_cancel.get(session_id, False):
                    break
                
                log(session_id, f"⏩ Tentando todas quadras no horário {horario_prioritario}...")
                
                for quadra in grade:
                    if sucesso or user_cancel.get(session_id, False):
                        break
                    
                    codigo = quadra["dependencia"]["codigo"].strip()
                    nome = quadra["dependencia"]["descricao"]
                    
                    # Filtra apenas quadras desejadas
                    if codigo not in dados["quadras"]:
                        continue
                    
                    # Procura o horário específico nesta quadra
                    for item in quadra.get("horarios", []):
                        hora_inicio = item.get("horaInicial")
                        status = item.get("status", "").lower() if item.get("status") else ""
                        
                        if hora_inicio == horario_prioritario and status == "livre":
                            log(session_id, f"🟢 Livre: {nome} ({codigo}) - {horario_prioritario}")
                            try:
                                if reservar(token, horario_prioritario, codigo, dados["matricula"], data):
                                    atualizar_status(session_id, "sucesso", f"{nome} às {horario_prioritario}")
                                    log(session_id, "")
                                    log(session_id, "✅✅✅ RESERVA CONFIRMADA!")
                                    log(session_id, f"📍 Quadra: {nome} ({codigo})")
                                    log(session_id, f"🕐 Horário: {horario_prioritario}")
                                    log(session_id, f"📅 Data: {data}")
                                    sucesso = True
                                    break
                                else:
                                    log(session_id, f"❌ Falhou: {nome} ({codigo}) às {horario_prioritario}")
                            except PermissionError:
                                log(session_id, "⚠️ Token expirado durante reserva, refazendo login...")
                                token = login(dados["user"], dados["senha"])
                                break
                            except Exception as e:
                                log(session_id, f"❌ Erro ao reservar: {e}")
            
            if not sucesso:
                time.sleep(0.8)
        
        if not sucesso:
            atualizar_status(session_id, "falhou", "Nenhuma quadra disponível")
            log(session_id, "")
            log(session_id, "❌ Nenhuma quadra encontrada dentro da janela de tempo")
        
    except Exception as e:
        atualizar_status(session_id, "erro", str(e))
        log(session_id, f"❌ Erro geral: {e}")
        import traceback
        log(session_id, f"Detalhes: {traceback.format_exc()}")

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
    
    # Salva informações da sessão
    with lock:
        user_info[session_id] = {
            "usuario": dados.get("user", ""),
            "modo": modo,
            "status": "iniciando",
            "detalhes": "",
            "inicio": datetime.now().strftime('%H:%M:%S'),
            "ultimo_update": datetime.now().strftime('%H:%M:%S'),
            "quadras": dados.get("quadras", []),
            "horarios": dados.get("horarios", [])
        }
    
    func = funcoes[modo]
    
    thread = threading.Thread(target=func, args=(session_id, dados), daemon=True)
    user_threads[session_id] = thread
    thread.start()
    
    return jsonify({"status": "ok", "modo": modo, "session_id": session_id})

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

@app.route("/keep-alive")
def keep_alive():
    """Endpoint para manter o servidor acordado no Render"""
    return jsonify({
        "status": "alive",
        "active_threads": len(user_threads),
        "keep_alive_ativo": KEEP_ALIVE_ATIVO,
        "time": datetime.now().isoformat()
    })

@app.route("/ativar-keep-alive", methods=["POST"])
def ativar_keep_alive():
    """Ativa o sistema de keep-alive (útil para agendar às 14h)"""
    global KEEP_ALIVE_ATIVO
    
    if not KEEP_ALIVE_ATIVO and KEEP_ALIVE_URL:
        iniciar_keep_alive()
        return jsonify({"status": "ok", "msg": "Keep-alive ativado!"})
    elif not KEEP_ALIVE_URL:
        return jsonify({"status": "erro", "msg": "URL não configurada"})
    else:
        return jsonify({"status": "ok", "msg": "Já está ativo"})

@app.route("/status")
def status_geral():
    """Mostra status de todos os agendamentos ativos"""
    with lock:
        sessoes_ativas = []
        
        for session_id, info in user_info.items():
            # Verifica se thread ainda está viva
            thread = user_threads.get(session_id)
            if thread and thread.is_alive():
                sessoes_ativas.append({
                    "usuario": info.get("usuario", ""),
                    "modo": info.get("modo", ""),
                    "status": info.get("status", ""),
                    "detalhes": info.get("detalhes", ""),
                    "inicio": info.get("inicio", ""),
                    "ultimo_update": info.get("ultimo_update", ""),
                    "quadras": info.get("quadras", []),
                    "horarios": info.get("horarios", [])
                })
        
        return jsonify({
            "total_ativo": len(sessoes_ativas),
            "sessoes": sessoes_ativas,
            "hora_servidor": datetime.now().strftime('%H:%M:%S')
        })

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    
    # Inicia keep-alive automaticamente se URL estiver configurada
    if KEEP_ALIVE_URL:
        iniciar_keep_alive()
    
    app.run(host="0.0.0.0", port=port, debug=False)