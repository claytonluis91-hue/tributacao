from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class DadosMes:
    mes: int
    faturamento: float
    folha: float
    despesas_dedutiveis: float
    compras_credito: float

@dataclass
class ConfigTributaria:
    aliquota_rat: float
    fap: float
    aliquota_terceiros: float
    is_anexo_iv: bool
    fator_r_sujeito: bool
    presuncao_irpj: float
    presuncao_csll: float

@dataclass
class ResultadoMes:
    mes: int
    faturamento: float = 0.0
    
    # Detalhes SN
    sn_rbt12: float = 0.0
    sn_fator_r: float = 0.0
    sn_faixa: int = 1
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
    
    # Detalhes LP
    lp_base_irpj: float = 0.0
    lp_irpj_csll_normal: float = 0.0
    lp_adicional_irpj: float = 0.0
    lp_federal: float = 0.0
    lp_consumo: float = 0.0
    lp_encargos: float = 0.0
    
    # Detalhes LR
    lr_lair: float = 0.0
    lr_irpj_csll_normal: float = 0.0
    lr_adicional_irpj: float = 0.0
    lr_federal: float = 0.0
    lr_consumo: float = 0.0
    lr_encargos: float = 0.0

    @property
    def sn_total_das(self):
        return self.sn_valor_irpj + self.sn_valor_csll + self.sn_valor_cofins + self.sn_valor_pis + self.sn_valor_cpp + self.sn_valor_iss

    @property
    def total_sn(self):
        return self.sn_total_das + self.sn_encargos

    @property
    def total_lp(self):
        return self.lp_federal + self.lp_consumo + self.lp_encargos

    @property
    def total_lr(self):
        return self.lr_federal + self.lr_consumo + self.lr_encargos


# Tabelas do Simples Nacional (Limites, Alíquota Nominal, Parcela)
TABELA_ANEXO_III = [
    (180000, 0.06, 0),
    (360000, 0.112, 9360),
    (720000, 0.135, 17640),
    (1800000, 0.16, 35640),
    (3600000, 0.21, 125640),
    (4800000, 0.33, 648000)
]
REPARTICAO_ANEXO_III = [
    (0.0400, 0.0350, 0.1282, 0.0278, 0.4340, 0.3350), # Faixa 1
    (0.0400, 0.0350, 0.1405, 0.0305, 0.4340, 0.3200), # Faixa 2
    (0.0400, 0.0350, 0.1364, 0.0296, 0.4340, 0.3250), # Faixa 3
    (0.0400, 0.0350, 0.1364, 0.0296, 0.4340, 0.3250), # Faixa 4
    (0.0400, 0.0350, 0.1282, 0.0278, 0.4340, 0.3350), # Faixa 5
    (0.3500, 0.1500, 0.1603, 0.0347, 0.3050, 0.0000)  # Faixa 6
]

TABELA_ANEXO_V = [
    (180000, 0.155, 0),
    (360000, 0.18, 4500),
    (720000, 0.195, 9900),
    (1800000, 0.205, 17100),
    (3600000, 0.23, 62100),
    (4800000, 0.305, 540000)
]
REPARTICAO_ANEXO_V = [
    (0.0400, 0.0500, 0.1439, 0.0312, 0.2885, 0.4464), # Faixa 1
    (0.0400, 0.0500, 0.1439, 0.0312, 0.2785, 0.4564), # Faixa 2
    (0.0400, 0.0500, 0.1439, 0.0312, 0.2385, 0.4964), # Faixa 3
    (0.0400, 0.0500, 0.1439, 0.0312, 0.2385, 0.4964), # Faixa 4
    (0.0400, 0.0500, 0.1439, 0.0312, 0.2385, 0.4964), # Faixa 5
    (0.2950, 0.1650, 0.2105, 0.0458, 0.2837, 0.0000)  # Faixa 6
]

def calcula_inss_patronal(folha: float, config: ConfigTributaria) -> float:
    cota = 0.20
    rat_ajustado = config.aliquota_rat * config.fap
    total_aliquota = cota + rat_ajustado + config.aliquota_terceiros
    return folha * total_aliquota

def get_aliquota_efetiva_simples(rbt12: float, anexo: List[Tuple[float, float, float]], reparticao: List[Tuple]) -> Tuple[float, int, Tuple]:
    if rbt12 == 0:
        return anexo[0][1], 1, reparticao[0]
    
    for i, (limite, aliquota_nominal, parcela) in enumerate(anexo):
        if rbt12 <= limite:
            efetiva = ((rbt12 * aliquota_nominal) - parcela) / rbt12
            return max(efetiva, 0.0), i + 1, reparticao[i]
            
    limite, aliquota_nominal, parcela = anexo[-1]
    efetiva = ((4800000 * aliquota_nominal) - parcela) / 4800000
    return max(efetiva, 0.0), 6, reparticao[-1]

