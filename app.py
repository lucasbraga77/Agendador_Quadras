from flask import Flask, render_template, request, jsonify, session
import threading
import time
from datetime import datetime, timedelta
import requests
import hashlib
import uuid
import os
import pytz

app = Flask(__name__)
app.secret_key = "uma_chave_super_secreta_qualquer"

# ===== TIMEZONE =====
TIMEZONE_BRASIL = pytz.timezone('America/Sao_Paulo')

def agora_brasilia():
    """Retorna datetime atual no horário de Brasília"""
    return datetime.now(TIMEZONE_BRASIL)

# ===== FEATURE FLAGS =====
FEATURES = {
    "modo_agendado": True,
    "modo_reserva": True,
}

# ===== CONFIG =====
INICIO_TENTATIVAS = "14:00:00"  # Horário de Brasília
FIM_EXECUCAO = "14:00:15"

# Dashboard password
DASHBOARD_PASSWORD = "dash123@"

# Keep-alive config
KEEP_ALIVE_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
KEEP_ALIVE_ATIVO = False

# ===== SESSÕES =====
user_threads = {}
user_logs = {}
user_cancel = {}
user_info = {}
lock = threading.Lock()

# ===== KEEP-ALIVE AUTOMÁTICO =====
def keep_alive_worker():
    """Thread que mantém o app ativo fazendo ping em si mesmo"""
    global KEEP_ALIVE_ATIVO
    
    while KEEP_ALIVE_ATIVO:
        try:
            hora_atual = agora_brasilia().hour
            
            if 7 <= hora_atual <= 22:
                if KEEP_ALIVE_URL:
                    requests.get(f"{KEEP_ALIVE_URL}/health", timeout=5)
                    print(f"[{agora_brasilia().strftime('%H:%M:%S')}] Keep-alive ping enviado")
            
            time.sleep(600)
            
        except Exception as e:
            print(f"Erro no keep-alive: {e}")
            time.sleep(60)

def iniciar_keep_alive():
    """Inicia o sistema de keep-alive"""
    global KEEP_ALIVE_ATIVO
    
    if not KEEP_ALIVE_URL:
        print("⚠️ RENDER_EXTERNAL_URL não configurada. Keep-alive desabilitado.")
        return
    
    KEEP_ALIVE_ATIVO = True
    thread = threading.Thread(target=keep_alive_worker, daemon=True)
    thread.start()
    print(f"✅ Keep-alive iniciado! Mantendo ativo das 7h às 22h (horário de Brasília)")

# ===== UTIL =====
def log(session_id, msg):
    with lock:
        if session_id not in user_logs:
            user_logs[session_id] = []
        timestamp = agora_brasilia().strftime('%H:%M:%S')
        user_logs[session_id].append(f"[{timestamp}] {msg}")
        if len(user_logs[session_id]) > 200:
            user_logs[session_id] = user_logs[session_id][-200:]

def atualizar_status(session_id, status, detalhes=""):
    """Atualiza o status de uma sessão"""
    with lock:
        user_info[session_id]["status"] = status
        user_info[session_id]["detalhes"] = detalhes
        user_info[session_id]["ultimo_update"] = agora_brasilia().strftime('%H:%M:%S')

