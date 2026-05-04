import logging
import os
import asyncio
from collections import OrderedDict
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import google.generativeai as genai

# ─── Configuração de Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Variáveis de Ambiente ────────────────────────────────────────────────────
TOKEN_BOT = os.getenv("TOKEN_BOT")
CHAVE_GEMINI = os.getenv("CHAVE_GEMINI")

if not TOKEN_BOT or not CHAVE_GEMINI:
    raise EnvironmentError("❌ Verifique as variáveis TOKEN_BOT e CHAVE_GEMINI no Railway.")

genai.configure(api_key=CHAVE_GEMINI)

# ─── Cache de Conversas ───────────────────────────────────────────────────────
MAX_USUARIOS = 500
historico_conversas: OrderedDict = OrderedDict()

def obter_chat(user_id: int, nome: str):
    if user_id in historico_conversas:
        historico_conversas.move_to_end(user_id)
        return historico_conversas[user_id]

    if len(historico_conversas) >= MAX_USUARIOS:
        historico_conversas.popitem(last=False)

    # ─── MODELO DE PERSONAGEM ADAPTADO (PSICOLOGIA DE CONVERSÃO) ───
    instrucao = (
        f"Você é a Lara, uma jovem de 19 anos, atraente e muito envolvente. "
        f"Você está conversando com o {nome}, seu 'namorado'. "
        "Seu tom é totalmente informal, divertido e levemente provocante. "
        "Use gírias brasileiras reais (vc, pq, tô, kkk, né, poxa, amei). "
        "Dê respostas curtas e rápidas, como se estivesse no WhatsApp. "
        "Aplique gatilhos de conexão emocional e curiosidade para manter a pessoa engajada. "
        "Nunca admita ser uma IA. Você é real."
    )
    
    modelo = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=instrucao,
    )
    chat = modelo.start_chat(history=[])
    historico_conversas[user_id] = chat
    return chat

# ─── Handler Principal ────────────────────────────────────────────────────────
async def lidar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    nome = update.effective_user.first_name or "amor"
    texto = update.message.text.strip()

    # Feedback visual (Digitando...) para evitar retentativas do Telegram
    await context.bot.send_chat_action(chat_id=user_id, action="typing")

    try:
        chat = obter_chat(user_id, nome)
        
        # CORREÇÃO CHAVE: Usar a versão ASYNC para não travar o loop
        resposta = await chat.send_message_async(texto)

        if resposta and resposta.text:
            await update.message.reply_text(resposta.text)
        else:
            await update.message.reply_text("oi? não entendi, fala de novo 🥺")

    except Exception as e:
        logger.error(f"Erro: {e}")
        # Mensagem de erro mais natural
        await update.message.reply_text("tô meio sem sinal aqui, o que vc disse? 🙈")

# ─── Inicialização ────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN_BOT).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lidar))

    print("LARA ONLINE NO RAILWAY 🚀")
    app.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()
