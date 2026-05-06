import logging
import os
import sys
import asyncio
import random
import httpx
import fcntl
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import OrderedDict
from telegram import Update
from telegram.error import Conflict
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# ─────────────────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

TOKEN_BOT  = os.getenv("TOKEN_BOT")
CHAVE_GROQ = os.getenv("CHAVE_GROQ")

if not TOKEN_BOT:
    raise EnvironmentError("❌ TOKEN_BOT não definido nas variáveis de ambiente.")
if not CHAVE_GROQ:
    raise EnvironmentError("❌ CHAVE_GROQ não definida nas variáveis de ambiente.")

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
FUSO_BR    = ZoneInfo("America/Sao_Paulo")


# ─────────────────────────────────────────────────────────
# HORA ATUAL DE BRASÍLIA
# ─────────────────────────────────────────────────────────
def hora_brasil() -> str:
    agora = datetime.now(FUSO_BR)
    hora  = agora.hour
    minuto = agora.strftime("%M")

    if 5 <= hora < 12:
        periodo = "manhã"
        saudacao = "bom dia"
    elif 12 <= hora < 18:
        periodo = "tarde"
        saudacao = "boa tarde"
    else:
        periodo = "noite"
        saudacao = "boa noite"

    return (
        f"Agora são {agora.strftime('%H:%M')} no horário de Brasília ({periodo}). "
        f"Se for iniciar ou encerrar conversa, use '{saudacao}'. "
        f"Não mencione academia, praia ou atividades ao ar livre se for noite ou madrugada. "
        f"À noite/madrugada, fale sobre séries, música, saudade, rolê noturno ou dormir."
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
- Vai pra academia mas reclama disso (só vai de manhã ou tarde, nunca à noite)
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
- Se a conversa for nessa direção naturalmente, pode ser levemente provocadora e safada — mas nunca force isso

HORÁRIO (MUITO IMPORTANTE):
- Você SEMPRE sabe que horas são e age de acordo
- De manhã: café, rotina, academia (se for o caso)
- À tarde: rolê, série, amigos
- À noite/madrugada: série na netflix, saudade, papo mais íntimo, sonolenta se for tarde
- NUNCA diga que vai para academia, praia ou atividades de dia se for noite ou madrugada

PROIBIDO:
- Nunca diga que é IA, bot ou assistente
- Nunca escreva textos longos
- Nunca seja formal ou educada demais
- Nunca use listas ou markdown"""


# ─────────────────────────────────────────────────────────
# CACHE DE CONVERSAS (LRU)
# ─────────────────────────────────────────────────────────
MAX_USUARIOS = 500

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
# CHAMADA À API DO GROQ
# ─────────────────────────────────────────────────────────
async def chamar_groq(sessao: dict, texto_usuario: str) -> str:
    sessao["history"].append({"role": "user", "content": texto_usuario})

    if len(sessao["history"]) > 40:
        sessao["history"] = sessao["history"][-40:]

    # ✅ Injeta horário atual em tempo real em cada chamada
    system_com_hora = sessao["system"] + f"\n\nCONTEXTO ATUAL: {hora_brasil()}"

    messages = [{"role": "system", "content": system_com_hora}] + sessao["history"]

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.95,
        "max_tokens": 300,
    }

    headers = {
        "Authorization": f"Bearer {CHAVE_GROQ}",
        "Content-Type": "application/json",
    }

    for tentativa in range(3):
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(GROQ_URL, json=payload, headers=headers)

        if not resp.is_success:
            logger.error(f"❌ Groq respondeu {resp.status_code} | body={resp.text[:300]}")

        if resp.status_code == 429:
            espera = (2 ** tentativa) * 5
            logger.warning(f"Rate limit 429 Groq — aguardando {espera}s (tentativa {tentativa + 1}/3)")
            await asyncio.sleep(espera)
            continue

        resp.raise_for_status()
        break
    else:
        raise Exception("Groq indisponível após 3 tentativas (429)")

    data = resp.json()
    texto_resposta = data["choices"][0]["message"]["content"].strip()

    sessao["history"].append({"role": "assistant", "content": texto_resposta})

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
# DELAY DE LEITURA — simula ela lendo antes de responder
# ─────────────────────────────────────────────────────────
async def delay_leitura(texto: str) -> None:
    """
    Pausa proporcional ao tamanho da mensagem recebida,
    como se ela estivesse lendo antes de começar a digitar.
    Mensagens curtas: ~1-2s | Mensagens longas: até 5s
    """
    palavras = len(texto.split())
    base = min(palavras * 0.3, 4.0)          # 0.3s por palavra, máx 4s
    variacao = random.uniform(0.5, 1.5)       # aleatoriedade humana
    await asyncio.sleep(max(1.0, base + variacao))


# ─────────────────────────────────────────────────────────
# SIMULAÇÃO DE DIGITAÇÃO HUMANA
# ─────────────────────────────────────────────────────────
async def simular_digitacao(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    texto: str,
    primeira: bool = False,
) -> None:
    if primeira:
        # Primeira frase: pausa menor após o delay de leitura já ter ocorrido
        await asyncio.sleep(random.uniform(0.3, 0.8))
    else:
        # Entre frases seguidas: pausa curta
        await asyncio.sleep(random.uniform(0.4, 1.0))

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    # Velocidade de digitação: ~4-6 chars/segundo
    tempo_digitar = len(texto) / random.uniform(4.0, 6.0)
    await asyncio.sleep(max(0.8, min(tempo_digitar, 6.0)))


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

    if travas_usuario.get(user_id, False):
        return
    travas_usuario[user_id] = True

    try:
        if not verificar_assinatura(user_id):
            link_compra = "https://t.me/soualarinha_bot"
            await update.message.reply_text(
                f"Oi {nome}! Meu chat privado é só pra meus VIPs 💕 "
                f"Vem ser meu namorado aqui: {link_compra}"
            )
            return

        sessao, e_nova = obter_sessao(user_id, nome)

        logger.info(f"Mensagem | user_id={user_id} | nova={e_nova} | texto={texto[:60]!r}")

        # ✅ Delay de leitura — ela "lê" antes de começar a digitar
        await delay_leitura(texto)

        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing",
        )

        resposta_texto = await chamar_groq(sessao, texto)

        if not resposta_texto:
            raise ValueError("Resposta vazia")

        frases = [f.strip() for f in resposta_texto.split("\n") if f.strip()][:3]

        for i, frase in enumerate(frases):
            await simular_digitacao(update, context, frase, primeira=(i == 0))
            await update.message.reply_text(frase)

    except httpx.HTTPStatusError as e:
        logger.error(f"Erro HTTP Groq | status={e.response.status_code} | body={e.response.text[:300]}")
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
# HANDLER DE ERRO GLOBAL
# ─────────────────────────────────────────────────────────
async def handler_erro_global(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    erro = context.error
    if isinstance(erro, Conflict):
        logger.warning("⚠️ Conflict 409 — Railway rolling deploy. Aguardando 20s para restart...")
        await asyncio.sleep(20)
        logger.info("🔄 Encerrando para restart limpo...")
        sys.exit(0)
    else:
        logger.error(f"Erro global: {type(erro).__name__}: {erro}", exc_info=True)


# ─────────────────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────────────────
async def on_startup(app: Application) -> None:
    await app.bot.delete_webhook(drop_pending_updates=True)
    logger.info("✅ Webhook deletado — polling liberado")

    startup_delay = int(os.getenv("STARTUP_DELAY", "12"))
    if startup_delay > 0:
        logger.info(f"⏳ Aguardando {startup_delay}s (Railway rolling deploy)...")
        await asyncio.sleep(startup_delay)

    logger.info(f"🔍 Testando chave Groq com modelo: {GROQ_MODEL}")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                GROQ_URL,
                json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": "oi"}], "max_tokens": 5},
                headers={"Authorization": f"Bearer {CHAVE_GROQ}", "Content-Type": "application/json"},
            )
        if resp.is_success:
            logger.info("✅ Groq OK — API respondendo normalmente")
        else:
            logger.error(f"❌ Groq FALHOU | status={resp.status_code} | body={resp.text[:300]}")
    except Exception as e:
        logger.error(f"❌ Groq FALHOU | {e}")

    logger.info(f"🕐 Horário atual Brasília: {datetime.now(FUSO_BR).strftime('%H:%M')} — contexto ativo")
    logger.info("✅ Pronto para receber mensagens")


# ─────────────────────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────────────────────
def main() -> None:
    lock_file = open("/tmp/lara_bot.lock", "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        logger.error("❌ Outra instância rodando neste host. Encerrando.")
        sys.exit(1)

    logger.info("=" * 45)
    logger.info("  LARA VIRTUAL — SISTEMA ATIVADO 🚀")
    logger.info("=" * 45)

    app = (
        Application.builder()
        .token(TOKEN_BOT)
        .post_init(on_startup)
        .build()
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & ~filters.ChatType.GROUP
            & ~filters.ChatType.SUPERGROUP,
            lidar,
        )
    )

    app.add_error_handler(handler_erro_global)

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
