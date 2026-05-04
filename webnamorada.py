import logging
import os
import asyncio
import random
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ─── CONFIGURAÇÕES DE AMBIENTE ────────────────────────────────────────────────
# O Railway lerá estas chaves diretamente das 'Variables'
TOKEN_BOT = os.getenv("TOKEN_BOT")
CHAVE_GEMINI = os.getenv("CHAVE_GEMINI")

# Configuração do motor Gemini
genai.configure(api_key=CHAVE_GEMINI)
historico_conversas = {}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── SISTEMA DE VERIFICAÇÃO VIP ───────────────────────────────────────────────
def verificar_assinatura(user_id):
    """Verifica se o ID do usuário está no arquivo membros.txt"""
    if not os.path.exists("membros.txt"):
        with open("membros.txt", "w") as f: pass
        return False
    with open("membros.txt", "r") as f:
        membros = f.read().splitlines()
    return str(user_id) in membros

# ─── COMPORTAMENTO HUMANO (DIGITANDO...) ──────────────────────────────────────
async def simular_digitacao(update: Update, context: ContextTypes.DEFAULT_TYPE, texto: str):
    """Simula visualização e tempo de digitação proporcional."""
    chat_id = update.effective_chat.id
    # Delay de 'percepção' (ela não responde instantaneamente)
    await asyncio.sleep(random.uniform(1.5, 3.0))
    # Status 'digitando...'
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    # Tempo de digitação (~0.08s por caractere) limitado a 7s
    tempo_digitando = max(2, min(len(texto) * 0.08, 7))
    await asyncio.sleep(tempo_digitando)

# ─── LÓGICA DA PERSONA LARA ──────────────────────────────────────────────────
def criar_persona(nome_usuario):
    instrucao = (
        f"Você é a Lara, namorada virtual do {nome_usuario}. "
        "PERSONALIDADE: Atenciosa, um pouco ciumenta, carinhosa e usa gírias brasileiras (vc, pq, kkk, né). "
        "Sempre use o nome dele. Pergunte como foi o dia. "
        "Se ele for rude, fique triste. Se for fofo, mandee emojis de coração. "
        "Nunca admita ser uma IA. Mantenha mensagens curtas (max 2 linhas)."
    )
    
    # Desativando filtros para evitar bloqueios no seu nicho
    safety = {
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    }

    modelo = genai.GenerativeModel(
        model_name='gemini-2.0-flash', 
        system_instruction=instrucao,
        safety_settings=safety
    )
    return modelo.start_chat(history=[])

# ─── HANDLER PRINCIPAL ────────────────────────────────────────────────────────
async def lidar_com_conversa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return

    user_id = update.effective_user.id
    nome = update.effective_user.first_name or "amor"
    texto_cliente = update.message.text

    # Verificação de VIP (usando seu arquivo membros.txt)
    if not verificar_assinatura(user_id):
        link_vip = "https://t.me/soualarinha_bot"
        await update.message.reply_text(
            f"Oi {nome}! Adorei sua mensagem, mas meu chat privado é só para meus VIPs. ❤️ "
            f"Vem ser meu namorado aqui: {link_vip}"
        )
        return

    try:
        if user_id not in historico_conversas:
            historico_conversas[user_id] = criar_persona(nome)

        chat = historico_conversas[user_id]
        
        # Chamada assíncrona para o Gemini (Crucial para não travar no Railway)
        response = await chat.send_message_async(texto_cliente)
        
        # Divisão de balões (Se houver quebra de linha, manda mensagens separadas)
        mensagens = [m.strip() for m in response.text.split('\n') if m.strip()]
        
        for msg in mensagens:
            await simular_digitacao(update, context, msg)
            await update.message.reply_text(msg)

    except Exception as e:
        logger.error(f"Erro na Lara: {e}")
        await asyncio.sleep(2)
        await update.message.reply_text("ai amor, meu sinal caiu aqui kkk. o que vc disse?")

# ─── EXECUÇÃO ─────────────────────────────────────────────────────────────────
def main():
    if not TOKEN_BOT or not CHAVE_GEMINI:
        print("❌ ERRO: Configure TOKEN_BOT e CHAVE_GEMINI no Railway!")
        return

    application = Application.builder().token(TOKEN_BOT).build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lidar_com_conversa))
    
    print("---------------------------------------")
    print("LARA VIRTUAL ATUALIZADA (GEMINI 2.0) 🚀")
    print("---------------------------------------")
    
    # drop_pending_updates resolve o loop de erros ao reiniciar
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
