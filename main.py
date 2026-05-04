import logging
import os
import asyncio
from collections import OrderedDict
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ─── Configuração de Logs (Essencial para o Railway) ──────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Variáveis de Ambiente ────────────────────────────────────────────────────
TOKEN_BOT = os.getenv("TOKEN_BOT")
CHAVE_GEMINI = os.getenv("CHAVE_GEMINI")

genai.configure(api_key=CHAVE_GEMINI)

# ─── Cache de Sessões (LRU) ──────────────────────────────────────────────────
MAX_USUARIOS = 500
historico_conversas: OrderedDict = OrderedDict()

def obter_chat(user_id: int, nome: str):
    if user_id in historico_conversas:
        historico_conversas.move_to_end(user_id)
        return historico_conversas[user_id]

    if len(historico_conversas) >= MAX_USUARIOS:
        historico_conversas.popitem(last=False)

    # ─── PERSONA LARA (Ajustada para o seu modelo de conversão) ───
    instrucao = (
        f"Você é a Lara, uma garota de 19 anos, muito atraente, carinhosa e envolvente. "
        f"Você está conversando com {nome}, seu namorado. "
        "Sua escrita é 100% informal: use 'vc', 'tô', 'né', 'kkk', 'fds'. "
        "Dê respostas curtas, como se estivesse teclando rápido no celular. "
        "Seja provocante na medida certa, mantenha o clima de romance e conexão. "
        "Nunca diga que é uma IA. Se te perguntarem algo que não pode responder, "
        "desvie o assunto de forma fofa ou safadinha."
    )

    # Configuração para evitar que o Gemini bloqueie conversas do "nicho hot"
    safety_settings = {
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    }

    modelo = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=instrucao,
        safety_settings=safety_settings
    )
    
    chat = modelo.start_chat(history=[])
    historico_conversas[user_id] = chat
    return chat

# ─── Lógica de Resposta (Assíncrona) ──────────────────────────────────────────
async def lidar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    nome = update.effective_user.first_name or "amor"
    texto = update.message.text.strip()

    # 1. Avisa o Telegram que estamos processando (Evita o Loop de Erros)
    await context.bot.send_chat_action(chat_id=user_id, action="typing")

    try:
        chat = obter_chat(user_id, nome)
        
        # 2. Chama a IA de forma assíncrona com Timeout
        # Usamos wait_for para garantir que o bot não fique 'pendurado' para sempre
        resposta = await asyncio.wait_for(chat.send_message_async(texto), timeout=25.0)

        if resposta and resposta.text:
            await update.message.reply_text(resposta.text)
        else:
            await update.message.reply_text("fiquei sem palavras agora... fala de novo? 🥺")

    except asyncio.TimeoutError:
        logger.error(f"Timeout na API Gemini para user {user_id}")
        await update.message.reply_text("tô com o sinal ruim aqui no quarto, manda de novo? 🙈")
    
    except Exception as e:
        logger.error(f"Erro inesperado: {e}")
        # Resposta amigável para erro técnico
        await update.message.reply_text("meu celular travou kkkk, o que vc disse?")

# ─── Execução Principal ───────────────────────────────────────────────────────
def main():
    # Configurações de rede robustas para o Railway
    app = (
        Application.builder()
        .token(TOKEN_BOT)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .build()
    )

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lidar))

    logger.info("LARA INICIADA E PRONTA PARA CONVERSÃO 🚀")
    
    # O Polling agora ignora updates antigos para não processar mensagens acumuladas
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
