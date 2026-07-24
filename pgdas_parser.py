"""Extração tolerante dos dados mensais disponíveis no extrato PGDAS-D."""

import io
import re
from statistics import mean
from typing import Dict, List

try:
    from PyPDF2 import PdfReader
except ImportError:  # runtime de validação do Codex
    from pypdf import PdfReader


VALOR_RE = r"([\d.]+,\d{2})"
COMPETENCIA_RE = r"(\d{2}/\d{4})"


def _numero_br(valor: str) -> float:
    return float(valor.replace(".", "").replace(",", "."))


def _primeiro(texto: str, padrao: str, padrao_flags=re.IGNORECASE | re.DOTALL) -> float:
    encontrado = re.search(padrao, texto, padrao_flags)
    return _numero_br(encontrado.group(1)) if encontrado else 0.0


def _pares_mensais(texto: str) -> List[Dict[str, float]]:
    return [
        {"Competência": competencia, "Valor": _numero_br(valor)}
        for competencia, valor in re.findall(
            rf"{COMPETENCIA_RE}\s+{VALOR_RE}", texto, re.IGNORECASE
        )
    ]


def extrair_dados_pgdas(file_bytes: bytes) -> Dict:
    reader = PdfReader(io.BytesIO(file_bytes))
    texto = "\n".join((pagina.extract_text() or "") for pagina in reader.pages)

    pa_match = re.search(r"Per[ií]odo de Apura[cç][aã]o\s*\(PA\):\s*(\d{2}/\d{4})", texto)
    pa = pa_match.group(1) if pa_match else ""

    rpa = _primeiro(
        texto,
        rf"Receita Bruta do PA \(RPA\).*?{VALOR_RE}",
    )
    rbt12 = _primeiro(texto, rf"\(RBT12\)\s*{VALOR_RE}")
    folha_total = _primeiro(
        texto,
        rf"Total de Folhas de Sal[aá]rios Anteriores.*?R\$\s*{VALOR_RE}",
    )
    fator_r = _primeiro(texto, r"Fator r\s*=\s*([\d,]+)")

    trecho_receitas = re.search(
        r"2\.2\.1\)\s*Mercado Interno(.*?)2\.2\.2\)\s*Mercado Externo",
        texto,
        re.IGNORECASE | re.DOTALL,
    )
    receitas = _pares_mensais(trecho_receitas.group(1)) if trecho_receitas else []

    trecho_folha = re.search(
        r"2\.3\)\s*Folha de Sal[aá]rios Anteriores(.*?)2\.3\.1\)",
        texto,
        re.IGNORECASE | re.DOTALL,
    )
    folhas = _pares_mensais(trecho_folha.group(1)) if trecho_folha else []

    mapa_folha = {item["Competência"]: item["Valor"] for item in folhas}
    media_folha = mean(mapa_folha.values()) if mapa_folha else 0.0

    # Para projetar o mês seguinte ao PA, a janela anterior deve conter os
    # onze meses anteriores mais o próprio PA. O PGDAS não traz a folha do PA;
    # ela entra como estimativa editável pela média dos meses disponíveis.
    receitas_ordenadas = receitas[-11:]
    historico = [
        {
            "Competência": item["Competência"],
            "Faturamento": item["Valor"],
            "Folha": mapa_folha.get(item["Competência"], media_folha),
            "Origem": "PGDAS-D",
        }
        for item in receitas_ordenadas
    ]
    if pa and rpa:
        historico.append(
            {
                "Competência": pa,
                "Faturamento": rpa,
                "Folha": media_folha,
                "Origem": "PGDAS-D | folha estimada",
            }
        )

    return {
        "pa": pa,
        "rpa": rpa,
        "rbt12": rbt12,
        "folha12": folha_total,
        "fator_r": fator_r,
        "historico": historico[-12:],
        "texto_extraido": texto,
    }
