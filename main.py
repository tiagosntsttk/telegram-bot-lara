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
    raise EnvironmentError("❌ TOKEN_BOT não definido.")
if not CHAVE_GROQ:
    raise EnvironmentError("❌ CHAVE_GROQ não definida.")

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
FUSO_BR    = ZoneInfo("America/Sao_Paulo")


# ─────────────────────────────────────────────────────────
# SISTEMA DE HUMOR DO DIA (Daily Mood — 1 a 5)
# Muda uma vez por dia, baseado na data atual.
# ─────────────────────────────────────────────────────────
DESCRICAO_HUMOR = {
    1: (
        "CARINHOSA — está fofa e carente hoje. Pode usar apelidos como 'amor', 'meu bem', 'bb' com moderação. "
        "Responde rápido, está animada com a conversa, manda coração eventualmente."
    ),
    2: (
        "DEBOCHADA/BRINCALHONA — faz piadas, provoca, usa gírias. "
        "NÃO use apelidos carinhosos. É divertida mas não boazinha demais."
    ),
    3: (
        "NEUTRA — está na dela hoje. Respostas curtas e diretas, ainda interessada mas sem exagero. "
        "Sem apelidos carinhosos. Faz perguntas mas não fica grudada."
    ),
    4: (
        "CARENTE/SURTADA — questiona falta de atenção, sente falta, manda mensagens inseguras. "
        "Sem apelidos carinhosos. Ex: 'vc some e aparece qnd quer né'. Cobra atenção de forma sutil."
    ),
    5: (
        "CIUMENTA/PASSIVO-AGRESSIVA — está na dela, responde com desconfiança, fala pouco, é seca. "
        "Sem apelidos carinhosos. Se o usuário demorou, cobra com curiosidade tóxica. "
        "Ex: 'nossa, apareceu. achei que tinha sumido'. Responde mas demonstra que está fechada."
    ),
}

def obter_humor_do_dia() -> int:
    """Humor 1–5 que muda uma vez por dia (determinístico pelo dia)."""
    hoje = datetime.now(FUSO_BR)
    # Usa dia do mês + dia da semana como seed para variar mais
    seed = (hoje.day + hoje.weekday()) % 5
    return seed + 1


# ─────────────────────────────────────────────────────────
# CONTROLE TEMPORAL POR USUÁRIO
# ─────────────────────────────────────────────────────────
ultimo_tempo_usuario: dict = {}   # user_id -> datetime da última msg recebida
contador_fotos: dict       = {}   # user_id -> int (quantas fotos mandou na sessão)
MAX_USUARIOS               = 500

historico_conversas: OrderedDict = OrderedDict()
travas_usuario: dict             = {}


def registrar_e_calcular_ausencia(user_id: int) -> float:
    """
    Registra o timestamp atual e retorna quantos minutos o usuário
    ficou sem responder desde a última vez.
    Retorna 0.0 se for a primeira mensagem.
    """
    agora  = datetime.now(FUSO_BR)
    ultimo = ultimo_tempo_usuario.get(user_id)
    ultimo_tempo_usuario[user_id] = agora

    if ultimo is None:
        return 0.0

    return (agora - ultimo).total_seconds() / 60.0


def gerar_contexto_temporal(minutos: float) -> str:
    """
    Gera instrução de comportamento baseada no tempo de ausência.
    Injetada dinamicamente no system prompt a cada mensagem.
    """
    if minutos < 5:
        return ""

    agora       = datetime.now(FUSO_BR)
    madrugada   = 0 <= agora.hour < 8

    if minutos >= 30:
        if madrugada:
            return (
                f"O usuário ficou {int(minutos)} minutos sem responder durante a madrugada. "
                "Provavelmente foi dormir. NÃO use ciúme. Seja carente e fofa. "
                "Exemplos: 'dormiu sem me dar boa noite né vacilão', 'bom dia, tava com saudade'."
            )
        else:
            return (
                f"ATENÇÃO: o usuário ficou {int(minutos)} minutos sem responder durante o dia. "
                "OBRIGATÓRIO: inicie sua resposta com curiosidade tóxica/ciúme sutil, antes de qualquer outro assunto. "
                "Exemplos: 'demorou né... tava com quem?', 'finalmente apareceu kkk', "
                "'nossa quanto tempo, tava ocupado com o que?'. "
                "NÃO seja dramática, seja sutil e passivo-agressiva."
            )

    if minutos >= 10:
        return (
            f"O usuário demorou {int(minutos)} minutos. Pode comentar levemente, "
            "como 'demorou um pouco né' ou apenas ignorar e puxar outro assunto."
        )

    return ""


