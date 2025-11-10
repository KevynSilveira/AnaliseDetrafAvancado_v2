# Sobe API (uvicorn) em background e inicia a web (vite) sem perguntas
import os, subprocess, sys, time, socket
from pathlib import Path

ROOT = Path(__file__).resolve().parent
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
        with open(log_path, "a") as log:
            log.write("\n=== Instalação de requisitos (pip) ===\n")
            log.flush()
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(req)],
                check=False,
                stdout=log,
                stderr=log,
            )
    return subprocess.Popen([sys.executable, "-m", "uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000", "--reload"])

def start_web():
    os.chdir(WEB)
    if not (WEB / "node_modules").exists():
        subprocess.run(["npm", "install"], check=True)
    env_path = WEB / ".env"
    if not env_path.exists():
        with open(env_path, "w") as f:
            f.write("VITE_API_URL=http://localhost:8000\n")
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
