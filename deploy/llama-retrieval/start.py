"""Serve private IPv4/IPv6 traffic with one bounded retrieval worker."""
import os
import socket

import uvicorn


def main():
    port = int(os.getenv('PORT', '8000'))
    if not 1 <= port <= 65535:
        raise ValueError('PORT must be between 1 and 65535')
    if socket.has_dualstack_ipv6():
        listener = socket.create_server(('::', port), family=socket.AF_INET6, dualstack_ipv6=True)
    else:
        listener = socket.create_server(('0.0.0.0', port))
    http_concurrency = int(os.getenv('LLAMA_HTTP_CONCURRENCY', '64'))
    keep_alive = int(os.getenv('LLAMA_HTTP_KEEP_ALIVE_SECONDS', '30'))
    if http_concurrency < 2 or keep_alive < 1:
        raise ValueError('HTTP concurrency must be at least 2 and keep-alive must be positive')
    config = uvicorn.Config('service:app', workers=1,
        limit_concurrency=http_concurrency, timeout_keep_alive=keep_alive)
    with listener:
        uvicorn.Server(config).run(sockets=[listener])


if __name__ == '__main__':
    main()
