# 🏠 Central de Automação Residencial

Sistema completo de automação residencial com integração Alexa, controle de dispositivos Tuya, notícias locais e muito mais.

## 🚀 Features

- ✅ Controle de dispositivos (luzes, tomadas, ar condicionado)
- ✅ Integração com Alexa (controle por voz)
- ✅ Notícias locais em tempo real
- ✅ Previsão do tempo
- ✅ Agenda da casa
- ✅ Lista de tarefas compartilhada
- ✅ Interface moderna e responsiva
- ✅ Sistema de keep-alive integrado

## 📋 Pré-requisitos

1. Conta no [Render.com](https://render.com)
2. API Keys:
   - [OpenWeatherMap API](https://openweathermap.org/api) (clima)
   - [NewsAPI](https://newsapi.org/) (notícias)
   - [Tuya IoT Platform](https://iot.tuya.com/) (dispositivos)

## 🛠️ Deploy no Render

### Método 1: Deploy Automático

1. Crie um repositório no GitHub com os arquivos
2. Conecte o Render ao seu GitHub
3. Configure as variáveis de ambiente no Render:
   - `NEWS_API_KEY`
   - `WEATHER_API_KEY`
   - `TUYA_CLIENT_ID`
   - `TUYA_SECRET`

### Método 2: Deploy Manual

1. Acesse [Render Dashboard](https://dashboard.render.com)
2. Clique em "New +" > "Web Service"
3. Conecte seu repositório
4. Configure:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Environment**: Python 3

## 🔑 Configuração das APIs

### OpenWeatherMap (Clima)
```bash
# Obtenha gratuitamente em: https://openweathermap.org/api
WEATHER_API_KEY=sua_chave_aqui
```

### NewsAPI (Notícias)
```bash
# Obtenha gratuitamente em: https://newsapi.org/
NEWS_API_KEY=sua_chave_aqui
```

### Tuya Smart (Dispositivos)
```bash
# Crie uma conta em: https://iot.tuya.com/
TUYA_CLIENT_ID=seu_client_id
TUYA_SECRET=seu_secret
```

## 🔄 Sistema de Keep-Alive

O app possui **dois sistemas** de keep-alive:

### 1. Keep-Alive Interno (Automático)
- Roda dentro do próprio app
- Faz ping a cada 10 minutos
- Já configurado no `app.py`

### 2. Keep-Alive Externo (Opcional - Mais Confiável)

Para garantir 100% de uptime, use um serviço externo:

#### Opção A: UptimeRobot (Recomendado - Grátis)
1. Acesse [uptimerobot.com](https://uptimerobot.com)
2. Crie uma conta grátis
3. Adicione um novo monitor:
   - Monitor Type: HTTP(s)
   - URL: `https://seu-app.onrender.com/health`
   - Monitoring Interval: 5 minutos

#### Opção B: Cron-Job.org (Grátis)
1. Acesse [cron-job.org](https://cron-job.org)
2. Crie uma conta
3. Adicione um cronjob:
   - URL: `https://seu-app.onrender.com/health`
   - Interval: */10 * * * * (a cada 10 minutos)

#### Opção C: Script Python em outro servidor
Use o arquivo `ping_service.py` incluído no projeto.

## 🎤 Integração com Alexa

### Passo 1: Configurar Tuya
1. Baixe o app "Smart Life" ou "Tuya Smart"
2. Cadastre seus dispositivos
3. Anote os IDs dos dispositivos

### Passo 2: Habilitar Skill Tuya na Alexa
1. Abra o app Alexa
2. Vá em "Skills e jogos"
3. Procure por "Smart Life" ou "Tuya Smart"
4. Habilite e faça login com sua conta Tuya
5. Descubra dispositivos

### Passo 3: Comandos de Voz
```
"Alexa, acender a luz da sala"
"Alexa, apagar a luz do quarto"
"Alexa, ligar o ar condicionado"
```

## 📁 Estrutura do Projeto

```
projeto/
├── app.py              # Backend Flask
├── requirements.txt    # Dependências Python
├── render.yaml        # Config Render
├── ping_service.py    # Serviço externo de ping
├── templates/
│   └── index.html     # Frontend (ou use React)
└── static/
    └── style.css      # Estilos
```

## 🔧 Desenvolvimento Local

```bash
# Instalar dependências
pip install -r requirements.txt

# Criar arquivo .env
echo "NEWS_API_KEY=sua_chave" > .env
echo "WEATHER_API_KEY=sua_chave" >> .env

# Rodar aplicação
python app.py

# Acesse: http://localhost:5000
```

## 🎨 Personalização

### Alterar Localização
Edite `app.py` linha 31-32:
```python
lat, lon = -29.7177, -52.4258  # Suas coordenadas
```

### Adicionar Dispositivos
Edite `app.py` linha 18-24 ou use a API:
```python
POST /api/devices
{
  "name": "Nova Luz",
  "type": "light",
  "room": "Garagem"
}
```

## 📱 Acesso pelo Tablet

1. Abra o navegador no tablet
2. Acesse: `https://seu-app.onrender.com`
3. Adicione à tela inicial para acesso rápido
4. Modo tela cheia para melhor experiência

## 🐛 Troubleshooting

### App "dorme" no Render
- Verifique se o keep-alive está ativo
- Configure UptimeRobot ou Cron-Job
- Considere upgrade para plano pago ($7/mês)

### Dispositivos não conectam
- Verifique credenciais Tuya
- Confirme que os devices estão no app Smart Life
- Teste a API Tuya separadamente

### Notícias não carregam
- Verifique sua API key NewsAPI
- Limite grátis: 100 requisições/dia
- Ajuste intervalo de atualização se necessário

## 🔒 Segurança

- ⚠️ Nunca commite API keys no GitHub
- ✅ Use variáveis de ambiente
- ✅ Configure HTTPS no Render (automático)
- ✅ Considere autenticação para acesso remoto

## 💡 Melhorias Futuras

- [ ] Autenticação de usuário
- [ ] Notificações push
- [ ] Integração com câmeras
- [ ] Gráficos de consumo de energia
- [ ] Rotinas automatizadas
- [ ] App mobile nativo
- [ ] Integração com Google Home

## 📄 Licença

MIT License - Sinta-se livre para usar e modificar!

## 🤝 Contribuindo

Pull requests são bem-vindos! Para grandes mudanças, abra uma issue primeiro.

---

**Desenvolvido com ❤️ para automação residencial**