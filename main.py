import logging
import os
import asyncio
import random
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# --- CONFIGURAÇÕES ---
TOKEN_BOT = os.getenv("TOKEN_BOT")
CHAVE_GEMINI = os.getenv("CHAVE_GEMINI")

genai.configure(api_key=CHAVE_GEMINI)
historico_conversas = {}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def verificar_assinatura(user_id):
    if not os.path.exists("membros.txt"):
        return False
    with open("membros.txt", "r") as f:
        membros = f.read().splitlines()
    return str(user_id) in membros

async def simular_comportamento_humano(update: Update, context: ContextTypes.DEFAULT_TYPE, resposta: str):
    """Simula o tempo de leitura e digitação baseado no tamanho da resposta."""
    # 1. Delay de 'visualização' (ela não responde no segundo que recebe)
    await asyncio.sleep(random.uniform(1.5, 3.0))
    
    # 2. Ativa o 'digitando...'
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    # 3. Tempo de digitação proporcional (aprox. 0.08s por caractere)
    # No máximo 7 segundos para não parecer travado
    tempo_digitando = max(1.5, min(len(resposta) * 0.07, 7.0))
    await asyncio.sleep(tempo_digitando)

async def lidar_com_conversa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    nome = update.effective_user.first_name or "amor"
    texto_cliente = update.message.text

    if not verificar_assinatura(user_id):
        link_compra = "https://t.me/soualarinha_bot"
        await update.message.reply_text(f"Oi {nome}! Adorei o contato, mas meu chat privado é só para meus VIPs. ❤️ Vem ser meu namorado aqui: {link_compra}")
        return

    try:
        if user_id not in historico_conversas:
            instrucao = (
                f"Você é a Lara, 19 anos, conversando com {nome}. "
                "PERSONALIDADE: carinhosa, provocadora, um pouco ciumenta. "
                "ESCRIBA: Curto (máximo 2 linhas), gírias (vc, pq, kkk), sem perfeição formal. "
                "NUNCA admita ser IA. Mantenha o mistério e a conexão gradual."
            )
            
            # CORREÇÃO: Nome do modelo correto e remoção de filtros de segurança
            modelo = genai.GenerativeModel(
                model_name='gemini-1.5-flash', # ou 'gemini-2.0-flash-exp'
                system_instruction=instrucao,
                safety_settings={
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                }
            )
            historico_conversas[user_id] = modelo.start_chat(history=[])

        chat = historico_conversas[user_id]
        
        # Chamada assíncrona para a API
        response = await chat.send_message_async(texto_cliente)
        
        if response.text:
            # Divide a resposta em frases se houver quebra de linha (comportamento humano)
            frases = [f.strip() for f in response.text.split('\n') if f.strip()]
            
            for frase in frases:
                await simular_comportamento_humano(update, context, frase)
                await update.message.reply_text(frase)
        
    except Exception as e:
        logger.error(f"Erro real detalhado: {e}")
        await asyncio.sleep(2)
        await update.message.reply_text("ai amor, meu celular deu tchuim kkkk. o que vc disse?")

def main():
    application = Application.builder().token(TOKEN_BOT).build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lidar_com_conversa))
    
    print("LARA VIRTUAL: SISTEMA DE ALTA PERFORMANCE ATIVADO!")
    # drop_pending_updates=True limpa as mensagens acumuladas no reinício
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
