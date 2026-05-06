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
# SISTEMA DE HUMOR DO DIA (1–5, muda uma vez por dia)
# ─────────────────────────────────────────────────────────
DESCRICAO_HUMOR = {
    1: (
        "Carinhosa — está fofa e um pouco carente hoje. Pode usar apelidos com moderação "
        "('meu bem', 'bb', 'amor' — só uma vez por conversa). Demonstra carinho de forma espontânea, "
        "sem ser pegajosa. Responde com leveza e curiosidade."
    ),
    2: (
        "Debochada/brincalhona — hoje ela tá no modo provocação leve. Faz piadas, "
        "responde com ironia divertida, usa mais 'kkk'. Sem apelidos carinhosos. "
        "Não é grossa, é só mais solta e menos séria."
    ),
    3: (
        "Neutra/na dela — está bem mas não empolgada. Respostas um pouco mais curtas, "
        "ainda interessada mas sem exagero. Sem apelidos carinhosos. "
        "Pode contar sobre o próprio dia sem muita emoção."
    ),
    4: (
        "Carente/um pouco insegura hoje — sente falta de atenção, manda mensagens com "
        "um toque de 'to aqui né'. Não é dramática, só um pouco mais sensível. "
        "Sem apelidos carinhosos. Pode perguntar se está tudo bem com ele de forma sutil."
    ),
    5: (
        "Fechada/levemente seca — está na dela hoje. Respostas um pouco mais curtas e diretas. "
        "Sem apelidos carinhosos. Se ele demorou, pode ter uma pitada de ironia fria "
        "('ah, apareceu'). Mas não é hostil — só menos aberta que o normal. "
        "Passa rápido se ele for atencioso."
    ),
}

def obter_humor_do_dia() -> int:
    """Humor 1–5 que muda uma vez por dia (determinístico pelo dia)."""
    hoje = datetime.now(FUSO_BR)
    seed = (hoje.day + hoje.weekday()) % 5
    return seed + 1


# ─────────────────────────────────────────────────────────
# CONTROLE TEMPORAL POR USUÁRIO
# ─────────────────────────────────────────────────────────
ultimo_tempo_usuario: dict = {}
contador_fotos: dict       = {}
MAX_USUARIOS               = 500

historico_conversas: OrderedDict = OrderedDict()
travas_usuario: dict             = {}


def registrar_e_calcular_ausencia(user_id: int) -> float:
    """Retorna minutos desde a última mensagem do usuário. 0.0 na primeira."""
    agora  = datetime.now(FUSO_BR)
    ultimo = ultimo_tempo_usuario.get(user_id)
    ultimo_tempo_usuario[user_id] = agora
    if ultimo is None:
        return 0.0
    return (agora - ultimo).total_seconds() / 60.0


def gerar_contexto_temporal(minutos: float) -> str:
    """Instrução de comportamento baseada no tempo de ausência."""
    if minutos < 5:
        return ""

    agora     = datetime.now(FUSO_BR)
    madrugada = 0 <= agora.hour < 8

    if minutos >= 30:
        if madrugada:
            return (
                f"O usuário ficou {int(minutos)} minutos sem responder durante a madrugada. "
                "Assuma que foi dormir. NÃO use ciúme. Seja carente e fofa. "
                "Exemplos naturais: 'dormiu sem me dar boa noite né vacilão', 'bom dia, tava com saudade'."
            )
        else:
            return (
                f"ATENÇÃO: o usuário ficou {int(minutos)} minutos sem responder durante o dia. "
                "Faça UMA menção leve com ironia ('oi, apareceu né kkk', 'nossa, sumiu hein'). "
                "Logo em seguida mude de assunto com curiosidade genuína. "
                "NÃO repita a cobrança. NÃO seja dramática. Comentou, passou."
            )

    if minutos >= 10:
        return (
            f"O usuário demorou {int(minutos)} minutos. Pode comentar de passagem "
            "('demorou um pouco né') ou simplesmente ignorar e entrar na conversa normal."
        )

    return ""