def simular_12_meses(dados: List[DadosMes], config: ConfigTributaria, rbt12_inicial: float = 0, folha12m_inicial: float = 0) -> List[ResultadoMes]:
    resultados = []
    
    rbt12_atual = rbt12_inicial
    folha12m_atual = folha12m_inicial
    soma_base_irpj_trimestre = 0.0
    
    for idx, d in enumerate(dados):
        res = ResultadoMes(mes=d.mes, faturamento=d.faturamento)
        
        # ---------------------------------------------------------
        # SIMPLES NACIONAL
        # ---------------------------------------------------------
        fator_r = 0.0
        if rbt12_atual > 0:
            fator_r = folha12m_atual / rbt12_atual
        
        tabela_usada = TABELA_ANEXO_III
        reparticao_usada = REPARTICAO_ANEXO_III
        if config.fator_r_sujeito and fator_r < 0.28:
            tabela_usada = TABELA_ANEXO_V
            reparticao_usada = REPARTICAO_ANEXO_V
            
        aliq_efetiva, faixa, rep = get_aliquota_efetiva_simples(rbt12_atual, tabela_usada, reparticao_usada)
        das_mensal = d.faturamento * aliq_efetiva
        
        res.sn_rbt12 = rbt12_atual
        res.sn_fator_r = fator_r
        res.sn_faixa = faixa
        res.sn_aliquota_efetiva = aliq_efetiva
        
        res.sn_valor_irpj = das_mensal * rep[0]
        res.sn_valor_csll = das_mensal * rep[1]
        res.sn_valor_cofins = das_mensal * rep[2]
        res.sn_valor_pis = das_mensal * rep[3]
        res.sn_valor_cpp = das_mensal * rep[4]
        res.sn_valor_iss = das_mensal * rep[5]
        
        # Compatibilidade com o grafico: Consumo = COFINS+PIS+ISS, Federal = IRPJ+CSLL, Encargos = CPP
        res.sn_federal = res.sn_valor_irpj + res.sn_valor_csll
        res.sn_consumo = res.sn_valor_cofins + res.sn_valor_pis + res.sn_valor_iss
        res.sn_encargos = res.sn_valor_cpp
        
        if config.is_anexo_iv:
            inss_por_fora = calcula_inss_patronal(d.folha, config)
            res.sn_encargos += inss_por_fora # Soma com a CPP caso exista
            
        # ---------------------------------------------------------
        # LUCRO PRESUMIDO
        # ---------------------------------------------------------
        pis_cofins_lp = d.faturamento * 0.0365
        res.lp_consumo = pis_cofins_lp
        
        base_irpj = d.faturamento * config.presuncao_irpj
        base_csll = d.faturamento * config.presuncao_csll
        
        irpj_lp = base_irpj * 0.15
        csll_lp = base_csll * 0.09
        
        res.lp_base_irpj = base_irpj
        res.lp_irpj_csll_normal = irpj_lp + csll_lp
        res.lp_federal = irpj_lp + csll_lp
        soma_base_irpj_trimestre += base_irpj
        
        if (idx + 1) % 3 == 0:
            if soma_base_irpj_trimestre > 60000:
                adicional = (soma_base_irpj_trimestre - 60000) * 0.10
                res.lp_adicional_irpj = adicional
                res.lp_federal += adicional
            soma_base_irpj_trimestre = 0.0
            
        res.lp_encargos = calcula_inss_patronal(d.folha, config)
        
        # ---------------------------------------------------------
        # LUCRO REAL
        # ---------------------------------------------------------
        pis_cofins_lr_debito = d.faturamento * 0.0925
        pis_cofins_lr_credito = d.compras_credito * 0.0925
        res.lr_consumo = max(pis_cofins_lr_debito - pis_cofins_lr_credito, 0.0)
        
        inss_lr = calcula_inss_patronal(d.folha, config)
        res.lr_encargos = inss_lr
        
        lair = d.faturamento - d.despesas_dedutiveis - d.folha - inss_lr - res.lr_consumo
        res.lr_lair = lair
        
        if lair > 0:
            irpj_lr = lair * 0.15
            csll_lr = lair * 0.09
            adicional_lr = 0.0
            if lair > 20000:
                adicional_lr = (lair - 20000) * 0.10
            
            res.lr_irpj_csll_normal = irpj_lr + csll_lr
            res.lr_adicional_irpj = adicional_lr
            res.lr_federal = irpj_lr + csll_lr + adicional_lr
        else:
            res.lr_federal = 0.0
            
        delta_rbt12 = d.faturamento - (rbt12_atual / 12 if rbt12_atual > 0 else 0)
        rbt12_atual += delta_rbt12
        
        delta_folha = d.folha - (folha12m_atual / 12 if folha12m_atual > 0 else 0)
        folha12m_atual += delta_folha

        resultados.append(res)

    return resultados
