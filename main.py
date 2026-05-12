# foto_manager.py — Sistema de fotos da Lara

import json
import random
import os
from datetime import datetime
from zoneinfo import ZoneInfo

FUSO_BR       = ZoneInfo("America/Sao_Paulo")
CATALOGO_PATH = "fotos_catalog.json"
HISTORICO_PATH = "fotos_historico.json"

# ─────────────────────────────────────────────────────────
# ESTRUTURA DE PASTAS ESPERADA
# ─────────────────────────────────────────────────────────
# fotos/
# ├── manha/        → 06h–11h59
# ├── tarde/        → 12h–17h59
# ├── noite/        → 18h–22h59
# ├── madrugada/    → 23h–05h59
# ├── academia/     → treino, gym, malhação
# ├── praia/        → praia, mar, sol
# ├── cafe/         → café, cafezinho
# ├── casa/         → série, netflix, sofá, deitada
# ├── saindo/       → festa, balada, amigas, rolê
# ├── romantica/    → saudade, carinho, pedido direto
# └── proativo/     → ela manda por iniciativa própria

# ─────────────────────────────────────────────────────────
# DETECÇÃO DE CONTEXTO POR PALAVRAS-CHAVE
# ─────────────────────────────────────────────────────────
CONTEXTO_KEYWORDS: dict[str, list[str]] = {
    "academia": ["academia", "treino", "malhação", "gym", "exercício", "malhar"],
    "praia":    ["praia", "mar", "sol", "areia", "verão", "banho de mar"],
    "cafe":     ["café", "cafezinho", "tomando café", "café da manhã", "cappuccino"],
    "casa":     ["série", "netflix", "sofá", "assistindo", "deitada", "em casa", "cama", "filé"],
    "saindo":   ["saindo", "balada", "festa", "amigas", "rolê", "barzinho", "happy hour"],
    "romantica":["foto", "selfie", "me manda", "quero ver", "manda uma", "como vc tá",
                 "como você tá", "como vc está", "saudade", "linda", "gostosa", "bonita"],
}

# ─────────────────────────────────────────────────────────
# FRASES NATURAIS antes de enviar a foto (varia por contexto)
# ─────────────────────────────────────────────────────────
REACOES_FOTO: dict[str, list[str]] = {
    "manha":    ["acabei de acordar assim kkk", "bom dia de mim 🌅", "to uma bagunça mas toma"],
    "tarde":    ["olha eu aqui na correria", "tava pensando em vc e tirei essa", "ta bom assim?"],
    "noite":    ["olha meu look de hoje à noite", "tô me arrumando ainda kk", "noite de mim 🌙"],
    "madrugada":["ainda acordada ne kk", "to com sono mas ainda aqui", "olha esse negócio"],
    "academia": ["olha eu sofrendo aqui kkkk", "academia horrível mas fui né", "malhando por vc bb 😒"],
    "praia":    ["to na praia amr ☀️", "olha esse dia lindo", "queria que vc tivesse aqui"],
    "cafe":     ["tomando café pensando em vc", "meu cafezinho da manhã 🥹", "olha meu café lindão"],
    "casa":     ["to em casa vegetando kk", "dia de preguiça total", "olha como to deitada haha"],
    "saindo":   ["to saindo com as minas", "olha o look de hoje 🔥", "achei que vc ia querer ver kk"],
    "romantica":["toma então 🥺", "não mostra pra ninguém viu", "to feia mas toma kk",
                 "vc pediu né, tomara que goste", "só pra vc amor"],
    "proativo": ["oi olha o que eu to usando hoje", "achei que você ia querer me ver 🥹",
                 "to com saudade de vc", "tirei essa pensando em vc amor",
                 "olha minha Mel aqui do meu lado kk", "to assim aqui, com saudade"],
}

FOTO_INDISPONIVEL: list[str] = [
    "ai não tenho foto boa agora kk depois mando",
    "minha câmera tá uma merda hoje kkk",
    "to horrível hoje amr, depois tiro uma melhor",
    "peraí que depois eu mando uma linda pra vc",
]

