import socket
from threading import Lock
from typing import ClassVar


class SocketSingleton:
    """Reference-counted UDP sockets shared by receive port."""

    _instances: ClassVar[dict[int, dict[str, "SocketSingleton | int"]]] = {}
    _lock = Lock()

    def __new__(cls, recv_port):
        """Reuse the socket for recv_port, creating and binding it when absent."""
        with cls._lock:
            if recv_port not in cls._instances:
                instance = super().__new__(cls)
                cls._instances[recv_port] = {
                    "instance": instance,
                    "ref_count": 0,
                }
            return cls._instances[recv_port]["instance"]

    def __init__(self, recv_port):
        """Acquire one reference to the shared socket."""
        self.recv_port = recv_port
        self._create_socket()

        SocketSingleton._instances[self.recv_port]["ref_count"] += 1

    def _create_socket(self):
        """Creates a new socket and binds it to the specified port."""
        if not hasattr(self, "udp_server"):
            self.udp_server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_server.bind(("", self.recv_port))

    def close(self):
        """Decrements the reference count and closes the socket if no more references
        exist.
        """
        with SocketSingleton._lock:
            if self.recv_port in SocketSingleton._instances:
                SocketSingleton._instances[self.recv_port]["ref_count"] -= 1
                if SocketSingleton._instances[self.recv_port]["ref_count"] <= 0:
                    self.udp_server.close()
                    del SocketSingleton._instances[self.recv_port]

    def sendto(self, data, address):
        self.udp_server.sendto(data, address)

    def recvfrom(self, buffer_size=1024):
        return self.udp_server.recvfrom(buffer_size)

    def settimeout(self, timeout):
        self.udp_server.settimeout(timeout)
