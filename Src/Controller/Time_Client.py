from __future__ import annotations

import logging
import selectors as sel
import socket
import sys
import time
from enum import Enum, auto
from types import SimpleNamespace
from typing import Tuple
from ntplib import * # type: ignore
from threading import Lock, Event

SOCKADDR = Tuple[str, int]
NTPSERVER = Tuple[str, SOCKADDR]


class Status(Enum):
    NotSet = auto()
    Sent = auto()
    Received = auto()
    Timedout = auto()


class Time_Client(NTPClient):
    def __init__(self, ntp_servers: list[str]) -> None:
        super().__init__()
        self._sel = sel.DefaultSelector()
        self._is_setup = False
        self._ip_translated = True
        self._server = self.__get_addr_info(
            [*ntp_servers, "time.nist.gov", "pool.ntp.org"])
        logging.info(f"Chosen NTP server: {self._server[0]}.")

        self._polling_interval = 3
        logging.info(
            f"Initial NTP polling interval: {2**self._polling_interval}s.")
        self._status = Status.NotSet
        self._last_sent = 0
        self._last_update = 0

        ntp_stats = {
            "Delay": sys.maxsize,
            "Offset": sys.maxsize,
            "Time": 0,
            "Used": False
        }
        self._buffer = [ntp_stats.copy() for i in range(8)]
        self._index = 0
        self._previous_clock_update = 0
        self._offset = 0

    def __get_addr_info(self, hosts: list, port="ntp") -> NTPSERVER:
        for host in hosts:
            logging.info(f"Getting the IP for the NTP server {host}.")
            try:
                return host, socket.getaddrinfo(host, port)[0][4] # type: ignore
            except socket.gaierror:
                logging.error(f"The NTP server {host} is not available.")
        logging.error(
            f"No NTP servers could be reached. "
            f"Defaulting to {hosts[0]}:123."
        )
        self._ip_translated = False
        return hosts[0], (hosts[0], 123)

    def setup(self) -> None:
        logging.info("Setting up NTP Socket.")
        self._lock = Lock()
        self._sock = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._sock.setblocking(False)
        data = SimpleNamespace(callback=self.readNTPPacket)
        self._sel.register(self._sock, sel.EVENT_READ, data)
        self._is_setup = True
        logging.info("Synchronizing with the NTP server for the first time.")
        self.update(time.time())

    def __set_polling_interval(self) -> None:
        if self._status == Status.Received:
            if self._polling_interval < 4:
                self._polling_interval += 1
                logging.info(
                    f"Increasing NTP polling interval to: "
                    f"{2**self._polling_interval}s."
                    )
            elif self._polling_interval > 4:
                self._polling_interval = 4
        elif self._status == Status.Timedout:
            logging.error(
                f"Unable to reach NTP server. Doubling polling interval.")
            self._polling_interval += 1

    def __writeNTPPacket(self, ntp_server: NTPSERVER, version=3) -> int:
        # create the request packet - mode 3 is client
        query_packet = NTPPacket(
            mode=3,
            version=version,
            tx_timestamp=system_to_ntp_time(time.time() + self._offset) # type: ignore
        )
        try:
            sent = self._sock.sendto(query_packet.to_data(), ntp_server[1])
        except socket.gaierror:
            self._status = Status.Timedout
        else:
            if not self._ip_translated:
                logging.info(f"NTP server {ntp_server[0]} is back online!")
                self._ip_translated = True
                self._server = self.__get_addr_info([self._server[0]])
            self._status = Status.Sent
            self._last_sent = time.time()
        finally:
            return sent # type: ignore

    def __set_peer_update(self, response: bytes, now: float) -> None:
        stats = NTPStats()
        stats.from_data(response)
        stats.dest_timestamp = system_to_ntp_time(now) # type: ignore
        self._buffer[self._index]["Delay"] = stats.delay
        self._buffer[self._index]["Offset"] = stats.offset
        self._buffer[self._index]["Time"] = now
        self._buffer[self._index]["Used"] = False

    """
    Get the offset from the peer update with the lowest delay from the past 8
    peer updates. Each peer update can only be used once and it must be more
    recent than the last peer update that was chosen.
    """
    def __get_peer_update(self) -> float:
        pui = self._index
        delay0 = self._buffer[pui]["Delay"]
        offset0 = self._buffer[pui]["Offset"]
        logging.info(f'Recent Delay: {delay0}')
        logging.info(f'Recent Offset: {offset0}')
        for i in range(8):
            small_delay = self._buffer[i]["Delay"] < self._buffer[pui]["Delay"]
            recent = self._buffer[i]["Time"] >= self._previous_clock_update
            if small_delay and recent:
                pui = i
        delay1 = self._buffer[pui]["Delay"]
        offset1 = self._buffer[pui]["Offset"]
        peer_update = 0
        if not self._buffer[pui]["Used"]:
            peer_update = offset1
            if offset0 > offset1:
                peer_update -= ((delay0 - delay1) / 2)
            elif offset0 < offset1:
                peer_update += ((delay0 - delay1) / 2)
        logging.info(f'Offset: {peer_update}')
        self._buffer[pui]["Used"] = True
        self._previous_clock_update = self._buffer[pui]["Time"]
        return peer_update

    def readNTPPacket(self, key: sel.SelectorKey) -> None:
        response_packet, addr = self._sock.recvfrom(256)
        if (addr[0] == self._server[1][0]) and (self._status == Status.Sent):
            with self._lock:
                now = time.time()
                self._status = Status.Received
                self._last_update = now
                self.__set_polling_interval()

                self.__set_peer_update(response_packet, now + self._offset)
                self._offset += self.__get_peer_update()
                self._index = (self._index + 1) % 8
        else:
            logging.error(
                "Received NTP packet from a different server "
                "or out of sync. Discarding."
            )

    def update(self, now: float) -> None:
        if not self._is_setup:
            self.setup()

        if self._status == Status.Sent:
            if (now - self._last_sent) >= 3:
                self._status = Status.Timedout
        else:
            if (now - self._last_update) >= (2**self._polling_interval):
                self.__writeNTPPacket(self._server)

        if self._status == Status.Timedout:
            self._last_update = now
            self.__set_polling_interval()
            self._status = Status.NotSet

    def stay_updated(self, stop: Event) -> None:
        try:
            while not stop.is_set():
                self.update(time.time())
                ce = self._sel.select(1)
                for key, mask in ce:
                    callback = key.data.callback
                    callback(key)
        finally:
            self.shutdown()

    def time_ms(self) -> int:
        if not self._is_setup:
            self.setup()
        with self._lock:
            return int((time.time() + self._offset) * 1000)

    def shutdown(self) -> None:
        logging.info("Shutting down NTP socket.")
        self._sel.unregister(self._sock)
        self._sock.close()


# if __name__ == "__main__":
#     root = logging.getLogger()
#     root.setLevel(logging.DEBUG)
#     s = sel.DefaultSelector()
#     a = Time_Client(s)
#     a.setup()
#     while True:
#         now = time.time()
#         a.update(now)
#         ce = s.select(1)
#         for key, mask in ce:
#             callback = key.data.callback
#             callback(key)
        # print("Timestamp: ", a.time_ms())