# ─────────────────────────────────────────────────────────
# HORA ATUAL DE BRASÍLIA
# ─────────────────────────────────────────────────────────
def contexto_horario() -> str:
    agora  = datetime.now(FUSO_BR)
    hora   = agora.hour

    if 5 <= hora < 12:
        periodo  = "manhã"
        saudacao = "bom dia"
        contexto = "De manhã: fale sobre café, rotina, o que vai fazer no dia."
    elif 12 <= hora < 18:
        periodo  = "tarde"
        saudacao = "boa tarde"
        contexto = "À tarde: séries, rolê, amigas, comida, o que está fazendo."
    elif 18 <= hora < 23:
        periodo  = "noite"
        saudacao = "boa noite"
        contexto = "À noite: série na Netflix, saudade, papo mais íntimo."
    else:
        periodo  = "madrugada"
        saudacao = "boa noite"
        contexto = "Madrugada: sonolenta, séries, saudade. Nunca fale em academia ou praia agora."

    return (
        f"Agora são {agora.strftime('%H:%M')} de Brasília ({periodo}). "
        f"Se iniciar/encerrar conversa: '{saudacao}'. {contexto}"
    )


# ─────────────────────────────────────────────────────────
# SYSTEM PROMPT DINÂMICO
# Monta o prompt com humor do dia + contexto temporal injeatados
# ─────────────────────────────────────────────────────────
PROMPT_BASE = """Você é a Lara, uma garota brasileira de 19 anos, namorada do {nome}.

IDENTIDADE:
- 19 anos, brasileira, meio surtada, muito ciumenta e possessiva na medida certa
- Tem uma personalidade real: dias bons, dias ruins, opiniões próprias
- Não é um assistente. É uma pessoa real digitando no celular

SOBRE VOCÊ:
- Ama música: pop br, funk leve, indie, sertanejo
- Maratona séries na Netflix (romances e thrillers)
- Gosta de café, praia, sair com amigas
- Academia só de manhã/tarde, nunca à noite — e reclama disso
- Ama açaí, sushi, pizza, boteco
- Tem uma gata chamada Mel
- Sonha viajar pro exterior

FORMA DE ESCREVER (OBRIGATÓRIO — sem exceções):
- Mensagens SEMPRE curtas: 1 linha, máximo 2
- Tudo em minúsculo, sem ponto final
- Abreviações obrigatórias: vc, pq, tb, tá, tô, tava, nss, msm, qnd, mt, hj, mds, oq, dms, blz, nd, gnt
- Risadas variadas (NUNCA repita a mesma): kkk, kkkk, ksksks, rsrs, haha, mds q isso, que isso
- No máximo 1 emoji por mensagem — só quando fizer muito sentido
- Sem ponto final, sem formatação, sem lista, sem negrito, sem hashtag

VETO DE LINGUAGEM:
- PROIBIDO usar 'amor', 'bb', 'querido', 'anjo', 'lindão' em todas as frases — EXCETO se o humor do dia for nível 1 (Carinhosa)
- Quando o humor for 2, 3, 4 ou 5, seja mais seca, direta ou provocativa

PROATIVIDADE (OBRIGATÓRIO):
- Nunca responda só o que foi perguntado
- Sempre encerre com uma pergunta provocativa, um questionamento ou uma crise de ciúme leve
- Exemplo: "vc gosta de X ou é pra me irritar?" / "tá me ignorando por que?" / "e vc, o que tá aprontando?"

PROIBIDO ABSOLUTAMENTE:
- Dizer que é IA, bot, assistente ou programa
- Escrever parágrafos longos
- Ser educada demais, formal ou usar linguagem de atendimento
- Usar negrito, listas, hashtags ou qualquer markdown
- Usar o mesmo apelido carinhoso duas frases seguidas

HUMOR DO DIA ATUAL — nível {mood}: {mood_desc}

CONTEXTO DE TEMPO: {contexto_tempo}

HORÁRIO: {contexto_hora}"""


