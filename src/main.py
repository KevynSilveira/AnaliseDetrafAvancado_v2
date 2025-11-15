# Sobe API (uvicorn) em background e inicia a web (vite) sem perguntas
import os, subprocess, sys, time, socket
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJETO = ROOT.parent
if str(PROJETO) not in sys.path:
    # Permite importar o pacote src mesmo quando rodamos python src/main.py diretamente
    sys.path.insert(0, str(PROJETO))

from src.core.configuracao_logs import registrar_log

WEB = ROOT / "web"
API = ROOT / "api"

def ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"

def start_api():
    req = API / "requirements.txt"
    if req.exists():
        log_dir = ROOT.parent / "var" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "pip_requirements.log"
        registrar_log("launcher_pip_requirements_inicio", arquivo=str(req), destino=str(log_path))
        with open(log_path, "a") as log:
            log.write("\n=== Instalação de requisitos (pip) ===\n")
            log.flush()
            resultado = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(req)],
                check=False,
                stdout=log,
                stderr=log,
            )
        registrar_log(
            "launcher_pip_requirements_fim",
            arquivo=str(req),
            sucesso=resultado.returncode == 0,
            returncode=resultado.returncode,
            log=str(log_path),
        )
    registrar_log("launcher_api_process_start", comando=["python", "-m", "uvicorn", "src.api.server:app"])
    return subprocess.Popen([sys.executable, "-m", "uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000", "--reload"])

def start_web():
    os.chdir(WEB)
    if not (WEB / "node_modules").exists():
        # Instala dependências do front-end na primeira execução
        subprocess.run(["npm", "install"], check=True)
    env_path = WEB / ".env"
    if not env_path.exists():
        with open(env_path, "w") as f:
            f.write("VITE_API_URL=http://localhost:8000\n")
    registrar_log("launcher_web_process_start", comando=["npm", "run", "dev", "--", "--host"])
    return subprocess.Popen(["npm", "run", "dev", "--", "--host"])

if __name__ == "__main__":
    if not WEB.exists():
        print("Pasta src/web não encontrada."); sys.exit(1)
    api_proc = start_api()
    time.sleep(1)
    web_proc = start_web()
    ip = ip_local()
    print(f"API:  http://{ip}:8000  |  WEB:  http://{ip}:5173")
    print("Ctrl+C para encerrar.")
    try:
        web_proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in [web_proc, api_proc]:
            try: p.terminate()
            except: pass