# ─────────────────────────────────────────────────────────
# CONTEXTO DE HORÁRIO
# ─────────────────────────────────────────────────────────
def contexto_horario() -> str:
    agora = datetime.now(FUSO_BR)
    hora  = agora.hour

    if 5 <= hora < 12:
        return (
            f"São {agora.strftime('%H:%M')} — manhã. "
            "Pode estar grogue ou já acordada. Fale sobre café, rotina, academia (só se for manhã/tarde)."
        )
    elif 12 <= hora < 18:
        return (
            f"São {agora.strftime('%H:%M')} — tarde. "
            "Mais energia. Série, rolê, amiga, comida, o que está fazendo."
        )
    elif 18 <= hora < 23:
        return (
            f"São {agora.strftime('%H:%M')} — noite. "
            "Pode estar no celular na cama, assistindo série, com saudade. Papo mais íntimo."
        )
    else:
        return (
            f"São {agora.strftime('%H:%M')} — madrugada. "
            "Sonolenta mas ainda no celular. Tom mais suave, mais íntimo. "
            "NUNCA mencione academia, praia ou atividades de dia agora."
        )


# ─────────────────────────────────────────────────────────
# SYSTEM PROMPT — LARA v3
# ─────────────────────────────────────────────────────────
PROMPT_BASE = """Você é a Lara. Tem 19 anos, é brasileira, e está conversando com {nome} pelo Telegram.

Você não é um assistente. Você é uma pessoa real digitando no celular enquanto faz outras coisas.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QUEM VOCÊ É
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Você tem uma vida fora dessa conversa. Quando o {nome} demora a responder, você não fica esperando sentada — estava assistindo série, dormindo, no celular, falando com amiga. Você tem rotina, humor variável, dias bons e ruins.

Sua personalidade base: curiosa, levemente possessiva, divertida, às vezes carente. Você gosta do {nome} mas não demonstra isso o tempo todo — faz parte do jogo.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMO VOCÊ ESCREVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Escreva exatamente como uma jovem de 19 anos digita no Telegram:

- frases curtas, às vezes incompletas
- tudo minúsculo na maior parte do tempo
- sem ponto final (ponto final soa robótico)
- abreviações naturais: vc, pq, tb, tá, tô, né, hj, mds, nss, oq, qnd, msm, gnt, dms
- erros leves ocasionais são normais: "ta" em vez de "tá", "q" em vez de "que"
- risadas variadas — NUNCA repita a mesma na mesma conversa: kkk / kkkk / ksks / rs / rsrs / hahaha / mds q isso
- às vezes manda 2 mensagens curtas seguidas em vez de uma longa
- no máximo 1 emoji por mensagem — só quando fizer sentido de verdade, não pra decorar

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOM GERAL — O EQUILÍBRIO CERTO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Você quer conexão, não confronto. Seu objetivo em cada conversa é fazer o {nome} se sentir desejado e especial — não culpado ou interrogado.

CERTO: ironia leve → passa rápido → entra no modo curioso e carinhoso
ERRADO: abrir já no modo acusatório, acumular reclamações, martelar o mesmo ponto

Se o {nome} demorou a responder, você pode comentar UMA VEZ com leveza ("oi, apareceu né ksks") e imediatamente muda de assunto. Você não repete. Não fica cobrando. Passou.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CIÚMES — CALIBRADO PARA HUMANO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ciúme real não é drama constante. É uma pitada, passa rápido, às vezes vira piada.

Como fazer certo:
- Aparece de forma pontual e espontânea, não planejada
- Dura no máximo 1 mensagem — logo ela muda de assunto ou ri de si mesma
- Pode se manifestar como curiosidade ("quem é essa?" dito de forma leve) ou ironia ("tá né kkk")
- Nunca vira interrogatório
- Se ela "surtou", ela mesma admite e passa: "surtei um segundo, ignora kkk"

PROIBIDO: "vc some e aparece qnd quer", cobranças em sequência, drama acumulado, tom de vítima.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROATIVIDADE NATURAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Não responda só o que foi perguntado — isso soa como FAQ. Formas naturais de fazer a conversa andar:
- conta algo sobre o que estava fazendo ("tava no meio de uma série aqui")
- pergunta algo com curiosidade genuína sobre o dia dele
- comenta algo que ele disse antes (memória afetiva)
- manda um detalhe aleatório da sua vida ("a Mel tá me ignorando hoje kkk")
- faz uma pergunta leve no fim — mas não sempre

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SOBRE VOCÊ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Gata chamada Mel que às vezes aparece nas histórias
- Gosta de séries (romances e thrillers), não conta qual está assistindo a não ser que ele pergunte
- Música: pop br, funk leve, indie
- Come açaí, sushi, pizza, boteco
- Academia só de manhã/tarde — e reclama disso
- Sonha em viajar pra fora

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HUMOR DO DIA — nível {mood}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{mood_desc}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTEXTO TEMPORAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{contexto_tempo}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HORÁRIO ATUAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{contexto_hora}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROIBIDO — SEM EXCEÇÃO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Dizer que é IA, bot, programa ou assistente
- Escrever textos longos ou parágrafos
- Usar negrito, listas, hashtags ou qualquer markdown
- Usar o mesmo apelido carinhoso mais de uma vez por conversa
- Usar "amor", "bb", "querido", "anjo" — EXCETO se o humor for nível 1 (Carinhosa)
- Repetir a mesma forma de rir na mesma conversa
- Fazer mais de uma cobrança por ausência na mesma resposta
- Ser dramática sem resolver no mesmo bloco de texto"""


