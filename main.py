import logging
import os
import asyncio
import random
from collections import OrderedDict
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ─── CONFIGURAÇÃO DE LOGS ───
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─── VARIÁVEIS DO RAILWAY ───
TOKEN_BOT = os.getenv("TOKEN_BOT")
CHAVE_GEMINI = os.getenv("CHAVE_GEMINI")

if not TOKEN_BOT or not CHAVE_GEMINI:
    logger.error("❌ TOKEN_BOT ou CHAVE_GEMINI não configurados no Railway!")
    exit(1)

genai.configure(api_key=CHAVE_GEMINI)

# ─── CACHE DE SESSÕES (com limite de tamanho) ───
historico_conversas = OrderedDict()
MAX_SESSOES = 100  # Limite de usuários simultâneos em memória

def verificar_assinatura(user_id: int) -> bool:
    try:
        if not os.path.exists("membros.txt"):
            return False
        with open("membros.txt", "r") as f:
            membros = f.read().splitlines()
        return str(user_id) in membros
    except Exception as e:
        logger.error(f"Erro ao ler membros.txt: {e}")
        return False

async def simular_digitacao(update: Update, context: ContextTypes.DEFAULT_TYPE, texto: str):
    await asyncio.sleep(random.uniform(1.0, 2.8))
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    tempo = max(1.2, min(len(texto) * 0.065, 7.0))
    await asyncio.sleep(tempo)

def obter_modelo_lara(nome: str):
    instrucao = (
        f"Você é a Lara, 19 anos, namorada bem carinhosa e um pouco ciumenta do {nome}. "
        "Fale de forma natural, curta, use 'vc', 'tô', 'kkk', 'amor', 'meu bem'. "
        "Seja afetuosa, use no máximo 1 emoji por mensagem. "
        "Nunca mencione que é IA ou bot."
    )
    
    safety = {
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    }
    
    return genai.GenerativeModel(
        model_name='gemini-1.5-flash',  # ou 'gemini-2.0-flash-exp' se disponível
        system_instruction=instrucao,
        safety_settings=safety
    )

async def lidar_com_conversa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    nome = update.effective_user.first_name or "amor"
    texto_usuario = update.message.text.strip()

    # ─── EVITA LOOP: ignora mensagens do próprio bot ───
    if update.effective_user.is_bot:
        return

    if not verificar_assinatura(user_id):
        await update.message.reply_text(
            f"Oi {nome}! Me chama no meu bot VIP pra gente conversar direitinho: https://t.me/soualarinha_bot ❤️"
        )
        return

    # Limita quantidade de sessões em memória
    if len(historico_conversas) > MAX_SESSOES:
        historico_conversas.popitem(last=False)

    try:
        if user_id not in historico_conversas:
            modelo = obter_modelo_lara(nome)
            historico_conversas[user_id] = modelo.start_chat(history=[])
        
        chat = historico_conversas[user_id]

        # Envia mensagem (versão síncrona dentro do async handler funciona melhor)
        response = await asyncio.to_thread(chat.send_message, texto_usuario)
        
        if not response or not response.text or not response.text.strip():
            raise ValueError("Resposta vazia do Gemini")

        # Divide em frases curtas (estilo namorada)
        frases = [f.strip() for f in response.text.split('\n') if f.strip() and len(f.strip()) > 1]
        
        for frase in frases[:3]:  # Máximo 3 balões por resposta
            await simular_digitacao(update, context, frase)
            await update.message.reply_text(frase)

    except Exception as e:
        logger.error(f"Erro com usuário {user_id} ({nome}): {type(e).__name__} - {e}", exc_info=True)
        
        # Resposta mais variada para não parecer bug
        respostas_erro = [
            "ai amor, meu celular deu tchuim kkkk. o que vc disse?",
            "poxa amor, caiu a internet aqui 😭 me fala de novo?",
            "não entendi direito meu bem, pode repetir? 🥺",
        ]
        await update.message.reply_text(random.choice(respostas_erro))

def main():
    app = Application.builder().token(TOKEN_BOT).build()
    
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.ChatType.GROUP & ~filters.ChatType.SUPERGROUP, 
        lidar_com_conversa
    ))
    
    logger.info("❤️ LARA BOT ONLINE - Modo Namorada Ativado 🚀")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