def gerar_md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def esperar(session_id, hora_alvo):
    """Aguarda até atingir o horário alvo (formato HH:MM:SS) no horário de Brasília"""
    log(session_id, f"⏳ Aguardando até {hora_alvo} (horário de Brasília) para iniciar...")
    
    # Mostra hora atual
    agora_str = agora_brasilia().strftime('%H:%M:%S')
    log(session_id, f"⏰ Hora atual: {agora_str}")
    
    # Verifica se o horário já passou hoje
    if agora_str >= hora_alvo:
        log(session_id, f"⚠️ Horário {hora_alvo} já passou hoje!")
        log(session_id, f"⏰ Aguardando até amanhã às {hora_alvo}...")
    
    atualizar_status(session_id, "aguardando", f"Aguardando até {hora_alvo}")
    
    while True:
        if user_cancel.get(session_id, False):
            return False
        
        agora_str = agora_brasilia().strftime("%H:%M:%S")
        
        # Comparação de string igual ao seu código Python
        if agora_str >= hora_alvo:
            log(session_id, "▶️ Horário atingido! Iniciando processo...")
            return True
        
        # Atualiza status mostrando quanto falta
        try:
            agora_dt = datetime.strptime(agora_str, "%H:%M:%S")
            alvo_dt = datetime.strptime(hora_alvo, "%H:%M:%S")
            diff = (alvo_dt.hour * 3600 + alvo_dt.minute * 60 + alvo_dt.second) - \
                   (agora_dt.hour * 3600 + agora_dt.minute * 60 + agora_dt.second)
            
            # Se diff for negativo, o horário já passou - espera até amanhã
            if diff < 0:
                diff = 86400 + diff  # 86400 = segundos em 1 dia
            
            if diff > 0:
                horas = diff // 3600
                minutos = (diff % 3600) // 60
                segundos = diff % 60
                
                if horas > 0:
                    tempo_falta = f"{horas}h {minutos}min"
                elif minutos > 0:
                    tempo_falta = f"{minutos}min {segundos}s"
                else:
                    tempo_falta = f"{segundos}s"
                
                atualizar_status(session_id, "aguardando", f"Faltam {tempo_falta}")
        except:
            pass
        
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
    
    if data.get("ehSucesso") and data.get("retorno", {}).get("token", {}).get("valor"):
        return data["retorno"]["token"]["valor"]
    else:
        raise Exception(f"Falha no login: {str(data)}")

