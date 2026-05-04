import logging
import os
import asyncio
import random
import aiosqlite
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
import google.generativeai as genai

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Variáveis de Ambiente ────────────────────────────────────────────────────
TOKEN_BOT = os.getenv("TOKEN_BOT")
CHAVE_GEMINI = os.getenv("CHAVE_GEMINI")

if not TOKEN_BOT or not CHAVE_GEMINI:
    raise EnvironmentError("❌ Verifique TOKEN_BOT e CHAVE_GEMINI.")

genai.configure(api_key=CHAVE_GEMINI)

# ─── Banco de Dados ───────────────────────────────────────────────────────────
DB_PATH = "conversas.db"

async def iniciar_banco():
    """Cria as tabelas se não existirem."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS historico (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                role        TEXT NOT NULL,   -- 'user' ou 'model'
                conteudo    TEXT NOT NULL,
                criado_em   DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                user_id     INTEGER PRIMARY KEY,
                nome        TEXT NOT NULL,
                criado_em   DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Índice para buscas por user_id serem rápidas
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_historico_user
            ON historico(user_id, criado_em)
        """)
        await db.commit()

async def salvar_mensagem(user_id: int, role: str, conteudo: str):
    """Salva uma mensagem no banco."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO historico (user_id, role, conteudo) VALUES (?, ?, ?)",
            (user_id, role, conteudo)
        )
        await db.commit()

async def carregar_historico(user_id: int, limite: int = 20):
    """
    Retorna as últimas N mensagens formatadas para o Gemini.
    Limite evita context window gigante e mantém custo baixo.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT role, conteudo FROM (
                SELECT role, conteudo, criado_em
                FROM historico
                WHERE user_id = ?
                ORDER BY criado_em DESC
                LIMIT ?
            ) ORDER BY criado_em ASC
            """,
            (user_id, limite)
        ) as cursor:
            rows = await cursor.fetchall()

    # Formato esperado pelo Gemini: lista de dicts
    return [{"role": role, "parts": [conteudo]} for role, conteudo in rows]

async def salvar_usuario(user_id: int, nome: str):
    """Registra o usuário se ainda não existir."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO usuarios (user_id, nome) VALUES (?, ?)",
            (user_id, nome)
        )
        await db.commit()

async def limpar_historico(user_id: int):
    """Apaga todo o histórico de um usuário (usado no /reset)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM historico WHERE user_id = ?", (user_id,))
        await db.commit()

# ─── Delay Natural ────────────────────────────────────────────────────────────
async def digitar_com_delay(context, chat_id: int, texto: str):
    """
    Simula digitação humana:
    - Calcula tempo baseado no número de caracteres
    - Adiciona variação aleatória para não parecer robótico
    - Envia 'typing...' enquanto espera
    - Quebra textos longos em múltiplas mensagens com pausas
    """
    # Velocidade base: ~60 chars/seg (humano digitando rápido no celular)
    # Variação: ±30% para naturalidade
    CHARS_POR_SEGUNDO = random.uniform(45, 75)
    DELAY_MINIMO = 0.8   # segundos — nunca responde instantâneo
    DELAY_MAXIMO = 6.0   # segundos — nunca demora demais

    # Quebra em parágrafos para simular mensagens separadas (mais natural)
    partes = [p.strip() for p in texto.split("\n\n") if p.strip()]
    if not partes:
        partes = [texto]

    for parte in partes:
        delay = len(parte) / CHARS_POR_SEGUNDO
        delay = max(DELAY_MINIMO, min(delay, DELAY_MAXIMO))

        # Envia "digitando..." enquanto o delay acontece
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        # Para textos mais longos, renova o "digitando..." a cada 4s
        tempo_restante = delay
        while tempo_restante > 0:
            await asyncio.sleep(min(tempo_restante, 4.0))
            tempo_restante -= 4.0
            if tempo_restante > 0:
                await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        await context.bot.send_message(chat_id=chat_id, text=parte)

        # Pausa pequena entre mensagens separadas
        if len(partes) > 1:
            await asyncio.sleep(random.uniform(0.5, 1.2))

# ─── Construção do Modelo ─────────────────────────────────────────────────────
def criar_modelo(nome: str) -> genai.GenerativeModel:
    instrucao = (
        f"Você é a Lara, 19 anos. Está conversando com {nome}, seu namorado. "
        "Seja carinhosa, divertida e espontânea como uma namorada real no WhatsApp. "
        "Respostas curtas e naturais. Use gírias brasileiras (vc, pq, tô, né, kkk, ai). "
        "Demonstre interesse genuíno pela vida dele, faça perguntas, lembre de coisas que ele contou. "
        "Varie entre carinhosa, animada, curiosa e levemente ciumentinha. "
        "Mande às vezes uma mensagem só com emoji. "
        "Nunca responda de forma robótica ou formal."
    )
    return genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=instrucao,
    )

# ─── Handler: Mensagem Normal ─────────────────────────────────────────────────
async def lidar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or not update.effective_user:
        return

    user_id = update.effective_user.id
    nome    = update.effective_user.first_name or "amor"
    texto   = update.message.text.strip()

    if not texto:
        return

    await salvar_usuario(user_id, nome)

    try:
        # Carrega histórico do banco e inicializa chat com contexto
        historico = await carregar_historico(user_id)
        modelo    = criar_modelo(nome)
        chat      = modelo.start_chat(history=historico)

        # Salva mensagem do usuário ANTES de enviar (garante ordem)
        await salvar_mensagem(user_id, "user", texto)

        # Chama a API de forma async
        resposta = await chat.send_message_async(texto)

        if resposta and resposta.text:
            resposta_texto = resposta.text

            # Salva resposta da Lara no banco
            await salvar_mensagem(user_id, "model", resposta_texto)

            # Envia com delay natural simulando digitação
            await digitar_com_delay(context, user_id, resposta_texto)
        else:
            await update.message.reply_text("oi? não entendi, fala de novo 🥺")

    except Exception as e:
        logger.error(f"Erro | user_id={user_id} | {e}", exc_info=True)
        await update.message.reply_text("tô meio sem sinal aqui 😅 manda de novo?")

# ─── Handler: /start ──────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = update.effective_user.first_name or "amor"
    await digitar_com_delay(
        context,
        update.effective_user.id,
        f"oi {nome}!! 🥰 finalmente vc apareceu\no que foi que vc tava fazendo hein"
    )

# ─── Handler: /reset ──────────────────────────────────────────────────────────
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await limpar_historico(user_id)
    await update.message.reply_text("okay, começando do zero 🫶")

# ─── Inicialização ────────────────────────────────────────────────────────────
async def post_init(application: Application):
    """Executado logo após o bot iniciar — garante que o banco existe."""
    await iniciar_banco()
    logger.info("Banco de dados inicializado ✅")

def main():
    app = (
        Application.builder()
        .token(TOKEN_BOT)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lidar))

    logger.info("LARA ONLINE 🚀")
    app.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()
