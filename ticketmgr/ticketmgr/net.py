"""Find the addresses other computers on the network can use to reach this one."""

import socket


def lan_addresses():
    """Return this computer's local network IPv4 addresses, best guess first."""
    found = []
    try:
        # Connecting a UDP socket sends nothing; it just picks the outgoing interface.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in found:
                found.append(ip)
    except OSError:
        pass
    return [ip for ip in found if not ip.startswith(("127.", "169.254.", "0."))]