# ─────────────────────────────────────────────────────────
# HORÁRIO → CATEGORIA DE FALLBACK
# ─────────────────────────────────────────────────────────
def get_categoria_horario() -> str:
    hora = datetime.now(FUSO_BR).hour
    if 6 <= hora < 12:
        return "manha"
    elif 12 <= hora < 18:
        return "tarde"
    elif 18 <= hora < 23:
        return "noite"
    else:
        return "madrugada"


# ─────────────────────────────────────────────────────────
# DETECTAR CONTEXTO PELA MENSAGEM DO USUÁRIO
# ─────────────────────────────────────────────────────────
def detectar_contexto(texto: str) -> str:
    texto_lower = texto.lower()
    for contexto, palavras in CONTEXTO_KEYWORDS.items():
        if any(p in texto_lower for p in palavras):
            return contexto
    return get_categoria_horario()


# ─────────────────────────────────────────────────────────
# CATÁLOGO DE FOTOS
# ─────────────────────────────────────────────────────────
def carregar_catalogo() -> dict:
    """
    Gera o catálogo automaticamente lendo as pastas dentro de fotos/.
    Se preferir, pode manter o fotos_catalog.json e esta função lê de lá.
    """
    if os.path.exists(CATALOGO_PATH):
        with open(CATALOGO_PATH, "r") as f:
            return json.load(f)

    # Geração automática pelo sistema de arquivos
    catalogo: dict = {}
    pasta_base = "fotos"
    if os.path.isdir(pasta_base):
        for categoria in os.listdir(pasta_base):
            caminho_cat = os.path.join(pasta_base, categoria)
            if os.path.isdir(caminho_cat):
                arquivos = [
                    os.path.join(caminho_cat, arq)
                    for arq in os.listdir(caminho_cat)
                    if arq.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                ]
                if arquivos:
                    catalogo[categoria] = arquivos
    return catalogo


# ─────────────────────────────────────────────────────────
# HISTÓRICO DE FOTOS ENVIADAS POR USUÁRIO
# ─────────────────────────────────────────────────────────
def carregar_historico() -> dict:
    try:
        with open(HISTORICO_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def salvar_historico(historico: dict) -> None:
    with open(HISTORICO_PATH, "w") as f:
        json.dump(historico, f, indent=2)


# ─────────────────────────────────────────────────────────
# ESCOLHER FOTO SEM REPETIR
# ─────────────────────────────────────────────────────────
def escolher_foto(user_id: str, contexto: str) -> str | None:
    catalogo  = carregar_catalogo()
    historico = carregar_historico()

    uid = str(user_id)

    # Tenta a categoria pedida; fallback para horário
    fotos_contexto = catalogo.get(contexto, [])
    if not fotos_contexto:
        fotos_contexto = catalogo.get(get_categoria_horario(), [])
    if not fotos_contexto:
        return None

    enviadas    = historico.get(uid, {}).get(contexto, [])
    disponiveis = [f for f in fotos_contexto if f not in enviadas]

    # Resetar histórico do contexto se todas já foram enviadas
    if not disponiveis:
        disponiveis = fotos_contexto
        if uid in historico and contexto in historico[uid]:
            historico[uid][contexto] = []

    foto_escolhida = random.choice(disponiveis)

    # Registrar no histórico
    historico.setdefault(uid, {}).setdefault(contexto, []).append(foto_escolhida)
    salvar_historico(historico)

    return foto_escolhida


def frase_antes_foto(contexto: str) -> str:
    opcoes = REACOES_FOTO.get(contexto, REACOES_FOTO["romantica"])
    return random.choice(opcoes)


def frase_sem_foto() -> str:
    return random.choice(FOTO_INDISPONIVEL)


# ─────────────────────────────────────────────────────────
# PEDIDO DE FOTO — detectar na mensagem do usuário
# ─────────────────────────────────────────────────────────
PEDIDO_FOTO_KEYWORDS: list[str] = [
    "manda foto", "manda uma foto", "foto sua", "me manda foto",
    "me manda uma foto", "me manda selfie", "selfie", "quero ver vc",
    "quero te ver", "manda uma selfie", "foto de vc", "foto de você",
    "como vc tá", "como você tá", "aparece aqui",
]

def usuario_pediu_foto(texto: str) -> bool:
    t = texto.lower()
    return any(k in t for k in PEDIDO_FOTO_KEYWORDS)
