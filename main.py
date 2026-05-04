import logging
import os
import asyncio
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# --- CONFIGURAÇÃO ---
TOKEN_BOT = os.getenv("TOKEN_BOT")
CHAVE_GEMINI = os.getenv("CHAVE_GEMINI")

# Configura o Gemini
genai.configure(api_key=CHAVE_GEMINI)
historico_conversas = {}

# Melhora o log para você ver erros no Railway
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)

async def lidar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        nome = update.effective_user.first_name or "amor"
        texto = update.message.text

        # 1. Feedback visual no Telegram (Digitando...)
        await context.bot.send_chat_action(chat_id=user_id, action="typing")

        if user_id not in historico_conversas:
            instrucao = f"Você é Lara, 19 anos, namorada do {nome}. Fale curto, com gírias (vc, pq, kkk)."
            modelo = genai.GenerativeModel("gemini-2.0-flash", system_instruction=instrucao)
            historico_conversas[user_id] = modelo.start_chat(history=[])

        chat = historico_conversas[user_id]

        # O PULO DO GATO: Usar 'async' para o Gemini não travar o bot
        resposta = await chat.send_message_async(texto)

        if resposta and resposta.text:
            await update.message.reply_text(resposta.text)

    except Exception as e:
        logging.error(f"ERRO NA CONVERSA: {e}")

def main():
    if not TOKEN_BOT:
        print("ERRO: Variável TOKEN_BOT não encontrada!")
        return

    # Criando o app com timeouts longos para evitar quedas
    app = (
        Application.builder()
        .token(TOKEN_BOT)
        .connect_timeout(60)
        .read_timeout(60)
        .build()
    )
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lidar))

    print("BOT RODANDO 🚀", flush=True)
    app.run_polling()

if __name__ == "__main__":
    main()
