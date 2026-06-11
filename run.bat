@echo off
cd /d "%~dp0"
echo Iniciando o Simulador Tributario 12 Meses...
echo Por favor, aguarde enquanto o servidor Streamlit e iniciado.
python -m pip install -q -r requirements.txt
python -m streamlit run app.py
pause
