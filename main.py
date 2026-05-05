import logging
import os
import asyncio
import random
import time
from collections import OrderedDict
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import google.generativeai as genai

from brain import SYSTEM_PROMPT_BASE, RESPOSTAS_ERRO, FRASES_DIGITANDO

# ─────────────────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

TOKEN_BOT    = os.getenv("TOKEN_BOT")
CHAVE_GEMINI = os.getenv("CHAVE_GEMINI")

if not TOKEN_BOT:
    raise EnvironmentError("❌ TOKEN_BOT não definido nas variáveis de ambiente.")
if not CHAVE_GEMINI:
    raise EnvironmentError("❌ CHAVE_GEMINI não definida nas variáveis de ambiente.")

genai.configure(api_key=CHAVE_GEMINI)

# ─────────────────────────────────────────────────────────
# CACHE DE SESSÕES (LRU)
# ─────────────────────────────────────────────────────────
MAX_USUARIOS = 500
historico_conversas: OrderedDict = OrderedDict()
travas_usuario: dict              = {}  # evita processamento simultâneo


# ─────────────────────────────────────────────────────────
# VERIFICAÇÃO DE ASSINATURA
# ─────────────────────────────────────────────────────────
def verificar_assinatura(user_id: int) -> bool:
    try:
        if not os.path.exists("membros.txt"):
            return False
        with open("membros.txt", "r") as f:
            return str(user_id) in f.read().splitlines()
    except Exception as e:
        logger.error(f"Erro ao verificar membros.txt: {e}")
        return False


# ─────────────────────────────────────────────────────────
# CRIAÇÃO DE SESSÃO GEMINI (síncrono — roda em thread)
# ─────────────────────────────────────────────────────────
def _criar_chat_sync(nome: str):
    instrucao = SYSTEM_PROMPT_BASE.replace("{NOME}", nome)

    modelo = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=instrucao,
        safety_settings=[
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",  "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HARASSMENT",          "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH",         "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT",   "threshold": "BLOCK_NONE"},
        ],
    )
    return modelo.start_chat(history=[])


async def obter_chat(user_id: int, nome: str):
    if user_id in historico_conversas:
        historico_conversas.move_to_end(user_id)
        return historico_conversas[user_id], False  # (chat, é_novo)

    if len(historico_conversas) >= MAX_USUARIOS:
        removido = next(iter(historico_conversas))
        historico_conversas.pop(removido)
        logger.info(f"Sessão removida por LRU: user_id={removido}")

    chat = await asyncio.to_thread(_criar_chat_sync, nome)
    historico_conversas[user_id] = chat
    logger.info(f"Nova sessão: user_id={user_id}, nome={nome}")
    return chat, True  # (chat, é_novo)


# ─────────────────────────────────────────────────────────
# GEMINI — CHAMADA SÍNCRONA (roda em thread separada)
# ─────────────────────────────────────────────────────────
def _enviar_mensagem_sync(chat, texto: str) -> str:
    """
    ✅ FIX PRINCIPAL: send_message() é síncrono.
    Nunca chame diretamente em função async — bloqueia o event loop.
    Sempre use via asyncio.to_thread().
    """
    response = chat.send_message(texto)
    return response.text.strip() if response and response.text else ""


# ─────────────────────────────────────────────────────────
# SIMULAÇÃO DE DIGITAÇÃO HUMANA
# ─────────────────────────────────────────────────────────
async def simular_digitacao(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    texto: str,
    e_primeira: bool = False,
) -> None:
    """
    Simula o tempo real de digitação baseado no tamanho da mensagem.
    Velocidade humana: ~35–55 palavras/min ≈ 3.5–5.5 chars/segundo.
    """
    # Tempo de "pensar" antes de começar a digitar
    tempo_pensar = random.uniform(1.2, 3.0) if e_primeira else random.uniform(0.4, 1.5)
    await asyncio.sleep(tempo_pensar)

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    # Tempo de digitação proporcional ao tamanho
    chars_por_segundo = random.uniform(3.5, 5.5)
    tempo_digitar = len(texto) / chars_por_segundo
    tempo_digitar = max(1.2, min(tempo_digitar, 7.0))
    await asyncio.sleep(tempo_digitar)


# ─────────────────────────────────────────────────────────
# HANDLER PRINCIPAL
# ─────────────────────────────────────────────────────────
async def lidar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    if not update.effective_user or update.effective_user.is_bot:
        return

    user_id = update.effective_user.id
    nome    = update.effective_user.first_name or "amor"
    texto   = update.message.text.strip()

    if not texto:
        return

    # Trava: evita processamento paralelo para o mesmo usuário
    if travas_usuario.get(user_id, False):
        return
    travas_usuario[user_id] = True

    try:
        # ── Verificação de assinatura ────────────────────────────────────────
        if not verificar_assinatura(user_id):
            link_compra = "https://t.me/soualarinha_bot"
            await update.message.reply_text(
                f"Oi {nome}! Adorei o contato, mas meu chat privado é exclusivo pra meus VIPs 💕 "
                f"Vem ser meu namorado aqui: {link_compra}"
            )
            return

        # ── Obter ou criar sessão ────────────────────────────────────────────
        chat, e_novo = await obter_chat(user_id, nome)

        logger.info(f"Mensagem | user_id={user_id} | novo={e_novo} | texto={texto[:60]!r}")

        # Mostra "digitando..." enquanto processa
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing",
        )

        # ── ✅ Chamada correta: síncrona em thread separada ──────────────────
        resposta_texto = await asyncio.to_thread(
            _enviar_mensagem_sync,
            chat,
            texto,
        )

        if not resposta_texto:
            raise ValueError("Resposta vazia do Gemini")

        # Divide em balões (linhas = mensagens separadas, máx 3)
        frases = [f.strip() for f in resposta_texto.split("\n") if f.strip()][:3]

        for i, frase in enumerate(frases):
            await simular_digitacao(update, context, frase, e_primeira=(i == 0 and e_novo))
            await update.message.reply_text(frase)

    except genai.types.BlockedPromptException:
        logger.warning(f"Prompt bloqueado | user_id={user_id}")
        await asyncio.sleep(random.uniform(0.8, 1.5))
        await update.message.reply_text("ei, sobre isso prefiro não falar não 😅")

    except Exception as e:
        logger.error(f"Erro | user_id={user_id} | {e}", exc_info=True)

        # Remove sessão corrompida para recriar na próxima mensagem
        historico_conversas.pop(user_id, None)

        await asyncio.sleep(random.uniform(0.8, 1.8))
        await update.message.reply_text(random.choice(RESPOSTAS_ERRO))

    finally:
        travas_usuario[user_id] = False


# ─────────────────────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────────────────────
def main() -> None:
    logger.info("=" * 45)
    logger.info("  LARA VIRTUAL — SISTEMA ATIVADO 🚀")
    logger.info("=" * 45)

    app = Application.builder().token(TOKEN_BOT).build()

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & ~filters.ChatType.GROUP & ~filters.ChatType.SUPERGROUP,
            lidar,
        )
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
