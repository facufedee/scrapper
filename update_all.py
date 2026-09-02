"""Re-scrapea todas las fuentes registradas, una por una.

Uso:
    python update_all.py                  # todas las fuentes
    python update_all.py remax carlucci    # solo estas

Por qué esto sirve para "actualizar" y no solo para la carga inicial: el
upsert es por (source, source_id) — no duplica nada, sólo actualiza lo que
cambió (precio, estado, etc.) y agrega lo nuevo. Correr esto en octubre es
literalmente lo mismo que correrlo hoy.

No corre las fuentes que no son scrapers automáticos:
- mercadolibre: es ingesta manual (`cli.py ingest-ml archivo.txt`), no se
  puede "actualizar sola" porque depende de que vos pegues contenido nuevo.
- zonaprop: se deja afuera del run-all porque su Cloudflare escala a bloqueo
  con volumen — correrlo hay que hacerlo aparte, con cuidado (ver README).
- argenprop: mismo motivo, pero peor (llega a captcha, no a un challenge
  resoluble) — correrlo aparte, nunca en loop automático.
"""

import subprocess
import sys
import time

from cli import SCRAPERS

EXCLUDE_FROM_AUTO_RUN = {"zonaprop", "argenprop"}


def main():
    requested = sys.argv[1:] or [s for s in SCRAPERS if s not in EXCLUDE_FROM_AUTO_RUN]
    unknown = [s for s in requested if s not in SCRAPERS]
    if unknown:
        print(f"Fuentes desconocidas: {unknown}. Opciones: {sorted(SCRAPERS)}")
        sys.exit(1)

    print(f"Actualizando {len(requested)} fuentes: {', '.join(requested)}\n")

    results = []
    for source in requested:
        print(f"=== {source} ===")
        started = time.time()
        proc = subprocess.run([sys.executable, "cli.py", "run", source, "--operation", "all"])
        elapsed = time.time() - started
        results.append((source, proc.returncode, elapsed))
        print(f"--- {source} terminado en {elapsed:.0f}s (exit={proc.returncode}) ---\n")

    print("\n=== Resumen ===")
    for source, code, elapsed in results:
        status = "OK" if code == 0 else "FALLÓ"
        print(f"{source:15s} {status:6s} {elapsed:6.0f}s")


if __name__ == "__main__":
    main()
