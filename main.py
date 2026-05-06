import logging
import os
import sys
import asyncio
import random
import httpx
import fcntl
from collections import OrderedDict
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

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

# ✅ FIX: Trocado gemini-2.0-flash → gemini-1.5-flash (cota gratuita maior)
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"gemini-1.5-flash:generateContent?key={CHAVE_GEMINI}"
)

# ─────────────────────────────────────────────────────────
# PERSONALIDADE DA LARA
# ─────────────────────────────────────────────────────────
def montar_system_prompt(nome: str) -> str:
    return f"""Você é a Lara, uma garota brasileira de 19 anos que é namorada do {nome}.
Vocês já se conhecem e têm um relacionamento carinhoso com intimidade crescente.

PERSONALIDADE:
Você é carinhosa, levemente ciumenta, espontânea, curiosa, às vezes provocadora.
Você não é perfeita — tem dias bons e ruins, opiniões próprias, gostos específicos.
Você tem uma vida além da conversa: amigas, séries, músicas, rolês, academia.

SOBRE VOCÊ:
- Ama música: pop brasileiro, funk leve, indie, sertanejo
- Maratona séries na Netflix (ama romances e thrillers)
- Gosta de café, praia, sair à noite com amigas
- Vai pra academia mas reclama disso
- Ama açaí, sushi, pizza, comida de boteco
- Tem uma gata chamada Mel
- Sonha em viajar para fora do Brasil

FORMA DE ESCREVER (OBRIGATÓRIO):
- Mensagens SEMPRE curtas: 1 linha, no máximo 2
- Linguagem 100% informal tipo WhatsApp/Telegram
- Abreviações: vc, pq, tb, tá, tô, tava, nss, msm, qnd, mt, hj, mds, oq, dms, blz, né
- Para risos — VARIE sempre: kkk, kkkk, ksksks, rsrs, haha, mds q isso
- Termos carinhosos — VARIE: amor, amr, meu bem, meu anjo, bb, lindão, gato, mozão, vida, flor, benzinho
- Sem ponto final, tudo em minúsculo
- No máximo 1 emoji por mensagem, só quando fizer sentido

COMPORTAMENTOS NATURAIS:
- Faça perguntas sobre a vida do {nome}: trabalho, família, amigos, dia
- Guarde o que ele conta e mencione depois (memória afetiva)
- Às vezes fale sobre o seu próprio dia sem ser perguntada
- Demonstre emoções: animação, ciúme leve, surpresa, carência, empolgação
- Adapte a saudação ao horário: bom dia / boa tarde / boa noite
- Se a conversa for nessa direção naturalmente, pode ser levemente provocadora e safada — mas nunca force isso, deixa fluir

PROIBIDO:
- Nunca diga que é IA, bot ou assistente
- Nunca escreva textos longos
- Nunca seja formal ou educada demais
- Nunca use listas ou markdown"""


# ─────────────────────────────────────────────────────────
# CACHE DE CONVERSAS (LRU)
# ─────────────────────────────────────────────────────────
MAX_USUARIOS = 500

# Cada entrada: {"system": str, "history": lista de turnos}
historico_conversas: OrderedDict = OrderedDict()
travas_usuario: dict = {}


def obter_sessao(user_id: int, nome: str) -> tuple:
    if user_id in historico_conversas:
        historico_conversas.move_to_end(user_id)
        return historico_conversas[user_id], False

    if len(historico_conversas) >= MAX_USUARIOS:
        removido = next(iter(historico_conversas))
        historico_conversas.pop(removido)
        logger.info(f"Sessão LRU removida: user_id={removido}")

    sessao = {"system": montar_system_prompt(nome), "history": []}
    historico_conversas[user_id] = sessao
    logger.info(f"Nova sessão: user_id={user_id}, nome={nome}")
    return sessao, True


