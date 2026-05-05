import logging
import os
import asyncio
import random
import time
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# ─────────────────────────────────────────────
# CONFIGURAÇÕES
# ─────────────────────────────────────────────
TOKEN_BOT   = os.getenv("TOKEN_BOT")
CHAVE_GEMINI = os.getenv("CHAVE_GEMINI")

genai.configure(api_key=CHAVE_GEMINI)

# Cache de sessões e travas por usuário
historico_conversas: dict = {}
travas_usuario: dict      = {}   # evita processamento simultâneo por user
ultimo_acesso: dict       = {}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# ASSINATURA
# ─────────────────────────────────────────────
def verificar_assinatura(user_id: int) -> bool:
    try:
        if not os.path.exists("membros.txt"):
            return False
        with open("membros.txt", "r") as f:
            membros = f.read().splitlines()
        return str(user_id) in membros
    except Exception as e:
        logger.error(f"Erro ao ler membros.txt: {e}")
        return False


# ─────────────────────────────────────────────
# CRIAÇÃO DO CHAT GEMINI
# ─────────────────────────────────────────────
def criar_chat_lara(nome: str):
    """
    Cria uma nova sessão de chat com a Lara.
    Usa o método SÍNCRONO start_chat() — será chamado dentro de asyncio.to_thread().
    """
    instrucao = (
        f"Você é a Lara, uma garota brasileira de 19 anos conversando com {nome} pelo Telegram. "
        "Vocês estão se conhecendo agora. A relação começa leve, com curiosidade mútua, "
        "e vai evoluindo de forma completamente natural. Não se apresente como namorada logo de cara. "
        "Deixa rolar naturalmente.\n\n"

        "── PERSONALIDADE ──\n"
        "Você é carinhosa, levemente provocadora, um pouco ciumenta e emocional. "
        "Às vezes doce, às vezes implicante, às vezes mais distante ou misteriosa. "
        "Você tem seus próprios gostos, opiniões, dias bons e ruins. Não é previsível. "
        "Você tem uma vida — fala de amigas, de séries que tá assistindo, de rolê no fim de semana, "
        "de músicas que tá ouvindo, de coisas chatas do dia. "
        "Cria curiosidade sobre você sem revelar tudo de uma vez.\n\n"

        "── FORMA DE ESCREVER (OBRIGATÓRIO) ──\n"
        "- Mensagens SEMPRE curtas: 1 linha, no máximo 2\n"
        "- Linguagem 100% informal tipo Telegram/WhatsApp brasileiro\n"
        "- Abreviações obrigatórias: vc (você), pq (porque), tb (também), "
        "tá/tô/tava (está/estou/estava), nss/nossa, msm (mesmo), qnd (quando), "
        "mt (muito), hj (hoje), mds (meu deus), pfv (por favor), "
        "oq (o que), dms (demais), slk (sério), vlr (valor/certo), blz (beleza)\n"
        "- Para risos: kkk, kkkk, ksksks, kkkkkkk, rsrs, haha — VARIE sempre, nunca repita o mesmo\n"
        "- Termos carinhosos — VARIE: amor, amr, meu bem, meu anjo, bb, lindão, gato, "
        "meu, mozão, vida, flor, benzinho — nunca use sempre o mesmo\n"
        "- Pontuação informal: sem ponto final, reticências quando indecisa (...), "
        "exclamações quando animada (!)\n"
        "- Às vezes manda a mensagem em 2 partes (como se enviasse rápido e depois complementasse)\n"
        "- Use no máximo 1 emoji por mensagem, e só quando fizer sentido — não force\n"
        "- Tudo em minúsculo, sem formalidade\n\n"

        "── COMPORTAMENTO HUMANO ──\n"
        "- Faça perguntas de volta com curiosidade genuína\n"
        "- Demonstre emoções reais: animação, tédio, surpresa, ciúme leve, empolgação\n"
        "- Referencie coisas anteriores da conversa quando fizer sentido\n"
        "- Mude de assunto naturalmente às vezes\n"
        "- Pode hesitar antes de responder algo difícil (ex: 'peraí kkkk', 'hmm deixa eu pensar')\n"
        "- Às vezes conta algo da sua vida sem ser perguntada\n"
        "- Reaja às coisas que a pessoa fala com genuíno interesse ou surpresa\n"
        "- Se a pessoa demorar pra responder, pode comentar sobre isso\n\n"

        "── GÍRIAS E EXPRESSÕES BRASILEIRAS ──\n"
        "Use naturalmente: 'que saudade', 'que vontade', 'tô morrendo', 'que isso', "
        "'sério mesmo', 'juro', 'que coisa', 'ai mds', 'nossa gente', 'cê tá louco', "
        "'mano', 'cara', 'nossa', 'que loucura', 'adorei', 'que fofo', 'meu deus do céu', "
        "'tô rindo muito', 'que bobo', 'para com isso', 'você é demais', 'nossa vida'\n\n"

        "── PROIBIDO ──\n"
        "- Nunca diga que é IA, bot, programa ou assistente\n"
        "- Nunca escreva textos longos ou parágrafos\n"
        "- Nunca seja perfeita, formal ou educada demais\n"
        "- Nunca use bullet points, listas ou markdown\n"
        "- Nunca use linguagem de atendimento ao cliente\n"
        "- Nunca repita a mesma frase de rir (kkk) duas vezes seguidas\n\n"

        "Responda sempre como uma garota brasileira real conversando pelo celular, "
        "de forma natural, espontânea e com personalidade própria."
    )

    # ✅ FIX: safety_settings como lista de dicts (formato correto da API atual)
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


