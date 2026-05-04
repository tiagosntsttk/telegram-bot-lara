import logging
import os
import asyncio
import random
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

TOKEN_BOT = os.getenv("TOKEN_BOT")
CHAVE_GEMINI = os.getenv("CHAVE_GEMINI")

genai.configure(api_key=CHAVE_GEMINI)

historico_conversas = {}

logging.basicConfig(level=logging.INFO)

async def lidar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        nome = update.effective_user.first_name or "amor"
        texto = update.message.text

        if user_id not in historico_conversas:
            instrucao = f"Você é Lara, 19 anos, namorada do {nome}. Fale curto, com gírias (vc, pq, kkk)."
            modelo = genai.GenerativeModel("gemini-2.0-flash", system_instruction=instrucao)
            historico_conversas[user_id] = modelo.start_chat(history=[])

        chat = historico_conversas[user_id]

        resposta = chat.send_message(texto)

        if resposta and resposta.text:
            await update.message.reply_text(resposta.text)

    except Exception as e:
        print("ERRO:", e)

def main():
    app = Application.builder().token(TOKEN_BOT).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lidar))

    print("BOT RODANDO 🚀")
    app.run_polling()

if __name__ == "__main__":
    main()