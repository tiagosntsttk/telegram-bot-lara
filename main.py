import logging
import os
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

# ─── Variáveis de Ambiente com Validação ──────────────────────────────────────
TOKEN_BOT = os.getenv("TOKEN_BOT")
CHAVE_GEMINI = os.getenv("CHAVE_GEMINI")

if not TOKEN_BOT:
    raise EnvironmentError("❌ Variável TOKEN_BOT não definida.")
if not CHAVE_GEMINI:
    raise EnvironmentError("❌ Variável CHAVE_GEMINI não definida.")

genai.configure(api_key=CHAVE_GEMINI)

# ─── Cache de Conversas com Limite de Tamanho (LRU simples) ───────────────────
MAX_USUARIOS = 500  # Máximo de sessões simultâneas em memória
historico_conversas: OrderedDict = OrderedDict()


def obter_chat(user_id: int, nome: str):
    """
    Retorna o chat existente do usuário ou cria um novo.
    Aplica política LRU: remove o mais antigo se atingir o limite.
    """
    if user_id in historico_conversas:
        # Move para o final (mais recente)
        historico_conversas.move_to_end(user_id)
        return historico_conversas[user_id]

    # Remove o mais antigo se necessário
    if len(historico_conversas) >= MAX_USUARIOS:
        removido = next(iter(historico_conversas))
        historico_conversas.pop(removido)
        logger.info(f"Sessão removida por limite LRU: user_id={removido}")

    instrucao = (
        f"Você é Lara, 19 anos, namorada do {nome}. "
        "Fale de forma curta e carinhosa, use gírias brasileiras (vc, pq, tô, kkk, né). "
        "Nunca quebre o personagem."
    )
    modelo = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=instrucao,
    )
    chat = modelo.start_chat(history=[])
    historico_conversas[user_id] = chat
    logger.info(f"Nova sessão criada: user_id={user_id}, nome={nome}")
    return chat


# ─── Handler Principal ────────────────────────────────────────────────────────
async def lidar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Proteção contra updates sem mensagem (edições, canais, etc.)
    if not update.message or not update.message.text:
        return

    # Proteção contra usuário inválido
    if not update.effective_user:
        return

    user_id = update.effective_user.id
    nome = update.effective_user.first_name or "amor"
    texto = update.message.text.strip()

    if not texto:
        return

    logger.info(f"Mensagem recebida | user_id={user_id} | texto={texto[:50]!r}")

    try:
        chat = obter_chat(user_id, nome)
        resposta = chat.send_message(texto)

        if resposta and resposta.text:
            await update.message.reply_text(resposta.text)
        else:
            logger.warning(f"Resposta vazia da API | user_id={user_id}")
            await update.message.reply_text("oi? não entendi direito, manda dnv 🥺")

    except genai.types.BlockedPromptException:
        logger.warning(f"Prompt bloqueado | user_id={user_id}")
        await update.message.reply_text("ei, não posso responder isso 😅")

    except Exception as e:
        logger.error(f"Erro inesperado | user_id={user_id} | erro={e}", exc_info=True)
        await update.message.reply_text("deu um errinho aqui, tenta de novo? 🙈")


# ─── Inicialização do Bot ─────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN_BOT).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lidar))

    logger.info("BOT RODANDO 🚀")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
