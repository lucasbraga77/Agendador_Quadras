from flask import Flask, render_template, request, jsonify
import threading
import time
from datetime import datetime, timedelta
import requests
import hashlib

app = Flask(__name__)

# ===== CONFIG FIXA =====
LOGIN_ANTECIPADO = "11:48:50"
INICIO_TENTATIVAS = "11:48:59"
FIM_EXECUCAO = "11:49:10"

DATA = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

logs = []
cancelado = False
lock = threading.Lock()

# ===== UTIL =====
def log(msg):
    with lock:
        logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def gerar_md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def esperar(hora):
    while datetime.now().strftime("%H:%M:%S") < hora:
        if cancelado:
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

def buscar_horarios(token):
    url = f"https://api-associados.areadosocio.com.br/api/GruposDeDependencia/01/Horarios?data={DATA}T00:00:00"
    headers = {"Authorization": f"Bearer {token}", "tenant": "uniaocorinthians"}
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json().get("gradeHorarios", [])

def reservar(token, horario, quadra, matricula):
    url = "https://api-associados.areadosocio.com.br/api/Reservas"
    payload = {
        "codigoDependencia": quadra,
        "dia": f"{DATA}T00:00:00",
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

# ===== PROCESSO PRINCIPAL =====
def processo(dados):
    global cancelado
    cancelado = False

    log("Bot iniciado")
    log("Aguardando horário de login...")

    try:
        if not esperar(LOGIN_ANTECIPADO):
            log("Cancelado")
            return

        log("Realizando login...")
        token = login(dados["user"], dados["senha"])
        log("Login realizado com sucesso")

        if not esperar(INICIO_TENTATIVAS):
            log("Cancelado")
            return

        log("Iniciando tentativas de reserva")

        fim = datetime.strptime(FIM_EXECUCAO, "%H:%M:%S").time()

        while datetime.now().time() < fim:
            if cancelado:
                log("Cancelado pelo usuário")
                return

            grade = buscar_horarios(token)

            for h in dados["horarios"]:
                for q in grade:
                    codigo = q["dependencia"]["codigo"]
                    if codigo not in dados["quadras"]:
                        continue

                    for item in q["horarios"]:
                        if item["horaInicial"] == h and item["status"].lower() == "livre":
                            log(f"Tentando {codigo} às {h}")
                            if reservar(token, h, codigo, dados["matricula"]):
                                log(f"✅ Reserva confirmada: {codigo} às {h}")
                                return

            time.sleep(0.7)

        log("❌ Nenhuma quadra disponível")

    except Exception as e:
        log(f"Erro: {e}")

# ===== ROTAS =====
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/start", methods=["POST"])
def start():
    dados = request.json
    threading.Thread(target=processo, args=(dados,), daemon=True).start()
    return jsonify({"status": "ok"})

@app.route("/cancel", methods=["POST"])
def cancel():
    global cancelado
    cancelado = True
    log("Cancelamento solicitado")
    return jsonify({"status": "cancelado"})

@app.route("/logs")
def get_logs():
    with lock:
        return jsonify(logs[-200:])

if __name__ == "__main__":
    app.run(debug=True)
