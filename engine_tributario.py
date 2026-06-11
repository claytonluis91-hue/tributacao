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
    sn_aliquota_efetiva: float = 0.0
    sn_federal: float = 0.0
    sn_consumo: float = 0.0
    sn_encargos: float = 0.0
    
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
    def total_sn(self):
        return self.sn_federal + self.sn_consumo + self.sn_encargos

    @property
    def total_lp(self):
        return self.lp_federal + self.lp_consumo + self.lp_encargos

    @property
    def total_lr(self):
        return self.lr_federal + self.lr_consumo + self.lr_encargos

# Tabelas do Simples Nacional (Simplificadas para o exemplo - Anexo III e V)
TABELA_ANEXO_III = [
    (180000, 0.06, 0),
    (360000, 0.112, 9360),
    (720000, 0.135, 17640),
    (1800000, 0.16, 35640),
    (3600000, 0.21, 125640),
    (4800000, 0.33, 648000)
]

TABELA_ANEXO_V = [
    (180000, 0.155, 0),
    (360000, 0.18, 4500),
    (720000, 0.195, 9900),
    (1800000, 0.205, 17100),
    (3600000, 0.23, 62100),
    (4800000, 0.305, 540000)
]

def calcula_inss_patronal(folha: float, config: ConfigTributaria) -> float:
    cota = 0.20
    rat_ajustado = config.aliquota_rat * config.fap
    total_aliquota = cota + rat_ajustado + config.aliquota_terceiros
    return folha * total_aliquota

def get_aliquota_efetiva_simples(rbt12: float, anexo: List[Tuple[float, float, float]]) -> float:
    if rbt12 == 0:
        return anexo[0][1]
    
    for limite, aliquota_nominal, parcela in anexo:
        if rbt12 <= limite:
            efetiva = ((rbt12 * aliquota_nominal) - parcela) / rbt12
            return max(efetiva, 0.0)
            
    limite, aliquota_nominal, parcela = anexo[-1]
    efetiva = ((4800000 * aliquota_nominal) - parcela) / 4800000
    return max(efetiva, 0.0)

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
        if config.fator_r_sujeito and fator_r < 0.28:
            tabela_usada = TABELA_ANEXO_V
            
        aliq_efetiva = get_aliquota_efetiva_simples(rbt12_atual, tabela_usada)
        das_mensal = d.faturamento * aliq_efetiva
        
        res.sn_rbt12 = rbt12_atual
        res.sn_fator_r = fator_r
        res.sn_aliquota_efetiva = aliq_efetiva
        res.sn_consumo = das_mensal * 0.5
        res.sn_federal = das_mensal * 0.5
        
        if config.is_anexo_iv:
            res.sn_encargos = calcula_inss_patronal(d.folha, config)
        else:
            res.sn_encargos = 0.0
            
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
