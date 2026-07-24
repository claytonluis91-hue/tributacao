"""Motor de simulação tributária.

O modelo é gerencial e comparativo. Ele usa histórico mensal real para formar
RBT12/FS12 e fecha IRPJ/CSLL dos regimes trimestrais por trimestre.
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Dict, Iterable, List, Sequence, Tuple


@dataclass
class DadosMes:
    mes: int
    faturamento: float
    folha: float
    despesas_dedutiveis: float
    compras_credito: float
    competencia: str = ""


@dataclass
class ConfigTributaria:
    aliquota_rat: float = 0.02
    fap: float = 1.0
    aliquota_terceiros: float = 0.058
    is_anexo_iv: bool = False
    fator_r_sujeito: bool = True
    presuncao_irpj: float = 0.32
    presuncao_csll: float = 0.32
    aliquota_issqn: float = 0.02
    ano_referencia: int = 2026


@dataclass
class ResultadoMes:
    mes: int
    competencia: str = ""
    faturamento: float = 0.0
    folha: float = 0.0
    despesas_dedutiveis: float = 0.0
    compras_credito: float = 0.0

    # Simples Nacional
    sn_rbt12: float = 0.0
    sn_fs12: float = 0.0
    sn_fator_r: float = 0.0
    sn_anexo: str = "III"
    sn_faixa: int = 1
    sn_aliquota_nominal: float = 0.0
    sn_parcela_deduzir: float = 0.0
    sn_aliquota_efetiva: float = 0.0
    sn_valor_irpj: float = 0.0
    sn_valor_csll: float = 0.0
    sn_valor_cofins: float = 0.0
    sn_valor_pis: float = 0.0
    sn_valor_cpp: float = 0.0
    sn_valor_iss: float = 0.0
    sn_encargos: float = 0.0
    sn_federal: float = 0.0
    sn_consumo: float = 0.0
    sn_observacao: str = ""

    # Lucro Presumido
    lp_trimestre: str = ""
    lp_base_irpj: float = 0.0
    lp_base_csll: float = 0.0
    lp_irpj: float = 0.0
    lp_csll: float = 0.0
    lp_irpj_csll_normal: float = 0.0
    lp_adicional_irpj: float = 0.0
    lp_pis: float = 0.0
    lp_cofins: float = 0.0
    lp_valor_iss: float = 0.0
    lp_federal: float = 0.0
    lp_consumo: float = 0.0
    lp_encargos: float = 0.0

    # Lucro Real trimestral (apropriação mensal gerencial)
    lr_trimestre: str = ""
    lr_lair: float = 0.0
    lr_irpj: float = 0.0
    lr_csll: float = 0.0
    lr_irpj_csll_normal: float = 0.0
    lr_adicional_irpj: float = 0.0
    lr_pis_debito: float = 0.0
    lr_cofins_debito: float = 0.0
    lr_creditos: float = 0.0
    lr_valor_iss: float = 0.0
    lr_federal: float = 0.0
    lr_consumo: float = 0.0
    lr_encargos: float = 0.0

    @property
    def sn_total_das(self) -> float:
        return (
            self.sn_valor_irpj
            + self.sn_valor_csll
            + self.sn_valor_cofins
            + self.sn_valor_pis
            + self.sn_valor_cpp
            + self.sn_valor_iss
        )

    @property
    def total_sn(self) -> float:
        return self.sn_federal + self.sn_consumo + self.sn_encargos

    @property
    def total_lp(self) -> float:
        return self.lp_federal + self.lp_consumo + self.lp_encargos

    @property
    def total_lr(self) -> float:
        return self.lr_federal + self.lr_consumo + self.lr_encargos


# (limite, alíquota nominal, parcela a deduzir)
TABELA_ANEXO_III = [
    (180_000, 0.060, 0),
    (360_000, 0.112, 9_360),
    (720_000, 0.135, 17_640),
    (1_800_000, 0.160, 35_640),
    (3_600_000, 0.210, 125_640),
    (4_800_000, 0.330, 648_000),
]
TABELA_ANEXO_IV = [
    (180_000, 0.045, 0),
    (360_000, 0.090, 8_100),
    (720_000, 0.102, 12_420),
    (1_800_000, 0.140, 39_780),
    (3_600_000, 0.220, 183_780),
    (4_800_000, 0.330, 828_000),
]
TABELA_ANEXO_V = [
    (180_000, 0.155, 0),
    (360_000, 0.180, 4_500),
    (720_000, 0.195, 9_900),
    (1_800_000, 0.205, 17_100),
    (3_600_000, 0.230, 62_100),
    (4_800_000, 0.305, 540_000),
]

# IRPJ, CSLL, Cofins, PIS/Pasep, CPP, ISS
REPARTICAO_ANEXO_III = [
    (0.0400, 0.0350, 0.1282, 0.0278, 0.4340, 0.3350),
    (0.0400, 0.0350, 0.1405, 0.0305, 0.4340, 0.3200),
    (0.0400, 0.0350, 0.1364, 0.0296, 0.4340, 0.3250),
    (0.0400, 0.0350, 0.1364, 0.0296, 0.4340, 0.3250),
    (0.0400, 0.0350, 0.1282, 0.0278, 0.4340, 0.3350),
    (0.3500, 0.1500, 0.1603, 0.0347, 0.3050, 0.0000),
]
REPARTICAO_ANEXO_IV = [
    (0.1880, 0.1520, 0.1767, 0.0383, 0.0000, 0.4450),
    (0.1980, 0.1520, 0.2055, 0.0445, 0.0000, 0.4000),
    (0.2080, 0.1520, 0.1973, 0.0427, 0.0000, 0.4000),
    (0.1780, 0.1920, 0.1890, 0.0410, 0.0000, 0.4000),
    (0.1880, 0.1920, 0.1808, 0.0392, 0.0000, 0.4000),
    (0.5350, 0.2150, 0.2055, 0.0445, 0.0000, 0.0000),
]
# Repartições oficiais do Anexo V. A versão anterior do projeto usava
# percentuais de outro anexo e não reconciliava com o PGDAS.
REPARTICAO_ANEXO_V = [
    (0.2500, 0.1500, 0.1410, 0.0305, 0.2885, 0.1400),
    (0.2300, 0.1500, 0.1410, 0.0305, 0.2785, 0.1700),
    (0.2400, 0.1500, 0.1492, 0.0323, 0.2385, 0.1900),
    (0.2100, 0.1500, 0.1574, 0.0341, 0.2385, 0.2100),
    (0.2300, 0.1250, 0.1410, 0.0305, 0.2385, 0.2350),
    (0.3500, 0.1550, 0.1644, 0.0356, 0.2950, 0.0000),
]


def calcula_inss_patronal(folha: float, config: ConfigTributaria) -> float:
    """CPP patronal + RAT ajustado pelo FAP + terceiros."""
    aliquota = 0.20 + (config.aliquota_rat * config.fap) + config.aliquota_terceiros
    return max(folha, 0.0) * aliquota


def get_aliquota_efetiva_simples(
    rbt12: float,
    anexo: Sequence[Tuple[float, float, float]],
    reparticao: Sequence[Tuple[float, ...]],
) -> Tuple[float, int, Tuple[float, ...], float, float]:
    """Retorna alíquota efetiva, faixa, repartição, nominal e dedução."""
    base = max(rbt12, 0.01)
    for i, (limite, nominal, deducao) in enumerate(anexo):
        if base <= limite:
            efetiva = max(((base * nominal) - deducao) / base, 0.0)
            return efetiva, i + 1, reparticao[i], nominal, deducao
    nominal, deducao = anexo[-1][1], anexo[-1][2]
    efetiva = max(((base * nominal) - deducao) / base, 0.0)
    return efetiva, 6, reparticao[-1], nominal, deducao


def _componentes_simples(aliquota_efetiva: float, reparticao: Sequence[float]) -> List[float]:
    """Calcula percentuais efetivos e limita o ISS a 5%.

    A diferença do ISS é redistribuída proporcionalmente entre os tributos
    federais da faixa, conforme a Resolução CGSN nº 140/2018.
    """
    componentes = [aliquota_efetiva * p for p in reparticao]
    if componentes[5] > 0.05:
        excesso = componentes[5] - 0.05
        componentes[5] = 0.05
        total_federal = sum(componentes[:5])
        if total_federal:
            for i in range(5):
                componentes[i] += excesso * (componentes[i] / total_federal)
    return componentes


def _periodo(dado: DadosMes, indice: int, ano_padrao: int) -> Tuple[int, int, str]:
    if dado.competencia:
        for formato in ("%m/%Y", "%Y-%m"):
            try:
                dt = datetime.strptime(dado.competencia, formato)
                trimestre = (dt.month - 1) // 3 + 1
                return dt.year, trimestre, f"{trimestre}T{dt.year}"
            except ValueError:
                pass
    mes = ((indice % 12) + 1)
    trimestre = (mes - 1) // 3 + 1
    return ano_padrao, trimestre, f"{trimestre}T{ano_padrao}"


def _historico_exato(valores: Iterable[float] | None, total: float) -> Deque[float]:
    lista = [max(float(v), 0.0) for v in (valores or [])][-12:]
    if len(lista) < 12:
        faltantes = 12 - len(lista)
        saldo = max(total - sum(lista), 0.0)
        preenchimento = saldo / faltantes if faltantes else 0.0
        lista = ([preenchimento] * faltantes) + lista
    return deque(lista, maxlen=12)


def _aplicar_fechamentos_trimestrais(resultados: List[ResultadoMes]) -> None:
    grupos: Dict[str, List[ResultadoMes]] = defaultdict(list)
    for resultado in resultados:
        grupos[resultado.lp_trimestre].append(resultado)

    for itens in grupos.values():
        # Lucro Presumido: adicional exato no fechamento do trimestre.
        base_lp = sum(item.lp_base_irpj for item in itens)
        adicional_lp = max(base_lp - (20_000 * len(itens)), 0.0) * 0.10
        itens[-1].lp_adicional_irpj = adicional_lp
        itens[-1].lp_federal += adicional_lp

        # Lucro Real trimestral: prejuízos do próprio trimestre compensam lucros.
        lucro_trimestre = sum(item.lr_lair for item in itens)
        for item in itens:
            item.lr_irpj = item.lr_csll = item.lr_irpj_csll_normal = 0.0
            item.lr_adicional_irpj = item.lr_federal = 0.0
        if lucro_trimestre <= 0:
            continue

        positivos = [max(item.lr_lair, 0.0) for item in itens]
        soma_positivos = sum(positivos) or 1.0
        irpj_total = lucro_trimestre * 0.15
        csll_total = lucro_trimestre * 0.09
        for item, lucro_positivo in zip(itens, positivos):
            proporcao = lucro_positivo / soma_positivos
            item.lr_irpj = irpj_total * proporcao
            item.lr_csll = csll_total * proporcao
            item.lr_irpj_csll_normal = item.lr_irpj + item.lr_csll
            item.lr_federal = item.lr_irpj_csll_normal
        adicional_lr = max(lucro_trimestre - (20_000 * len(itens)), 0.0) * 0.10
        itens[-1].lr_adicional_irpj = adicional_lr
        itens[-1].lr_federal += adicional_lr


def simular_12_meses(
    dados: List[DadosMes],
    config: ConfigTributaria,
    rbt12_inicial: float = 0,
    folha12m_inicial: float = 0,
    historico_faturamento: Iterable[float] | None = None,
    historico_folha: Iterable[float] | None = None,
) -> List[ResultadoMes]:
    resultados: List[ResultadoMes] = []
    receitas_anteriores = _historico_exato(historico_faturamento, rbt12_inicial)
    folhas_anteriores = _historico_exato(historico_folha, folha12m_inicial)
    receita_por_trimestre: Dict[str, float] = defaultdict(float)

    for idx, d in enumerate(dados):
        ano, trimestre, chave_trimestre = _periodo(d, idx, config.ano_referencia)
        rbt12 = sum(receitas_anteriores)
        fs12 = sum(folhas_anteriores)
        res = ResultadoMes(
            mes=d.mes,
            competencia=d.competencia or f"Mês {d.mes}",
            faturamento=max(d.faturamento, 0.0),
            folha=max(d.folha, 0.0),
            despesas_dedutiveis=max(d.despesas_dedutiveis, 0.0),
            compras_credito=max(d.compras_credito, 0.0),
            lp_trimestre=chave_trimestre,
            lr_trimestre=chave_trimestre,
        )

        # Simples Nacional
        if rbt12 > 0:
            fator_r = fs12 / rbt12 if fs12 > 0 else 0.01
            base_aliquota = rbt12
        else:
            fator_r = (res.folha / res.faturamento) if res.faturamento else 0.01
            base_aliquota = res.faturamento * 12  # RBT12 proporcionalizada

        if config.is_anexo_iv:
            tabela, reparticao, anexo_nome = TABELA_ANEXO_IV, REPARTICAO_ANEXO_IV, "IV"
        elif config.fator_r_sujeito and fator_r < 0.28:
            tabela, reparticao, anexo_nome = TABELA_ANEXO_V, REPARTICAO_ANEXO_V, "V"
        else:
            tabela, reparticao, anexo_nome = TABELA_ANEXO_III, REPARTICAO_ANEXO_III, "III"

        efetiva, faixa, rep, nominal, deducao = get_aliquota_efetiva_simples(
            base_aliquota, tabela, reparticao
        )
        componentes = _componentes_simples(efetiva, rep)
        valores = [res.faturamento * componente for componente in componentes]
        (
            res.sn_valor_irpj,
            res.sn_valor_csll,
            res.sn_valor_cofins,
            res.sn_valor_pis,
            res.sn_valor_cpp,
            res.sn_valor_iss,
        ) = valores
        res.sn_rbt12 = rbt12
        res.sn_fs12 = fs12
        res.sn_fator_r = fator_r
        res.sn_anexo = anexo_nome
        res.sn_faixa = faixa
        res.sn_aliquota_nominal = nominal
        res.sn_parcela_deduzir = deducao
        res.sn_aliquota_efetiva = efetiva
        res.sn_federal = res.sn_valor_irpj + res.sn_valor_csll
        res.sn_consumo = res.sn_valor_cofins + res.sn_valor_pis + res.sn_valor_iss
        res.sn_encargos = res.sn_valor_cpp
        if anexo_nome == "IV":
            res.sn_encargos += calcula_inss_patronal(res.folha, config)
        if rbt12 > 3_600_000:
            res.sn_observacao = (
                "RBT12 acima do sublimite de R$ 3,6 milhões: validar ISS fora do DAS."
            )
        if rbt12 > 4_800_000:
            res.sn_observacao = (
                "RBT12 acima de R$ 4,8 milhões: possível impedimento/exclusão do Simples."
            )

        # Lucro Presumido
        receita_anterior_trimestre = receita_por_trimestre[chave_trimestre]
        limite_trimestral = 1_250_000.0
        receita_normal = max(min(res.faturamento, limite_trimestral - receita_anterior_trimestre), 0.0)
        receita_excedente = max(res.faturamento - receita_normal, 0.0)
        multiplicador_irpj = 1.10 if ano >= 2026 else 1.0
        multiplicador_csll = 1.10 if (ano > 2026 or (ano == 2026 and trimestre >= 2)) else 1.0
        res.lp_base_irpj = (
            receita_normal * config.presuncao_irpj
            + receita_excedente * config.presuncao_irpj * multiplicador_irpj
        )
        res.lp_base_csll = (
            receita_normal * config.presuncao_csll
            + receita_excedente * config.presuncao_csll * multiplicador_csll
        )
        receita_por_trimestre[chave_trimestre] += res.faturamento
        res.lp_irpj = res.lp_base_irpj * 0.15
        res.lp_csll = res.lp_base_csll * 0.09
        res.lp_irpj_csll_normal = res.lp_irpj + res.lp_csll
        res.lp_federal = res.lp_irpj_csll_normal
        res.lp_pis = res.faturamento * 0.0065
        res.lp_cofins = res.faturamento * 0.0300
        res.lp_valor_iss = res.faturamento * config.aliquota_issqn
        res.lp_consumo = res.lp_pis + res.lp_cofins + res.lp_valor_iss
        res.lp_encargos = calcula_inss_patronal(res.folha, config)

        # Lucro Real trimestral
        res.lr_pis_debito = res.faturamento * 0.0165
        res.lr_cofins_debito = res.faturamento * 0.0760
        res.lr_creditos = min(
            res.compras_credito * 0.0925,
            res.lr_pis_debito + res.lr_cofins_debito,
        )
        res.lr_valor_iss = res.faturamento * config.aliquota_issqn
        res.lr_consumo = (
            res.lr_pis_debito + res.lr_cofins_debito - res.lr_creditos + res.lr_valor_iss
        )
        res.lr_encargos = calcula_inss_patronal(res.folha, config)
        res.lr_lair = (
            res.faturamento
            - res.despesas_dedutiveis
            - res.folha
            - res.lr_encargos
            - res.lr_consumo
        )

        resultados.append(res)
        receitas_anteriores.append(res.faturamento)
        folhas_anteriores.append(res.folha)

    _aplicar_fechamentos_trimestrais(resultados)
    return resultados