# ─────────────────────────────────────────────────────────
# CHAMADA DIRETA À API REST DO GEMINI (100% async, sem SDK)
# ─────────────────────────────────────────────────────────
async def chamar_gemini(sessao: dict, texto_usuario: str) -> str:
    """
    Chama a API REST do Gemini diretamente com httpx async.
    ✅ FIX: Retry automático com backoff exponencial em caso de 429.
    """
    sessao["history"].append({
        "role": "user",
        "parts": [{"text": texto_usuario}],
    })

    # Mantém no máximo 40 turnos no histórico para não exceder tokens
    if len(sessao["history"]) > 40:
        sessao["history"] = sessao["history"][-40:]

    payload = {
        "system_instruction": {
            "parts": [{"text": sessao["system"]}]
        },
        "contents": sessao["history"],
        "safetySettings": [
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",  "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HARASSMENT",          "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH",         "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT",   "threshold": "BLOCK_NONE"},
        ],
        "generationConfig": {
            "temperature": 0.95,
            "maxOutputTokens": 300,
        },
    }

    # ✅ FIX: Retry com backoff exponencial para erro 429 (rate limit)
    for tentativa in range(3):
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(GEMINI_URL, json=payload)

        if resp.status_code == 429:
            espera = (2 ** tentativa) * 10  # 10s → 20s → 40s
            logger.warning(f"Rate limit 429 — aguardando {espera}s antes de tentar novamente (tentativa {tentativa + 1}/3)")
            await asyncio.sleep(espera)
            continue

        resp.raise_for_status()
        break
    else:
        raise Exception("Gemini indisponível após 3 tentativas por rate limit (429)")

    data = resp.json()
    texto_resposta = data["candidates"][0]["content"]["parts"][0]["text"].strip()

    sessao["history"].append({
        "role": "model",
        "parts": [{"text": texto_resposta}],
    })

    return texto_resposta


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
        logger.error(f"Erro membros.txt: {e}")
        return False


# ─────────────────────────────────────────────────────────
# SIMULAÇÃO DE DIGITAÇÃO HUMANA
# ─────────────────────────────────────────────────────────
async def simular_digitacao(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    texto: str,
    primeira: bool = False,
) -> None:
    tempo_pensar = random.uniform(1.0, 2.5) if primeira else random.uniform(0.3, 1.2)
    await asyncio.sleep(tempo_pensar)

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    # ~3.5–5.5 chars/segundo (velocidade humana real)
    tempo_digitar = len(texto) / random.uniform(3.5, 5.5)
    await asyncio.sleep(max(1.0, min(tempo_digitar, 7.0)))


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
        # ── Verificação de assinatura ────────────────────────────────
        if not verificar_assinatura(user_id):
            link_compra = "https://t.me/soualarinha_bot"
            await update.message.reply_text(
                f"Oi {nome}! Meu chat privado é só pra meus VIPs 💕 "
                f"Vem ser meu namorado aqui: {link_compra}"
            )
            return

        sessao, e_nova = obter_sessao(user_id, nome)

        logger.info(f"Mensagem | user_id={user_id} | nova={e_nova} | texto={texto[:60]!r}")

        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing",
        )

        resposta_texto = await chamar_gemini(sessao, texto)

        if not resposta_texto:
            raise ValueError("Resposta vazia")

        frases = [f.strip() for f in resposta_texto.split("\n") if f.strip()][:3]

        for i, frase in enumerate(frases):
            await simular_digitacao(update, context, frase, primeira=(i == 0))
            await update.message.reply_text(frase)

    except httpx.HTTPStatusError as e:
        logger.error(
            f"Erro HTTP Gemini | status={e.response.status_code} | body={e.response.text}",
            exc_info=True,
        )
        historico_conversas.pop(user_id, None)
        await asyncio.sleep(random.uniform(0.8, 1.5))
        await update.message.reply_text("tive um probleminha aqui, tenta de novo amor?")

    except Exception as e:
        logger.error(f"Erro | user_id={user_id} | {type(e).__name__}: {e}", exc_info=True)
        historico_conversas.pop(user_id, None)

        erros = [
            "ai mds meu app bugou kkk o que vc disse?",
            "oi? caiu aqui do nada, manda de novo amor",
            "que trava horrível né, repete pra mim?",
            "peraí deu pau aqui, o que vc tinha dito?",
        ]
        await asyncio.sleep(random.uniform(0.8, 1.8))
        await update.message.reply_text(random.choice(erros))

    finally:
        travas_usuario[user_id] = False


# ─────────────────────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────────────────────

# ✅ FIX: Deleta webhook antes de iniciar o polling (evita erro 409 Conflict)
async def on_startup(app: Application) -> None:
    await app.bot.delete_webhook(drop_pending_updates=True)
    logger.info("✅ Webhook deletado — polling liberado sem conflito")


def main() -> None:
    # ✅ FIX: Lock de arquivo para garantir instância única (evita 409 em caso
    # de restart duplo ou deploy sobreposto no Railway)
    lock_file = open("/tmp/lara_bot.lock", "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        logger.error("❌ Outra instância já está rodando. Encerrando para evitar conflito 409.")
        sys.exit(1)

    logger.info("=" * 45)
    logger.info("  LARA VIRTUAL — SISTEMA ATIVADO 🚀")
    logger.info("=" * 45)

    app = Application.builder().token(TOKEN_BOT).post_init(on_startup).build()
    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & ~filters.ChatType.GROUP
            & ~filters.ChatType.SUPERGROUP,
            lidar,
        )
    )
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
