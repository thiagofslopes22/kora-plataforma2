#!/usr/bin/env python3
"""
Launcher dos backends com socket DUAL-STACK (IPv4 + IPv6 no mesmo listener).

Por que isto existe em vez de um `uvicorn --host ...` direto:

  --host 0.0.0.0  -> so IPv4. O dominio publico funciona, mas a rede privada do
                     Railway (que e IPv6-only, *.railway.internal) nao alcanca o
                     servico: o frontend recebe "connection refused" em /api e /conc.

  --host ::       -> so IPv6, apesar de parecer "todas as interfaces". O asyncio
                     do CPython seta IPV6_V6ONLY=1 ao abrir socket AF_INET6
                     (base_events.create_server), justamente para permitir
                     bindar 0.0.0.0 e :: separadamente. Resultado: a rede privada
                     passa a funcionar e o dominio publico comeca a dar 502,
                     porque o proxy de borda chega por IPv4.

A saida e abrir o socket na mao com IPV6_V6ONLY=0 — um unico listener que aceita
os dois protocolos (IPv4 chega como endereco mapeado ::ffff:a.b.c.d) — e entregar
o descritor pronto ao uvicorn via `fd=`.

Uso:  python serve.py <modulo:app> [porta_padrao]
      PORT do ambiente tem precedencia sobre a porta padrao.
"""
from __future__ import annotations

import os
import socket
import sys

import uvicorn


def abrir_socket_dual_stack(porta: int) -> socket.socket:
    if not socket.has_ipv6:
        # Ambiente sem IPv6: cai para IPv4 puro em vez de falhar.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", porta))
        s.listen(2048)
        print(f"[serve] IPv6 indisponivel; escutando apenas IPv4 em 0.0.0.0:{porta}", flush=True)
        return s

    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        # O ponto do arquivo: 0 = NAO restringir a IPv6.
        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        dual = True
    except OSError:
        # Alguns kernels/containers proibem desligar o V6ONLY.
        dual = False
    s.bind(("::", porta))
    s.listen(2048)
    print(
        f"[serve] escutando em [::]:{porta} "
        f"({'dual-stack: IPv4 + IPv6' if dual else 'IPv6 apenas — V6ONLY nao pode ser desligado'})",
        flush=True,
    )
    return s


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("uso: python serve.py <modulo:app> [porta_padrao]")
    app = sys.argv[1]
    padrao = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
    porta = int(os.getenv("PORT", padrao))

    sock = abrir_socket_dual_stack(porta)
    # Entregamos o OBJETO socket, nao `fd=`: o caminho do fd no uvicorn faz
    # socket.fromfd(fd, AF_UNIX, ...) — trata o descritor como socket de dominio
    # unix, o que erra a familia do nosso socket TCP e nem existe no Windows.
    servidor = uvicorn.Server(
        uvicorn.Config(app, log_level=os.getenv("KORA_LOG_LEVEL", "info"))
    )
    servidor.run(sockets=[sock])


if __name__ == "__main__":
    main()