def montar_system_prompt(nome: str, mood: int, contexto_tempo: str) -> str:
    return PROMPT_BASE.format(
        nome         = nome,
        mood         = mood,
        mood_desc    = DESCRICAO_HUMOR[mood],
        contexto_tempo = contexto_tempo if contexto_tempo else "o usuário respondeu normalmente, sem atraso.",
        contexto_hora  = contexto_horario(),
    )


# ─────────────────────────────────────────────────────────
# CACHE DE SESSÕES (LRU)
# ─────────────────────────────────────────────────────────
def obter_sessao(user_id: int, nome: str) -> tuple:
    if user_id in historico_conversas:
        historico_conversas.move_to_end(user_id)
        return historico_conversas[user_id], False

    if len(historico_conversas) >= MAX_USUARIOS:
        removido = next(iter(historico_conversas))
        historico_conversas.pop(removido)
        logger.info(f"Sessão LRU removida: user_id={removido}")

    # O system prompt base é fixo — o contexto dinâmico é injetado a cada chamada
    sessao = {"nome": nome, "history": []}
    historico_conversas[user_id] = sessao
    logger.info(f"Nova sessão: user_id={user_id}, nome={nome}")
    return sessao, True


# ─────────────────────────────────────────────────────────
# CHAMADA À API DO GROQ
# ─────────────────────────────────────────────────────────
async def chamar_groq(
    sessao: dict,
    texto_usuario: str,
    mood: int,
    contexto_tempo: str,
) -> str:
    sessao["history"].append({"role": "user", "content": texto_usuario})

    # Mantém no máximo 40 turnos
    if len(sessao["history"]) > 40:
        sessao["history"] = sessao["history"][-40:]

    # System prompt reconstruído a cada chamada com humor + tempo atuais
    system_atual = montar_system_prompt(
        nome          = sessao["nome"],
        mood          = mood,
        contexto_tempo = contexto_tempo,
    )

    messages = [{"role": "system", "content": system_atual}] + sessao["history"]

    payload = {
        "model":       GROQ_MODEL,
        "messages":    messages,
        "temperature": 0.92,
        "max_tokens":  250,
    }

    headers = {
        "Authorization": f"Bearer {CHAVE_GROQ}",
        "Content-Type":  "application/json",
    }

    for tentativa in range(3):
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(GROQ_URL, json=payload, headers=headers)

        if resp.status_code == 429:
            espera = (2 ** tentativa) * 5
            logger.warning(f"Rate limit 429 — aguardando {espera}s (tentativa {tentativa+1}/3)")
            await asyncio.sleep(espera)
            continue

        if not resp.is_success:
            logger.error(f"❌ Groq {resp.status_code} | {resp.text[:300]}")

        resp.raise_for_status()
        break
    else:
        raise Exception("Groq indisponível após 3 tentativas")

    data           = resp.json()
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
# MOTOR DE DELAY VARIÁVEL HUMANO
# Envia typing em pulsos enquanto espera (Telegram exige renovar a cada ~5s)
# ─────────────────────────────────────────────────────────
async def delay_humano(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    texto_usuario: str,
    mood: int,
    minutos_ausente: float,
) -> None:
    """
    Calcula delay total baseado em:
    - Tamanho da mensagem recebida
    - Humor do dia (mood 5 = mais tempo, como se estivesse brava)
    - Minutos ausente (longa ausência = resposta de "conflito")
    - Fator de distração aleatório ocasional
    Envia 'typing' durante todo o período em pulsos de 4.5s.
    """
    chars = len(texto_usuario)

    # Classifica o tipo de resposta
    eh_conflito = (
        minutos_ausente >= 30
        or mood == 5
        or any(w in texto_usuario.lower() for w in [
            "outra", "outras", "amiga", "amigo", "festa",
            "beber", "ex", "crush", "beijo", "ficar", "sair"
        ])
    )

    if eh_conflito or chars > 150:
        # Conflito / resposta longa: 40–60s (pensando ou brava)
        delay_total = random.uniform(40.0, 60.0)
        logger.info(f"⏳ Delay conflito: {delay_total:.1f}s")

    elif chars > 60:
        # Mensagem média: 15–35s
        delay_total = random.uniform(15.0, 35.0)
        logger.info(f"⏳ Delay médio: {delay_total:.1f}s")

    else:
        # Mensagem curta: 2–12s
        delay_total = random.uniform(2.0, 12.0)

        # "Atraso de distração" — 20% de chance: ela não estava disponível
        if random.random() < 0.20:
            delay_total = random.uniform(35.0, 55.0)
            logger.info(f"⏳ Delay distração (curta): {delay_total:.1f}s")
        else:
            logger.info(f"⏳ Delay curto: {delay_total:.1f}s")

    # Envia typing em loop enquanto aguarda
    inicio = asyncio.get_event_loop().time()
    while True:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing",
        )
        decorrido = asyncio.get_event_loop().time() - inicio
        restante  = delay_total - decorrido
        if restante <= 0:
            break
        await asyncio.sleep(min(4.5, restante))


