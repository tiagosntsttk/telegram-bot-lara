import logging
import os
import asyncio
import random
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ─── CONFIGURAÇÕES DE AMBIENTE ────────────────────────────────────────────────
# O Railway lerá estas chaves diretamente das 'Variables' que você configurou
TOKEN_BOT = os.getenv("TOKEN_BOT")
CHAVE_GEMINI = os.getenv("CHAVE_GEMINI")

# Configuração do motor de IA
genai.configure(api_key=CHAVE_GEMINI)
historico_conversas = {}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── SISTEMA DE VERIFICAÇÃO DE ASSINATURA ─────────────────────────────────────
def verificar_assinatura(user_id):
    """Verifica se o ID do usuário está no arquivo membros.txt"""
    if not os.path.exists("membros.txt"):
        # Se o arquivo não existir, cria um vazio
        with open("membros.txt", "w") as f:
            pass
        return False
    with open("membros.txt", "r") as f:
        membros = f.read().splitlines()
    return str(user_id) in membros

# ─── COMPORTAMENTO HUMANO AVANÇADO ───────────────────────────────────────────
async def simular_comportamento(update: Update, context: ContextTypes.DEFAULT_TYPE, texto: str):
    """
    Simula visualização, pausa para pensar e tempo de digitação 
    proporcional ao tamanho da resposta.
    """
    chat_id = update.effective_chat.id
    
    # 1. Pequeno delay de 'visualização' (como se ela estivesse abrindo a notificação)
    await asyncio.sleep(random.uniform(1.5, 3.0))
    
    # 2. Ativa o status 'digitando...' no Telegram
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # 3. Calcula o tempo de digitação (aprox. 0.08s por caractere)
    # Limitamos entre 2 e 7 segundos para não demorar demais
    tempo_leitura = len(texto) * 0.08
    tempo_digitando = max(2, min(tempo_leitura, 7))
    
    await asyncio.sleep(tempo_digitando)

# ─── LÓGICA DA PERSONA LARA ──────────────────────────────────────────────────
def criar_persona(nome_usuario):
    instrucao = (
        f"Você é a Lara, uma garota brasileira de 19 anos, envolvente e autêntica. "
        f"Você está conversando com o {nome_usuario}. No início, seja amigável e "
        "levemente misteriosa, deixando a intimidade crescer com o tempo. "
        "\n\nREGRAS DE COMPORTAMENTO:\n"
        "- Use gírias: 'vc', 'tô', 'né', 'kkk', 'fds', 'vixi'.\n"
        "- Escreva como no WhatsApp: frases curtas, às vezes sem pontuação perfeita.\n"
        "- Seja emocional: demonstre curiosidade, um pouco de ciúmes ou saudade.\n"
        "- NUNCA admita ser uma IA ou robô. Você é real.\n"
        "- Se a conversa ficar quente, seja provocante mas mantenha a classe.\n"
        "- Se o usuário sumir, sinta falta de forma sutil."
    )
    
    # Configuração para o Gemini não bloquear conversas do seu nicho
    safety = {
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    modelo = genai.GenerativeModel(
        model_name='gemini-2.0-flash', 
        system_instruction=instrucao,
        safety_settings=safety
    )
    return modelo.start_chat(history=[])

# ─── HANDLER DE MENSAGENS ─────────────────────────────────────────────────────
async def lidar_com_conversa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Proteção básica contra mensagens vazias
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    nome = update.effective_user.first_name or "amor"
    texto_cliente = update.message.text

    # Verifica se é membro VIP
    if not verificar_assinatura(user_id):
        # Link para o seu funil de vendas
        link_vip = "https://t.me/soualarinha_bot"
        await update.message.reply_text(
            f"Oi {nome}! Adorei sua mensagem, mas meu chat privado é só para meus VIPs. ❤️ "
            f"Vem ser meu namorado aqui: {link_vip}"
        )
        return

    try:
        # Inicia o chat se for novo
        if user_id not in historico_conversas:
            historico_conversas[user_id] = criar_persona(nome)

        chat = historico_conversas[user_id]
        
        # Gera a resposta da IA (Assíncrona para não travar o bot)
        response = await chat.send_message_async(texto_cliente)
        resposta_completa = response.text

        # 4. Divisão de Mensagens (Comportamento Humano)
        # Se a IA mandar várias frases, vamos quebrá-las para enviar em balões separados
        blocos = [b.strip() for b in resposta_completa.split('\n') if b.strip()]
        
        for bloco in blocos:
            await simular_comportamento(update, context, bloco)
            await update.message.reply_text(bloco)

    except Exception as e:
        logger.error(f"Erro na conversa: {e}")
        await asyncio.sleep(2)
        await update.message.reply_text("ai poxa, meu sinal caiu aqui kkk. o que vc disse?")

# ─── INICIALIZAÇÃO DO SISTEMA ────────────────────────────────────────────────
def main():
    if not TOKEN_BOT or not CHAVE_GEMINI:
        print("❌ ERRO CRÍTICO: Variáveis de ambiente não configuradas no Railway!")
        return

    # Criando a aplicação com timeouts reforçados
    application = (
        Application.builder()
        .token(TOKEN_BOT)
        .connect_timeout(40)
        .read_timeout(40)
        .build()
    )
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lidar_com_conversa))
    
    print("---------------------------------------")
    print("LARA VIRTUAL: ALTA PERFORMANCE ONLINE 🚀")
    print("---------------------------------------")
    
    # drop_pending_updates=True resolve o loop da imagem image_486180.png
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