def buscar_horarios(token, data):
    """data deve estar no formato YYYY-MM-DD"""
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
    horario: HH:MM
    """
    url = "https://api-associados.areadosocio.com.br/api/Reservas"
    
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
        "captcha": "qualquerValor"
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
            data = (agora_brasilia() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        log(session_id, f"📅 Data: {data}")
        log(session_id, f"🎾 Quadras: {', '.join(dados['quadras'])}")
        log(session_id, f"🕐 Horários: {', '.join(dados['horarios'])}")
        log(session_id, f"📋 Matrícula: {dados['matricula']}")
        log(session_id, "")
        log(session_id, "🚀 Iniciando tentativas...")
        
        fim = agora_brasilia() + timedelta(seconds=10)
        tentativa = 0
        
        while agora_brasilia() < fim:
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
    
    agora = agora_brasilia()
    
    log(session_id, "🤖 Modo Agendamento Automático - Bot iniciado")
    log(session_id, f"⏰ Hora atual (Brasília): {agora.strftime('%H:%M:%S')}")
    log(session_id, f"🎯 Horário programado: {INICIO_TENTATIVAS}")
    log(session_id, "")
    log(session_id, "ℹ️ IMPORTANTE: O sistema libera reservas às 14h para o DIA SEGUINTE")
    log(session_id, f"ℹ️ Quando executar às 14h, buscará quadras para {(agora + timedelta(days=1)).strftime('%d/%m/%Y')}")
    log(session_id, "")
    
    atualizar_status(session_id, "aguardando", f"Aguardando até {INICIO_TENTATIVAS}")
    
    try:
        # AGUARDA até 14:00:00 (horário de Brasília)
        if not esperar(session_id, INICIO_TENTATIVAS):
            atualizar_status(session_id, "cancelado", "Cancelado antes do início")
            log(session_id, "Cancelado antes do início")
            return
        
        # Faz login IMEDIATAMENTE quando atingir 14:00:00
        atualizar_status(session_id, "login", "Fazendo login...")
        log(session_id, "🔐 Fazendo login...")
        token = login(dados["user"], dados["senha"])
        log(session_id, "✅ Login realizado!")
        
        # Usa D+1 (amanhã no horário de Brasília)
        # IMPORTANTE: O sistema libera reservas às 14h para o DIA SEGUINTE
        # Exemplo: às 14h do dia 18, libera reservas para o dia 19
        agora = agora_brasilia()
        data = (agora + timedelta(days=1)).strftime("%Y-%m-%d")
        
        log(session_id, f"📅 Hoje: {agora.strftime('%d/%m/%Y')} às {agora.strftime('%H:%M:%S')}")
        log(session_id, f"📅 Buscando reservas para: {data} (D+1)")
        log(session_id, f"🎾 Quadras: {', '.join(dados['quadras'])}")
        log(session_id, f"🕐 Horários: {', '.join(dados['horarios'])}")
        log(session_id, "")
        log(session_id, "🚀 Iniciando tentativas de reserva...")
        
        # Define horário de fim - mas se já passou de 14h, dá uma janela de 15 segundos
        agora = agora_brasilia()
        fim_execucao_time = datetime.strptime(FIM_EXECUCAO, "%H:%M:%S").time()
        
        # Se já passou de 14h hoje, permite execução imediata por 15 segundos
        if agora.time() > fim_execucao_time:
            log(session_id, "ℹ️ Executando fora do horário programado - janela de 15 segundos")
            fim_real = agora + timedelta(seconds=15)
        else:
            fim_real = agora.replace(hour=fim_execucao_time.hour, 
                                     minute=fim_execucao_time.minute, 
                                     second=fim_execucao_time.second)
        
        sucesso = False
        tentativa = 0
        
        while agora_brasilia() < fim_real and not sucesso:
            tentativa += 1
            atualizar_status(session_id, "tentando", f"Tentativa {tentativa}")
            
            if user_cancel.get(session_id, False):
                atualizar_status(session_id, "cancelado", "Usuário cancelou")
                log(session_id, "Cancelado pelo usuário")
                return
            
            try:
                grade = buscar_horarios(token, data)
                log(session_id, f"Tentativa {tentativa}: {len(grade)} dependências encontradas")
                
                # DEBUG: Mostra TODAS as quadras retornadas
                if tentativa == 1:
                    log(session_id, "")
                    log(session_id, "🔍 DEBUG - Quadras retornadas pela API:")
                    for q in grade:
                        codigo = q["dependencia"]["codigo"].strip()
                        nome = q["dependencia"]["descricao"]
                        qtd_horarios = len(q.get("horarios", []))
                        log(session_id, f"  • {nome} ({codigo}) - {qtd_horarios} horários")
                    log(session_id, "")
                    log(session_id, f"🔍 DEBUG - Quadras que você selecionou: {dados['quadras']}")
                    log(session_id, f"🔍 DEBUG - Horários que você quer: {dados['horarios']}")
                    log(session_id, "")
                
            except PermissionError:
                log(session_id, "⚠️ Token expirado, refazendo login...")
                token = login(dados["user"], dados["senha"])
                continue
            except Exception as e:
                log(session_id, f"⚠️ Erro ao buscar horários: {e}")
                time.sleep(0.5)
                continue
            
            # Itera pelos horários na ordem de prioridade
            for horario_prioritario in dados["horarios"]:
                if sucesso or user_cancel.get(session_id, False):
                    break
                
                log(session_id, f"⏩ Verificando horário {horario_prioritario} em todas as quadras...")
                
                for quadra in grade:
                    if sucesso or user_cancel.get(session_id, False):
                        break
                    
                    codigo = quadra["dependencia"]["codigo"].strip()
                    nome = quadra["dependencia"]["descricao"]
                    
                    if codigo not in dados["quadras"]:
                        continue
                    
                    # DEBUG: Mostra os horários dessa quadra
                    if tentativa == 1:
                        log(session_id, f"  🔍 {nome} ({codigo}) - horários disponíveis:")
                        for item in quadra.get("horarios", []):
                            h_ini = item.get("horaInicial")
                            st = item.get("status", "")
                            log(session_id, f"     • {h_ini}: {st}")
                    
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
                time.sleep(0.5)
        
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
    
    if not dados.get("user") or not dados.get("senha") or not dados.get("matricula"):
        return jsonify({"status": "erro", "msg": "Preencha usuário, senha e matrícula"})
    
    if not dados.get("quadras") or not dados.get("horarios"):
        return jsonify({"status": "erro", "msg": "Selecione quadras e horários"})
    
    funcoes = {
        "reserva": reservar_agora,
        "agendado": processo_agendado,
    }
    
    if modo not in funcoes:
        return jsonify({"status": "erro", "msg": "Modo inválido"})
    
    with lock:
        user_info[session_id] = {
            "usuario": dados.get("user", ""),
            "modo": modo,
            "status": "iniciando",
            "detalhes": "",
            "inicio": agora_brasilia().strftime('%H:%M:%S'),
            "ultimo_update": agora_brasilia().strftime('%H:%M:%S'),
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
    return jsonify({
        "status": "ok",
        "time_utc": datetime.utcnow().isoformat(),
        "time_brasilia": agora_brasilia().isoformat()
    })

@app.route("/keep-alive")
def keep_alive():
    return jsonify({
        "status": "alive",
        "active_threads": len(user_threads),
        "keep_alive_ativo": KEEP_ALIVE_ATIVO,
        "time_brasilia": agora_brasilia().isoformat()
    })

@app.route("/ativar-keep-alive", methods=["POST"])
def ativar_keep_alive():
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
    """Endpoint protegido - requer autenticação"""
    if not session.get("dashboard_autenticado", False):
        return jsonify({"erro": "Não autenticado"}), 401
    
    with lock:
        sessoes_ativas = []
        sessoes_finalizadas = []
        
        for session_id, info in user_info.items():
            thread = user_threads.get(session_id)
            sessao_data = {
                "session_id": session_id[:8],  # Primeiros 8 caracteres
                "usuario": info.get("usuario", ""),
                "modo": info.get("modo", ""),
                "status": info.get("status", ""),
                "detalhes": info.get("detalhes", ""),
                "inicio": info.get("inicio", ""),
                "ultimo_update": info.get("ultimo_update", ""),
                "quadras": info.get("quadras", []),
                "horarios": info.get("horarios", []),
                "logs": user_logs.get(session_id, [])[-50:]  # Últimos 50 logs
            }
            
            if thread and thread.is_alive():
                sessoes_ativas.append(sessao_data)
            else:
                sessoes_finalizadas.append(sessao_data)
        
        return jsonify({
            "total_ativo": len(sessoes_ativas),
            "total_finalizado": len(sessoes_finalizadas),
            "sessoes_ativas": sessoes_ativas,
            "sessoes_finalizadas": sessoes_finalizadas[-10:],  # Últimas 10 finalizadas
            "hora_servidor_brasilia": agora_brasilia().strftime('%H:%M:%S')
        })

@app.route("/dashboard")
def dashboard():
    """Página de monitoramento em tempo real"""
    return render_template("dashboard.html")

@app.route("/dashboard/auth", methods=["POST"])
def dashboard_auth():
    """Valida senha do dashboard"""
    data = request.json
    senha = data.get("senha", "")
    
    if senha == DASHBOARD_PASSWORD:
        session["dashboard_autenticado"] = True
        return jsonify({"status": "ok"})
    else:
        return jsonify({"status": "erro", "msg": "Senha incorreta"}), 401

@app.route("/dashboard/check")
def dashboard_check():
    """Verifica se está autenticado"""
    autenticado = session.get("dashboard_autenticado", False)
    return jsonify({"autenticado": autenticado})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    
    if KEEP_ALIVE_URL:
        iniciar_keep_alive()
    
    print(f"🇧🇷 Servidor rodando no horário de Brasília: {agora_brasilia().strftime('%H:%M:%S')}")
    app.run(host="0.0.0.0", port=port, debug=False)