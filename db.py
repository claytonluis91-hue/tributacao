import sqlite3
import json
from datetime import datetime

DB_PATH = "simulacoes.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS simulacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_simulacao TEXT NOT NULL,
            regime_vencedor TEXT NOT NULL,
            custo_simples REAL,
            custo_presumido REAL,
            custo_real REAL,
            detalhes_json TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def salvar_simulacao(vencedor: str, custo_sn: float, custo_lp: float, custo_lr: float, detalhes: dict):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    data_atual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    detalhes_str = json.dumps(detalhes)
    
    cursor.execute('''
        INSERT INTO simulacoes (data_simulacao, regime_vencedor, custo_simples, custo_presumido, custo_real, detalhes_json)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (data_atual, vencedor, custo_sn, custo_lp, custo_lr, detalhes_str))
    
    conn.commit()
    conn.close()

def listar_simulacoes():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, data_simulacao, regime_vencedor, custo_simples, custo_presumido, custo_real FROM simulacoes ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows
