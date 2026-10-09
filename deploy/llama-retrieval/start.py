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
    config = uvicorn.Config('service:app', workers=1, limit_concurrency=8, timeout_keep_alive=5)
    with listener:
        uvicorn.Server(config).run(sockets=[listener])


if __name__ == '__main__':
    main()
