import socket
import time
import threading
from enum import Enum

class AlliancePosition(Enum):
    R1 = 0
    R2 = 1
    R3 = 2
    B1 = 3
    B2 = 4
    B3 = 5

class MatchType(Enum):
    PRACTICE = 1
    QUALIFICATION = 2
    ELIMINATION = 3
    OTHER = 0


DRIVER_STATION_UDP_PORT = 1121
DRIVER_STATION_UDP_RECEIVE_PORT = 1160

class DriverStationConnection:
    def __init__(self, team_id: int, alliance_station: AlliancePosition, ds_address: str):
        self.team_id = team_id
        self.alliance_station = alliance_station
        self.auto = False
        self.enabled = False
        self.estop = False
        self.packet_count = 0
        self.last_packet_time = time.time()
        self.last_robot_linked_time = time.time()
        self.ds_linked = False
        self.radio_linked = False
        self.robot_linked = False
        self.battery_voltage = 0.0
        self.running = True

        self.udp_conn = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_conn.connect((ds_address, DRIVER_STATION_UDP_PORT))

        self.listener_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.listener_socket.bind(('', DRIVER_STATION_UDP_RECEIVE_PORT))

        self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listen_thread.start()

    def encode_control_packet(self, match_type: MatchType = MatchType.QUALIFICATION, match_number=1, match_seconds_remaining=135):
        packet = bytearray(22)
        packet[0] = (self.packet_count >> 8) & 0xFF
        packet[1] = self.packet_count & 0xFF
        packet[2] = 0

        packet[3] = 0
        if self.auto:
            packet[3] |= 0x02
        if self.enabled:
            packet[3] |= 0x04
        if self.estop:
            packet[3] |= 0x80

        packet[4] = 0
        packet[5] = self.alliance_station.value

        packet[6] = match_type.value

        packet[7] = (match_number >> 8) & 0xFF
        packet[8] = match_number & 0xFF
        packet[9] = 1  # match repeat number

        now = time.localtime()
        micros = int((time.time() % 1) * 1_000_000)
        packet[10] = (micros >> 24) & 0xFF
        packet[11] = (micros >> 16) & 0xFF
        packet[12] = (micros >> 8) & 0xFF
        packet[13] = micros & 0xFF
        packet[14] = now.tm_sec
        packet[15] = now.tm_min
        packet[16] = now.tm_hour
        packet[17] = now.tm_mday
        packet[18] = now.tm_mon
        packet[19] = now.tm_year - 1900

        packet[20] = (match_seconds_remaining >> 8) & 0xFF
        packet[21] = match_seconds_remaining & 0xFF

        self.packet_count += 1
        return packet

    def _listen_loop(self):
        print(f"Listening for driver station packets on UDP port {DRIVER_STATION_UDP_RECEIVE_PORT}")
        while self.running:
            try:
                data, _ = self.listener_socket.recvfrom(50)
                if len(data) < 8:
                    continue

                team_id = (data[4] << 8) + data[5]
                if team_id != self.team_id:
                    continue

                self.ds_linked = True
                self.last_packet_time = time.time()

                self.radio_linked = (data[3] & 0x10) != 0
                self.robot_linked = (data[3] & 0x20) != 0
                if self.robot_linked:
                    self.last_robot_linked_time = time.time()
                    self.battery_voltage = data[6] + data[7] / 256
            except Exception as e:
                print(f"UDP listener error: {e}")

    def send_control_packet(self):
        packet = self.encode_control_packet()
        self.udp_conn.send(packet)
        self.last_packet_time = time.time()

    # Robot control methods
    def enable_robot(self):
        self.enabled = True
        self.send_control_packet()

    def disable_robot(self):
        self.enabled = False
        self.send_control_packet()

    def set_auto(self, auto=True):
        self.auto = auto
        self.send_control_packet()

    def estop_robot(self):
        self.estop = True
        self.send_control_packet()

    def stop(self):
        self.running = False
        self.listen_thread.join()
        self.udp_conn.close()
        self.listener_socket.close()

if __name__ == "__main__":
    DriverStationConnection(5987, AlliancePosition.R1, "127.0.0.1")