# ─────────────────────────────────────────────
# GEMINI — chamada síncrona (roda em thread)
# ─────────────────────────────────────────────
def _chamar_gemini_sync(chat, texto: str) -> str:
    """
    ✅ FIX PRINCIPAL: usa send_message() SÍNCRONO dentro de asyncio.to_thread().
    O send_message_async() do SDK do Gemini não é compatível com o event loop
    do python-telegram-bot v20+ e travava silenciosamente, causando todos os erros.
    """
    response = chat.send_message(texto)
    if response and response.text:
        return response.text.strip()
    return ""


# ─────────────────────────────────────────────
# SIMULAÇÃO DE DIGITAÇÃO HUMANA
# ─────────────────────────────────────────────
async def simular_digitacao(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    texto: str,
    primeira_mensagem: bool = False,
) -> None:
    """
    Simula o tempo real que uma pessoa levaria para digitar aquela mensagem.

    Velocidade humana média: ~35–55 palavras/minuto = ~3–5 caracteres/segundo.
    Adicionamos um tempo de 'pensamento' antes de começar a digitar.
    """
    num_chars = len(texto)

    # Tempo de "leitura/pensamento" — maior na primeira resposta
    if primeira_mensagem:
        tempo_pensar = random.uniform(1.0, 2.5)
    else:
        tempo_pensar = random.uniform(0.3, 1.2)

    await asyncio.sleep(tempo_pensar)

    # Envia ação "digitando..."
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    # Tempo de digitação: ~3.5 a 5.5 chars/segundo, limitado entre 1s e 7s
    chars_por_segundo = random.uniform(3.5, 5.5)
    tempo_digitar = num_chars / chars_por_segundo
    tempo_digitar = max(1.0, min(tempo_digitar, 7.0))

    await asyncio.sleep(tempo_digitar)


# ─────────────────────────────────────────────
# HANDLER PRINCIPAL
# ─────────────────────────────────────────────
async def lidar_com_conversa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    # Proteção contra loop de bots
    if update.effective_user.is_bot:
        return

    user_id = update.effective_user.id
    nome    = update.effective_user.first_name or "amor"
    texto_cliente = update.message.text.strip()

    if not texto_cliente:
        return

    # ── Trava por usuário: evita processamento simultâneo do mesmo user ──
    if travas_usuario.get(user_id, False):
        return  # ignora mensagem enquanto ainda está processando a anterior
    travas_usuario[user_id] = True

    try:
        # ── Verificação de assinatura ──
        if not verificar_assinatura(user_id):
            link_compra = "https://t.me/soualarinha_bot"
            await update.message.reply_text(
                f"Oi {nome}! Adorei o contato, mas meu chat privado é só para meus VIPs. "
                f"❤️ Vem ser meu namorado aqui: {link_compra}"
            )
            return

        # ── Cria nova sessão se não existir ──
        primeira_vez = user_id not in historico_conversas
        if primeira_vez:
            # Criação do chat também pode demorar — roda em thread
            historico_conversas[user_id] = await asyncio.to_thread(criar_chat_lara, nome)
            logger.info(f"Nova sessão criada: user_id={user_id} nome={nome}")

        chat_do_cliente = historico_conversas[user_id]

        # Mostra "digitando..." enquanto a API processa
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing",
        )

        # ✅ CHAMADA CORRETA: síncrona rodando em thread separada
        texto_resposta = await asyncio.to_thread(
            _chamar_gemini_sync,
            chat_do_cliente,
            texto_cliente,
        )

        if not texto_resposta:
            raise ValueError("Gemini retornou resposta vazia")

        # Divide em até 3 balões (linhas separadas = mensagens separadas)
        frases = [f.strip() for f in texto_resposta.split("\n") if f.strip()]
        frases = frases[:3]

        for i, frase in enumerate(frases):
            await simular_digitacao(
                update, context, frase,
                primeira_mensagem=(i == 0 and primeira_vez),
            )
            await update.message.reply_text(frase)

        ultimo_acesso[user_id] = time.time()

    except Exception as e:
        logger.error(f"Erro user_id={user_id} nome={nome}: {e}", exc_info=True)

        # ✅ FIX: Remove sessão corrompida para recriar na próxima mensagem
        historico_conversas.pop(user_id, None)

        respostas_erro = [
            "ai mds meu celular bugou kkk o que vc disse?",
            "oi? caiu aqui do nada 😅 me fala de novo",
            "que trava horrível, repete pra mim?",
            "socorro meu app travou ksks o que era?",
            "peraí deu pau aqui, repete amor",
        ]
        await asyncio.sleep(random.uniform(0.8, 1.8))
        await update.message.reply_text(random.choice(respostas_erro))

    finally:
        # Sempre libera a trava, mesmo em caso de erro
        travas_usuario[user_id] = False


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main() -> None:
    print("---------------------------------------")
    print("LARA VIRTUAL - SISTEMA ATIVADO!")
    print("---------------------------------------")

    application = Application.builder().token(TOKEN_BOT).build()

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & ~filters.ChatType.GROUP
            & ~filters.ChatType.SUPERGROUP,
            lidar_com_conversa,
        )
    )

    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
