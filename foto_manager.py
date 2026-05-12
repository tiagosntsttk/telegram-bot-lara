# foto_manager.py
import json
import random
from datetime import datetime

CATALOGO_PATH = "fotos_catalog.json"
HISTORICO_PATH = "fotos_historico.json"

# Palavras-chave para detectar contexto pela conversa
CONTEXTO_KEYWORDS = {
    "academia": ["academia", "treino", "malhação", "gym", "exercício"],
    "praia":    ["praia", "mar", "sol", "areia", "verão"],
    "cafe":     ["café", "cafezinho", "tomando café", "café da manhã"],
    "casa":     ["série", "netflix", "sofá", "assistindo", "deitada", "em casa"],
    "saindo":   ["saindo", "balada", "festa", "amigas", "rolê"],
    "romantica":["foto", "selfie", "me manda", "quero ver", "saudade", "linda", "gostosa"],
}

def get_horario_categoria() -> str:
    hora = datetime.now().hour
    if 6 <= hora < 12:
        return "manha"
    elif 12 <= hora < 18:
        return "tarde"
    elif 18 <= hora < 23:
        return "noite"
    else:
        return "madrugada"

def detectar_contexto(texto: str) -> str:
    texto_lower = texto.lower()
    for contexto, palavras in CONTEXTO_KEYWORDS.items():
        if any(p in texto_lower for p in palavras):
            return contexto
    return get_horario_categoria()  # fallback para horário

def carregar_catalogo() -> dict:
    with open(CATALOGO_PATH, "r") as f:
        return json.load(f)

def carregar_historico() -> dict:
    try:
        with open(HISTORICO_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def salvar_historico(historico: dict):
    with open(HISTORICO_PATH, "w") as f:
        json.dump(historico, f)

def escolher_foto(user_id: str, contexto: str) -> str | None:
    catalogo  = carregar_catalogo()
    historico = carregar_historico()

    fotos_contexto = catalogo.get(contexto, [])
    if not fotos_contexto:
        fotos_contexto = catalogo.get(get_horario_categoria(), [])

    enviadas = historico.get(str(user_id), {}).get(contexto, [])
    disponiveis = [f for f in fotos_contexto if f not in enviadas]

    # Se já enviou todas, reseta o histórico daquele contexto
    if not disponiveis:
        disponiveis = fotos_contexto
        if str(user_id) in historico:
            historico[str(user_id)][contexto] = []

    if not disponiveis:
        return None

    foto_escolhida = random.choice(disponiveis)

    # Registra no histórico
    if str(user_id) not in historico:
        historico[str(user_id)] = {}
    if contexto not in historico[str(user_id)]:
        historico[str(user_id)][contexto] = []
    historico[str(user_id)][contexto].append(foto_escolhida)
    salvar_historico(historico)

    return foto_escolhida