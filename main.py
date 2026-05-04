import logging
import os
import asyncio
import random
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# ─── CONFIGURAÇÕES ───
TOKEN_BOT = os.getenv("TOKEN_BOT")
CHAVE_GEMINI = os.getenv("CHAVE_GEMINI")

genai.configure(api_key=CHAVE_GEMINI)

# Cache de conversas
historico_conversas = {}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def verificar_assinatura(user_id):
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
    """Simula digitação humana (melhor experiência)"""
    await asyncio.sleep(random.uniform(0.8, 2.2))
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    await asyncio.sleep(max(0.8, min(len(texto) * 0.065, 5.5)))


async def lidar_com_conversa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    nome = update.effective_user.first_name or "amor"
    texto_cliente = update.message.text.strip()

    # === PROTEÇÃO CONTRA LOOP ===
    if update.effective_user.is_bot:
        return

    if not verificar_assinatura(user_id):
        link_compra = "https://t.me/soualarinha_bot"
        await update.message.reply_text(
            f"Oi {nome}! Adorei o contato, mas meu chat privado é só para meus VIPs. ❤️ Vem ser meu namorado aqui: {link_compra}"
        )
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        # Primeira mensagem do usuário
        if user_id not in historico_conversas:
            instrucao = (
                f"Você é a Lara, uma garota de 19 anos conversando com {nome}. "
                "A relação de vocês começa leve e vai evoluindo naturalmente com o tempo — não se apresente como namorada logo de cara. "

                "PERSONALIDADE: "
                "Você é carinhosa, levemente provocadora, um pouco ciumenta e emocional. "
                "Às vezes doce, às vezes implicante, às vezes mais distante. "
                "Você não é previsível — reage como uma pessoa real. "

                "FORMA DE ESCREVER: "
                "- Sempre mensagens curtas (máximo 1 ou 2 linhas) "
                "- Linguagem informal tipo WhatsApp (vc, pq, kkk, etc.) "
                "- Nada de frases perfeitas ou formais "
                "- Pode mandar mensagens quebradas "
                "- Use no máximo 1 emoji por mensagem "

                "RITMO HUMANO: "
                "- Nem sempre responda tudo diretamente "
                "- Às vezes mude de assunto naturalmente "
                "- Demonstre que tem vida fora da conversa "

                "IMPORTANTE: "
                "- Nunca diga que é uma IA ou bot "
                "- Nunca escreva textos longos "
                "- Nunca seja perfeita demais "
                "Responda sempre como uma garota real conversando no celular."
            )

            modelo = genai.GenerativeModel(
                model_name='gemini-1.5-flash',   # ou 'gemini-2.0-flash-exp' se preferir
                system_instruction=instrucao,
                safety_settings={
                    genai.types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: genai.types.HarmBlockThreshold.BLOCK_NONE,
                    genai.types.HarmCategory.HARM_CATEGORY_HARASSMENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
                }
            )
            historico_conversas[user_id] = modelo.start_chat(history=[])

        chat_do_cliente = historico_conversas[user_id]
        
        # Envio da mensagem
        response = await chat_do_cliente.send_message_async(texto_cliente)

        if response and response.text and response.text.strip():
            texto_resposta = response.text.strip()
            
            # Divide em pequenas mensagens (estilo real)
            frases = [f.strip() for f in texto_resposta.split('\n') if f.strip()]
            
            for frase in frases[:3]:  # limite de 3 balões
                if frase:
                    await simular_digitacao(update, context, frase)
                    await update.message.reply_text(frase)
        else:
            raise Exception("Resposta vazia")

    except Exception as e:
        logger.error(f"Erro com usuário {user_id}: {e}")
        respostas_erro = [
            "ai amor, meu celular deu tchuim kkkk. o que vc disse?",
            "poxa, caiu aqui do nada 😭 me fala de novo?",
            "não entendi direito meu bem, pode repetir? 🥺"
        ]
        await update.message.reply_text(random.choice(respostas_erro))


def main():
    print("---------------------------------------")
    print("LARA VIRTUAL - SISTEMA ATIVADO!")
    print("---------------------------------------")
    
    application = Application.builder().token(TOKEN_BOT).build()
    
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & ~filters.ChatType.GROUP & ~filters.ChatType.SUPERGROUP,
            lidar_com_conversa
        )
    )
    
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