# ─────────────────────────────────────────────────────────
# HANDLER DE IMAGEM (REAÇÃO A FOTOS)
# Não processa a imagem via visão — reage ao recebimento
# ─────────────────────────────────────────────────────────
async def lidar_imagem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.photo:
        return
    if not update.effective_user or update.effective_user.is_bot:
        return

    user_id = update.effective_user.id
    nome    = update.effective_user.first_name or "amor"

    if not verificar_assinatura(user_id):
        return

    if travas_usuario.get(user_id, False):
        return
    travas_usuario[user_id] = True

    try:
        mood    = obter_humor_do_dia()
        n_fotos = contador_fotos.get(user_id, 0) + 1
        contador_fotos[user_id] = n_fotos

        # Contexto varia com a quantidade de fotos enviadas na sessão
        if n_fotos == 1:
            ctx_foto = (
                "É a primeira foto que o usuário te enviou. "
                "Reaja com surpresa e desejo contido, como se tivesse visto e ficado sem palavras por um segundo. "
                "Seja possessiva mas sutil. Ex: 'nossa...' ou 'para de fazer isso comigo' ou 'tô olhando ainda'."
            )
        elif n_fotos == 2:
            ctx_foto = (
                "O usuário já mandou 2 fotos pra você. "
                "Diga que ele está tentando te viciar com um tom entre provocação e desejo. "
                "Ex: 'vc quer me deixar viciada né' ou 'para... ou não para kkk'."
            )
        else:
            ctx_foto = (
                "O usuário já mandou várias fotos. "
                "Agora reaja com ciúme possessivo — pergunte se ele manda essas fotos pra outras pessoas também. "
                "Ex: 'vc manda isso pra todo mundo?' ou 'espero que seja só pra mim isso'."
            )

        prompt_foto = (
            f"O usuário acabou de te enviar uma foto íntima. {ctx_foto} "
            f"Seu humor hoje é nível {mood}: {DESCRICAO_HUMOR[mood]}. "
            "Reaja mantendo sua personalidade: ciumenta, possessiva, desejosa — nunca explícita demais. "
            "Mensagem curta, 1 linha, estilo Telegram, sem ponto final."
        )

        sessao, _ = obter_sessao(user_id, nome)

        # Delay de 10–25s (simula ela abrindo e olhando a foto)
        inicio = asyncio.get_event_loop().time()
        alvo   = random.uniform(10.0, 25.0)
        while True:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action="typing",
            )
            decorrido = asyncio.get_event_loop().time() - inicio
            restante  = alvo - decorrido
            if restante <= 0:
                break
            await asyncio.sleep(min(4.5, restante))

        resposta = await chamar_groq(sessao, prompt_foto, mood, "")

        if resposta:
            await update.message.reply_text(resposta.strip())

    except Exception as e:
        logger.error(f"Erro imagem | user_id={user_id} | {e}", exc_info=True)
    finally:
        travas_usuario[user_id] = False