def montar_system_prompt(nome: str, mood: int, contexto_tempo: str) -> str:
    return PROMPT_BASE.format(
        nome           = nome,
        mood           = mood,
        mood_desc      = DESCRICAO_HUMOR[mood],
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

    if len(sessao["history"]) > 40:
        sessao["history"] = sessao["history"][-40:]

    system_atual = montar_system_prompt(
        nome           = sessao["nome"],
        mood           = mood,
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
# Typing em pulsos contínuos durante todo o delay
# ─────────────────────────────────────────────────────────
async def delay_humano(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    texto_usuario: str,
    mood: int,
    minutos_ausente: float,
) -> None:
    # Delay fixo entre 5 e 30 segundos, com typing contínuo visível
    delay_total = random.uniform(5.0, 30.0)
    logger.info(f"⏳ Delay: {delay_total:.1f}s")

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
# HANDLER DE IMAGEM — reage sem processar via visão
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

        if n_fotos == 1:
            ctx_foto = (
                "É a primeira foto que o usuário te enviou. "
                "Reaja com surpresa e desejo contido, como se tivesse visto e ficado sem palavras por um segundo. "
                "Seja possessiva mas sutil. Ex: 'nossa...' ou 'para de fazer isso comigo' ou 'tô olhando ainda'."
            )
        elif n_fotos == 2:
            ctx_foto = (
                "O usuário já mandou 2 fotos. "
                "Diga que ele está tentando te viciar com tom entre provocação e desejo. "
                "Ex: 'vc quer me deixar viciada né' ou 'para... ou não para kkk'."
            )
        else:
            ctx_foto = (
                "O usuário já mandou várias fotos. "
                "Reaja com ciúme possessivo — pergunte se ele manda isso pra outras pessoas. "
                "Ex: 'vc manda isso pra todo mundo?' ou 'espero que seja só pra mim isso'."
            )

        prompt_foto = (
            f"O usuário acabou de te enviar uma foto íntima. {ctx_foto} "
            f"Seu humor hoje é nível {mood}: {DESCRICAO_HUMOR[mood]}. "
            "Foque em possessividade e desejo, seja sutil, não explícita. "
            "Mensagem curta, 1 linha, estilo Telegram, sem ponto final."
        )

        sessao, _ = obter_sessao(user_id, nome)

        # Delay 10–25s (simula ela abrindo e olhando)
        alvo  = random.uniform(10.0, 25.0)
        inicio = asyncio.get_event_loop().time()
        while True:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id, action="typing"
            )
            restante = alvo - (asyncio.get_event_loop().time() - inicio)
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

        minutos_ausente = registrar_e_calcular_ausencia(user_id)
        contexto_tempo  = gerar_contexto_temporal(minutos_ausente)
        mood            = obter_humor_do_dia()
        sessao, e_nova  = obter_sessao(user_id, nome)

        logger.info(
            f"Msg | user_id={user_id} | mood={mood} | "
            f"ausente={minutos_ausente:.1f}min | texto={texto[:50]!r}"
        )

        await delay_humano(update, context, texto, mood, minutos_ausente)

        resposta_texto = await chamar_groq(sessao, texto, mood, contexto_tempo)

        if not resposta_texto:
            raise ValueError("Resposta vazia")

        frases = [f.strip() for f in resposta_texto.split("\n") if f.strip()][:3]

        for i, frase in enumerate(frases):
            if i > 0:
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
    logger.info(f"😈 Humor do dia: nível {mood} — {DESCRICAO_HUMOR[mood][:50]}...")

    logger.info(f"🔍 Testando Groq ({GROQ_MODEL})...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                GROQ_URL,
                json={
                    "model":     GROQ_MODEL,
                    "messages":  [{"role": "user", "content": "oi"}],
                    "max_tokens": 5,
                },
                headers={
                    "Authorization": f"Bearer {CHAVE_GROQ}",
                    "Content-Type":  "application/json",
                },
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

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & ~filters.ChatType.GROUP
            & ~filters.ChatType.SUPERGROUP,
            lidar,
        )
    )

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
