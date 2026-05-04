import logging
import os
import asyncio
import random
from collections import OrderedDict
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ─── CONFIGURAÇÃO DE LOGS (Veja isso no painel do Railway) ───
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─── VARIÁVEIS DO RAILWAY ───
TOKEN_BOT = os.getenv("TOKEN_BOT")
CHAVE_GEMINI = os.getenv("CHAVE_GEMINI")

genai.configure(api_key=CHAVE_GEMINI)

# ─── CACHE DE SESSÕES ───
historico_conversas = OrderedDict()

def verificar_assinatura(user_id):
    if not os.path.exists("membros.txt"):
        return False
    with open("membros.txt", "r") as f:
        membros = f.read().splitlines()
    return str(user_id) in membros

async def simular_digitacao(update: Update, context: ContextTypes.DEFAULT_TYPE, texto: str):
    # Delay de visualização (1 a 3 segundos)
    await asyncio.sleep(random.uniform(1, 3))
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    # Tempo de digitação proporcional ao texto
    tempo = max(1.5, min(len(texto) * 0.07, 6.5))
    await asyncio.sleep(tempo)

def obter_modelo_lara(nome):
    instrucao = (
        f"Você é a Lara, 19 anos, namorada do {nome}. "
        "Fale curto, use 'vc', 'tô', 'kkk'. Seja carinhosa e um pouco ciumenta. "
        "Nunca admita ser IA. Use no máximo 1 emoji por frase."
    )
    # BLOCK_NONE é essencial para o seu nicho não ser censurado
    safety = {
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    }
    return genai.GenerativeModel(
        model_name='gemini-1.5-flash', # Versão estável
        system_instruction=instrucao,
        safety_settings=safety
    )

async def lidar_com_conversa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    user_id = update.effective_user.id
    nome = update.effective_user.first_name or "amor"
    texto_usuario = update.message.text

    if not verificar_assinatura(user_id):
        await update.message.reply_text(f"Oi {nome}! Me chama no meu bot VIP pra gente conversar: https://t.me/soualarinha_bot ❤️")
        return

    try:
        if user_id not in historico_conversas:
            modelo = obter_modelo_lara(nome)
            historico_conversas[user_id] = modelo.start_chat(history=[])

        chat = historico_conversas[user_id]
        
        # IMPORTANTE: Chamada assíncrona para não travar
        response = await chat.send_message_async(texto_usuario)
        
        if response.text:
            # Quebra em balões de texto se a resposta for longa
            frases = [f.strip() for f in response.text.split('\n') if f.strip()]
            for frase in frases:
                await simular_digitacao(update, context, frase)
                await update.message.reply_text(frase)

    except Exception as e:
        logger.error(f"Erro Real: {e}")
        await update.message.reply_text("ai amor, meu celular deu tchuim kkkk. o que vc disse?")

def main():
    app = Application.builder().token(TOKEN_BOT).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lidar_com_conversa))
    logger.info("LARA ONLINE 🚀")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