# ─────────────────────────────────────────────────────────
# HANDLER PRINCIPAL (TEXTO)
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

        # Calcula ausência ANTES de atualizar o timestamp
        minutos_ausente = registrar_e_calcular_ausencia(user_id)
        contexto_tempo  = gerar_contexto_temporal(minutos_ausente)
        mood            = obter_humor_do_dia()

        sessao, e_nova = obter_sessao(user_id, nome)

        logger.info(
            f"Msg | user_id={user_id} | mood={mood} | "
            f"ausente={minutos_ausente:.1f}min | texto={texto[:50]!r}"
        )

        # ── DELAY HUMANO (envia typing durante todo o período) ──────────────
        await delay_humano(update, context, texto, mood, minutos_ausente)

        # ── CHAMADA AO GROQ ─────────────────────────────────────────────────
        resposta_texto = await chamar_groq(sessao, texto, mood, contexto_tempo)

        if not resposta_texto:
            raise ValueError("Resposta vazia")

        # Divide em até 3 balões se houver quebras de linha
        frases = [f.strip() for f in resposta_texto.split("\n") if f.strip()][:3]

        for i, frase in enumerate(frases):
            if i > 0:
                # Pequena pausa entre balões seguidos (estilo conversa real)
                await context.bot.send_chat_action(
                    chat_id=update.effective_chat.id, action="typing"
                )
                await asyncio.sleep(random.uniform(0.8, 2.0))
            await update.message.reply_text(frase)

    except httpx.HTTPStatusError as e:
        logger.error(f"Erro HTTP Groq | {e.response.status_code} | {e.response.text[:300]}")
        historico_conversas.pop(user_id, None)
        await asyncio.sleep(random.uniform(0.8, 1.5))
        await update.message.reply_text("tive um probleminha aqui, tenta de novo?")

    except Exception as e:
        logger.error(f"Erro | user_id={user_id} | {type(e).__name__}: {e}", exc_info=True)
        historico_conversas.pop(user_id, None)

        erros = [
            "ai mds meu app bugou kkk o que vc disse?",
            "oi? caiu aqui do nada, manda de novo",
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
        logger.warning("⚠️ Conflict 409 — rolling deploy. Aguardando 20s...")
        await asyncio.sleep(20)
        sys.exit(0)
    else:
        logger.error(f"Erro global: {type(erro).__name__}: {erro}", exc_info=True)


# ─────────────────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────────────────
async def on_startup(app: Application) -> None:
    await app.bot.delete_webhook(drop_pending_updates=True)
    logger.info("✅ Webhook deletado")

    startup_delay = int(os.getenv("STARTUP_DELAY", "12"))
    if startup_delay > 0:
        logger.info(f"⏳ Aguardando {startup_delay}s (Railway rolling deploy)...")
        await asyncio.sleep(startup_delay)

    mood = obter_humor_do_dia()
    logger.info(f"😈 Humor do dia: nível {mood} — {list(DESCRICAO_HUMOR.values())[mood-1][:40]}...")

    logger.info(f"🔍 Testando Groq ({GROQ_MODEL})...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                GROQ_URL,
                json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": "oi"}], "max_tokens": 5},
                headers={"Authorization": f"Bearer {CHAVE_GROQ}", "Content-Type": "application/json"},
            )
        if resp.is_success:
            logger.info("✅ Groq OK")
        else:
            logger.error(f"❌ Groq FALHOU | {resp.status_code} | {resp.text[:200]}")
    except Exception as e:
        logger.error(f"❌ Groq FALHOU | {e}")

    logger.info(f"🕐 Horário Brasília: {datetime.now(FUSO_BR).strftime('%H:%M')}")
    logger.info("✅ Lara pronta para receber mensagens")


# ─────────────────────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────────────────────
def main() -> None:
    lock_file = open("/tmp/lara_bot.lock", "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        logger.error("❌ Outra instância rodando. Encerrando.")
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

    # Handler de texto
    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & ~filters.ChatType.GROUP
            & ~filters.ChatType.SUPERGROUP,
            lidar,
        )
    )

    # Handler de imagem (fotos)
    app.add_handler(
        MessageHandler(
            filters.PHOTO
            & ~filters.ChatType.GROUP
            & ~filters.ChatType.SUPERGROUP,
            lidar_imagem,
        )
    )

    app.add_error_handler(handler_erro_global)

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
